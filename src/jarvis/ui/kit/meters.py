"""Medidores: LevelMeter (nivel de entrada), CountdownRing (contagem regressiva), ProgressBar (fina)."""
from __future__ import annotations

import time
from typing import Literal

from PySide6.QtCore import QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import MOTION, RADIUS, SIZE, SPACE, TYPE, make_font, pal
from .base import animate, set_a11y, strs, watch_theme

Band = Literal["low", "ok", "clip"]
_BAND_STATE: dict[str, str] = {"low": "warn", "ok": "ok", "clip": "error"}
_GAP = 2.0


class LevelMeter(QWidget):
    """Medidor horizontal de nivel em dBFS com tres faixas: baixo, otimo e saturado.

    Cada faixa tem NOME escrito sob a barra (a cor nao e o unico sinal), a faixa atual fica em
    destaque e o valor aparece como numeral tabular. Marcador de pico cai 18 dB/s (sem timer:
    calculado a cada ``set_level``). Sem logica de negocio: quem chama decide os limiares.
    """

    PEAK_FALL_DB_PER_S = 18.0

    def __init__(self, *, floor_db: float = -60.0, low_db: float = -42.0, high_db: float = -6.0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._floor, self._low, self._high = floor_db, low_db, high_db
        self._level = floor_db
        self._peak = floor_db
        self._peak_t = time.monotonic()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        watch_theme(self)
        self._sync_a11y()

    # --- API
    def set_level(self, db: float) -> None:
        db = max(self._floor, min(0.0, db))
        now = time.monotonic()
        fallen = self._peak - (now - self._peak_t) * self.PEAK_FALL_DB_PER_S
        self._peak = max(db, fallen, self._floor)
        self._peak_t = now
        self._level = db
        self._sync_a11y()
        self.update()

    def level(self) -> float:
        return self._level

    def band(self) -> Band:
        return "low" if self._level < self._low else ("clip" if self._level >= self._high else "ok")

    def set_thresholds(self, low_db: float, high_db: float) -> None:
        self._low, self._high = low_db, high_db
        self.update()

    def reset_peak(self) -> None:
        self._peak = self._level
        self.update()

    def _band_name(self, band: str) -> str:
        s = strs().status
        return {"low": s.level_low, "ok": s.level_ok, "clip": s.level_clip}[band]

    def _sync_a11y(self) -> None:
        set_a11y(self, strs().status.meter_name, f"{strs().status.db(self._level)}, {self._band_name(self.band())}")

    # --- geometria
    def sizeHint(self) -> QSize:
        return QSize(SIZE.target * 10, SPACE.xxl + SPACE.sm + SPACE.md + SPACE.lg + SPACE.xs)

    def minimumSizeHint(self) -> QSize:
        return QSize(SIZE.target * 5, self.sizeHint().height())

    def _x(self, db: float, left: float, width: float) -> float:
        return left + (db - self._floor) / (0.0 - self._floor) * width

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        band = self.band()
        # leitura numerica (tabular) + nome da faixa atual
        g.setFont(make_font(TYPE.title, TYPE.semibold, tabular=True))
        g.setPen(QColor(p.text))
        value_txt = strs().status.db(self._level)
        g.drawText(QRectF(0, 0, w, SPACE.xxl), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), value_txt)
        vw = QFontMetrics(g.font()).horizontalAdvance(value_txt)
        g.setFont(make_font(TYPE.body, TYPE.semibold))
        g.setPen(QColor(p.state(_BAND_STATE[band])))
        g.drawText(QRectF(vw + SPACE.md, 0, w, SPACE.xxl), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._band_name(band))
        # trilho em tres faixas
        top, h = float(SPACE.xxl + SPACE.xs), float(SPACE.md)
        edges = [self._floor, self._low, self._high, 0.0]
        for i, name in enumerate(("low", "ok", "clip")):
            x0 = self._x(edges[i], 0, w) + (0 if i == 0 else _GAP / 2)
            x1 = self._x(edges[i + 1], 0, w) - (0 if i == 2 else _GAP / 2)
            seg = QRectF(x0, top, x1 - x0, h)
            ink = p.state(_BAND_STATE[name])
            dim = QColor(ink)
            dim.setAlphaF(0.22)
            g.setPen(Qt.PenStyle.NoPen)
            g.setBrush(dim)
            g.drawRoundedRect(seg, RADIUS.sm, RADIUS.sm)
            lit_to = min(self._level, edges[i + 1])
            if lit_to > edges[i]:
                lit = QRectF(x0, top, max(0.0, self._x(lit_to, 0, w) - x0), h)
                g.setBrush(QColor(ink))
                g.drawRoundedRect(lit, RADIUS.sm, RADIUS.sm)
            # nomes sob a barra: a faixa atual em destaque
            active = name == band
            g.setFont(make_font(TYPE.caption, TYPE.semibold if active else TYPE.regular))
            g.setPen(QColor(p.text if active else p.text_muted))
            g.drawText(QRectF(x0, top + h + SPACE.xs, x1 - x0, SPACE.lg), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       self._band_name(name))
        # marcador de pico
        if self._peak > self._floor + 1:
            px_ = self._x(self._peak, 0, w)
            g.setPen(QPen(QColor(p.text), 2))
            g.drawLine(int(px_), int(top - 3), int(px_), int(top + h + 3))
        g.end()


class CountdownRing(QWidget):
    """Anel de contagem regressiva com o numero de segundos restantes em numeral tabular.

    ``set_active(True)`` (gravando) pinta o arco em ambar; parado usa o texto normal. O numero
    mostra segundos restantes (arredondado para cima), a unidade "s" fica sob ele.
    """

    def __init__(self, total_s: float = 20.0, *, diameter: int = SIZE.target * 5, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._total = max(0.001, total_s)
        self._remaining = total_s
        self._active = False
        self._d = diameter
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        watch_theme(self)
        self._sync_a11y()

    def set_total(self, seconds: float) -> None:
        self._total = max(0.001, seconds)
        self.update()

    def set_remaining(self, seconds: float) -> None:
        self._remaining = max(0.0, min(self._total, seconds))
        self._sync_a11y()
        self.update()

    def remaining(self) -> float:
        return self._remaining

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def _sync_a11y(self) -> None:
        set_a11y(self, strs().status.countdown_name, f"{self._shown()} {strs().status.seconds}")

    def _shown(self) -> int:
        return int(-(-self._remaining // 1))

    def sizeHint(self) -> QSize:
        return QSize(self._d, self._d)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        stroke = float(SPACE.sm)
        box = QRectF(self.rect()).adjusted(stroke / 2, stroke / 2, -stroke / 2, -stroke / 2)
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(QPen(QColor(p.border), stroke))
        g.drawEllipse(box)
        frac = self._remaining / self._total
        if frac > 0:
            pen = QPen(QColor(p.accent if self._active else p.text_muted), stroke)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            g.setPen(pen)
            g.drawArc(box, 90 * 16, int(-frac * 360 * 16))
        g.setFont(make_font(TYPE.counter, TYPE.bold, tabular=True))
        g.setPen(QColor(p.text))
        g.drawText(QRectF(self.rect()).adjusted(0, -SPACE.md, 0, -SPACE.md), int(Qt.AlignmentFlag.AlignCenter), str(self._shown()))
        g.setFont(make_font(TYPE.small))
        g.setPen(QColor(p.text_muted))
        g.drawText(QRectF(self.rect()).adjusted(0, self.height() // 2 + SPACE.lg + SPACE.xs, 0, 0), int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                   strs().status.seconds)
        g.end()


class ProgressBar(QWidget):
    """Barra fina (4 px) de progresso determinado, animada em 150 ms. Ex.: "Frase 7 de 20"."""

    def __init__(self, value: float = 0.0, maximum: float = 1.0, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max = max(maximum, 1e-9)
        self._value = value
        self._shown = value
        self._anim: QVariantAnimation | None = None
        self.setFixedHeight(SPACE.xs + 2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        watch_theme(self)

    def set_progress(self, value: float, maximum: float | None = None) -> None:
        if maximum is not None:
            self._max = max(maximum, 1e-9)
        self._value = max(0.0, min(self._max, value))
        if self._anim is not None:
            self._anim.stop()
        self._anim = animate(self, self._shown, self._value, MOTION.base, self._set_shown)

    def value(self) -> float:
        return self._value

    def _set_shown(self, v: float) -> None:
        self._shown = v
        self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(QColor(p.border))
        g.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        g.setBrush(QColor(p.text_muted))
        g.drawRoundedRect(QRectF(0, 0, r.width() * (self._shown / self._max), r.height()), r.height() / 2, r.height() / 2)
        g.end()
