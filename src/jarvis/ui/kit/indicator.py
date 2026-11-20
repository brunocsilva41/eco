"""ListeningIndicator: o UNICO elemento do kit com brilho (glow), para "ouvindo" e "gravando".

Motivo (R-13/R-19): e o estado vivo do produto e precisa ser visto de longe; o brilho e o pulso
marcam captura de audio real. Nenhum outro componente tem glow nem animacao em laco. Sem
"reduzir animacoes" ligado o pulso para e o brilho fica estatico. O pulso para ao esconder/fechar.
"""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import SPACE, TYPE, make_font, motion_enabled, pal
from .base import set_a11y, strs, watch_theme

IndicatorState = Literal["idle", "listening", "recording"]
_DOT = float(SPACE.md)
_DOT_R = _DOT / 2
_GLOW = float(SPACE.xl)
_PULSE_MS = 1400


class ListeningIndicator(QWidget):
    """Ponto + texto. idle: anel apagado; listening: anel ambar com pulso; recording: ponto cheio com brilho."""

    def __init__(self, state: IndicatorState = "idle", *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state: IndicatorState = state
        self._phase = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(_PULSE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_phase)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        watch_theme(self)
        self._sync()

    def set_state(self, state: IndicatorState) -> None:
        self._state = state
        self._sync()

    def state(self) -> IndicatorState:
        return self._state

    def _label(self) -> str:
        s = strs().status
        return {"idle": s.idle, "listening": s.listening, "recording": s.recording}[self._state]

    def _sync(self) -> None:
        set_a11y(self, self._label())
        self._update_anim()
        self.updateGeometry()
        self.update()

    def _update_anim(self) -> None:
        run = self._state != "idle" and self.isVisible() and motion_enabled()
        if run and self._anim.state() != QVariantAnimation.State.Running:
            self._anim.start()
        elif not run:
            self._anim.stop()
            self._phase = 1.0

    def _on_phase(self, v: float) -> None:
        self._phase = 0.55 + 0.45 * float(v)
        self.update()

    def showEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(e)
        self._update_anim()

    def hideEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        self._anim.stop()
        super().hideEvent(e)

    def closeEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        self._anim.stop()
        super().closeEvent(e)

    def sizeHint(self) -> QSize:
        w = QFontMetrics(make_font(TYPE.body, TYPE.semibold)).horizontalAdvance(self._label())
        return QSize(int(_GLOW * 2 + SPACE.xs + w), int(_GLOW * 2))

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = QPointF(_GLOW, self.height() / 2)
        live = self._state != "idle"
        if live:
            glow = QRadialGradient(c, _GLOW * (0.7 + 0.3 * self._phase))
            tone = QColor(p.accent)
            tone.setAlphaF(0.38 * self._phase)
            glow.setColorAt(0.0, tone)
            tone.setAlphaF(0.0)
            glow.setColorAt(1.0, tone)
            g.setPen(Qt.PenStyle.NoPen)
            g.setBrush(glow)
            g.drawEllipse(c, _GLOW, _GLOW)
        dot = QRectF(c.x() - _DOT_R, c.y() - _DOT_R, _DOT, _DOT)
        if self._state == "recording":
            g.setPen(Qt.PenStyle.NoPen)
            g.setBrush(QColor(p.accent))
        else:
            g.setBrush(Qt.BrushStyle.NoBrush)
            g.setPen(QPen(QColor(p.accent_ink if live else p.text_muted), 2))
            dot = dot.adjusted(1, 1, -1, -1)
        g.drawEllipse(dot)
        g.setFont(make_font(TYPE.body, TYPE.semibold))
        g.setPen(QColor(p.text if live else p.text_muted))
        g.drawText(QRectF(_GLOW * 2 + SPACE.xs, 0, self.width(), self.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._label())
        g.end()
