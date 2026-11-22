"""WaveBars: ondas da Ilha em camadas (sem numpy: listas de floats, zero alocacao por quadro no calculo).

Camadas: (1) halo largo e translucido (brilho na cor de destaque, so com energia), (2) barras de fundo, mais baixas e
defasadas, (3) barras da frente com gradiente vertical, (4) PICOS (ponto que cai devagar). Simetricas no eixo
horizontal; ataque ~15 ms e queda ~75 ms independentes do fps; 'respiracao' em silencio. Barras alinhadas a grade
de pixels fisicos. Reage ao nivel real (``bands`` 0..1 vindas do nucleo).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap

from . import tokens as T

_SPR: dict[tuple, QPixmap] = {}


def _sprite(kind: str, color: str, alpha: float, w: float, hpx: int, dpr: float) -> QPixmap:
    """Barra rasterizada UMA vez por (tipo, cor, largura, altura em px FISICOS, dpr): desenhar um sprite pequeno por
    barra e bem mais barato que um retangulo arredondado com gradiente a cada quadro, e igualmente nitido (o sprite e
    vetor rasterizado no tamanho fisico, e a altura ja era alinhada a grade de pixels)."""
    key = (kind, color, round(alpha, 2), w, hpx, round(dpr, 2))
    pm = _SPR.get(key)
    if pm is None:
        if len(_SPR) > 600:
            _SPR.clear()
        pm = QPixmap(max(1, round(w * dpr)), max(1, hpx))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        h = hpx / dpr
        col = QColor(color)
        if kind == "cap":
            col.setAlphaF(alpha)
            p.setBrush(col)
            p.drawEllipse(QRectF(0, 0, w, h))
        elif kind == "halo":
            col.setAlphaF(0.16 * alpha)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(0, 0, w, h), w / 2, w / 2)
        else:
            a = alpha * (0.38 if kind == "back" else 1.0)
            top = QColor(col)
            top.setAlphaF(0.55 * a)
            mid = QColor(col)
            mid.setAlphaF(a)
            g = QLinearGradient(0.0, 0.0, 0.0, h)
            g.setColorAt(0.0, top)
            g.setColorAt(0.5, mid)
            g.setColorAt(1.0, top)
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, 0, w, h), w / 2, w / 2)
        p.end()
        _SPR[key] = pm
    return pm


class WaveBars:
    def __init__(self, n: int, bar_w: int, gap: int, max_h: float, min_h: float = 2.0) -> None:
        self.n, self.bar_w, self.gap, self.max_h, self.min_h = n, bar_w, gap, max_h, min_h
        self.width = n * bar_w + (n - 1) * gap
        c = (n - 1) / 2.0
        self._pos = [abs((i - c) / max(c, 1.0)) for i in range(n)]       # 0 centro (graves) .. 1 bordas (agudos)
        self._phase = [i * 0.55 for i in range(n)]
        self.value = [0.0] * n
        self.back = [0.0] * n
        self.peak = [0.0] * n
        self.energy = 0.0
        self._map: list[tuple[int, int, float]] = []
        self._map_n = 0

    def reset(self) -> None:
        for arr in (self.value, self.back, self.peak):
            for i in range(self.n):
                arr[i] = 0.0
        self.energy = 0.0

    def _build_map(self, nb: int) -> None:
        self._map_n = nb
        self._map = []
        for pos in self._pos:
            x = pos * (nb - 1)
            i0 = int(x)
            i1 = min(nb - 1, i0 + 1)
            self._map.append((i0, i1, x - i0))

    def advance(self, bands, dt: float, t: float, *, breathe: bool, amp: float = 1.0) -> None:
        """``bands``: sequencia 0..1 (graves primeiro) ou None; ``breathe``: respiracao em silencio."""
        n = self.n
        up = 1.0 - math.exp(-dt / T.ATTACK_S)
        dn = 1.0 - math.exp(-dt / T.DECAY_S)
        fall = T.PEAK_FALL * dt
        if bands is not None and len(bands):
            if self._map_n != len(bands):
                self._build_map(len(bands))
            m = self._map
        else:
            m = None
        total = 0.0
        val, back, peak, ph = self.value, self.back, self.peak, self._phase
        w = 2 * math.pi * 0.7 * t
        for i in range(n):
            if m is not None:
                a, b, f = m[i]
                tgt = (float(bands[a]) * (1.0 - f) + float(bands[b]) * f) * amp
            else:
                tgt = 0.0
            if breathe:
                br = 0.05 + 0.07 * (0.5 + 0.5 * math.sin(w - ph[i]))
                if br > tgt:
                    tgt = br
            v = val[i]
            v += (tgt - v) * (up if tgt > v else dn)
            val[i] = v
            back[i] += (v - back[i]) * (1.0 - math.exp(-dt / 0.16))     # camada de fundo: segue mais devagar
            p = peak[i] - fall
            peak[i] = v if v > p else (p if p > 0.0 else 0.0)
            total += v
        self.energy = total / n

    def draw(self, p: QPainter, x: float, cy: float, color: str, *, alpha: float = 1.0, dpr: float = 1.0) -> None:
        """Centro vertical em ``cy``, borda esquerda em ``x``. So desenha sprites (sem AA por quadro)."""
        step = self.bar_w + self.gap
        span = self.max_h - self.min_h
        bw = float(self.bar_w)
        inv = 1.0 / dpr
        mn = self.min_h
        val, back, peak = self.value, self.back, self.peak
        n = self.n
        draw = p.drawPixmap
        if self.energy > 0.12:                                           # brilho: halo largo sob as barras da frente
            for i in range(n):
                v = val[i]
                if v < 0.25:
                    continue
                hp = round((mn + span * v + 4.0) * dpr)
                spr = _sprite("halo", color, alpha, bw + 3.0, hp, dpr)
                draw(QPointF(round((x + i * step - 1.5) * dpr) * inv, round((cy - hp * inv / 2) * dpr) * inv), spr)
        for i in range(n):                                               # camada de fundo
            hp = round((mn + span * 0.78 * back[i]) * dpr)
            draw(QPointF(round((x + i * step + 1.0) * dpr) * inv, round((cy - hp * inv / 2) * dpr) * inv),
                 _sprite("back", color, alpha, bw, hp, dpr))
        for i in range(n):                                               # frente
            hp = round((mn + span * val[i]) * dpr)
            draw(QPointF(round((x + i * step) * dpr) * inv, round((cy - hp * inv / 2) * dpr) * inv),
                 _sprite("front", color, alpha, bw, hp, dpr))
        d = max(2.0, bw - 1.0)
        dot = _sprite("cap", color, alpha, d, round(d * dpr), dpr)       # picos
        for i in range(n):
            pk = peak[i]
            if pk - val[i] > 0.06:
                h = mn + span * pk
                cx = x + i * step + bw / 2.0 - d / 2.0
                draw(QPointF(cx, cy - h / 2 - 2.5 - d), dot)
                draw(QPointF(cx, cy + h / 2 + 2.5), dot)


def clear_cache() -> None:
    _SPR.clear()
