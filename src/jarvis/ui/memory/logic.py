"""Lógica pura do painel de memória (sem Qt): formatação, mensagens de erro e nomes de arquivo."""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ...memory import Message, Session
from .texts import plural, tr

CONFIRM_WORD: Final = "APAGAR"
MAX_VIEW_CHARS: Final = 6000


def fmt_ts(ts: float | None) -> str:
    """'20/11/2026 14:30' no fuso local; '-' quando não há data."""
    if ts is None:
        return "-"
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return "-"


def fmt_date(ts: float | None) -> str:
    if ts is None:
        return "-"
    try:
        return time.strftime("%d/%m/%Y", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return "-"


def fmt_mb(size_bytes: int) -> str:
    """'12,34 MB' (vírgula decimal)."""
    return f"{size_bytes / (1024 * 1024):.2f}".replace(".", ",") + " MB"


def trash_days_left(deleted_at: float | None, trash_days: float, now: float | None = None) -> int:
    """Dias inteiros (para cima) que faltam para a lixeira apagar a conversa; 0 = na próxima limpeza."""
    if deleted_at is None:
        return 0
    elapsed = ((now if now is not None else time.time()) - deleted_at) / 86400
    return max(0, math.ceil(trash_days - elapsed))


def session_state_text(s: Session, trash_days: float, now: float | None = None) -> str:
    c = tr().conversations
    if s.state == "lixeira":
        return c.state_trash_left(trash_days_left(s.deleted_at, trash_days, now))
    return c.state_active if s.state == "ativa" else c.state_ended


@dataclass(frozen=True, slots=True)
class FriendlyError:
    """Erro pronto para a tela: o que houve, por que importa, o que fazer. ``busy``: vale 'tentar de novo'."""
    what: str
    why: str
    todo: str
    busy: bool


def is_busy_error(message: str) -> bool:
    low = message.lower()
    return any(w in low for w in tr().errors.lock_words)


def friendly_error(message: str, *, what: str = "") -> FriendlyError:
    """Nunca devolve traceback nem texto vazio. Banco ocupado vira aviso próprio com 'Tentar de novo'."""
    e = tr().errors
    text = " ".join((message or "").split())
    if is_busy_error(text):
        return FriendlyError(e.busy_what, e.busy_why, e.busy_todo, True)
    why = (text if len(text) <= 300 else text[:299] + "…") or e.unknown_why
    return FriendlyError(what or e.fail_what, why, e.fail_todo, False)


def is_outside_data(m: Message) -> bool:
    """Ferramenta e conteúdo marcado como não confiável são sempre 'dado de fora'."""
    return m.role == "tool" or m.untrusted


def called_tools(m: Message) -> list[str]:
    names: list[str] = []
    for call in m.tool_calls or []:
        fn = call.get("function") if isinstance(call, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str) and name:
            names.append(name)
    return names


def default_save_dir() -> Path:
    docs = Path.home() / "Documents"
    try:
        return docs if docs.is_dir() else Path.home()
    except OSError:
        return Path.home()


def safe_file_stem(text: str, fallback: str = "conversa") -> str:
    """Nome de arquivo seguro (sem caracteres proibidos no Windows) a partir de um título."""
    keep = "".join(ch if (ch.isalnum() or ch in " -_") else " " for ch in text)
    stem = "-".join(keep.split())[:60].strip("-_.")
    return stem or fallback


def with_suffix_default(path: str | os.PathLike[str], allowed: tuple[str, ...], default: str) -> Path:
    """Acrescenta a extensão padrão se o usuário não digitou nenhuma das permitidas."""
    p = Path(path)
    return p if p.suffix.lower() in allowed else p.with_name(p.name + default)


def expiry_text(expires_at: float | None, now: float | None = None) -> tuple[str, bool]:
    """(texto da validade, já expirou?)."""
    m = tr().memories
    if expires_at is None:
        return m.never_expires, False
    expired = expires_at <= (now if now is not None else time.time())
    when = fmt_date(expires_at)
    return (m.expired_on.format(when=when) if expired else m.expires_on.format(when=when)), expired


__all__ = ["CONFIRM_WORD", "MAX_VIEW_CHARS", "FriendlyError", "called_tools", "default_save_dir", "expiry_text", "fmt_date",
           "fmt_mb", "fmt_ts", "friendly_error", "is_busy_error", "is_outside_data", "plural",
           "safe_file_stem", "session_state_text", "trash_days_left", "with_suffix_default"]
