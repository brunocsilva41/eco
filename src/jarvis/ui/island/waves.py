"""WaveBars: barras arredondadas simetricas (espelhadas no eixo horizontal) com altura suavizada.

Ataque quase imediato e queda lenta (~75 ms) independentes do fps; 'respiracao' discreta em
silencio; leve gradiente vertical da cor de destaque. Barras alinhadas a grade de pixels fisicos
(sem serrilhado). A geometria e pre-calculada; ``advance`` so usa numpy.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter

from . import tokens as T


class WaveBars:
    def __init__(self, n: int, bar_w: int, gap: int, max_h: float, min_h: float = 2.0) -> None:
        self.n, self.bar_w, self.gap, self.max_h, self.min_h = n, bar_w, gap, max_h, min_h
        self.width = n * bar_w + (n - 1) * gap
        c = (n - 1) / 2.0
        # posicao 0 (centro, graves) a 1 (bordas, agudos): espelhado, como nos visualizadores de voz
        self._pos = np.abs((np.arange(n) - c) / max(c, 1.0)).astype(np.float32)
        self._phase = (np.arange(n) * 0.55).astype(np.float32)
        self.value = np.zeros(n, dtype=np.float32)

    def reset(self) -> None:
        self.value[:] = 0.0

    def advance(self, bands: np.ndarray | None, dt: float, t: float, *, breathe: bool, amp: float = 1.0) -> None:
        """``bands``: 0..1 (N bandas, graves primeiro) ou None; ``breathe``: respiracao em silencio."""
        if bands is not None and len(bands):
            target = np.interp(self._pos, np.linspace(0.0, 1.0, len(bands)), bands).astype(np.float32) * amp
        else:
            target = np.zeros(self.n, dtype=np.float32)
        if breathe:
            wave = 0.5 + 0.5 * np.sin(2 * math.pi * 0.7 * t - self._phase)
            target = np.maximum(target, (0.05 + 0.07 * wave).astype(np.float32))
        up = 1.0 - math.exp(-dt / T.ATTACK_S)
        dn = 1.0 - math.exp(-dt / T.DECAY_S)
        coef = np.where(target > self.value, up, dn)
        self.value += (target - self.value) * coef

    def draw(self, p: QPainter, x: float, cy: float, color: str, *, alpha: float = 1.0, dpr: float = 1.0) -> None:
        """Desenha com o centro vertical em ``cy`` e a borda esquerda em ``x``."""
        col = QColor(color)
        top = QColor(col)
        top.setAlphaF(0.55 * alpha)
        mid = QColor(col)
        mid.setAlphaF(alpha)
        g = QLinearGradient(0.0, cy - self.max_h / 2, 0.0, cy + self.max_h / 2)
        g.setColorAt(0.0, top)
        g.setColorAt(0.5, mid)
        g.setColorAt(1.0, top)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        step = self.bar_w + self.gap
        r = self.bar_w / 2.0
        span = self.max_h - self.min_h
        for i in range(self.n):
            h = self.min_h + span * float(self.value[i])
            h = round(h * dpr) / dpr
            bx = round((x + i * step) * dpr) / dpr
            by = round((cy - h / 2) * dpr) / dpr
            p.drawRoundedRect(QRectF(bx, by, self.bar_w, h), r, r)
