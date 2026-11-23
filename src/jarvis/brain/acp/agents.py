"""Catálogo dos agentes ACP conhecidos e detecção (instalado? com login?). Nunca lê o CONTEÚDO de credenciais.

A detecção tem dois níveis:
- barata (`detect_all`): procura o executável e a EXISTÊNCIA do arquivo de login (sem abrir);
- ativa (`probe`): inicia o agente, faz `initialize` + `session/new` sem MCP e sem prompt. `session/new` que falha com
  "autenticação necessária" = instalado mas sem login. É a única prova real de que o login existe.
O Eco não faz login pelo usuário: quem entra é o próprio agente (`opencode acp --login`, `claude`, `codex login`...).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ...core.cancel import CancelToken
from .client import AcpAuthRequired, AcpClient, AcpError

log = logging.getLogger(__name__)
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(frozen=True)
class AgentDef:
    id: str
    label: str
    exe: str                              # executável que precisa existir
    args: tuple[str, ...]                 # argumentos que o executável recebe
    via_npx: str = ""                     # pacote npm do adaptador ACP (quando o agente não fala ACP nativamente)
    native: bool = True
    cred_hint: str = ""                   # caminho (relativo ao perfil) cuja EXISTÊNCIA sugere login; nunca é lido
    login_help: str = ""


CATALOG: tuple[AgentDef, ...] = (
    AgentDef("opencode", "OpenCode", "opencode", ("acp",), cred_hint=r".local\share\opencode\auth.json",
             login_help="opencode auth login (escolha um provedor e entre)"),
    AgentDef("antigravity", "Google Antigravity", "agy", ("acp",), login_help="agy (entre com a conta Google quando pedir)"),
    AgentDef("claude", "Claude Code", "claude", (), via_npx="@agentclientprotocol/claude-agent-acp", native=False,
             cred_hint=r".claude\.credentials.json", login_help="claude (dentro dele digite /login)"),
    AgentDef("codex", "OpenAI Codex CLI", "codex", (), via_npx="@agentclientprotocol/codex-acp", native=False,
             cred_hint=r".codex\auth.json", login_help="codex login"),
    AgentDef("copilot", "GitHub Copilot CLI", "copilot", ("--acp",), login_help="copilot (dentro dele digite /login)"),
)
BY_ID = {a.id: a for a in CATALOG}
AGENT_IDS = tuple(a.id for a in CATALOG)
# Comando EXATO que a pessoa roda num terminal para entrar (o login é interativo/OAuth: o Eco não o faz por ninguém).
LOGIN_COMMANDS = {"opencode": "opencode auth login", "antigravity": "agy", "claude": "claude", "codex": "codex login",
                  "copilot": "copilot"}


def login_command(agent_id: str) -> str:
    return LOGIN_COMMANDS.get(agent_id, agent_id)


@dataclass(frozen=True)
class Detected:
    id: str
    label: str
    installed: bool
    path: str
    version: str
    login: str                            # "provável" (arquivo de login existe) | "desconhecido" | "sem login" | "pronto"
    command: tuple[str, ...]              # linha de comando que o Eco usaria
    note: str = ""


def command_for(agent_id: str) -> list[str] | None:
    """Linha de comando para iniciar o agente por ACP, ou None se não estiver instalado."""
    a = BY_ID.get(agent_id)
    if a is None:
        return None
    exe = _agent_exe(a)
    if a.via_npx:
        npx = shutil.which("npx")
        if not npx or not exe:
            return None
        return [npx, "-y", a.via_npx]
    return [exe, *a.args] if exe else None


def _agent_exe(a: AgentDef) -> str | None:
    """Executável do agente: o caminho PERSONALIZADO (Configurações > Caminhos dos programas) vale antes do PATH."""
    from ...core import toolpaths
    try:
        return toolpaths.exe(a.id)
    except KeyError:
        return shutil.which(a.exe)


def _version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, timeout=20, text=True, errors="replace",
                             creationflags=_NO_WINDOW)
        first = (out.stdout or out.stderr or "").strip().splitlines()
        return first[0][:60] if first else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def detect(agent_id: str, with_version: bool = True) -> Detected:
    a = BY_ID[agent_id]
    exe = _agent_exe(a)
    cmd = command_for(agent_id)
    note = ""
    if a.via_npx and exe and not shutil.which("npx"):
        note = "precisa do Node.js (npx) para o adaptador ACP"
    elif a.via_npx and exe:
        note = f"usa o adaptador {a.via_npx} (baixado pelo npx na 1ª vez)"
    login = "desconhecido"
    if a.cred_hint:
        login = "provável" if (Path.home() / a.cred_hint).exists() else "sem login"
    return Detected(a.id, a.label, bool(exe) and cmd is not None, exe or "", _version(exe) if (exe and with_version) else "",
                    login if exe else "—", tuple(cmd or ()), note)


def detect_all(with_version: bool = True) -> list[Detected]:
    return [detect(a.id, with_version) for a in CATALOG]


def probe(agent_id: str, cwd: Path, timeout_s: float = 60.0) -> tuple[str, str]:
    """(estado, detalhe): "pronto" | "sem login" | "erro". Inicia o agente, `initialize` + `session/new`, e encerra. Sem prompt."""
    cmd = command_for(agent_id)
    if cmd is None:
        return "erro", "não instalado"
    client = AcpClient(cmd, cwd, env=child_env(agent_id), name=agent_id)
    try:
        client.start()
        client.initialize(timeout_s)
        client.new_session(cwd, [], timeout_s)
        who = client.agent_info.get("title") or client.agent_info.get("name") or agent_id
        return "pronto", f"{who} {client.agent_info.get('version', '')}".strip()
    except AcpAuthRequired as exc:
        return "sem login", str(exc)[:160]
    except AcpError as exc:
        return "erro", (str(exc) + " " + client.stderr_tail()[-200:]).strip()[:240]
    finally:
        client.close()


# ---------------------------------------------------------------------------- ambiente do processo filho
_PARENT_AGENT_ENV = re.compile(r"^(CLAUDECODE|CLAUDE_CODE_(?!EXECUTABLE$).*|CLAUDE_AGENT_SDK_.*|CLAUDE_PID|CLAUDE_EFFORT|"
                               r"CODEX_(THREAD|SESSION|SANDBOX).*|OPENCODE_(SERVER|PID|RUN).*)$")


def child_env(agent_id: str) -> dict[str, str | None]:
    """Variáveis do filho: REMOVE as herdadas de uma sessão-pai de outro agente (ex.: CLAUDECODE/CLAUDE_CODE_* quando o Eco foi
    aberto de dentro do Claude Code) e acerta o executável do Claude. Nunca devolve segredos: só remove ou aponta caminhos."""
    env: dict[str, str | None] = {k: None for k in os.environ if _PARENT_AGENT_ENV.match(k)}
    if agent_id == "claude":
        exe = shutil.which("claude.exe") or shutil.which("claude")
        if exe and exe.lower().endswith(".exe"):
            # sem isto o adaptador tenta executar o atalho do npm e falha com "spawn EFTYPE" no Windows
            env["CLAUDE_CODE_EXECUTABLE"] = exe
    if agent_id == "opencode":                                    # nega o que age no PC sem passar pelo Eco (só neste filho)
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"permission": {
            "bash": "deny", "edit": "deny", "write": "deny", "webfetch": "deny", "external_directory": "deny", "doom_loop": "deny"}})
    return env


# ---------------------------------------------------------------------------- modelos alternativos (só os do próprio filho)
# Se o modelo padrão do agente falhar por conta/crédito/modelo, o Eco tenta estes (nesta ordem, só os que o agente anunciar).
ALT_MODELS: dict[str, tuple[str, ...]] = {
    "opencode": ("opencode/big-pickle", "opencode/deepseek-v4.1-flash-free", "opencode/flint-40b-free", "opencode/beam-free"),
    "codex": ("gpt-6-luna[low]", "gpt-5.6-luna[low]", "gpt-5.6-terra[low]"),
    "copilot": ("auto",),
}

# Modelo mais rápido (voz precisa de latência baixa) quando o usuário não fixou nenhum e nada foi lembrado.
VOICE_DEFAULT: dict[str, str] = {"claude": "haiku"}

# ---------------------------------------------------------------------------- falhas que o agente devolve como "resposta"
_FAIL_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (re.compile(rx, re.I), kind, why) for rx, kind, why in (
        (r"usage limit|exceeded your (?:monthly |daily )?quota|monthly quota|rate.?limit|too many requests|"
         r"insufficient (?:credits?|quota|funds)|more credits|can only afford|billing|out of credits|quota (?:exceeded|exhausted)",
         "quota", "limite de uso ou créditos da conta esgotados"),
        (r"model\b.{0,80}\b(?:not available|not supported|not found|unavailable|does not exist)|not supported when using|"
         r"unknown model|invalid model", "model", "modelo indisponível para esta conta"),
        (r"unauthori[sz]ed|authentication (?:is )?required|not (?:logged|signed) in|please (?:log|sign) ?in|invalid (?:api )?key|"
         r"login required|\b401\b|\b403\b|provider authentication", "auth", "sem login ou credencial inválida"),
        (r"(?:^|[\n.:\]]\s*)(?:error|erro|fatal|failed|exception)\s*[:\-]|execution failed|internal (?:service )?error|"
         r"service ?unavailable|timed? ?out", "error", "o agente devolveu um erro"),
    ))
_PT_ACCENT = re.compile(r"[ãõçáéíóúâêô]")
_ERR_PREFIX = re.compile(r"^\s*(?:error|erro)\s*:", re.I)


def explain_failure(text: str) -> tuple[str, str] | None:
    """(tipo, motivo curto em português) se o texto que o agente devolveu é um ERRO (conta, modelo, login...) e não uma resposta.
    Só olha respostas curtas; o motivo nunca repete URLs, IDs ou trechos do erro. Texto em português que só cita "erro" passa."""
    t = (text or "").strip()
    if not t or len(t) > 700:
        return None
    for rx, kind, why in _FAIL_PATTERNS:
        if rx.search(t):
            if kind == "error" and _PT_ACCENT.search(t) and not _ERR_PREFIX.match(t):
                continue
            return kind, why
    return None
