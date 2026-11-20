"""StatusChip: estado ok/atencao/erro SEMPRE com icone + texto (nunca so cor). Unica pilula do kit."""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import SIZE, SPACE, TYPE, Palette, make_font, pal
from . import icons
from .base import set_a11y, strs, watch_theme

ChipState = Literal["ok", "warn", "error", "neutral"]
STATE_ICON: dict[str, str] = {"ok": "ok", "warn": "alert", "error": "error", "neutral": "info"}
_CHIP_H = SPACE.xl
_ICON = SIZE.icon - 2


def state_label(state: str) -> str:
    s = strs().status
    return {"ok": s.ok, "warn": s.warn, "error": s.error}.get(state, s.neutral)


def state_ink(p: Palette, state: str) -> str:
    return p.state(state) if state in ("ok", "warn", "error") else p.text_muted


def state_tint(p: Palette, state: str) -> str:
    return p.state_bg(state) if state in ("ok", "warn", "error") else p.hover


class StatusChip(QWidget):
    """Selo de estado. Pilula permitida aqui porque e um rotulo de estado, nao um controle.

    ``icon_name`` troca o icone padrao do estado (ex.: "refresh" no selo "Requer reinicio").
    Nome acessivel: "Erro: <texto>".
    """

    def __init__(self, state: ChipState, text: str, *, icon_name: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state: ChipState = state
        self._text = text
        self._icon_name = icon_name
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        watch_theme(self)
        self._sync()

    def set_state(self, state: ChipState, text: str | None = None) -> None:
        self._state = state
        if text is not None:
            self._text = text
        self._sync()

    def state(self) -> ChipState:
        return self._state

    def text(self) -> str:
        return self._text

    def _sync(self) -> None:
        set_a11y(self, f"{state_label(self._state)}: {self._text}")
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        w = SPACE.sm + _ICON + SPACE.xs + QFontMetrics(make_font(TYPE.small, TYPE.semibold)).horizontalAdvance(self._text) + SPACE.md
        return QSize(w, _CHIP_H)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(QColor(state_tint(p, self._state)))
        g.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        ink = state_ink(p, self._state)
        name = self._icon_name or STATE_ICON[self._state]
        g.drawPixmap(int(SPACE.sm), int((rect.height() - _ICON) / 2), icons.pixmap(name, ink, _ICON, self))
        g.setFont(make_font(TYPE.small, TYPE.semibold))
        g.setPen(QColor(ink))
        text_rect = QRectF(SPACE.sm + _ICON + SPACE.xs, 0, rect.width(), rect.height())
        g.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._text)
        g.end()
