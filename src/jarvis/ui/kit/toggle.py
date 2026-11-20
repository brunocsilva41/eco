"""ToggleSwitch: interruptor de verdade (trilho + botao deslizante), com texto de estado."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from ..theme import MOTION, SIZE, SPACE, TYPE, make_font, pal
from .base import animate, paint_focus_ring, set_a11y, strs, watch_theme


class ToggleSwitch(QAbstractButton):
    """Liga/desliga. Espaco ou clique alternam; ``valueChanged(bool)``.

    O estado nunca depende so de cor: o botao muda de lado e o texto "Ligado/Desligado" acompanha
    (``show_text=False`` esconde o texto quando o rotulo da linha ja o diz).
    """

    valueChanged = Signal(bool)

    def __init__(self, checked: bool = False, *, show_text: bool = True, accessible_name: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self._show_text = show_text
        self._pos = 1.0 if checked else 0.0
        self._anim: QVariantAnimation | None = None
        self._invalid = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.toggled.connect(self._on_toggled)
        watch_theme(self)
        if accessible_name:
            set_a11y(self, accessible_name)

    # --- API de valor
    def value(self) -> bool:
        return self.isChecked()

    def set_value(self, value: bool) -> None:
        self.setChecked(value)

    def set_invalid(self, invalid: bool) -> None:
        self._invalid = invalid
        self.update()

    def is_invalid(self) -> bool:
        return self._invalid

    # --- geometria
    def _text(self) -> str:
        return strs().common.on if self.isChecked() else strs().common.off

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(make_font(TYPE.body))
        text_w = max(fm.horizontalAdvance(strs().common.on), fm.horizontalAdvance(strs().common.off)) if self._show_text else 0
        extra = SPACE.sm + text_w if self._show_text else 0
        return QSize(SIZE.toggle_w + 2 * SIZE.focus_ring + extra + SPACE.xs, SIZE.target)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _track_rect(self) -> QRectF:
        top = (self.height() - SIZE.toggle_h) / 2
        return QRectF(SIZE.focus_ring + 1, top, SIZE.toggle_w, SIZE.toggle_h)

    # --- animacao
    def _on_toggled(self, checked: bool) -> None:
        if self._anim is not None:
            self._anim.stop()
        self._anim = animate(self, self._pos, 1.0 if checked else 0.0, MOTION.base, self._set_pos)
        self.valueChanged.emit(checked)

    def _set_pos(self, v: float) -> None:
        self._pos = v
        self.update()

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._anim is not None:
            self._anim.stop()
            self._pos = 1.0 if self.isChecked() else 0.0
        super().hideEvent(event)

    # --- pintura
    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = self._track_rect()
        radius = track.height() / 2          # trilho em capsula: e um interruptor, nao um botao
        on = self.isChecked()
        if not self.isEnabled():
            fill, edge, thumb = p.surface, p.border, p.text_disabled
        else:
            fill = p.accent if on else p.raised
            edge = p.error if self._invalid else (p.accent_ink if on else p.border_strong)
            thumb = p.on_accent if on else p.text_muted
            if self.underMouse() and not on:
                fill = p.hover
        g.setBrush(QColor(fill))
        g.setPen(QPen(QColor(edge), SIZE.border))
        g.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        d = track.height() - 2 * SPACE.xs + 2
        x = track.left() + SPACE.xs - 1 + self._pos * (track.width() - d - 2 * (SPACE.xs - 1))
        g.setBrush(QColor(thumb))
        g.setPen(Qt.PenStyle.NoPen)
        g.drawEllipse(QRectF(x, track.center().y() - d / 2, d, d))
        if self._show_text:
            g.setFont(make_font(TYPE.body))
            g.setPen(QColor(p.text if self.isEnabled() else p.text_disabled))
            text_rect = QRectF(track.right() + SPACE.sm, 0, self.width() - track.right() - SPACE.sm, self.height())
            g.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._text())
        if self.hasFocus():
            paint_focus_ring(g, track.adjusted(-SIZE.focus_ring - 1, -SIZE.focus_ring - 1, SIZE.focus_ring + 1, SIZE.focus_ring + 1),
                             radius + SIZE.focus_ring + 1)
        g.end()
