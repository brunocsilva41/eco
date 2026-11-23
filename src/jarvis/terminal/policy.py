"""Política do terminal integrado: o que NUNCA roda, o que força confirmação, o que roda direto, pastas e segredos.

Camadas (nesta ordem):
1. BLOQUEIO FIXO: formatar/particionar disco, apagar raiz/sistema/perfil, `reg delete`, desligar/reiniciar, matar processos de
   terceiros, ler cofres de segredo (.ssh, .aws, .gnupg, OpenBot, Eco instalado...), executar código baixado/ofuscado,
   persistência e elevação. Nenhum modo (nem o livre) nem confirmação passa disso. `terminal.blocked_extra` acrescenta trechos.
2. CONFIRMAÇÃO FORÇADA: aponta para fora das pastas permitidas, `..` que escapa, arquivos .env/chaves.
3. LISTA PERMITIDA: comando SIMPLES (sem ; & | > < crase $( chaves) cujo começo está em `terminal.allowed_commands`.

Limite honesto: é uma rede de proteção por texto, não uma sandbox. A defesa real é a confirmação, a pasta de trabalho, o
ambiente sem segredos e o log. Ofuscação criativa pode escapar do texto; por isso o texto é normalizado antes (aspas, crases,
acentos circunflexos do cmd, invisíveis e Unicode) e `executar_comando` mostra o comando EXATO na confirmação.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config

__all__ = ["Verdict", "analyze", "normalize", "redact", "resolve_cwd", "clean_env", "visible", "is_simple", "allowlisted"]

_INVISIBLE = {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}
MAX_COMMAND_CHARS = 2000


@dataclass(frozen=True)
class Verdict:
    blocked: str | None = None                     # motivo (pt-BR): recusado SEMPRE
    confirm: tuple[str, ...] = ()                  # motivos que forçam confirmação mesmo na lista permitida
    allowlisted: bool = False                      # comando simples da lista permitida
    hidden_chars: int = 0                          # invisíveis encontrados (a confirmação avisa)
    paths: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- normalização
def normalize(command: str) -> str:
    """Forma canônica para comparar: Unicode NFKC, sem invisíveis, sem aspas/crases/circunflexo do cmd, minúsculas, espaços únicos."""
    text = unicodedata.normalize("NFKC", command)
    text = "".join(c for c in text if unicodedata.category(c) not in _INVISIBLE or c in "\t\r\n")
    text = re.sub(r"[`'\"^]", "", text)
    text = text.replace("/", "\\") if re.search(r"[a-zA-Z]:/", text) else text
    return re.sub(r"\s+", " ", text).strip().lower()


def hidden_count(command: str) -> int:
    return sum(1 for c in command if unicodedata.category(c) in _INVISIBLE and c not in "\t\r\n")


def visible(command: str, limit: int = 300) -> tuple[str, bool]:
    """Comando para MOSTRAR numa confirmação: sem controle/invisíveis, em uma linha; (texto, foi_cortado)."""
    one = " ⏎ ".join(part.strip() for part in command.splitlines() if part.strip())
    one = "".join(c for c in one if unicodedata.category(c) not in _INVISIBLE)
    return (one[:limit - 1] + "…", True) if len(one) > limit else (one, False)


# --------------------------------------------------------------------------- bloqueios fixos
_S = r"(?:^|[\s;&|(){}])"                           # início de comando/palavra
_BLOCK: tuple[tuple[re.Pattern[str], str], ...] = tuple((re.compile(p), why) for p, why in (
    (_S + r"(format(\.com)?\s+[a-z]:|(?:format-volume|clear-disk|remove-partition|initialize-disk|diskpart|mkfs\S*|bcdedit|fsutil|cipher\s+/w|sdelete)\b)",
     "formatar, particionar ou apagar um disco"),
    (_S + r"dd\s+if=", "gravar direto em disco (dd)"),
    (_S + r"(shutdown|restart-computer|stop-computer|logoff|psshutdown|wininit)(\.exe)?\b", "desligar, reiniciar ou sair do Windows"),
    (_S + r"(taskkill|tskill|stop-process|pkill|killall|kill\s+-?\d)", "encerrar processos (o Eco só encerra o que ele mesmo iniciou)"),
    (_S + r"wmic\s+process", "mexer em processos pelo WMIC"),
    (_S + r"reg(\.exe)?\s+(delete|save|restore|load|unload|import)\b", "alterar ou exportar o registro do Windows (reg)"),
    (_S + r"reg(\.exe)?\s+add\s+\S*(hklm|hkey_local_machine|\\run)", "gravar no registro do sistema ou no início automático"),
    (r"(remove|set|new|clear|rename|copy|move)-item(property)?\b.*\bhk(lm|cr|u|cc|ey_[a-z_]+)\b", "alterar o registro do Windows"),
    (r"\bhk(lm|cr|u)\s*:\\?.*\b(remove|clear)", "alterar o registro do Windows"),
    (r"\bhkcu:?\\.*\\run\b|\bhkey_current_user\\.*\\run\b", "gravar no início automático do Windows"),
    (_S + r"(runas|takeown)(\.exe)?\b|-verb\s+runas", "elevar privilégios"),
    (_S + r"icacls\b.*(/grant|/setowner|/reset|/remove)", "mudar permissões de arquivos"),
    (_S + r"schtasks(\.exe)?\s+/(create|change|delete)|(new|register|set)-scheduledtask", "criar ou alterar tarefas agendadas"),
    (_S + r"sc(\.exe)?\s+(create|config|delete|stop|start)\b|new-service|set-service|remove-service", "criar ou alterar serviços do Windows"),
    (_S + r"net(\.exe)?\s+(user|localgroup|accounts|share|use)\b", "mexer em contas, grupos ou compartilhamentos"),
    (_S + r"(set-executionpolicy|set-mppreference|add-mppreference|disable-windowsoptionalfeature|disable-computerrestore)\b",
     "enfraquecer a segurança do Windows"),
    (_S + r"netsh(\.exe)?\s+(advfirewall|firewall|winhttp|interface\s+portproxy)", "mexer em firewall ou rede do sistema"),
    (_S + r"(iex|invoke-expression)\b|downloadstring|frombase64string.*(iex|invoke)", "executar texto como código (iex)"),
    (r"(iwr|irm|invoke-webrequest|invoke-restmethod|curl|wget)\b.*\|\s*(iex|sh|bash|zsh|powershell|pwsh|cmd|python\S*|node)\b",
     "baixar e executar código na hora"),
    (_S + r"(powershell|pwsh)(\.exe)?\b.*\s-(e|ec|enc|encodedcommand)\b", "comando PowerShell codificado"),
    (_S + r"(mshta|wscript|cscript|bitsadmin|regsvr32|rundll32|installutil|msiexec)(\.exe)?\b", "programa de execução indireta de código"),
    (_S + r"certutil(\.exe)?\b.*(-urlcache|-decode|-encode|-split)", "certutil como baixador ou decodificador"),
    (_S + r"(cmdkey|vaultcmd|get-credential|mimikatz|procdump|lsass|ntdsutil)\b", "acessar credenciais do Windows"),
    (_S + r"(rm|del|erase|rd|rmdir|ri|remove-item)\b[^\n]*(?:^|[\s\\/])\.git[\\/]?\s*$", "apagar a pasta .git inteira"),
    (_S + r"gh\s+auth\s+(token|status\s+.*-t|refresh)", "ler o token do GitHub"),
    (_S + r"git\s+credential\b|git\s+config\s+.*credential|credential\.helper", "mexer em credenciais do git"),
    (_S + r"(printenv|env)\s*$|^set\s*$|(gci|ls|dir|get-childitem)\s+env:|get-item\s+env:|\[environment\]::getenvironmentvariables",
     "listar as variáveis de ambiente (podem ter segredos)"),
))

# pastas/arquivos com segredos ou o próprio Eco (leitura e escrita bloqueadas)
_SECRET_PATHS = re.compile(
    r"(\\|^|\s|/)(\.ssh|\.aws|\.gnupg|\.git-credentials|\.netrc|_netrc|\.kube|\.azure|\.docker\\config\.json|id_rsa|id_ed25519)(\\|/|$|\s|\.)"
    r"|\\appdata\\roaming\\openbot|\\openbot\\(agents|shared)\\|(\\|%|:)openbot(\\|\s|$)|\\\.config\\opencode|\\\.local\\share\\opencode|auth\.json"
    r"|\\atlas\\cli-bridge|\\programs\\(eco|eco)(\\|\s|$)|\\appdata\\local\\programs\\(eco|eco)|\\data\\control\\|yolo\.key"
    r"|\\microsoft\\credentials|\\microsoft\\protect|\\google\\chrome\\user data|\\microsoft\\edge\\user data|\\mozilla\\firefox\\profiles"
    r"|\\system32\\config\\(sam|system|security)|ntds\.dit")

_DELETE_VERBS = {"rm", "del", "erase", "rd", "rmdir", "ri", "remove-item"}
_SYSTEM_TARGET = re.compile(
    r"^(?:[a-z]:\\?\*?|\\\*?|/\*?|~/?\*?|\*|\.\.\\?\*?)$"
    r"|^[a-z]:\\(windows|users|program files|program files \(x86\)|programdata|\$recycle\.bin|system volume information)(\\.*)?$"
    r"|^~[\\/].*|^\$(env:)?(home|userprofile|programfiles|windir|systemroot|appdata|localappdata)\b"
    r"|^%(userprofile|systemroot|windir|programfiles|appdata|localappdata|homepath|systemdrive|programdata)%")
_DRIVE_PATH = re.compile(r"(?<![a-z0-9])([a-z]:[\\/][^\s\"'|;&<>()]*)", re.I)
_UNC_PATH = re.compile(r"(?<![\w:\\])\\\\[^\s\"'|;&<>()\\][^\s\"'|;&<>()]*")
_ENV_FILE = re.compile(r"(^|[\\/\s])\.env(\.[a-z0-9_-]+)?(\s|$)|(secret|credential|token|password)s?\.(json|txt|ya?ml|ini|xml|key)|\.(pem|pfx|p12|key)(\s|$)")
_META = re.compile(r"[;&|<>`${}\n\r%^]|\$\(")
_BAD_ARGS = ("--output", "--exec", "--ext-diff", "--textconv", "--open-files-in-pager", "--upload-pack", "--git-dir", "--work-tree", "-c")


def is_simple(command: str) -> bool:
    """Um comando só, sem encadear, redirecionar, expandir ou substituir (candidato à lista permitida)."""
    return bool(command.strip()) and "\n" not in command.strip() and not _META.search(command)


def allowlisted(command: str, allowed: tuple[str, ...]) -> bool:
    if not is_simple(command):
        return False
    toks = command.strip().lower().split()
    if any(t.startswith(_BAD_ARGS) or t in _BAD_ARGS for t in toks[1:]):
        return False
    for entry in allowed:
        e = entry.strip().lower().split()
        if e and toks[:len(e)] == e:
            return True
    return False


def _within(path: str, roots: list[str]) -> bool:
    low = os.path.normcase(os.path.normpath(path))
    return any(low == r or low.startswith(r + os.sep) for r in roots)


def _norm_roots(roots: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for r in roots:
        try:
            out.append(os.path.normcase(os.path.normpath(str(Path(r).resolve()))))
        except OSError:
            out.append(os.path.normcase(os.path.normpath(r)))
    return out


def analyze(command: str, cfg: Config, cwd: str | Path | None = None) -> Verdict:
    """Classifica o comando. `cwd` é a pasta onde ele vai rodar (para resolver `..` e caminhos relativos)."""
    t = cfg.terminal
    if not command or not command.strip():
        return Verdict(blocked="comando vazio")
    if len(command) > MAX_COMMAND_CHARS:
        return Verdict(blocked=f"comando longo demais (máximo {MAX_COMMAND_CHARS} caracteres)")
    hidden = hidden_count(command)
    n = normalize(command)
    for pat, why in _BLOCK:
        if pat.search(n):
            return Verdict(blocked=why, hidden_chars=hidden)
    for extra in t.blocked_extra:
        if normalize(extra) and normalize(extra) in n:
            return Verdict(blocked=f"contém «{extra.strip()[:40]}», bloqueado nas suas configurações", hidden_chars=hidden)
    if _SECRET_PATHS.search(n):
        return Verdict(blocked="aponta para um local de segredos ou para o próprio Eco", hidden_chars=hidden)
    toks = n.split()
    if toks and any(tok in _DELETE_VERBS for tok in toks):
        for tok in [*toks, *(f"{a} {b}" for a, b in zip(toks, toks[1:]))]:      # pares: «c:\program files» tem espaço
            if tok in _DELETE_VERBS or tok.startswith("-") or (tok.startswith("/") and 2 <= len(tok) <= 4 and tok[1].isalpha()):
                continue
            if _SYSTEM_TARGET.match(tok.strip("\\") if len(tok) > 3 else tok):
                return Verdict(blocked="apagar a raiz de um disco, o Windows, o perfil ou as pastas do sistema", hidden_chars=hidden)

    reasons: list[str] = []
    roots = _norm_roots(t.roots)
    base = Path(cwd) if cwd else None
    seen: list[str] = []
    for m in [*_DRIVE_PATH.findall(command), *_UNC_PATH.findall(command)]:
        seen.append(m)
        if not _within(m.rstrip("\\/") or m, roots):
            reasons.append(f"aponta para fora das pastas permitidas ({m[:60]})")
    if base is not None:
        for tok in re.findall(r"[^\s\"'|;&<>()]*\.\.[^\s\"'|;&<>()]*", command):
            if not re.match(r"^[a-zA-Z]:", tok):
                target = os.path.normpath(os.path.join(str(base), tok))
                if not _within(target, roots):
                    reasons.append(f"«{tok[:40]}» sai das pastas permitidas")
    if _ENV_FILE.search(n):
        reasons.append("mexe em arquivo que costuma guardar segredos (.env, chaves, tokens)")
    uniq = tuple(dict.fromkeys(reasons))
    return Verdict(confirm=uniq, allowlisted=allowlisted(command, t.allowed_commands), hidden_chars=hidden, paths=tuple(seen))


# --------------------------------------------------------------------------- pasta de trabalho
def resolve_cwd(requested: str | None, current: str | Path | None, cfg: Config) -> tuple[Path | None, str]:
    """(pasta resolvida, erro). A pasta TEM de existir e estar dentro de `terminal.roots` (links/junções resolvidos)."""
    roots = _norm_roots(cfg.terminal.roots)
    if not roots:
        return None, "nenhuma pasta permitida para o terminal (veja Configurações > Terminal)"
    raw = (requested or "").strip()
    if raw:
        cand = Path(raw)
        if not cand.is_absolute():
            cand = Path(current or cfg.terminal.roots[0]) / cand
    else:
        cand = Path(current) if current else Path(cfg.terminal.roots[0])
    try:
        real = cand.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, f"a pasta «{str(cand)[:80]}» não existe"
    if not real.is_dir():
        return None, f"«{str(cand)[:80]}» não é uma pasta"
    if not _within(str(real), roots):
        return None, f"a pasta «{str(real)[:80]}» está fora das pastas permitidas do terminal"
    return real, ""


# --------------------------------------------------------------------------- segredos
_SECRET_ENV = re.compile(r"(token|secret|passw|passwd|pwd|apikey|api_key|api-key|credential|private_key|auth|session|cookie|bearer)", re.I)
_KEEP_ENV = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA",
             "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "COMPUTERNAME", "USERNAME", "OS", "PROCESSOR_ARCHITECTURE",
             "NUMBER_OF_PROCESSORS", "SYSTEMDRIVE", "PSMODULEPATH", "LANG", "HOME"}


def clean_env() -> dict[str, str]:
    """Ambiente do filho SEM segredos: tira variáveis com cara de token/senha/chave e as do próprio Eco."""
    out: dict[str, str] = {}
    for k, v in os.environ.items():
        if k.upper() in _KEEP_ENV or not (_SECRET_ENV.search(k) or k.upper().startswith(("JARVIS_", "OPENBOT_", "ANTHROPIC_", "OPENAI_", "GH_", "GITHUB_"))):
            out[k] = v
    out["PYTHONIOENCODING"] = "utf-8"
    out["GIT_TERMINAL_PROMPT"] = "0"                 # nunca fica esperando senha
    out["GCM_INTERACTIVE"] = "never"
    out["NO_COLOR"] = "1"
    try:                                             # programas com caminho PERSONALIZADO entram no PATH do terminal (git, python, ffmpeg...)
        from ..core import toolpaths
        extra: list[str] = []
        for key in ("git", "python", "ffmpeg", "ollama"):
            d = toolpaths.BY_KEY[key]
            if toolpaths.is_custom(d):
                f = toolpaths.resolve(key)
                if f.path is not None and f.source == toolpaths.SRC_CUSTOM and str(f.path.parent) not in extra:
                    extra.append(str(f.path.parent))
        if extra:
            pk = next((k for k in out if k.upper() == "PATH"), "PATH")
            out[pk] = os.pathsep.join(extra + [out.get(pk, "")])
    except Exception:                                # noqa: BLE001  (caminho personalizado ruim nunca derruba o terminal)
        pass
    return out


_REDACT: tuple[tuple[re.Pattern[str], str], ...] = tuple((re.compile(p, re.I), r) for p, r in (
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)", "[chave privada removida]"),
    (r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})", "[token removido]"),
    (r"\b(sk-[A-Za-z0-9_-]{16,}|sk_live_[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{12,}|AIza[0-9A-Za-z_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|glpat-[A-Za-z0-9_-]{16,})", "[chave removida]"),
    (r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}", "[jwt removido]"),
    (r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)", "[credenciais removidas]"),
    (r"(\bbearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1[removido]"),
    (r"(\b[\w.-]*(?:token|secret|segredo|senha|passw(?:or)?d|passwd|pwd|api[_-]?key|apikey|authorization|private[_-]?key|credential)[\w.-]*\s*[=:]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s\"',;]+)", r"\1[removido]"),
))


def redact(text: str) -> str:
    for pat, repl in _REDACT:
        text = pat.sub(repl, text)
    return text
