"""Configuração centralizada, tipada e validada. Fonte única: `config.toml` na raiz do programa (opcional).

Sem segredos aqui: este arquivo nunca guarda senha, PIN ou token (`validate` recusa chaves com esses nomes).
Valores inválidos levantam `ConfigError` com a lista de TODOS os problemas de uma vez.
Caminhos relativos no TOML valem a partir da raiz do projeto (ROOT), não do diretório de execução.
"""
from __future__ import annotations

import ipaddress
import os
import re
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

from .win.keys import KeyError_, parse_combo

ROOT = Path(__file__).resolve().parents[2]          # raiz do projeto
CONFIG_FILE = ROOT / "config.toml"

# processos onde o agente NUNCA digita (equivaleria a executar comandos). A config só pode ACRESCENTAR.
HARD_DENIED_TYPING: frozenset[str] = frozenset({
    "cmd.exe", "powershell.exe", "pwsh.exe", "powershell_ise.exe", "windowsterminal.exe", "wt.exe",
    "conhost.exe", "openconsole.exe", "explorer.exe", "regedit.exe", "mmc.exe", "taskmgr.exe",
    "wscript.exe", "cscript.exe", "mshta.exe", "msiexec.exe", "runas.exe", "bash.exe", "wsl.exe",
    "sihost.exe", "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "lockapp.exe", "logonui.exe", "consent.exe", "securityhealthsystray.exe", "windowsdefender.exe",
})

_SECRET_KEY = re.compile(r"(passw|senha|secret|segredo|token|api[_-]?key|\bpin\b|credential)", re.I)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PathsCfg:
    root: Path = ROOT
    models: Path = ROOT / "models"
    logs: Path = ROOT / "logs"
    data: Path = ROOT / "data"                       # SQLite, estado local, gravações
    llama_bin: Path = ROOT / "bin" / "llama-b12531-vulkan"


@dataclass(frozen=True)
class AudioCfg:
    input_device: str | int | None = None            # None = padrão do Windows; índice ou parte do nome
    output_device: str | int | None = None
    sample_rate: int = 16000                         # captura (VAD e STT esperam 16 kHz)
    vad_threshold: float = 0.5
    min_speech_ms: int = 250
    end_silence_ms: int = 700
    max_utterance_s: float = 15.0
    pre_roll_ms: int = 300


@dataclass(frozen=True)
class SttCfg:
    model_dir: Path = ROOT / "models" / "whisper" / "hf_base"
    compute_type: str = "int8"
    cpu_threads: int = 6                             # 6 threads: 9% mais lento que 12 mas 45% menos CPU (medido; regra: <10% = menos CPU)
    beam_size: int = 5
    language: str = "pt"
    device: str = "auto"                             # "auto" (GPU se der, senão CPU) | "gpu" | "cpu". GPU = whisper.cpp Vulkan (0,87 s/frase com o small; CPU faster-whisper base 0,94 s, small 2,5 s)
    gpu_model: Path = ROOT / "models" / "whisper" / "ggml-small.bin"   # modelo ggml do motor GPU


@dataclass(frozen=True)
class TtsCfg:
    voice_onnx: Path = ROOT / "models" / "piper-faber" / "pt_BR-faber-medium.onnx"
    voice_json: Path = ROOT / "models" / "piper-faber" / "pt_BR-faber-medium.onnx.json"
    volume: float = 1.0
    device: str = "cpu"                              # "cpu" | "auto" | "gpu". MEDIDO: CPU vence (DirectML 2,7x mais lento em frase curta, 27% em longa); "gpu" cai para a CPU com aviso
    length_scale: float | None = None                # velocidade: <1 mais rápido, >1 mais lento; None = padrão da voz


@dataclass(frozen=True)
class LlmCfg:
    model: Path = ROOT / "models" / "qwen3vl-4b" / "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
    mmproj: Path | None = ROOT / "models" / "qwen3vl-4b" / "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"   # "" = sem visão
    host: str = "127.0.0.1"                          # SEMPRE loopback (validado em load, LlamaServer e LlmClient)
    port: int = 8089
    ctx: int = 8192
    ngl: int = 99
    device: str = "auto"                             # "auto" (GPU; se o servidor não subir, cai para CPU com aviso) | "gpu" | "cpu" (ngl 0: 6,5 tok/s e 165 CPU-s contra 21,8 tok/s e 5 CPU-s na GPU)
    mmproj_device: str = "auto"                      # visão: "auto"/"gpu" (7,6 s por imagem) | "cpu" (40,8 s e 72 CPU-s; economiza ~0,77 GB de VRAM)
    sleep_idle_s: int = 600                          # ocioso por este tempo, o servidor DESCARREGA o modelo (libera ~5 GB de VRAM e ~2,5 GB de RAM; volta em ~6 s no próximo pedido). 0 = nunca
    mmap: bool = False                               # False = carrega sem mmap (RAM do servidor cai de ~2,9 GB para ~0,5 GB com tudo na GPU); True = mmap do llama.cpp
    startup_timeout_s: float = 120.0
    request_timeout_s: float = 90.0
    max_tokens: int = 220
    temperature: float = 0.4
    reasoning_off: bool = False                      # True para modelos "thinking" (Qwen3.5, Gemma 4)


@dataclass(frozen=True)
class SafetyCfg:
    emergency_hotkey: str = "ctrl+alt+f12"           # OBRIGATÓRIA: não pode ser desativada
    talk_key: str = "f9"                             # tecla de falar (sem modificadores)
    listen_mode: str = "push"                        # "push" = fala apertando a tecla | "open" = ESCUTA ABERTA (ouve sozinho, sem apertar nada; alterna na Ilha/bandeja/atalho)
    open_listen_hotkey: str = "ctrl+alt+l"           # liga/desliga a escuta aberta
    talk_mode: str = "hold"                          # "hold" = segurar para falar; "toggle" = aperta, fala, para no silêncio
    mute_hotkey: str = "ctrl+alt+m"
    confirm_yes_hotkey: str = "ctrl+alt+y"           # responde SIM a uma confirmação pendente
    confirm_no_hotkey: str = "ctrl+alt+n"            # responde NÃO
    confirm_timeout_s: float = 15.0                  # sem resposta = NÃO
    max_agent_steps: int = 6
    tool_timeout_s: float = 15.0
    max_typed_chars: int = 500
    # digitar_texto: só em programas desta lista (e nunca nos de HARD_DENIED_TYPING)
    typing_allowed_processes: tuple[str, ...] = (
        "notepad.exe", "wordpad.exe", "winword.exe", "onenote.exe", "notepad++.exe", "code.exe", "excel.exe", "powerpnt.exe",
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "outlook.exe", "olk.exe", "thunderbird.exe",
        "whatsapp.exe", "telegram.exe", "discord.exe", "slack.exe", "obsidian.exe")
    typing_denied_extra: tuple[str, ...] = ()        # acrescenta à lista fixa de bloqueio
    typing_allowed_titles: tuple[str, ...] = ("calculadora", "calculator")   # apps UWP (rodam em ApplicationFrameHost): só digita se o TÍTULO da janela contém um destes
    typing_confirm: str = "untrusted_or_multiline"   # "always" | "untrusted_or_multiline" (só conteúdo de fora ou parecido com comando)
    permission_mode: str = "balanced"                # "balanced": só ações nocivas confirmam | "strict": também confirma tudo que age depois de ler conteúdo de fora
    yolo_hotkey: str = "ctrl+alt+shift+y"            # LIGA/DESLIGA o modo YOLO (sem confirmações). Só por tecla física; nunca por voz. Vazio = desativado
    yolo_minutes: int = 30                           # o YOLO desliga sozinho após este tempo (e ao reiniciar)


@dataclass(frozen=True)
class VisionCfg:
    max_side_px: int = 1024
    jpeg_quality: int = 80


@dataclass(frozen=True)
class AppsCfg:
    """Allowlist: nome falado -> executável/URI. Só o que está aqui abre."""
    launch: dict[str, str] = field(default_factory=lambda: {
        "bloco de notas": "notepad.exe",
        "calculadora": "calc.exe",
        "explorador de arquivos": "explorer.exe",
        "paint": "mspaint.exe",
        "configurações": "ms-settings:",
        "navegador": "default-browser",                  # o navegador padrão do Windows (resolvido na hora, só em Program Files/LocalAppData)
        "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    })
    hotkeys: tuple[str, ...] = (                     # atalhos que o agente pode apertar (o resto é recusado)
        "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+a", "ctrl+s", "ctrl+f",
        "ctrl+t", "ctrl+tab", "ctrl+l", "ctrl+n", "alt+tab", "enter", "esc", "tab",
        "pagedown", "pageup", "home", "end", "f5", "win+d", "win+e",
    )
    hotkeys_confirm: tuple[str, ...] = ("ctrl+s",)   # estes pedem Sim/Não antes (enter em diálogo sempre pede; copiar/colar/recortar são livres)


@dataclass(frozen=True)
class ToolsCfg:
    disabled: tuple[str, ...] = ()                   # ferramentas desligadas (o modelo nem as vê)
    confirm: tuple[str, ...] = ()                    # ferramentas que SEMPRE pedem confirmação (além das arriscadas)


@dataclass(frozen=True)
class ToolPathsCfg:
    """Onde está cada programa de apoio. VAZIO = o Eco procura sozinho (PATH, instalação padrão, pasta do Eco).
    Caminho de REDE (\\\\servidor\\...) nunca é aceito. Quem valida/descobre é `jarvis.core.toolpaths`."""
    whispercpp_dir: str = ""                         # pasta do whisper.cpp (jarvis_whisper.dll)
    ffmpeg: str = ""
    git: str = ""
    powershell: str = ""                             # pwsh.exe ou powershell.exe
    git_bash: str = ""                               # bash.exe do Git for Windows (nunca o do WSL)
    python: str = ""                                 # python.exe de apoio (só para o Terminal/ferramentas; o Eco roda no dele)
    ollama: str = ""
    lmstudio: str = ""
    opencode: str = ""
    antigravity: str = ""                            # agy.exe
    claude: str = ""
    codex: str = ""
    copilot: str = ""


@dataclass(frozen=True)
class MemoryCfg:
    enabled: bool = True                             # False = "modo sem histórico": nada é gravado em disco
    idle_minutes: int = 30                           # inatividade que abre uma nova conversa (0 = nunca)
    recall_top_k: int = 5                            # memórias de longo prazo injetadas no prompt (como DADO)
    model_can_remember: bool = True                  # o modelo pode propor "lembrar" (sempre com confirmação se a origem for conteúdo externo)
    conversation_ttl_days: int = 365                 # conversas mais velhas que isso vão para a lixeira
    trash_days: int = 7                              # a lixeira de conversas/memórias guarda por este tempo


@dataclass(frozen=True)
class ContextCfg:
    compact_at_pct: int = 70                         # compacta ao passar desta % do contexto (n_ctx real do servidor)
    keep_recent_messages: int = 6                    # mensagens recentes que nunca entram no resumo
    tool_result_max_chars: int = 1200                # truncamento de resultados de ferramentas no prompt
    summary_max_tokens: int = 350                    # tamanho do resumo estruturado


def _default_docs_root() -> str:
    """Pasta padrão em Documentos: `Eco`; se só existir a antiga `Jarvis` (instalações anteriores), continua nela."""
    base = Path.home() / "Documents"
    old, new = base / "Jarvis", base / "Eco"
    return str(old if old.exists() and not new.exists() else new)


@dataclass(frozen=True)
class FilesCfg:
    """Ferramentas de arquivos: só dentro das raízes abaixo; apagar vai sempre para a Lixeira."""
    roots: tuple[str, ...] = (_default_docs_root(),)    # raízes permitidas (pastas)
    max_read_kb: int = 256
    max_write_kb: int = 512
    undo_keep: int = 20                              # operações que "desfaz" consegue reverter
    undo_max_mb: int = 200                           # espaço máximo de backups


@dataclass(frozen=True)
class LogsCfg:
    level: str = "INFO"
    max_mb: int = 2                                  # tamanho por arquivo
    keep_files: int = 5                              # rotações guardadas


@dataclass(frozen=True)
class UiCfg:
    tray_enabled: bool = True                        # ícone na bandeja do sistema com menu (vive no processo da Ilha)
    island_enabled: bool = True                      # mostra a Ilha (janela no topo da tela) enquanto o Eco roda
    island_mode: str = "docked"                      # "docked" (topo) | "floating" (pílula afastada do topo) | "dock_right" | "dock_left" (trilho lateral)
    island_pinned: bool = False                      # alfinete: fixada = nunca esconde sozinha (a Ilha devolve o estado ao núcleo)
    island_opacity: float = 0.92                     # 0.35..1.0: opacidade do fundo (vidro); o contraste do texto é garantido pela Ilha
    island_side_y_pct: int = 50                      # dock lateral: altura do trilho na tela, 0 (topo) .. 100 (base)
    island_float_gap_px: int = 10                    # afastamento do topo no modo flutuante (0..64)
    island_autohide: bool = True                     # escondida por padrão: aparece com o mouse no topo, F9/ouvindo, confirmação, erro
    island_hide_delay_s: float = 3.0                 # some sozinha depois deste tempo em repouso
    island_hover_reveal: bool = True                 # mouse no centro do topo da tela revela a Ilha


@dataclass(frozen=True)
class UpdatesCfg:
    enabled: bool = True                             # verificação automática de novas versões (desligada = só pelo menu da bandeja)
    check_on_start: bool = True                      # verifica ao iniciar o Eco
    interval_hours: int = 12                         # e a cada N horas (1..168)
    channel: str = "stable"                          # "stable" (só versões finais) | "prerelease" (inclui pré-lançamentos)
    repo: str = "brunocsilva41/eco"         # dono/repositório no GitHub (privado ou público)
    auto_install: bool = False                       # oferece "Instalar automaticamente" já no pop-up; nunca instala sem hash válido


@dataclass(frozen=True)
class BrainCfg:
    """Cérebro: o modelo LOCAL é o padrão. A nuvem (via ACP, o agente usa o próprio login) é opt-in e cai para o local."""
    kind: str = "local"                              # "local" | "cloud"
    agent: str = "opencode"                          # opencode | antigravity | claude | codex | copilot
    fallback_local: bool = True                      # nuvem indisponível/erro/sem login -> responde com o modelo local
    request_timeout_s: float = 90.0                  # tempo máximo de um pedido à nuvem (10..600)
    startup_timeout_s: float = 45.0                  # tempo máximo para iniciar o agente (5..300)
    use_tools: bool = True                           # o agente pode usar as ferramentas do Eco (MCP em loopback, mesmas travas)
    builtin_tools: str = "deny"                      # ferramentas PRÓPRIAS do agente (shell, editar arquivos): "deny" | "ask"
    consent_screen: tuple[str, ...] = ()             # agentes autorizados a ver a tela/janelas (por padrão nenhum: só texto)
    consent_memory: tuple[str, ...] = ()             # agentes autorizados a ler/gravar memória e conversas
    consent_files: tuple[str, ...] = ()              # agentes autorizados a usar as ferramentas de arquivos
    consent_terminal: tuple[str, ...] = ()           # agentes autorizados a pedir comandos ao terminal integrado (sempre com confirmação forte)
    action_modes: dict[str, str] = field(default_factory=dict)   # agente -> o que ele pode fazer no PC: deny | confirm | normal (padrão: confirm)
    models: dict[str, str] = field(default_factory=dict)         # agente -> modelo (vazio = o do próprio agente; o Eco troca se ele falhar)


TERMINAL_ALLOWED_DEFAULT: tuple[str, ...] = (       # só leitura: rodam sem perguntar no modo "allowlist" (comando simples, sem ; & | > `)
    "git status", "git log", "git diff", "git branch", "git show", "git remote -v", "git rev-parse", "git describe",
    "git ls-files", "git --version", "dir", "ls", "pwd", "cd", "Get-ChildItem", "Get-Location", "where", "hostname",
    "python --version", "node --version", "npm --version")


@dataclass(frozen=True)
class TerminalCfg:
    """Terminal integrado: o Eco roda comandos de linha de comando (git etc.). DESLIGADO por padrão."""
    mode: str = "off"                                # off | confirm (sempre pergunta) | allowlist (lista roda direto, o resto pergunta) | free (sem perguntar; só liberado à mão no painel Terminal, por tempo)
    shell: str = "powershell"                        # powershell | cmd | bash (Git Bash)
    roots: tuple[str, ...] = (_default_docs_root(),)   # pastas onde os comandos podem rodar
    allowed_commands: tuple[str, ...] = TERMINAL_ALLOWED_DEFAULT
    blocked_extra: tuple[str, ...] = ()              # trechos de texto que SEMPRE bloqueiam o comando (além da lista fixa)
    timeout_s: int = 120                             # tempo máximo de um comando; passou disso, o Eco o encerra (10..3600)
    max_output_kb: int = 256                         # quanto da saída fica guardado para o painel (16..4096)
    result_chars: int = 3000                         # quanto da saída volta ao modelo (200..8000)
    free_minutes: int = 15                           # duração do modo livre depois de liberado no painel (1..120)


@dataclass(frozen=True)
class Config:
    paths: PathsCfg = field(default_factory=PathsCfg)
    audio: AudioCfg = field(default_factory=AudioCfg)
    stt: SttCfg = field(default_factory=SttCfg)
    tts: TtsCfg = field(default_factory=TtsCfg)
    llm: LlmCfg = field(default_factory=LlmCfg)
    safety: SafetyCfg = field(default_factory=SafetyCfg)
    vision: VisionCfg = field(default_factory=VisionCfg)
    apps: AppsCfg = field(default_factory=AppsCfg)
    tools: ToolsCfg = field(default_factory=ToolsCfg)
    memory: MemoryCfg = field(default_factory=MemoryCfg)
    context: ContextCfg = field(default_factory=ContextCfg)
    files: FilesCfg = field(default_factory=FilesCfg)
    logs: LogsCfg = field(default_factory=LogsCfg)
    ui: UiCfg = field(default_factory=UiCfg)
    updates: UpdatesCfg = field(default_factory=UpdatesCfg)
    brain: BrainCfg = field(default_factory=BrainCfg)
    terminal: TerminalCfg = field(default_factory=TerminalCfg)
    toolpaths: ToolPathsCfg = field(default_factory=ToolPathsCfg)


def assert_loopback(host: str) -> None:
    """Garante que o llama-server nunca fique exposto na rede (chamado também por LlamaServer/LlmClient)."""
    try:
        ok = ipaddress.ip_address(host).is_loopback
    except ValueError:
        ok = False
    if not ok:
        raise ConfigError(f"llm.host deve ser um IP de loopback (127.0.0.1 ou ::1), veio {host!r}")


# ---------------------------------------------------------------- carga
def _coerce(value: Any, default: Any, where: str, errors: list[str]) -> Any:
    """Converte `value` (vindo do TOML) para o tipo do `default`; registra o erro e usa o padrão se não der."""
    try:
        if isinstance(default, Path):
            if not isinstance(value, str):
                raise TypeError("esperado texto (caminho)")
            return Path(value)
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise TypeError("esperado true/false")
            return value
        if isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("esperado inteiro")
            return value
        if isinstance(default, float):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("esperado número")
            return float(value)
        if isinstance(default, str):
            if not isinstance(value, str):
                raise TypeError("esperado texto")
            return value
        if isinstance(default, tuple):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise TypeError("esperado lista de textos")
            return tuple(value)
        if isinstance(default, dict):
            if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                raise TypeError("esperado tabela texto -> texto")
            return dict(value)
        # default None (dispositivo de áudio, length_scale): aceita texto ou número
        if value is None or (isinstance(value, (str, int, float)) and not isinstance(value, bool)):
            return value
        raise TypeError("tipo não suportado")
    except TypeError as exc:
        errors.append(f"{where}: {exc} (recebido {value!r})")
        return default


def _build(cls: type, raw: dict[str, Any], where: str, errors: list[str]) -> Any:
    defaults = cls()
    known = {f.name for f in fields(cls)}
    kwargs: dict[str, Any] = {}
    for name, value in raw.items():
        if name not in known:
            if _SECRET_KEY.search(name):             # só chaves DESCONHECIDAS com cara de segredo (max_tokens etc. são campos normais)
                errors.append(f"{where}{name}: o Eco não guarda senhas, PINs nem tokens na configuração")
            else:
                errors.append(f"{where}{name}: opção desconhecida")
            continue
        default = getattr(defaults, name)
        if is_dataclass(default):
            if not isinstance(value, dict):
                errors.append(f"{where}{name}: esperado seção [{where}{name}]")
                continue
            kwargs[name] = _build(type(default), value, f"{where}{name}.", errors)
        elif cls is LlmCfg and name == "mmproj" and value == "":
            kwargs[name] = None                      # "" desliga a visão
        else:
            kwargs[name] = _coerce(value, default, f"{where}{name}", errors)
    return replace(defaults, **kwargs)


def _resolve_paths(obj: Any) -> Any:
    """Caminhos relativos passam a valer contra ROOT."""
    if not is_dataclass(obj):
        return obj
    changes: dict[str, Any] = {}
    for f in fields(obj):
        v = getattr(obj, f.name)
        if isinstance(v, Path):
            changes[f.name] = v if v.is_absolute() else (ROOT / v)
        elif is_dataclass(v):
            changes[f.name] = _resolve_paths(v)
    return replace(obj, **changes)


def _norm_combo(text: str, label: str, problems: list[str]) -> str | None:
    try:
        return parse_combo(text).norm
    except KeyError_ as exc:
        problems.append(f"{label}: {exc}")
        return None


_CLOUD_AGENTS = ("opencode", "antigravity", "claude", "codex", "copilot")
_LANG = re.compile(r"^[a-z]{2}$")
_COMPUTE = {"int8", "int8_float32", "int8_float16", "float32", "float16", "default"}


def validate(cfg: Config) -> list[str]:
    """Regras de negócio. Devolve a lista de problemas (vazia = ok)."""
    p: list[str] = []
    l, a, s = cfg.llm, cfg.audio, cfg.safety
    try:
        assert_loopback(l.host)
    except ConfigError as exc:
        p.append(f"{exc}: o servidor nunca fica exposto na rede")
    if not 1024 <= l.port <= 65535:
        p.append("llm.port fora de 1024..65535")
    if not 512 <= l.ctx <= 32768:
        p.append("llm.ctx fora de 512..32768")
    if not 0 <= l.ngl <= 999:
        p.append("llm.ngl fora de 0..999")
    for label, value in (("llm.device", l.device), ("llm.mmproj_device", l.mmproj_device), ("stt.device", cfg.stt.device), ("tts.device", cfg.tts.device)):
        if value not in ("auto", "gpu", "cpu"):
            p.append(f"{label} deve ser 'auto', 'gpu' ou 'cpu'")
    if l.sleep_idle_s != 0 and not 30 <= l.sleep_idle_s <= 86400:
        p.append("llm.sleep_idle_s deve ser 0 (nunca) ou entre 30 e 86400 segundos")
    if not 0 <= l.temperature <= 2:
        p.append("llm.temperature fora de 0..2")
    if not 16 <= l.max_tokens <= 4096:
        p.append("llm.max_tokens fora de 16..4096")
    if l.ctx < l.max_tokens + 1024:
        p.append("llm.ctx deve ser pelo menos llm.max_tokens + 1024")
    if not 10 <= l.startup_timeout_s <= 900:
        p.append("llm.startup_timeout_s fora de 10..900")
    if not 5 <= l.request_timeout_s <= 900:
        p.append("llm.request_timeout_s fora de 5..900")

    if a.sample_rate != 16000:
        p.append("audio.sample_rate deve ser 16000 (exigência do VAD e do Whisper)")
    if not 0.05 <= a.vad_threshold <= 0.95:
        p.append("audio.vad_threshold fora de 0.05..0.95")
    if not 200 <= a.end_silence_ms <= 5000:
        p.append("audio.end_silence_ms fora de 200..5000")
    if not 80 <= a.min_speech_ms <= 2000:
        p.append("audio.min_speech_ms fora de 80..2000")
    if not 0 <= a.pre_roll_ms <= 2000:
        p.append("audio.pre_roll_ms fora de 0..2000")
    if not 1 <= a.max_utterance_s <= 60:
        p.append("audio.max_utterance_s fora de 1..60")

    t = cfg.stt
    if not 1 <= t.cpu_threads <= 64 or not 1 <= t.beam_size <= 10:
        p.append("stt.cpu_threads deve estar em 1..64 e stt.beam_size em 1..10")
    if not _LANG.match(t.language):
        p.append("stt.language deve ter 2 letras (ex.: pt)")
    if t.compute_type not in _COMPUTE:
        p.append(f"stt.compute_type deve ser um de {sorted(_COMPUTE)}")
    if not 0 < cfg.tts.volume <= 2:
        p.append("tts.volume fora de 0..2")
    ls = cfg.tts.length_scale
    if ls is not None:
        try:
            if not 0.3 <= float(ls) <= 3.0:
                p.append("tts.length_scale fora de 0.3..3.0")
        except (TypeError, ValueError):
            p.append("tts.length_scale deve ser um número")

    if not 256 <= cfg.vision.max_side_px <= 4096:
        p.append("vision.max_side_px fora de 256..4096")
    if not 30 <= cfg.vision.jpeg_quality <= 95:
        p.append("vision.jpeg_quality fora de 30..95")

    if not 3 <= s.confirm_timeout_s <= 120:
        p.append("safety.confirm_timeout_s fora de 3..120")
    if not 1 <= s.tool_timeout_s <= 120:
        p.append("safety.tool_timeout_s fora de 1..120")
    if not 1 <= s.max_agent_steps <= 20:
        p.append("safety.max_agent_steps fora de 1..20")
    if not 1 <= s.max_typed_chars <= 2000:
        p.append("safety.max_typed_chars fora de 1..2000")
    if s.talk_mode not in ("hold", "toggle"):
        p.append("safety.talk_mode deve ser 'hold' ou 'toggle'")
    if s.listen_mode not in ("push", "open"):
        p.append("safety.listen_mode deve ser 'push' ou 'open'")
    if s.permission_mode not in ("balanced", "strict"):
        p.append("safety.permission_mode deve ser 'balanced' ou 'strict'")
    if not 1 <= s.yolo_minutes <= 240:
        p.append("safety.yolo_minutes fora de 1..240")
    up = cfg.updates
    if not 1 <= up.interval_hours <= 168:
        p.append("updates.interval_hours fora de 1..168")
    if up.channel not in ("stable", "prerelease"):
        p.append("updates.channel deve ser 'stable' ou 'prerelease'")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", up.repo):
        p.append("updates.repo deve ser 'dono/repositorio'")
    b = cfg.brain
    if b.kind not in ("local", "cloud"):
        p.append("brain.kind deve ser 'local' ou 'cloud'")
    if b.agent not in ("opencode", "antigravity", "claude", "codex", "copilot"):
        p.append("brain.agent deve ser opencode, antigravity, claude, codex ou copilot")
    if b.builtin_tools not in ("deny", "ask"):
        p.append("brain.builtin_tools deve ser 'deny' ou 'ask'")
    if not 10 <= b.request_timeout_s <= 600:
        p.append("brain.request_timeout_s fora de 10..600")
    if not 5 <= b.startup_timeout_s <= 300:
        p.append("brain.startup_timeout_s fora de 5..300")
    for ag, mode in b.action_modes.items():
        if ag not in _CLOUD_AGENTS or mode not in ("deny", "confirm", "normal"):
            p.append(f"brain.action_modes: {ag}={mode!r} inválido (agentes: {', '.join(_CLOUD_AGENTS)}; modos: deny, confirm, normal)")
    for ag in b.models:
        if ag not in _CLOUD_AGENTS:
            p.append(f"brain.models: agente desconhecido {ag!r}")
    for label, ids in (("consent_screen", b.consent_screen), ("consent_memory", b.consent_memory), ("consent_files", b.consent_files)):
        bad = [x for x in ids if x not in ("opencode", "antigravity", "claude", "codex", "copilot")]
        if bad:
            p.append(f"brain.{label}: agente desconhecido {bad}")
    u = cfg.ui
    if u.island_mode not in ("docked", "floating", "dock_right", "dock_left"):
        p.append("ui.island_mode deve ser 'docked', 'floating', 'dock_right' ou 'dock_left'")
    if not 0.35 <= u.island_opacity <= 1.0:
        p.append("ui.island_opacity fora de 0.35..1.0")
    if not 0 <= u.island_side_y_pct <= 100:
        p.append("ui.island_side_y_pct fora de 0..100")
    if not 0 <= u.island_float_gap_px <= 64:
        p.append("ui.island_float_gap_px fora de 0..64")
    if not 0.5 <= u.island_hide_delay_s <= 60:
        p.append("ui.island_hide_delay_s fora de 0.5..60")
    if s.typing_confirm not in ("always", "untrusted_or_multiline"):
        p.append("safety.typing_confirm deve ser 'always' ou 'untrusted_or_multiline'")
    for name in s.typing_allowed_processes:
        if name.lower() in HARD_DENIED_TYPING or name.lower() in {x.lower() for x in s.typing_denied_extra}:
            p.append(f"safety.typing_allowed_processes: {name} é bloqueado para digitação")

    # teclas de segurança: precisam ser válidas e distintas na forma NORMALIZADA (alt+ctrl+m == ctrl+alt+m)
    sec: dict[str, str | None] = {}
    for label, text in (("emergency_hotkey", s.emergency_hotkey), ("talk_key", s.talk_key), ("mute_hotkey", s.mute_hotkey),
                        ("confirm_yes_hotkey", s.confirm_yes_hotkey), ("confirm_no_hotkey", s.confirm_no_hotkey),
                        *((("yolo_hotkey", s.yolo_hotkey),) if s.yolo_hotkey.strip() else ()),
                        *((("open_listen_hotkey", s.open_listen_hotkey),) if s.open_listen_hotkey.strip() else ())):
        sec[label] = _norm_combo(text, f"safety.{label}", p)
    norms = [v for v in sec.values() if v]
    if len(set(norms)) < len(norms):
        p.append("safety: emergência, falar, mudo, sim e não devem ser teclas diferentes")
    try:
        if parse_combo(s.talk_key).mods:
            p.append("safety.talk_key deve ser uma tecla simples, sem Ctrl/Alt/Shift/Win (ex.: f9)")
    except KeyError_:
        pass

    # o agente nunca pode apertar as teclas de segurança (RegisterHotKey dispararia com entrada injetada)
    reserved = set(norms)
    hk_norm: set[str] = set()
    for i, h in enumerate(cfg.apps.hotkeys):
        n = _norm_combo(h, f"apps.hotkeys[{i}]", p)
        if n:
            hk_norm.add(n)
            if n in reserved:
                p.append(f"apps.hotkeys: {h!r} é uma tecla de segurança do Eco e não pode ser liberada ao agente")
    for i, h in enumerate(cfg.apps.hotkeys_confirm):
        n = _norm_combo(h, f"apps.hotkeys_confirm[{i}]", p)
        if n and n not in hk_norm:
            p.append(f"apps.hotkeys_confirm: {h!r} não está em apps.hotkeys")
    for name, target in cfg.apps.launch.items():
        if not name.strip() or not target.strip():
            p.append("apps.launch: nome e destino não podem ser vazios")
    if not cfg.logs.level.upper() in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        p.append("logs.level inválido (DEBUG, INFO, WARNING ou ERROR)")
    if not 1 <= cfg.logs.max_mb <= 100 or not 1 <= cfg.logs.keep_files <= 50:
        p.append("logs.max_mb deve estar em 1..100 e logs.keep_files em 1..50")
    m = cfg.memory
    if not 0 <= m.idle_minutes <= 1440 or not 0 <= m.recall_top_k <= 20 or not 1 <= m.conversation_ttl_days <= 3650 \
            or not 1 <= m.trash_days <= 365:
        p.append("memory: idle_minutes 0..1440, recall_top_k 0..20, conversation_ttl_days 1..3650, trash_days 1..365")
    c = cfg.context
    if not 30 <= c.compact_at_pct <= 95 or not 2 <= c.keep_recent_messages <= 40 \
            or not 200 <= c.tool_result_max_chars <= 8000 or not 100 <= c.summary_max_tokens <= 1500:
        p.append("context: compact_at_pct 30..95, keep_recent_messages 2..40, tool_result_max_chars 200..8000, summary_max_tokens 100..1500")
    f = cfg.files
    if not 1 <= f.max_read_kb <= 4096 or not 1 <= f.max_write_kb <= 8192 or not 1 <= f.undo_keep <= 200 \
            or not 10 <= f.undo_max_mb <= 5000:
        p.append("files: max_read_kb 1..4096, max_write_kb 1..8192, undo_keep 1..200, undo_max_mb 10..5000")
    for r in f.roots:
        rp = Path(r)
        if not rp.is_absolute():
            p.append(f"files.roots: {r!r} deve ser um caminho absoluto")
            continue
        try:
            low = str(rp.resolve()).lower().rstrip("\\") + "\\"
        except OSError:
            p.append(f"files.roots: não consegui resolver {r!r}")
            continue
        protected = [str(x.resolve()).lower().rstrip("\\") + "\\" for x in (cfg.paths.root, cfg.paths.data, cfg.paths.logs)]
        sysroot = (os.environ.get("SystemRoot", r"C:\Windows")).lower().rstrip("\\") + "\\"
        pf = [os.environ.get(v, "").lower().rstrip("\\") + "\\" for v in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(v)]
        if len(rp.parts) <= 1 or low.startswith(sysroot) or any(low.startswith(x) for x in pf) \
                or any(low.startswith(x) or x.startswith(low) for x in protected):
            p.append(f"files.roots: {r!r} é uma pasta protegida (raiz do disco, Windows, Program Files ou pasta do Eco)")
            continue
        # Pastas sensíveis: o perfil INTEIRO (ou acima), AppData, ProgramData, Inicializar, .ssh, .aws, .gnupg e qualquer
        # pasta que as contenha. A raiz precisa estar ESTRITAMENTE dentro de uma subpasta do perfil (ex.: Documents\Eco).
        env = os.environ
        home_s = env.get("USERPROFILE") or str(Path.home())
        sens_raw = [str(Path(home_s) / n) for n in ("AppData", ".ssh", ".aws", ".gnupg")]
        sens_raw += [env[v] for v in ("APPDATA", "LOCALAPPDATA", "ProgramData", "ALLUSERSPROFILE") if env.get(v)]
        sens_raw.append(r"C:\ProgramData")
        sens: list[str] = []
        homes: list[str] = []
        for raw_path in sens_raw:
            for form in {raw_path, str(Path(raw_path).resolve())}:
                sens.append(form.lower().rstrip("\\") + "\\")
        for raw_path in {home_s, str(Path(home_s).resolve())}:
            homes.append(raw_path.lower().rstrip("\\") + "\\")
        pieces = low.split("\\")
        if any(h.startswith(low) for h in homes):
            p.append(f"files.roots: {r!r} é o perfil do usuário inteiro (ou uma pasta acima dele); use uma subpasta, "
                     "como Documents\\Eco")
        elif any(low.startswith(x) or x.startswith(low) for x in sens) \
                or any(c in (".ssh", ".aws", ".gnupg") for c in pieces) \
                or "\\programs\\startup\\" in low or "\\programs\\inicializar\\" in low:
            p.append(f"files.roots: {r!r} é uma pasta sensível (AppData, ProgramData, Inicializar, .ssh, .aws, .gnupg "
                     "ou uma pasta que as contenha)")
    p += _terminal_problems(cfg)
    p += _toolpath_problems(cfg)
    return p


def is_network_path(text: str) -> bool:
    """Caminho UNC (\\\\servidor\\pasta ou //servidor/pasta) ou unidade de rede mapeada. Nunca aceito para programas e modelos."""
    t = text.strip().strip('"')
    if t.startswith("\\\\") or t.startswith("//"):
        return True
    if len(t) >= 2 and t[1] == ":" and os.name == "nt":
        try:
            import ctypes
            return ctypes.windll.kernel32.GetDriveTypeW(t[:2] + "\\") == 4          # DRIVE_REMOTE
        except (AttributeError, OSError):
            return False
    return False


def _toolpath_problems(cfg: Config) -> list[str]:
    p: list[str] = []
    for f in fields(cfg.toolpaths):
        v = getattr(cfg.toolpaths, f.name)
        if v and is_network_path(v):
            p.append(f"toolpaths.{f.name}: caminho de rede não é aceito ({v!r}); copie para uma pasta do seu computador")
    for label, v in (("paths.llama_bin", cfg.paths.llama_bin), ("paths.models", cfg.paths.models), ("paths.data", cfg.paths.data),
                     ("llm.model", cfg.llm.model), ("stt.gpu_model", cfg.stt.gpu_model), ("stt.model_dir", cfg.stt.model_dir),
                     ("tts.voice_onnx", cfg.tts.voice_onnx), ("tts.voice_json", cfg.tts.voice_json)):
        if is_network_path(str(v)):
            p.append(f"{label}: caminho de rede não é aceito ({str(v)!r}); copie para uma pasta do seu computador")
    return p


def _terminal_problems(cfg: Config) -> list[str]:
    """Regras do terminal integrado: modo/shell válidos, limites e pastas (mesma proteção das pastas de arquivos)."""
    t, p = cfg.terminal, []
    if t.mode not in ("off", "confirm", "allowlist", "free"):
        p.append("terminal.mode deve ser 'off', 'confirm', 'allowlist' ou 'free'")
    if t.shell not in ("powershell", "cmd", "bash"):
        p.append("terminal.shell deve ser 'powershell', 'cmd' ou 'bash'")
    if not 10 <= t.timeout_s <= 3600:
        p.append("terminal.timeout_s fora de 10..3600")
    if not 16 <= t.max_output_kb <= 4096:
        p.append("terminal.max_output_kb fora de 16..4096")
    if not 200 <= t.result_chars <= 8000:
        p.append("terminal.result_chars fora de 200..8000")
    if not 1 <= t.free_minutes <= 120:
        p.append("terminal.free_minutes fora de 1..120")
    if any(not x.strip() for x in t.allowed_commands) or any(not x.strip() for x in t.blocked_extra):
        p.append("terminal: allowed_commands e blocked_extra não aceitam itens vazios")
    bad = [x for x in cfg.brain.consent_terminal if x not in _CLOUD_AGENTS]
    if bad:
        p.append(f"brain.consent_terminal: agente desconhecido {bad}")
    env = os.environ
    sysroot = env.get("SystemRoot", r"C:\Windows")
    pf = [env[v] for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData") if env.get(v)]
    home = env.get("USERPROFILE") or str(Path.home())
    sens = [str(Path(home) / n) for n in ("AppData", ".ssh", ".aws", ".gnupg", ".config")] + \
           [env[v] for v in ("APPDATA", "LOCALAPPDATA") if env.get(v)]
    protected = [cfg.paths.root, cfg.paths.data, cfg.paths.logs]

    def key(x: str | Path) -> str:
        try:
            return str(Path(x).resolve()).lower().rstrip("\\") + "\\"
        except OSError:
            return str(x).lower().rstrip("\\") + "\\"

    for r in t.roots:
        rp = Path(r)
        if not rp.is_absolute():
            p.append(f"terminal.roots: {r!r} deve ser um caminho absoluto")
            continue
        low = key(rp)
        if len(rp.parts) <= 1:
            p.append(f"terminal.roots: {r!r} é a raiz de um disco")
        elif key(sysroot) and (low.startswith(key(sysroot)) or key(sysroot).startswith(low)) or any(low.startswith(key(x)) for x in pf):
            p.append(f"terminal.roots: {r!r} é uma pasta do sistema (Windows, Program Files ou ProgramData)")
        elif key(home).startswith(low):
            p.append(f"terminal.roots: {r!r} é o perfil do usuário inteiro (ou acima dele); use uma subpasta, como Documents\\Eco")
        elif any(low.startswith(key(x)) or key(x).startswith(low) for x in sens) or "\\programs\\eco\\" in low or "\\programs\\jarvis\\" in low:
            p.append(f"terminal.roots: {r!r} é uma pasta sensível (AppData, .ssh, .aws, .gnupg, .config ou o Eco instalado)")
        elif any(low.startswith(key(x)) or key(x).startswith(low) for x in protected):
            p.append(f"terminal.roots: {r!r} contém ou está dentro da pasta do próprio Eco (código, dados ou logs)")
    return p


def from_dict(raw: dict[str, Any]) -> Config:
    """Constrói e valida uma Config a partir de um dicionário (mesma validação do load). Usado pela tela de configurações."""
    errors: list[str] = []
    cfg = _resolve_paths(_build(Config, raw, "", errors))
    errors += validate(cfg)
    if errors:
        raise ConfigError("configuração inválida:\n - " + "\n - ".join(errors))
    return cfg


def load(path: Path | None = None) -> Config:
    """Lê o TOML (se existir), aplica sobre os padrões e valida. Levanta ConfigError com tudo que estiver errado."""
    path = path or CONFIG_FILE
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
            raise ConfigError(f"não consegui ler {path}: {exc}") from exc
    return from_dict(raw)
