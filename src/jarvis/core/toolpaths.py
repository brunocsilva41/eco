"""Onde está cada programa/arquivo de apoio do Eco: achar, validar, personalizar e varrer (sem Qt, testável).

* Cada ferramenta tem um item no CATALOG. O caminho PERSONALIZADO (config) vale antes de qualquer busca automática.
* `resolve(key)` diz onde a ferramenta está, de onde veio a informação (personalizado, PATH, instalação padrão, pasta do Eco)
  e a versão. É o que o app inteiro usa (agentes ACP, Terminal, escuta, doctor, Setup).
* `validate_path(key, texto)` confere um caminho digitado: não é de rede, existe, é do tipo certo, é MESMO aquela ferramenta
  (nome + `--version`/marcadores), versão mínima, permissão de escrita (pastas) e, para executável fora de pastas confiáveis,
  a assinatura digital (sem assinatura válida = pede confirmação).
* `scan_all()` varre tudo para a tela "Preparar o computador", o relatório e `Eco.cmd doctor --full`.
Só LÊ: nunca instala, apaga nem executa nada além de `--version` com tempo limite.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable

log = logging.getLogger("jarvis.toolpaths")
_NOWIN = 0x08000000

SRC_CUSTOM = "caminho personalizado"
SRC_PATH = "PATH do Windows"
SRC_STD = "instalação padrão"
SRC_ECO = "pasta do Eco"
SRC_DEFAULT = "padrão do Eco"
SRC_NONE = "não encontrado"


# ----------------------------------------------------------------------------- catálogo
@dataclass(frozen=True)
class ToolDef:
    key: str
    title: str
    kind: str                                   # exe | dir | file
    cfg: tuple[str, str]                        # (seção, campo) do config onde o caminho fica
    category: str                               # Sistema | Eco | Modelos | Agentes | Opcional
    names: tuple[str, ...] = ()                 # nomes aceitos do executável (sem extensão)
    markers: tuple[str, ...] = ()               # (dir) arquivos que precisam existir dentro da pasta
    suffixes: tuple[str, ...] = ()              # (file) extensões aceitas
    version_args: tuple[str, ...] = ("--version",)
    min_version: tuple[int, ...] = ()
    optional: bool = False
    std_dirs: tuple[str, ...] = ()              # pastas padrão (aceitam %VARIAVEIS%)
    help: str = ""                              # o que fazer quando falta
    url: str = ""                               # site oficial para baixar
    fix: str = ""                               # chave da ação do Setup (download_models, install_vcredist, install_ollama, open_url)
    writable: bool = False                      # (dir) precisa de permissão de escrita
    magic: bytes = b""                          # (file) primeiros bytes esperados
    min_size: int = 0
    ident: str = ""                             # (exe) regex que a resposta de --version precisa casar (garante que é MESMO a ferramenta)


def _eco_root() -> Path:
    from ..config import ROOT
    return ROOT


CATALOG: tuple[ToolDef, ...] = (
    ToolDef("llama_server", "Servidor do modelo (llama.cpp)", "dir", ("paths", "llama_bin"), "Eco", markers=("llama-server.exe",),
            help="Reinstale ou use Reparar: o instalador traz o llama-server (Vulkan).", fix="repair"),
    ToolDef("whispercpp", "Escuta na placa de vídeo (whisper.cpp)", "dir", ("toolpaths", "whispercpp_dir"), "Eco", optional=True,
            markers=("jarvis_whisper.dll",), help="Sem isso a escuta usa a CPU (mais lenta). Reinstale ou use Reparar."),
    ToolDef("models_dir", "Pasta dos modelos", "dir", ("paths", "models"), "Eco", writable=True,
            help="Pasta onde ficam os modelos baixados. Precisa existir e aceitar gravação."),
    ToolDef("data_dir", "Pasta de dados (memória, logs, gravações)", "dir", ("paths", "data"), "Eco", writable=True,
            help="Pasta do banco de memória e do estado. Precisa aceitar gravação."),
    ToolDef("llm_model", "Modelo de linguagem (.gguf)", "file", ("llm", "model"), "Modelos", suffixes=(".gguf",), magic=b"GGUF",
            min_size=50_000_000, help="Baixe pelo Setup (SHA-256 conferido).", fix="download_models"),
    ToolDef("llm_mmproj", "Visão (mmproj .gguf)", "file", ("llm", "mmproj"), "Modelos", optional=True, suffixes=(".gguf",), magic=b"GGUF",
            min_size=1_000_000, help="Sem isso o Eco não enxerga a tela.", fix="download_models"),
    ToolDef("stt_gpu_model", "Modelo de escuta (ggml)", "file", ("stt", "gpu_model"), "Modelos", optional=True, suffixes=(".bin",),
            min_size=10_000_000, help="Sem isso a escuta usa a CPU.", fix="download_models"),
    ToolDef("stt_model_dir", "Modelo de escuta (pasta, CPU)", "dir", ("stt", "model_dir"), "Modelos", markers=("model.bin",), optional=True,
            help="Usado só se a escuta cair para a CPU. Baixe pelo Setup.", fix="download_models"),
    ToolDef("tts_voice", "Voz Piper (.onnx)", "file", ("tts", "voice_onnx"), "Modelos", suffixes=(".onnx",), min_size=1_000_000,
            help="Baixe pelo Setup.", fix="download_models"),
    ToolDef("tts_voice_json", "Voz Piper (.json)", "file", ("tts", "voice_json"), "Modelos", suffixes=(".json",), min_size=10,
            help="Acompanha a voz; baixe pelo Setup.", fix="download_models"),
    ToolDef("git", "Git", "exe", ("toolpaths", "git"), "Sistema", names=("git",), min_version=(2, 20), optional=True, ident=r"git version",
            std_dirs=(r"%ProgramFiles%\Git\cmd", r"%ProgramFiles(x86)%\Git\cmd", r"%LocalAppData%\Programs\Git\cmd"),
            help="Usado pelo Terminal integrado.", url="https://git-scm.com/download/win", fix="open_url"),
    ToolDef("git_bash", "Git Bash", "exe", ("toolpaths", "git_bash"), "Sistema", names=("bash",), optional=True,
            std_dirs=(r"%ProgramFiles%\Git\bin", r"%ProgramFiles(x86)%\Git\bin", r"%LocalAppData%\Programs\Git\bin"),
            help="Vem com o Git for Windows (nunca o bash do WSL).", url="https://git-scm.com/download/win", fix="open_url"),
    ToolDef("powershell", "PowerShell", "exe", ("toolpaths", "powershell"), "Sistema", names=("pwsh", "powershell"), min_version=(5, 1),
            version_args=("-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"),
            std_dirs=(r"%ProgramFiles%\PowerShell\7", r"%SystemRoot%\System32\WindowsPowerShell\v1.0"),
            help="Usado pelo Terminal integrado. O Windows já traz o PowerShell 5.1."),
    ToolDef("python", "Python (apoio)", "exe", ("toolpaths", "python"), "Sistema", names=("python", "python3", "py"), optional=True,
            min_version=(3, 9), ident=r"python", std_dirs=(r"%LocalAppData%\Programs\Python",), url="https://www.python.org/downloads/windows/", fix="open_url",
            help="Só para comandos de Python no Terminal; o Eco roda com o Python dele."),
    ToolDef("ffmpeg", "FFmpeg", "exe", ("toolpaths", "ffmpeg"), "Opcional", names=("ffmpeg",), optional=True, version_args=("-version",),
            ident=r"ffmpeg version",
            std_dirs=(r"%LocalAppData%\Microsoft\WinGet\Links", r"C:\ffmpeg\bin", r"%ProgramFiles%\ffmpeg\bin"),
            help="O Eco não depende dele; serve a comandos de vídeo pelo Terminal.", url="https://www.gyan.dev/ffmpeg/builds/", fix="open_url"),
    ToolDef("ollama", "Ollama", "exe", ("toolpaths", "ollama"), "Opcional", names=("ollama",), optional=True,
            std_dirs=(r"%LocalAppData%\Programs\Ollama",), help="Opcional. O Eco já traz o próprio servidor de modelo.",
            url="https://ollama.com/download", fix="install_ollama"),
    ToolDef("lmstudio", "LM Studio", "exe", ("toolpaths", "lmstudio"), "Opcional", names=("lm studio", "lms"), optional=True,
            version_args=(), std_dirs=(r"%LocalAppData%\Programs\LM Studio",), help="Opcional.", url="https://lmstudio.ai/", fix="open_url"),
    ToolDef("opencode", "OpenCode (agente ACP)", "exe", ("toolpaths", "opencode"), "Agentes", names=("opencode",), optional=True,
            std_dirs=(r"%AppData%\npm", r"%USERPROFILE%\.opencode\bin"), help="Agente de nuvem opcional. Instale: npm i -g opencode-ai",
            url="https://opencode.ai/", fix="open_url"),
    ToolDef("antigravity", "Google Antigravity (agy)", "exe", ("toolpaths", "antigravity"), "Agentes", names=("agy",), optional=True,
            std_dirs=(r"%LocalAppData%\Programs\Antigravity\bin", r"%AppData%\npm"), help="Agente de nuvem opcional.", url="https://antigravity.google/",
            fix="open_url"),
    ToolDef("claude", "Claude Code", "exe", ("toolpaths", "claude"), "Agentes", names=("claude",), optional=True,
            std_dirs=(r"%AppData%\npm", r"%USERPROFILE%\.local\bin"), help="Agente de nuvem opcional.", url="https://claude.com/product/claude-code",
            fix="open_url"),
    ToolDef("codex", "OpenAI Codex CLI", "exe", ("toolpaths", "codex"), "Agentes", names=("codex",), optional=True,
            std_dirs=(r"%AppData%\npm",), help="Agente de nuvem opcional.", url="https://github.com/openai/codex", fix="open_url"),
    ToolDef("copilot", "GitHub Copilot CLI", "exe", ("toolpaths", "copilot"), "Agentes", names=("copilot",), optional=True,
            std_dirs=(r"%AppData%\npm", r"%LocalAppData%\Microsoft\WinGet\Links"), help="Agente de nuvem opcional.",
            url="https://github.com/features/copilot/cli", fix="open_url"),
)
BY_KEY: dict[str, ToolDef] = {t.key: t for t in CATALOG}
EXE_EXTS = (".exe", ".cmd", ".bat", ".com")


# ----------------------------------------------------------------------------- configuração atual
_cfg_cache: dict = {"mtime": None, "cfg": None, "override": None}


def configure(cfg) -> None:
    """Fixa a configuração usada (o app chama ao iniciar e depois de salvar). None volta a ler do config.toml."""
    _cfg_cache["override"] = cfg


def _cfg():
    if _cfg_cache["override"] is not None:
        return _cfg_cache["override"]
    from ..config import CONFIG_FILE, load
    try:
        mt = CONFIG_FILE.stat().st_mtime_ns
    except OSError:
        mt = None
    if _cfg_cache["cfg"] is None or _cfg_cache["mtime"] != mt:
        try:
            _cfg_cache["cfg"] = load(CONFIG_FILE)
        except Exception:                                            # noqa: BLE001  (config inválida: usa os padrões)
            from ..config import from_dict
            _cfg_cache["cfg"] = from_dict({})
        _cfg_cache["mtime"] = mt
    return _cfg_cache["cfg"]


def default_value(d: ToolDef) -> str:
    """Valor padrão do config para esta ferramenta ('' quando é automático)."""
    from ..config import Config
    base = getattr(getattr(Config(), d.cfg[0]), d.cfg[1])
    return "" if base is None or base == "" else str(base)


def configured_value(d: ToolDef, cfg=None) -> str:
    v = getattr(getattr(cfg or _cfg(), d.cfg[0]), d.cfg[1])
    return "" if v is None else str(v)


def is_custom(d: ToolDef, cfg=None) -> bool:
    cur = configured_value(d, cfg)
    return bool(cur) and os.path.normcase(os.path.normpath(cur)) != os.path.normcase(os.path.normpath(default_value(d) or "?"))


def config_key(d: ToolDef) -> str:
    return f"{d.cfg[0]}.{d.cfg[1]}"


# ----------------------------------------------------------------------------- busca automática
def _expand(p: str) -> Path:
    return Path(os.path.expandvars(p))


def _exe_in(dirpath: Path, names: tuple[str, ...]) -> Path | None:
    for n in names:
        for ext in EXE_EXTS:
            c = dirpath / (n + ext)
            if c.is_file():
                return c
    return None


def find_exe_auto(d: ToolDef) -> tuple[Path | None, str]:
    """(caminho, de onde veio) pela busca automática: PATH, instalação padrão. Nunca o python/bash do WSL ou da Microsoft Store (stub)."""
    for n in d.names:
        w = shutil.which(n)
        if w and not _is_store_stub(Path(w)) and not _is_wsl_bash(Path(w)):
            return Path(w), SRC_PATH
    for sd in d.std_dirs:
        p = _expand(sd)
        if p.is_dir():
            f = _exe_in(p, d.names)
            if f is None and d.key == "python":                      # %LocalAppData%\Programs\Python\Python3xx\python.exe
                for sub in sorted(p.glob("Python3*"), reverse=True):
                    f = _exe_in(sub, d.names)
                    if f:
                        break
            if f:
                return f, SRC_STD
    return None, SRC_NONE


def _is_store_stub(p: Path) -> bool:
    return "\\windowsapps\\" in str(p).lower() and p.stat().st_size == 0 if p.exists() else False


def _is_wsl_bash(p: Path) -> bool:
    low = str(p).lower().replace("/", "\\")
    return p.name.lower() == "bash.exe" and ("\\system32\\" in low or "\\windowsapps\\" in low)


def find_dir_auto(d: ToolDef) -> tuple[Path | None, str]:
    root = _eco_root()
    cands: list[Path] = []
    if d.key == "whispercpp":
        cands = [root / "bin" / "whispercpp-vulkan"]
    elif d.key == "llama_server":
        cands = sorted((root / "bin").glob("llama-*vulkan*"), reverse=True) if (root / "bin").is_dir() else []
    elif d.key == "models_dir":
        cands = [root / "models"]
    elif d.key == "data_dir":
        cands = [root / "data"]
    for c in cands:
        if c.is_dir() and all((c / m).exists() for m in d.markers):
            return c, SRC_ECO
    if d.key in ("models_dir", "data_dir") and cands:
        return cands[0], SRC_ECO
    return None, SRC_NONE


def detect(key: str) -> tuple[Path | None, str]:
    """Busca AUTOMÁTICA (ignora o caminho personalizado)."""
    d = BY_KEY[key]
    if d.kind == "exe":
        return find_exe_auto(d)
    if d.kind == "dir":
        return find_dir_auto(d)
    dv = default_value(d)
    if dv and Path(dv).is_file():
        return Path(dv), SRC_DEFAULT
    return None, SRC_NONE


# ----------------------------------------------------------------------------- versão
_VER = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(text: str) -> tuple[int, ...] | None:
    m = _VER.search(text or "")
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def _ver_str(v: tuple[int, ...]) -> str:
    return ".".join(str(x) for x in v)


def read_version(exe: Path, args: tuple[str, ...], timeout: float = 15.0) -> tuple[int | None, str]:
    """Roda `exe args` (só ler a versão). Devolve (código, primeira linha útil). Nunca passa nada do usuário no comando."""
    if not args:
        return 0, ""
    try:
        cmd = [str(exe), *args]
        if exe.suffix.lower() in (".cmd", ".bat"):
            cmd = [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", str(exe), *args]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=_NOWIN, stdin=subprocess.DEVNULL, cwd=str(exe.parent))
    except subprocess.TimeoutExpired:
        return None, "demorou demais para responder"
    except OSError as exc:
        return -2, str(exc)                                          # não é um programa executável (ou foi bloqueado)
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip().splitlines()
    return r.returncode, (out[0].strip()[:120] if out else "")


# ----------------------------------------------------------------------------- validação de um caminho
@dataclass(frozen=True)
class Validation:
    status: str                                 # ok | warn | fail
    message: str
    path: str = ""
    version: str = ""
    confirm: str = ""                           # texto de confirmação exigido (executável não confiável); vazio = nenhum
    source: str = ""

    @property
    def ok(self) -> bool:
        return self.status != "fail"


def _trusted_roots() -> list[str]:
    ev = os.environ
    roots = [str(_eco_root()), ev.get("ProgramFiles", ""), ev.get("ProgramFiles(x86)", ""), ev.get("SystemRoot", r"C:\Windows"),
             str(Path(ev.get("LocalAppData", "")) / "Programs"), str(Path(ev.get("AppData", "")) / "npm"),
             str(Path(ev.get("LocalAppData", "")) / "Microsoft" / "WinGet"), str(Path.home() / ".local"), str(Path.home() / ".opencode"),
             str(Path(ev.get("LocalAppData", "")) / "Microsoft" / "WindowsApps")]
    return [os.path.normcase(os.path.normpath(r)) + os.sep for r in roots if r]


def in_trusted_dir(p: Path) -> bool:
    low = os.path.normcase(os.path.normpath(str(p))) + os.sep
    return any(low.startswith(r) for r in _trusted_roots())


def _writable(dirp: Path) -> bool:
    try:
        dirp.mkdir(parents=True, exist_ok=True)
        probe = dirp / f".eco-w{os.getpid()}"
        probe.write_bytes(b"x")
        probe.unlink()
        return True
    except OSError:
        return False


def _signature_ok(p: Path) -> tuple[bool, str]:
    if p.suffix.lower() not in (".exe", ".com"):
        return False, "script sem assinatura"
    try:
        from ..setup import prereqs
        s = prereqs.verify_authenticode(p)
        return s.valid, prereqs.signer_name(s.subject) if s.valid else s.status
    except Exception as exc:                                         # noqa: BLE001
        return False, str(exc)


def validate_path(key: str, text: str, *, run_version: bool = True, check_signature: bool = True,
                  signature: Callable[[Path], tuple[bool, str]] = _signature_ok) -> Validation:
    """Valida o que a pessoa digitou/escolheu para `key`. Mensagens em pt-BR, dizendo o que houve e o que fazer."""
    from ..config import is_network_path
    d = BY_KEY[key]
    raw = (text or "").strip().strip('"').strip()
    if not raw:
        return Validation("ok", "Automático: o Eco procura sozinho.", "")
    if is_network_path(raw):
        return Validation("fail", "Caminho de rede não é aceito. Copie para uma pasta do seu computador e escolha de lá.")
    p = Path(os.path.expandvars(raw))
    if not p.is_absolute():
        p = _eco_root() / p
    if not p.exists():
        return Validation("fail", f"Não existe: {p}. Confira o endereço ou use “Detectar automaticamente”.")
    # ---- tipo certo
    if d.kind == "dir" and not p.is_dir():
        return Validation("fail", "Aqui precisa ser uma PASTA, e este caminho é um arquivo.")
    if d.kind in ("exe", "file") and p.is_dir():
        # pasta que contém o executável certo: aceita e aponta o arquivo
        if d.kind == "exe":
            f = _exe_in(p, d.names)
            if f is not None:
                p = f
            else:
                return Validation("fail", f"Aqui precisa ser o programa ({' ou '.join(n + '.exe' for n in d.names)}), não uma pasta. "
                                          "Escolha o arquivo dentro dela.")
        else:
            return Validation("fail", "Aqui precisa ser um ARQUIVO, e este caminho é uma pasta.")
    # ---- é a ferramenta certa?
    if d.kind == "exe":
        if p.suffix.lower() not in EXE_EXTS:
            return Validation("fail", f"Isto não é um programa ({p.suffix or 'sem extensão'}). Escolha um {' / '.join(EXE_EXTS)}.")
        if p.stem.lower() not in d.names:
            other = next((t for t in CATALOG if t.kind == "exe" and p.stem.lower() in t.names and t.key != d.key), None)
            who = f"“{other.title}”" if other else f"“{p.name}”"
            return Validation("fail", f"Este programa parece ser {who}, não {d.title}. Escolha {' ou '.join(n + '.exe' for n in d.names)}.")
        if d.key == "git_bash" and _is_wsl_bash(p):
            return Validation("fail", "Este bash.exe é o do WSL (Linux). O Eco usa só o Git Bash, que vem com o Git for Windows.")
    elif d.kind == "dir":
        miss = [m for m in d.markers if not (p / m).exists()]
        if miss:
            hint = ""
            sub = next((c.parent for c in p.rglob(d.markers[0])), None) if d.markers and p.is_dir() else None
            if sub:
                hint = f" Achei em {sub}; escolha essa pasta."
            return Validation("fail", f"Esta pasta não parece ser a certa: não achei {', '.join(miss)} nela.{hint}")
        if d.writable and not _writable(p):
            return Validation("fail", "Não consigo gravar nesta pasta. Escolha uma pasta sua (Documentos, outra unidade) ou libere a permissão.")
    else:                                                            # file
        if d.suffixes and p.suffix.lower() not in d.suffixes:
            return Validation("fail", f"Este arquivo não é do tipo certo (precisa terminar em {' ou '.join(d.suffixes)}).")
        try:
            size = p.stat().st_size
            head = b""
            if d.magic:
                with p.open("rb") as fh:
                    head = fh.read(max(len(d.magic), 4))
        except OSError as exc:
            return Validation("fail", f"Não consegui ler o arquivo: {exc.strerror or exc}")
        if size < max(d.min_size, 1):
            return Validation("fail", f"Arquivo pequeno demais ({size} bytes): parece incompleto ou de outra coisa.")
        if d.magic and not head.startswith(d.magic):
            return Validation("fail", f"O conteúdo não é do formato esperado ({d.magic.decode('latin1')}). Pode ser outro arquivo ou estar corrompido.")
        if d.suffixes == (".json",):
            try:
                json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return Validation("fail", "O arquivo .json está ilegível ou inválido.")
        return Validation("ok", "Arquivo válido.", str(p))
    if d.kind == "dir":
        return Validation("ok", "Pasta válida.", str(p))
    # ---- executável: versão
    version = ""
    if run_version and d.version_args:
        code, line = read_version(p, d.version_args)
        if code == -2:
            return Validation("fail", f"Este arquivo não executa como programa ({line[:80]}). Escolha o executável certo.")
        if code is None:
            return Validation("warn", f"Não consegui conferir a versão ({line}). Dá para usar, mas teste depois.", str(p))
        if code != 0 and not line:
            return Validation("fail", "O programa não respondeu como esperado. Parece que não é a ferramenta certa ou está quebrado.")
        if d.ident and not re.search(d.ident, line or "", re.I):
            return Validation("fail", f"A resposta de “--version” não é de {d.title} ({(line or 'vazia')[:60]}). "
                                      "Este programa parece ser outra coisa; escolha o certo.")
        v = parse_version(line) if line else None
        version = _ver_str(v) if v else line[:40]
        if d.min_version and v and v < d.min_version:
            return Validation("fail", f"Versão {version} é antiga; o Eco precisa da {_ver_str(d.min_version)} ou mais nova.", str(p), version)
    # ---- confiança
    msg = "Programa válido" + (f" (versão {version})" if version else "") + "."
    confirm = ""
    if not in_trusted_dir(p):
        ok, who = signature(p) if check_signature else (False, "não conferida")
        if ok:
            msg += f" Assinado por {who}."
        else:
            confirm = (f"Este programa está fora das pastas confiáveis e NÃO tem assinatura digital válida ({who}). "
                       "Só use se você sabe de onde ele veio e confia nele.")
            return Validation("warn", msg + " " + confirm, str(p), version, confirm)
    return Validation("ok", msg, str(p), version)


# ----------------------------------------------------------------------------- resolver (usado pelo app todo)
@dataclass(frozen=True)
class Found:
    key: str
    path: Path | None
    source: str
    version: str = ""
    problem: str = ""                           # caminho personalizado que não valeu (ainda usa a busca automática)

    @property
    def found(self) -> bool:
        return self.path is not None


def resolve(key: str, cfg=None, *, with_version: bool = False) -> Found:
    """Onde está a ferramenta AGORA: personalizado (se existir e for válido), senão busca automática. Sem rodar nada por padrão."""
    d = BY_KEY[key]
    problem = ""
    cur = configured_value(d, cfg)
    if cur and is_custom(d, cfg):
        v = validate_path(key, cur, run_version=False, check_signature=False)
        if v.ok and v.path:
            return Found(key, Path(v.path), SRC_CUSTOM, "", "")
        problem = f"o caminho personalizado não vale ({v.message}); usei a busca automática"
    elif cur and d.kind != "exe":                       # valor padrão do Eco
        p = Path(cur)
        p = p if p.is_absolute() else _eco_root() / p
        if p.exists():
            return Found(key, p, SRC_DEFAULT)
    path, src = detect(key)
    if path is None and cur and d.kind != "exe":
        p = Path(cur)
        p = p if p.is_absolute() else _eco_root() / p
        return Found(key, None, SRC_NONE, "", problem or f"esperado em {p}")
    return Found(key, path, src, "", problem)


def exe(key: str) -> str | None:
    """Atalho: caminho do executável (str) ou None. Usado no lugar de shutil.which pelo resto do app."""
    f = resolve(key)
    return str(f.path) if f.path is not None else None


# ----------------------------------------------------------------------------- varredura
@dataclass
class ScanItem:
    key: str
    title: str
    category: str
    status: str                                 # ok | warn | fail | info
    path: str = ""
    where: str = ""
    version: str = ""
    detail: str = ""
    hint: str = ""
    custom: bool = False
    optional: bool = False
    fix: str = ""
    url: str = ""
    config_key: str = ""


def scan_tool(key: str, cfg=None, *, with_version: bool = True) -> ScanItem:
    d = BY_KEY[key]
    f = resolve(key, cfg)
    custom = is_custom(d, cfg)
    base = dict(key=key, title=d.title, category=d.category, custom=custom, optional=d.optional, fix=d.fix, url=d.url, config_key=config_key(d))
    if f.path is None:
        status = "info" if d.optional else "fail"
        detail = "não instalado" if d.kind == "exe" else ("não encontrado" + (f" ({f.problem})" if f.problem else ""))
        if f.problem and custom:
            detail = f.problem
        return ScanItem(status=status, detail=detail, hint=d.help, **base)
    version = ""
    status, detail, hint = "ok", "", ""
    if d.kind == "exe" and with_version and d.version_args:
        code, line = read_version(f.path, d.version_args, timeout=12.0)
        v = parse_version(line) if line else None
        version = _ver_str(v) if v else (line[:40] if code == 0 else "")
        if code is None:
            status, detail = "warn", f"não respondeu à consulta de versão ({line})"
        elif d.min_version and v and v < d.min_version:
            status, detail = "warn", f"versão {version} é antiga (precisa de {_ver_str(d.min_version)} ou mais nova)"
    elif d.kind == "dir" and d.writable and not _writable(f.path):
        status, detail = "fail", "sem permissão de gravação"
    elif d.kind == "file":
        v = validate_path(key, str(f.path), run_version=False, check_signature=False)
        if not v.ok:
            status, detail = ("warn" if d.optional else "fail"), v.message
    elif d.kind == "dir" and d.markers:
        miss = [m for m in d.markers if not (f.path / m).exists()]
        if miss:
            status, detail = ("warn" if d.optional else "fail"), f"falta {', '.join(miss)}"
    if f.problem:
        status = "warn" if status == "ok" else status
        detail = (detail + "; " if detail else "") + f.problem
    return ScanItem(status=status, path=str(f.path), where=f.source, version=version, detail=detail or "encontrado", hint=hint, **base)


def scan_all(cfg=None, *, with_version: bool = True, progress: Callable[[ScanItem], None] | None = None) -> list[ScanItem]:
    """Varre todo o catálogo (em paralelo: cada `--version` é um processo curto)."""
    out: dict[str, ScanItem] = {}
    lock = threading.Lock()

    def one(k: str) -> None:
        try:
            it = scan_tool(k, cfg, with_version=with_version)
        except Exception as exc:                                     # noqa: BLE001
            d = BY_KEY[k]
            it = ScanItem(k, d.title, d.category, "warn", detail=f"erro ao verificar: {exc}", optional=d.optional)
        with lock:
            out[k] = it
        if progress:
            progress(it)
    threads = [threading.Thread(target=one, args=(t.key,), daemon=True) for t in CATALOG]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    return [out[t.key] for t in CATALOG if t.key in out]


# ----------------------------------------------------------------------------- relatório
_STATUS_TXT = {"ok": "OK", "warn": "AVISO", "fail": "FALTA", "info": "OPCIONAL", "error": "ERRO"}


def report_text(items: list[ScanItem], extra_lines: list[str] | None = None) -> str:
    lines = [f"Relatório do computador, {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    cat = ""
    for it in sorted(items, key=lambda i: (i.category, i.title)):
        if it.category != cat:
            cat = it.category
            lines += ["", f"== {cat} =="]
        lines.append(f"[{_STATUS_TXT.get(it.status, it.status)}] {it.title}")
        if it.version:
            lines.append(f"    versão: {it.version}")
        if it.path:
            lines.append(f"    onde: {it.path}  ({it.where}{', personalizado' if it.custom and it.where != SRC_CUSTOM else ''})")
        if it.detail:
            lines.append(f"    {it.detail}")
        if it.status in ("fail", "warn", "info") and it.hint:
            lines.append(f"    o que fazer: {it.hint}")
    if extra_lines:
        lines += [""] + extra_lines
    bad = sum(1 for i in items if i.status == "fail")
    warn = sum(1 for i in items if i.status == "warn")
    lines += ["", f"Resumo: {sum(1 for i in items if i.status == 'ok')} ok, {warn} aviso(s), {bad} faltando."]
    return "\n".join(lines)


def report_json(items: list[ScanItem], extra: dict | None = None) -> str:
    data = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": [asdict(i) for i in items]}
    if extra:
        data.update(extra)
    return json.dumps(data, ensure_ascii=False, indent=2)
