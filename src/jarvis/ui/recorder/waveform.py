"""Forma de onda da gravacao (minimo e maximo por coluna de pixels). Desenha so o que recebe."""
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..kit.base import set_a11y, watch_theme
from ..theme import RADIUS, SPACE, TYPE, make_font, pal
from .texts import T


class WaveformView(QWidget):
    """Mostra a onda; sem amostras, escreve ``empty_text`` (o espaco fica reservado, a tela nao pula)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples: NDArray[np.float32] | None = None
        self._state = ""
        self._text = T.stage.wave_empty
        self._cache: tuple[int, NDArray[np.float32], NDArray[np.float32]] | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(SPACE.xxl * 2)
        set_a11y(self, T.stage.wave_empty)
        watch_theme(self)

    def set_wave(self, samples: NDArray[np.float32] | None, state: str, text: str) -> None:
        self._samples = samples if samples is not None and samples.size else None
        self._state = state
        self._text = text
        self._cache = None
        set_a11y(self, text if self._samples is None else "Forma de onda da gravação")
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(SPACE.huge * 8, SPACE.xxl * 2)

    def _columns(self, width: int) -> tuple[NDArray[np.float32], NDArray[np.float32]] | None:
        data = self._samples
        if data is None or width <= 0:
            return None
        if self._cache is not None and self._cache[0] == width:
            return self._cache[1], self._cache[2]
        cols = min(width, data.size)
        edges = np.linspace(0, data.size, cols + 1, dtype=np.int64)[:-1]
        lows, highs = np.minimum.reduceat(data, edges), np.maximum.reduceat(data, edges)
        self._cache = (width, lows, highs)
        return lows, highs

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g.setPen(QPen(QColor(p.border)))
        g.setBrush(QColor(p.surface))
        g.drawRoundedRect(rect, RADIUS.sm, RADIUS.sm)
        mid = rect.center().y()
        cols = self._columns(int(rect.width()))
        if cols is None:
            g.setFont(make_font(TYPE.small))
            g.setPen(QColor(p.text_muted))
            g.drawText(rect.adjusted(SPACE.md, 0, -SPACE.md, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._text)
            g.end()
            return
        g.setPen(QPen(QColor(p.border)))
        g.drawLine(QPointF(rect.left(), mid), QPointF(rect.right(), mid))
        lows, highs = cols
        half = rect.height() / 2 - SPACE.xs
        g.setPen(QPen(QColor(p.state(self._state) if self._state else p.text_muted), 1))
        step = rect.width() / lows.size
        for i in range(lows.size):
            x = rect.left() + (i + 0.5) * step
            g.drawLine(QPointF(x, mid - float(highs[i]) * half), QPointF(x, mid - float(lows[i]) * half - 0.5))
        g.end()
