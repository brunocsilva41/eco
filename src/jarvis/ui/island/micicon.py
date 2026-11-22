"""Icone de microfone da Ilha, desenhado do zero com QPainterPath (sem fonte, sem emoji, sem SVG).

Grade de 24: capsula + berco em U + haste + base, traco de 2 px (escala com o tamanho, minimo 1,5),
pontas e juntas arredondadas. Estados: REST (contorno), LISTENING (capsula cheia + anel pulsante
suave), MUTED (barra diagonal com vao), ERROR (cor de erro + selo). Nitido em 16/20/24 px e em
100 a 200% porque e vetor desenhado direto no tamanho fisico do painter.
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

_CAPSULE = QRectF(9.0, 2.5, 6.0, 11.0)


class MicKind(Enum):
    REST = "repouso"
    LISTENING = "ouvindo"
    MUTED = "mudo"
    ERROR = "erro"


def _cradle() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(5.5, 11.0)
    p.arcTo(QRectF(5.5, 5.0, 13.0, 12.0), 180.0, 180.0)   # meia-elipse inferior: (5.5,11) -> (12,17) -> (18.5,11)
    p.moveTo(12.0, 17.0)
    p.lineTo(12.0, 20.5)
    p.moveTo(8.5, 20.5)
    p.lineTo(15.5, 20.5)
    return p


_CRADLE = _cradle()


def draw_mic(p: QPainter, rect: QRectF, kind: MicKind, color: str, *, bg: str, phase: float = 0.0,
             error_color: str | None = None) -> None:
    """Desenha em ``rect`` (quadrado). ``phase`` 0..1 anima o anel de LISTENING (0 = sem anel)."""
    s = min(rect.width(), rect.height())
    k = s / 24.0
    stroke = max(1.5, 2.0 * k) / k                     # em unidades da grade
    col = QColor(error_color or color) if kind is MicKind.ERROR else QColor(color)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(rect.x() + (rect.width() - s) / 2, rect.y() + (rect.height() - s) / 2)
    p.scale(k, k)
    pen = QPen(col, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    if kind is MicKind.LISTENING and phase > 0.0:
        ring = QColor(col)
        ring.setAlphaF(0.55 * (1.0 - phase))
        grow = 1.0 + 3.5 * phase
        p.setPen(QPen(ring, stroke * 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = _CAPSULE.adjusted(-grow, -grow, grow, grow)
        p.drawRoundedRect(r, 3.0 + grow, 3.0 + grow)
    p.setPen(pen)
    p.setBrush(col if kind is MicKind.LISTENING else Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(_CAPSULE, 3.0, 3.0)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(_CRADLE)
    if kind is MicKind.MUTED:
        p.setPen(QPen(QColor(bg), stroke + 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(4.5, 3.5), QPointF(19.5, 20.5))
        p.setPen(pen)
        p.drawLine(QPointF(4.5, 3.5), QPointF(19.5, 20.5))
    elif kind is MicKind.ERROR:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.drawEllipse(QPointF(19.0, 5.0), 4.6, 4.6)
        p.setBrush(col)
        p.drawEllipse(QPointF(19.0, 5.0), 3.2, 3.2)
    p.restore()


def pulse_phase(t: float, period: float = 1.4) -> float:
    """0..1 (dente de serra) para o anel de 'ouvindo'; o alpha cai ao crescer, entao a volta e suave."""
    return (t / period) % 1.0
