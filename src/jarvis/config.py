"""Configuração centralizada, tipada e validada. Fonte única: `F:\\Jarvis\\config.toml` (opcional).

Sem segredos aqui: este arquivo nunca guarda senha, PIN ou token.
Valores inválidos levantam `ConfigError` com a lista de todos os problemas de uma vez.
"""
from __future__ import annotations

import ipaddress
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]          # F:\Jarvis
CONFIG_FILE = ROOT / "config.toml"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PathsCfg:
    root: Path = ROOT
    models: Path = ROOT / "models"
    logs: Path = ROOT / "logs"
    data: Path = ROOT / "data"                       # SQLite, estado local
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
    model_name: str = "base"                         # medido em CPU: small ~3 s/frase, base ~1,3 s, tiny ~0,5 s
    compute_type: str = "int8"
    cpu_threads: int = 12
    beam_size: int = 5
    language: str = "pt"


@dataclass(frozen=True)
class TtsCfg:
    voice_onnx: Path = ROOT / "models" / "piper-faber" / "pt_BR-faber-medium.onnx"
    voice_json: Path = ROOT / "models" / "piper-faber" / "pt_BR-faber-medium.onnx.json"
    volume: float = 1.0
    length_scale: float | None = None                # None = padrão da voz


@dataclass(frozen=True)
class LlmCfg:
    model: Path = ROOT / "models" / "qwen3vl-4b" / "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
    mmproj: Path | None = ROOT / "models" / "qwen3vl-4b" / "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"
    host: str = "127.0.0.1"                          # SEMPRE loopback (validado)
    port: int = 8089
    ctx: int = 4096
    ngl: int = 99
    autostart: bool = True
    startup_timeout_s: float = 120.0
    request_timeout_s: float = 90.0
    max_tokens: int = 220
    temperature: float = 0.4
    reasoning_off: bool = False                      # True para modelos "thinking" (Qwen3.5, Gemma 4)


@dataclass(frozen=True)
class SafetyCfg:
    emergency_hotkey: str = "ctrl+alt+f12"
    talk_key: str = "f9"                             # push-to-talk (segurar para falar)
    mute_hotkey: str = "ctrl+alt+m"
    confirm_yes_hotkey: str = "ctrl+alt+y"           # responde SIM a uma confirmação pendente
    confirm_no_hotkey: str = "ctrl+alt+n"            # responde NÃO
    confirm_timeout_s: float = 15.0                  # sem resposta = NÃO
    max_agent_steps: int = 6
    tool_timeout_s: float = 15.0
    max_typed_chars: int = 500


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
    })
    hotkeys: tuple[str, ...] = (                     # atalhos que o agente pode apertar (o resto é recusado)
        "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+a", "ctrl+s", "ctrl+f",
        "ctrl+t", "ctrl+tab", "ctrl+l", "ctrl+n", "alt+tab", "enter", "esc", "tab",
        "pagedown", "pageup", "home", "end", "f5", "win+d", "win+e",
    )


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
    log_level: str = "INFO"


# ---------------------------------------------------------------- carga e validação
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
            if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
                raise TypeError("esperado tabela texto -> texto")
            return dict(value)
        # default None (ex.: dispositivo de áudio, mmproj opcional, length_scale): aceita texto/número
        if value is None or isinstance(value, (str, int, float)) and not isinstance(value, bool):
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
            errors.append(f"{where}{name}: opção desconhecida")
            continue
        default = getattr(defaults, name)
        if is_dataclass(default):
            if not isinstance(value, dict):
                errors.append(f"{where}{name}: esperado seção [{where}{name}]")
                continue
            kwargs[name] = _build(type(default), value, f"{where}{name}.", errors)
        else:
            kwargs[name] = _coerce(value, default, f"{where}{name}", errors)
    # campos Path|None vindos como texto (ex.: mmproj)
    for name, value in list(kwargs.items()):
        if getattr(defaults, name) is None and isinstance(value, str) and name in {"mmproj"}:
            kwargs[name] = Path(value)
    return replace(defaults, **kwargs)


def validate(cfg: Config) -> list[str]:
    """Regras de negócio. Devolve a lista de problemas (vazia = ok)."""
    p: list[str] = []
    try:
        if not ipaddress.ip_address(cfg.llm.host).is_loopback:
            p.append(f"llm.host deve ser loopback (127.0.0.1), veio {cfg.llm.host!r}: o servidor nunca fica exposto na rede")
    except ValueError:
        p.append(f"llm.host inválido: {cfg.llm.host!r} (use um IP, ex.: 127.0.0.1)")
    if not 1024 <= cfg.llm.port <= 65535:
        p.append("llm.port fora de 1024..65535")
    if not 512 <= cfg.llm.ctx <= 32768:
        p.append("llm.ctx fora de 512..32768")
    if not 0 <= cfg.llm.temperature <= 2:
        p.append("llm.temperature fora de 0..2")
    if cfg.llm.max_tokens < 16:
        p.append("llm.max_tokens muito baixo (<16)")
    if cfg.audio.sample_rate != 16000:
        p.append("audio.sample_rate deve ser 16000 (exigência do VAD e do Whisper)")
    if not 0.05 <= cfg.audio.vad_threshold <= 0.95:
        p.append("audio.vad_threshold fora de 0.05..0.95")
    if cfg.audio.end_silence_ms < 200 or cfg.audio.min_speech_ms < 80:
        p.append("audio.end_silence_ms deve ser >= 200 e audio.min_speech_ms >= 80")
    if not 1 <= cfg.audio.max_utterance_s <= 60:
        p.append("audio.max_utterance_s fora de 1..60")
    if cfg.stt.cpu_threads < 1 or cfg.stt.beam_size < 1:
        p.append("stt.cpu_threads e stt.beam_size devem ser >= 1")
    if not 0 < cfg.tts.volume <= 2:
        p.append("tts.volume fora de 0..2")
    if cfg.safety.confirm_timeout_s <= 0 or cfg.safety.tool_timeout_s <= 0:
        p.append("safety.*_timeout_s deve ser > 0")
    if not 1 <= cfg.safety.max_agent_steps <= 20:
        p.append("safety.max_agent_steps fora de 1..20")
    keys = [cfg.safety.emergency_hotkey, cfg.safety.talk_key, cfg.safety.mute_hotkey,
            cfg.safety.confirm_yes_hotkey, cfg.safety.confirm_no_hotkey]
    if len({k.lower() for k in keys}) < len(keys):
        p.append("safety: todas as teclas (emergência, falar, mudo, sim, não) devem ser diferentes")
    if cfg.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        p.append("log_level inválido (DEBUG, INFO, WARNING ou ERROR)")
    return p


def load(path: Path | None = None) -> Config:
    """Lê o TOML (se existir), aplica sobre os padrões e valida. Levanta ConfigError com tudo que estiver errado."""
    path = path or CONFIG_FILE
    errors: list[str] = []
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as exc:
            raise ConfigError(f"não consegui ler {path}: {exc}") from exc
    cfg = _build(Config, raw, "", errors)
    errors += validate(cfg)
    if errors:
        raise ConfigError("configuração inválida:\n - " + "\n - ".join(errors))
    return cfg
