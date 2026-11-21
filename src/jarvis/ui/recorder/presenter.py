"""Traduz o estado do modelo em dados de tela (textos pt-BR, numeros formatados, avisos). Sem Qt."""
from __future__ import annotations

from ...recording.audio_analysis import FLOOR_DBFS, Assessment
from ...recording.recorder import ErrorKind, RecorderError
from ...recording.session import ItemStatus, RecordingSession
from .model import TakeVerdict
from .state import Badge, Notice, RowKind, RowView
from .texts import T, Message

_LEVEL_BADGE = {"ok": Badge("ok", T.badges.ok), "baixo": Badge("warn", T.badges.low),
                "saturado": Badge("warn", T.badges.clip)}
_ROW_KIND: dict[ItemStatus, RowKind] = {ItemStatus.PENDING: "neutral", ItemStatus.RECORDED: "ok",
                                        ItemStatus.SKIPPED: "warn"}
_ROW_TEXT = {ItemStatus.PENDING: T.rows.pending, ItemStatus.RECORDED: T.rows.recorded,
             ItemStatus.SKIPPED: T.rows.skipped}
_LEVEL_STATE = {"ok": "ok", "baixo": "warn", "saturado": "error", "silencio": "warn"}
_LEVEL_MESSAGE = {"baixo": T.levels.low, "saturado": T.levels.clip, "silencio": T.levels.silence}


def _decimal(text: str) -> str:
    return text.replace(".", ",")


def fmt_seconds(value: float) -> str:
    return _decimal(f"{max(0.0, value):.1f}") + " s"


def fmt_db(value: float) -> str:
    return "−∞" if value <= FLOOR_DBFS else _decimal(f"{value:.1f}").replace("-", "−")


def metrics_text(a: Assessment) -> str:
    s = T.stage
    parts = (f"{s.peak} {fmt_db(a.peak_dbfs)} dBFS", f"{s.rms} {fmt_db(a.rms_dbfs)} dBFS",
             f"{s.clip_rate} {_decimal(f'{a.clip_rate * 100:.2f}')}%", f"{s.duration} {fmt_seconds(a.duration_s)}")
    return "   ".join(parts)


def wave_state(a: Assessment | None) -> str:
    """Estado de cor da onda (ok/warn/error) ou vazio quando nao ha avaliacao."""
    return _LEVEL_STATE.get(a.level, "") if a is not None else ""


def take_badge(status: ItemStatus, a: Assessment | None, *, recording: bool, saving: bool,
               unsaved: TakeVerdict | None) -> Badge:
    """Estado do take atual, sempre com texto (o chip junta icone, cor e palavra)."""
    if recording:
        return Badge("neutral", T.badges.recording)
    if saving:
        return Badge("neutral", T.badges.saving)
    if unsaved == "silence":
        return Badge("error", T.badges.unsaved_silence)
    if unsaved == "short":
        return Badge("warn", T.badges.unsaved_short)
    if status is ItemStatus.RECORDED:
        return _LEVEL_BADGE.get(a.level if a else "", Badge("ok", T.badges.recorded))
    if status is ItemStatus.SKIPPED:
        return Badge("warn", T.badges.skipped)
    return Badge("neutral", T.badges.pending)


def rows(session: RecordingSession) -> tuple[RowView, ...]:
    rset = session.recording_set
    return tuple(
        RowView(i + 1, rset.label(i), _ROW_TEXT[st], _ROW_KIND[st], f"{rset.filename(i)}: {_ROW_TEXT[st]}")
        for i, st in enumerate(session.statuses))


def _from(state: str, m: Message, *, action: str = "", detail: str = "") -> Notice:
    return Notice(state, m.what, m.why, m.todo, action, detail)  # type: ignore[arg-type]


def level_notice(a: Assessment | None, unsaved: TakeVerdict | None) -> Notice | None:
    """Aviso derivado do take mostrado: nivel baixo, saturado, silencio ou curto demais."""
    if unsaved == "short":
        return _from("warn", T.levels.short)
    if a is None or a.level == "ok":
        return None
    msg = _LEVEL_MESSAGE[a.level]
    return _from("error" if a.level == "silencio" else "warn", msg)


def device_notice(err: RecorderError | str, kind: ErrorKind = "other", *, retry: bool = True) -> Notice:
    """Erro de dispositivo em tres linhas. O texto tecnico vai so para a dica (e para o log)."""
    k = err.kind if isinstance(err, RecorderError) else kind
    msg: Message = getattr(T.failures, k if k in ("missing", "busy", "permission", "format", "stalled") else "other")
    return _from("error", msg, action=T.failures.retry if retry else "", detail=str(err))


def failure(msg: Message, state: str = "error", *, action: str = "", detail: str = "") -> Notice:
    return _from(state, msg, action=action, detail=detail)
