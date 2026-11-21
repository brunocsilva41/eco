"""Mapa estatico da tela: paginas (na ordem da navegacao), a que grupos do schema cada uma pertence e como
os campos se distribuem em secoes. So dados; nenhum widget aqui.

Campo do schema que nao estiver numa secao cai em "Outras opcoes" da sua pagina, entao nada fica sem tela.
"""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.settings import schema
from jarvis.settings.schema import FieldSpec


@dataclass(frozen=True)
class SectionSpec:
    id: str
    keys: tuple[str, ...] = ()
    level: int = 1                 # 1 = respiro largo (32/12), 2 = subgrupo curto (16/8)
    custom: str = ""               # nome de um bloco que a propria pagina desenha (tema, ferramentas, ...)


@dataclass(frozen=True)
class Category:
    key: str
    icon: str
    groups: tuple[str, ...] = ()   # grupos do schema que a pagina mostra
    sections: tuple[SectionSpec, ...] = ()


_S = SectionSpec

CATEGORIES: tuple[Category, ...] = (
    Category("general", "settings", (schema.G_RUN,), (
        _S("appearance", custom="theme"),
        _S("talk", ("safety.talk_key", "safety.talk_mode", "safety.mute_hotkey")),
        _S("confirm", ("safety.confirm_yes_hotkey", "safety.confirm_no_hotkey", "safety.confirm_timeout_s")),
        _S("limits", ("safety.max_agent_steps", "safety.tool_timeout_s"), 2),
    )),
    Category("voice", "listen", (schema.G_VOICE,), (
        _S("voice", ("tts.voice_onnx", "tts.voice_json")),
        _S("speech", ("tts.length_scale", "tts.volume"), 2),
        _S("output", ("audio.output_device",)),
    )),
    Category("my_voice", "mic"),
    Category("listening", "ear", (schema.G_STT,), (
        _S("mic", ("audio.input_device",)),
        _S("model_stt", ("stt.model_dir", "stt.language", "stt.compute_type")),
        _S("detect", ("audio.vad_threshold", "audio.end_silence_ms", "audio.min_speech_ms",
                      "audio.max_utterance_s", "audio.pre_roll_ms")),
        _S("perf", ("stt.cpu_threads", "stt.beam_size"), 2),
    )),
    Category("llm", "brain", (schema.G_LLM,), (
        _S("llm_model", ("llm.model", "llm.mmproj", "llm.reasoning_off")),
        _S("llm_work", ("llm.ctx", "llm.ngl", "llm.temperature", "llm.max_tokens")),
        _S("llm_net", ("llm.port", "llm.host", "llm.request_timeout_s", "llm.startup_timeout_s"), 2),
        _S("vision", ("vision.max_side_px", "vision.jpeg_quality"), 2),
    )),
    Category("tools", "shield", (schema.G_SEC, schema.G_TOOLS), (
        _S("emergency", ("safety.emergency_hotkey",)),
        _S("tools", ("tools.disabled", "tools.confirm"), custom="tools"),
        _S("apps", ("apps.launch", "apps.hotkeys", "apps.hotkeys_confirm")),
        _S("typing", ("safety.max_typed_chars", "safety.typing_allowed_processes",
                      "safety.typing_denied_extra", "safety.typing_confirm"), 2),
    )),
    Category("memory", "memory", (schema.G_MEM,), (
        _S("mem_basic", ("memory.enabled", "memory.model_can_remember", "memory.recall_top_k", "memory.idle_minutes")),
        _S("mem_keep", ("memory.conversation_ttl_days", "memory.trash_days")),
        _S("mem_ctx", ("context.compact_at_pct", "context.keep_recent_messages", "context.tool_result_max_chars",
                       "context.summary_max_tokens"), 2),
    )),
    Category("knows", "pin"),
    Category("files", "folder", (schema.G_FILES,), (
        _S("folders", ("files.roots",)),
        _S("file_limits", ("files.max_read_kb", "files.max_write_kb"), 2),
        _S("undo", ("files.undo_keep", "files.undo_max_mb"), 2),
    )),
    Category("advanced", "log", (schema.G_LOGS,), (
        _S("logs", ("logs.level", "logs.max_mb", "logs.keep_files")),
        _S("config_file", custom="config_file"),
        _S("reset", level=2, custom="reset"),
    )),
    Category("about", "info", (), (
        _S("status", custom="status"),
        _S("paths", custom="paths"),
        _S("details", level=2, custom="details"),
    )),
)

BY_PAGE: dict[str, Category] = {c.key: c for c in CATEGORIES}


def category_of(spec: FieldSpec) -> str:
    """Chave da pagina que mostra o campo."""
    for cat in CATEGORIES:
        if spec.group in cat.groups:
            return cat.key
    return CATEGORIES[0].key


def keys_by_page() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {c.key: [] for c in CATEGORIES}
    for spec in schema.FIELDS:
        out[category_of(spec)].append(spec.key)
    return out


def sections_for(cat: Category) -> list[SectionSpec]:
    """Secoes da pagina, mais uma "Outras opcoes" com qualquer campo do schema que ainda nao tenha lugar."""
    placed = {k for s in cat.sections for k in s.keys}
    extra = tuple(k for k in keys_by_page()[cat.key] if k not in placed)
    return [*cat.sections, *([SectionSpec("other", extra, 2)] if extra else [])]
