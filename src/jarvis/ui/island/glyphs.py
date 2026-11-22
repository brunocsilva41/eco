"""Icones vetoriais da Ilha (QPainterPath na grade de 24, traco 1,75 px ate 20 px e 2 px acima, pontas e juntas
arredondadas, mesmo peso visual). Sem fonte, sem emoji, sem SVG, sem sprite: tudo e desenhado direto no tamanho
FISICO do painter (nitido de 100 a 200%).

``draw(p, nome, rect, cor)``            icone estatico (cacheado como QPixmap por ``pixmap``).
``draw_state(p, estado, rect, cor, t)`` icone de ESTADO animado (ouvindo com anel, pensando orbital,
                                        executando com engrenagem e arco de progresso, falando com ondas...).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

_G = 24.0
_BG = "#050608"


def _poly(*pts: tuple[float, float], close: bool = False) -> QPainterPath:
    p = QPainterPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if close:
        p.closeSubpath()
    return p


def _join(*paths: QPainterPath) -> QPainterPath:
    out = QPainterPath()
    for q in paths:
        out.addPath(q)                                   # NAO usar "+" (united fecha e simplifica subcaminhos abertos)
    return out


def _capsule() -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(QRectF(9.0, 2.5, 6.0, 11.0), 3.0, 3.0)
    return p


def _cradle() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(5.5, 11.0)
    p.arcTo(QRectF(5.5, 5.0, 13.0, 12.0), 180.0, 180.0)
    p.moveTo(12.0, 17.0)
    p.lineTo(12.0, 20.5)
    p.moveTo(8.5, 20.5)
    p.lineTo(15.5, 20.5)
    return p


def _arcs() -> QPainterPath:
    """Ondas de som dos dois lados do microfone (escuta aberta)."""
    p = QPainterPath()
    for sx in (-1.0, 1.0):
        x0 = 12.0 + sx * 9.6
        p.moveTo(x0, 5.2)
        p.quadTo(x0 + sx * 2.2, 8.5, x0, 11.8)
    return p


def _gear() -> QPainterPath:
    pts: list[QPointF] = []
    for i in range(8):
        th = math.radians(i * 45.0)
        for off, r in ((-15.0, 6.9), (-8.5, 9.3), (8.5, 9.3), (15.0, 6.9)):
            a = th + math.radians(off)
            pts.append(QPointF(12.0 + r * math.cos(a), 12.0 + r * math.sin(a)))
    p = QPainterPath()
    p.moveTo(pts[0])
    for q in pts[1:]:
        p.lineTo(q)
    p.closeSubpath()
    p.addEllipse(QPointF(12.0, 12.0), 3.0, 3.0)
    return p


def _shield() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(12.0, 2.8)
    p.lineTo(19.2, 5.6)
    p.lineTo(19.2, 11.5)
    p.cubicTo(19.2, 16.0, 16.2, 19.4, 12.0, 21.2)
    p.cubicTo(7.8, 19.4, 4.8, 16.0, 4.8, 11.5)
    p.lineTo(4.8, 5.6)
    p.closeSubpath()
    return p


def _wrench() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(5.0, 19.0)
    p.lineTo(12.3, 11.7)
    p.moveTo(14.2, 5.2)
    p.arcTo(QRectF(11.7, 3.0, 8.4, 8.4), 215.0, 290.0)
    return p


_STROKES: dict[str, QPainterPath] = {
    "mic": _join(_cradle(), _capsule()),
    "listen": _join(_cradle(), _capsule(), _arcs()),
    "stop": _poly((7.0, 7.0), (17.0, 7.0), (17.0, 17.0), (7.0, 17.0), close=True),
    "check": _poly((5.0, 12.5), (10.0, 17.5), (19.0, 7.0)),
    "close": _join(_poly((6.5, 6.5), (17.5, 17.5)), _poly((17.5, 6.5), (6.5, 17.5))),
    "gear": _gear(),
    "pin": _join(_poly((8.5, 3.5), (15.5, 3.5), (14.5, 10.0), (18.0, 14.0), (6.0, 14.0), (9.5, 10.0), close=True),
                 _poly((12.0, 14.0), (12.0, 21.0))),
    "bolt": _poly((13.5, 2.5), (5.0, 13.5), (11.5, 13.5), (10.5, 21.5), (19.0, 10.0), (12.5, 10.0), close=True),
    "shield": _shield(),
    "layers": _join(_poly((12.0, 3.5), (20.5, 8.0), (12.0, 12.5), (3.5, 8.0), close=True),
                    _poly((3.5, 12.0), (12.0, 16.5), (20.5, 12.0)), _poly((3.5, 16.0), (12.0, 20.5), (20.5, 16.0))),
    "tool": _wrench(),
    "alert": _join(_poly((12.0, 3.8), (21.0, 19.5), (3.0, 19.5), close=True), _poly((12.0, 9.5), (12.0, 13.8))),
    "clock": _poly((12.0, 7.0), (12.0, 12.0), (15.5, 14.2)),
    "info": _poly((12.0, 11.0), (12.0, 17.0)),
    "text": _join(_poly((5.0, 7.5), (19.0, 7.5)), _poly((5.0, 12.0), (15.0, 12.0)), _poly((5.0, 16.5), (11.0, 16.5))),
}
_RINGS = {"clock": (12.0, 12.0, 9.0), "info": (12.0, 12.0, 9.0), "stop": None}
_FILLS: dict[str, QPainterPath] = {"mic": _capsule(), "listen": _capsule(), "stop": _STROKES["stop"], "pin": _STROKES["pin"],
                                   "bolt": _STROKES["bolt"], "shield": _STROKES["shield"]}
_DOTS = {"alert": [(12.0, 16.6, 1.15)], "info": [(12.0, 7.6, 1.15)]}


def _stroke_w(size: float) -> float:
    return 1.75 if size < 22 else 2.0


def _pen(col: QColor, w: float) -> QPen:
    return QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def _begin(p: QPainter, rect: QRectF) -> float:
    s = min(rect.width(), rect.height())
    k = s / _G
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(rect.x() + (rect.width() - s) / 2, rect.y() + (rect.height() - s) / 2)
    p.scale(k, k)
    return _stroke_w(s) / k                              # espessura em unidades da grade


def _color(color: str | QColor, alpha: float) -> QColor:
    c = QColor(color)
    if alpha < 1.0:
        c.setAlphaF(c.alphaF() * max(0.0, alpha))
    return c


def _draw_name(p: QPainter, name: str, col: QColor, w: float, fill: bool) -> None:
    p.setPen(_pen(col, w))
    p.setBrush(Qt.BrushStyle.NoBrush)
    ring = _RINGS.get(name)
    if ring:
        p.drawEllipse(QPointF(ring[0], ring[1]), ring[2], ring[2])
    if fill and name in _FILLS:
        p.setBrush(col)
    p.drawPath(_STROKES[name])
    for x, y, r in _DOTS.get(name, ()):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(x, y), r, r)


def draw(p: QPainter, name: str, rect: QRectF, color: str | QColor, *, fill: bool = False, alpha: float = 1.0,
         bg: str = _BG) -> None:
    """Icone estatico. ``name`` = mic, mic_off, stop, check, close, gear, pin, bolt, shield, layers, tool, alert,
    clock, info, text. ``fill`` preenche a forma (alfinete fixado, YOLO ligado, capsula do microfone, parar)."""
    w = _begin(p, rect)
    col = _color(color, alpha)
    if name == "mic_off":
        _draw_name(p, "mic", col, w, False)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)       # vao no icone sem pintar o fundo (vidro)
        p.setPen(QPen(QColor(bg), w + 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(4.5, 3.5), QPointF(19.5, 20.5))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setPen(_pen(col, w))
        p.drawLine(QPointF(4.5, 3.5), QPointF(19.5, 20.5))
    else:
        _draw_name(p, name, col, w, fill)
    p.restore()


_CACHE: dict[tuple, QPixmap] = {}


def pixmap(name: str, color: str, size: int, dpr: float, *, fill: bool = False, bg: str = _BG) -> QPixmap:
    """Icone rasterizado UMA vez por (nome, cor, tamanho, dpr, fill)."""
    key = (name, color, size, round(dpr, 2), fill, bg)
    pm = _CACHE.get(key)
    if pm is None:
        if len(_CACHE) > 96:
            _CACHE.clear()
        pm = QPixmap(round(size * dpr), round(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        draw(q, name, QRectF(0, 0, size, size), color, fill=fill, bg=bg)
        q.end()
        _CACHE[key] = pm
    return pm


# ------------------------------------------------------------------ icones de estado (animados)
def draw_state(p: QPainter, state: str, rect: QRectF, color: str, t: float, *, motion: bool = True,
               alpha: float = 1.0, bg: str = _BG) -> None:
    """``state``: idle, listening, transcribing, thinking, acting, speaking, confirming, error, muted.
    ``t`` em segundos (so usado com ``motion``)."""
    if state in ("idle", "muted", "listening"):
        w = _begin(p, rect)
        col = _color(color, alpha)
        if state == "listening":
            if motion:
                ph = (t / 1.4) % 1.0
                ring = _color(color, alpha * 0.55 * (1.0 - ph))
                grow = 1.0 + 3.5 * ph
                p.setPen(QPen(ring, w * 0.8))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(9.0, 2.5, 6.0, 11.0).adjusted(-grow, -grow, grow, grow), 3.0 + grow, 3.0 + grow)
            _draw_name(p, "mic", col, w, True)
        elif state == "muted":
            p.restore()
            draw(p, "mic_off", rect, color, alpha=alpha, bg=bg)
            return
        else:
            _draw_name(p, "mic", col, w, False)
        p.restore()
        return
    w = _begin(p, rect)
    col = _color(color, alpha)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if state == "transcribing":
        p.setPen(_pen(col, w))
        grow = 0.5 + 0.5 * math.sin(t * 5.0) if motion else 0.6
        p.drawLine(QPointF(5.0, 7.5), QPointF(19.0, 7.5))
        p.drawLine(QPointF(5.0, 12.0), QPointF(15.0, 12.0))
        p.drawLine(QPointF(5.0, 16.5), QPointF(5.0 + 3.0 + 9.0 * grow, 16.5))
    elif state == "thinking":
        base = (t * 1.1 * 2 * math.pi) if motion else 0.0
        p.setPen(Qt.PenStyle.NoPen)
        for i, a in enumerate((1.0, 0.6, 0.3)):
            ang = base - i * 0.55
            c = _color(color, alpha * a)
            p.setBrush(c)
            p.drawEllipse(QPointF(12.0 + 7.8 * math.cos(ang), 12.0 + 7.8 * math.sin(ang)), 2.1 - 0.2 * i, 2.1 - 0.2 * i)
        p.setPen(QPen(_color(color, alpha * 0.22), w * 0.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(12.0, 12.0), 7.8, 7.8)
    elif state == "acting":
        ang = (t * 90.0) % 360.0 if motion else 0.0
        p.save()
        p.translate(12.0, 12.0)
        p.scale(0.66, 0.66)
        p.rotate(ang)
        p.translate(-12.0, -12.0)
        p.setPen(_pen(col, w / 0.66))
        p.drawPath(_STROKES["gear"])
        p.restore()
        sweep = (t * 180.0) % 360.0 if motion else 0.0         # arco de progresso indeterminado em volta
        p.setPen(_pen(_color(color, alpha * 0.9), w * 0.8))
        p.drawArc(QRectF(1.8, 1.8, 20.4, 20.4), int(-sweep * 16), int(-100 * 16))
    elif state == "speaking":
        p.setPen(_pen(col, w))
        p.drawPath(_poly((3.8, 9.5), (7.5, 9.5), (12.5, 5.5), (12.5, 18.5), (7.5, 14.5), (3.8, 14.5), close=True))
        for i, rr in enumerate((4.0, 7.6)):
            a = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 7.0 - i * 1.3)) if motion else 1.0
            p.setPen(_pen(_color(color, alpha * a), w))
            p.drawArc(QRectF(12.5 - rr * 0.35, 12.0 - rr, rr * 1.1, rr * 2.0), -55 * 16, 110 * 16)
    elif state == "confirming":
        pulse = (1.0 + 0.05 * math.sin(t * 5.0)) if motion else 1.0
        p.translate(12.0, 12.0)
        p.scale(pulse, pulse)
        p.translate(-12.0, -12.0)
        p.setPen(_pen(col, w))
        p.drawPath(_STROKES["shield"])
        p.drawLine(QPointF(12.0, 8.2), QPointF(12.0, 12.6))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(12.0, 15.8), 1.15, 1.15)
    elif state == "error":
        p.restore()
        draw(p, "alert", rect, color, alpha=alpha)
        return
    p.restore()


def sheet_names() -> tuple[str, ...]:
    return ("mic", "listen", "mic_off", "stop", "check", "close", "gear", "pin", "bolt", "shield", "layers", "tool", "alert",
            "clock", "text")


# ------------------------------------------------------------------ icones de estado em cache (por quadro de animacao)
PERIOD = {"listening": 1.4, "transcribing": 1.2566, "thinking": 0.909, "acting": 4.0, "speaking": 0.8976,
          "confirming": 1.2566}
_SP: dict[tuple, QPixmap] = {}


def state_pixmap(state: str, color: str, size: int, dpr: float, t: float, *, alpha: float = 1.0, badge: int = 0,
                 motion: bool = True) -> QPixmap:
    """Icone de estado (opcionalmente dentro do emblema circular ``badge``) rasterizado UMA vez por quadro de animacao
    (30 por segundo do periodo do estado): desenhar um pixmap por quadro custa ~10x menos que refazer os tracos."""
    per = PERIOD.get(state)
    if per is None or not motion:
        frame, tt = 0, 0.0
    else:
        n = max(1, round(per * 30))
        frame = int((t % per) / per * n) % n
        tt = frame * per / n
    aq = round(max(0.0, min(1.0, alpha)) * 8) / 8
    key = (state, color, size, badge, round(dpr, 2), frame, aq, motion)
    pm = _SP.get(key)
    if pm is None:
        if len(_SP) > 1600:
            _SP.clear()
        side = badge or size
        pm = QPixmap(round(side * dpr), round(side * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if badge:
            q.setPen(QPen(_color(color, 0.28), 1.0))
            q.setBrush(_color(color, 0.13 * aq))
            q.drawEllipse(QRectF(0.5, 0.5, badge - 1, badge - 1))
        o = (side - size) / 2.0
        draw_state(q, state, QRectF(o, o, size, size), color, tt, motion=motion, alpha=aq)
        q.end()
        _SP[key] = pm
    return pm


def clear_caches() -> None:
    """Libera os pixmaps em cache (ao esconder a Ilha)."""
    _CACHE.clear()
    _SP.clear()
