"""Pintura da Ilha: camadas ESTATICAS por tamanho (texto, chips, rotulos: pintadas UMA vez por mudanca e cacheadas
como QPixmap por DPR) e camadas DINAMICAS por quadro (icone de estado, ondas, progresso, botoes).

Tudo em px logicos na grade de 4 px. Fontes, cores e metricas ficam em cache (nada de alocacao por quadro alem dos
retangulos). ``v`` e a IslandWindow (so leitura).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

from ..theme import TYPE, make_font
from . import conf, glyphs
from . import tokens as T
from .strings import S
from .tokens import IslandState

AL = Qt.AlignmentFlag
_VC = int(AL.AlignVCenter)
_VR = int(AL.AlignVCenter | AL.AlignRight)
_CC = int(AL.AlignCenter)

_FONTS: dict[tuple, QFont] = {}
_FM: dict[tuple, QFontMetrics] = {}
_COL: dict[tuple, QColor] = {}


def font(px: int, weight: int = TYPE.regular, tab: bool = False) -> QFont:
    k = (px, weight, tab)
    f = _FONTS.get(k)
    if f is None:
        f = _FONTS[k] = make_font(px, weight, tabular=tab)
    return f


def fm(f_key: tuple[int, int, bool]) -> QFontMetrics:
    m = _FM.get(f_key)
    if m is None:
        m = _FM[f_key] = QFontMetrics(font(*f_key))
    return m


def tw(s: str, px: int, weight: int = TYPE.regular, tab: bool = False) -> int:
    return fm((px, weight, tab)).horizontalAdvance(s)


def elide(s: str, w: int, px: int, weight: int = TYPE.regular) -> str:
    return fm((px, weight, False)).elidedText(s, Qt.TextElideMode.ElideRight, max(0, int(w)))


def col(c: str, a: float = 1.0) -> QColor:
    k = (c, round(a, 3))
    q = _COL.get(k)
    if q is None:
        q = QColor(c)
        if a < 1.0:
            q.setAlphaF(a)
        _COL[k] = q
    return q


def mixc(a: str, b: str, t: float) -> QColor:
    ca, cb = col(a), col(b)
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t))


def mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def wrap(text: str, width: int, px: int, weight: int = TYPE.regular) -> list[str]:
    m = fm((px, weight, False))
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if m.horizontalAdvance(trial) <= width:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            while m.horizontalAdvance(word) > width and len(word) > 1:
                cut = len(word) - 1
                while cut > 1 and m.horizontalAdvance(word[:cut]) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
        lines.append(cur)
    return lines


def text(p: QPainter, s: str, x: float, y: float, w: float, h: float, px: int, color: str, weight: int = TYPE.regular,
         align: int = _VC, tab: bool = False, alpha: float = 1.0) -> None:
    p.setFont(font(px, weight, tab))
    p.setPen(col(color, alpha))
    p.drawText(QRectF(x, y, max(0.0, w), h), align, s)


# ------------------------------------------------------------------ botoes (pintados por quadro)
class Btn:
    """Botao da Ilha: so dados + pintura (sem QWidget: menos memoria, sem foco/estilo do Qt)."""
    __slots__ = ("key", "glyph", "label", "hk", "variant", "h", "x", "y", "w", "hover", "press", "visible", "focus",
                 "fill", "name", "enabled")

    def __init__(self, key: str, glyph: str, label: str, hk: str, variant: str, h: int = 32, name: str = "") -> None:
        self.key, self.glyph, self.label, self.hk, self.variant, self.h = key, glyph, label, hk, variant, h
        self.x = self.y = self.w = 0.0
        self.hover = 0.0
        self.press = False
        self.visible = False
        self.focus = False
        self.fill = False
        self.enabled = True
        self.name = name or label

    def measure(self) -> float:
        if not self.label and not self.hk:
            return float(self.h)                                   # so icone: quadrado
        w = 10.0 + (16.0 if self.glyph else 0.0)
        if self.label:
            w += 6.0 + tw(self.label, TYPE.small, TYPE.semibold)
        if self.hk:
            w += 8.0 + tw(self.hk, 10, TYPE.semibold) + 12.0 + 8.0
        else:
            w += 10.0
        return w

    def rect(self) -> QRectF:
        return QRectF(self.x, self.y, self.w, self.h)

    def contains(self, px: float, py: float) -> bool:
        return self.visible and self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


def keycap(p: QPainter, hk: str, right: float, cy: float, color: str, alpha: float = 1.0) -> float:
    """Dica de atalho em 'keycap' discreto, encostada em ``right``; devolve a largura."""
    w = tw(hk, 10, TYPE.semibold) + 12.0
    r = QRectF(right - w, cy - 9.0, w, 18.0)
    p.setPen(QPen(col("#FFFFFF", 0.16 * alpha), 1.0))
    p.setBrush(col("#FFFFFF", 0.07 * alpha))
    p.drawRoundedRect(r, 5.0, 5.0)
    text(p, hk, r.x(), r.y(), r.width(), r.height(), 10, color, TYPE.semibold, _CC, alpha=alpha)
    return w


def paint_button(p: QPainter, b: Btn, dpr: float, alpha: float = 1.0) -> None:
    pal = T.PALETTE
    r = b.rect()
    hv = b.hover
    rad = b.h / 2.0
    if b.variant == "primary":
        bg = mixc(pal.accent, "#FFFFFF", 0.14 * hv)
        if b.press:
            bg = mixc(pal.accent, "#000000", 0.16)
        fg, key_fg = pal.on_accent, pal.on_accent
        edge = None
    elif b.variant == "danger":
        bg = mixc(pal.error_bg, pal.error, 0.10 + 0.25 * hv + (0.18 if b.press else 0.0))
        fg, key_fg, edge = pal.error, pal.error, col(pal.error, 0.55)
    elif b.variant == "ghost":
        bg = QColor(255, 255, 255, round(255 * (0.0 + 0.12 * hv + (0.10 if b.press else 0.0))))
        fg, key_fg, edge = pal.text, pal.text_muted, None
    else:
        bg = QColor(255, 255, 255, round(255 * (0.07 + 0.11 * hv + (0.12 if b.press else 0.0))))
        fg, key_fg, edge = pal.text, pal.text_muted, col("#FFFFFF", 0.10 + 0.16 * hv)
    if not b.enabled:
        alpha *= 0.45
    p.save()
    p.setOpacity(p.opacity() * alpha)
    p.setPen(QPen(edge, 1.0) if edge is not None else Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
    x = b.x + (10.0 if (b.label or b.hk) else (b.w - 16.0) / 2.0)
    cap_left = b.x + b.w - 8.0
    cy = b.y + b.h / 2.0
    gcol = fg if b.variant != "primary" else pal.on_accent
    if b.key == "yolo" and b.fill:
        gcol = pal.error
    if b.key == "pin" and b.fill:
        gcol = T.accent()
    if b.glyph:
        glyphs.draw(p, b.glyph, QRectF(x, cy - 8.0, 16.0, 16.0), gcol, fill=b.fill and b.key in ("yolo", "pin"))
        x += 16.0
    if b.label:
        text(p, b.label, x + 6.0, b.y, b.w, b.h, TYPE.small, fg, TYPE.semibold)
    if b.hk:
        keycap(p, b.hk, b.x + b.w - 8.0, cy, key_fg)
    if b.focus:                                                     # foco de teclado: anel de 2 px com 2 px de folga
        p.setPen(QPen(col(T.accent()), 2.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(-2.0, -2.0, 2.0, 2.0), rad + 2.0, rad + 2.0)
    p.restore()


# ------------------------------------------------------------------ pecas estaticas
def chip(p: QPainter, label: str, right: float, cy: float, fg: str, bg: str | QColor, edge: str | QColor,
         glyph: str = "", fill: bool = False) -> float:
    w = tw(label, TYPE.caption, TYPE.semibold, True) + 16.0 + (14.0 if glyph else 0.0)
    r = QRectF(right - w, cy - 10.0, w, 20.0)
    p.setPen(QPen(col(edge) if isinstance(edge, str) else edge, 1.0))
    p.setBrush(col(bg) if isinstance(bg, str) else bg)
    p.drawRoundedRect(r, 10.0, 10.0)
    x = r.x() + 8.0
    if glyph:
        glyphs.draw(p, glyph, QRectF(x, cy - 5.0, 10.0, 10.0), fg, fill=fill)
        x += 14.0
    text(p, label, x, r.y(), r.width(), r.height(), TYPE.caption, fg, TYPE.semibold, _VC, True)
    return w


def yolo_chip(v, p: QPainter, right: float, cy: float, label: str = S.yolo_short) -> float:
    pal = T.PALETTE
    return chip(p, label, right, cy, pal.error, pal.error_bg, col(pal.error, 0.7), "bolt", True)


def sub_line(v) -> str:
    st = v.state
    if st is IslandState.SPEAKING and v.reply:
        return v.reply
    if st is IslandState.CONFIRMING:
        return v.confirm_text
    if st is IslandState.ERROR:
        return v.error_text
    if st is IslandState.LISTENING:
        return v.transcript or S.waiting_speech
    if st is IslandState.IDLE and not v.transcript:
        hk = conf.display(v.cfg.hotkeys.get("talk", "f9"))
        return S.press_to_talk.format(key=hk) if hk else ""
    return v.transcript


def static_compact(v, p: QPainter) -> None:
    pal = T.PALETTE
    W, H = T.CW, T.CH
    cy = H / 2.0
    r = W - T.C_PAD
    if v.state not in (IslandState.IDLE, IslandState.ERROR, IslandState.CONFIRMING):
        r -= 6 * 3 + 5 * 3 + 8                                    # ondas (dinamicas)
    if v.yolo_left() is not None:
        r -= yolo_chip(v, p, r, cy) + 8
    if v.state is IslandState.ACTING:
        w = tw("0:00", TYPE.small, tab=True) + 2
        text(p, mmss(v.elapsed()), r - w, 0, w, H, TYPE.small, pal.text_muted, align=_VR, tab=True)
        r -= w + 8
    x = T.C_PAD + T.C_ICON + 8
    text(p, elide(v.label(short=True), r - x, TYPE.small, TYPE.semibold), x, 0, r - x, H, TYPE.small, pal.text, TYPE.semibold)


def static_medium(v, p: QPainter) -> None:
    pal = T.PALETTE
    W = T.MW
    x = T.M_TEXT_X
    wave_x = W - T.PAD - (T.M_BARS * 3 + (T.M_BARS - 1) * 3)
    right = wave_x - 12
    timer_w = 0
    if v.state is not IslandState.IDLE:
        timer_w = tw("00:00", TYPE.small, tab=True) + 2
        text(p, mmss(v.elapsed()), right - timer_w, 12, timer_w, 20, TYPE.small, pal.text_muted, align=_VR, tab=True)
    r = right - (timer_w + 8 if timer_w else 0)
    if v.yolo_left() is not None:
        r -= yolo_chip(v, p, r, 22) + 8
    text(p, elide(v.label(), r - x, TYPE.body + 1, TYPE.semibold), x, 12, r - x, 20, TYPE.body + 1, pal.text, TYPE.semibold)
    line = sub_line(v)
    text(p, elide(line, right - x, TYPE.small), x, 34, right - x, 18, TYPE.small, pal.text_muted)


def _question(v, p: QPainter, W: int) -> None:
    pal = T.PALETTE
    s = v.confirm_text if v.state is IslandState.CONFIRMING else v.error_text
    lines = wrap(s, W - 2 * T.PAD, TYPE.heading, TYPE.semibold)
    if len(lines) > 2:
        lines = lines[:2]
        lines[1] = elide(lines[1] + " …", W - 2 * T.PAD, TYPE.heading, TYPE.semibold)
    for i, ln in enumerate(lines):
        text(p, ln, T.PAD, T.L_Q_Y + i * 24, W - 2 * T.PAD, 24, TYPE.heading, pal.text, TYPE.semibold)


def static_large(v, p: QPainter) -> None:
    pal = T.PALETTE
    W = T.LW
    hy = T.L_HEAD_Y
    cy = hy + T.L_BADGE / 2.0
    right = W - T.PAD - 28 - 12                                    # a esquerda do alfinete
    st = v.state
    if v.context_pct is not None:
        lab = f"{int(round(v.context_pct))}%"
        w = tw(lab, TYPE.caption, TYPE.semibold, True)
        text(p, lab, right - w, hy, w, 28, TYPE.caption, pal.warn if v.context_pct >= 80 else pal.text_muted,
             TYPE.semibold, _VR, True)
        glyphs.draw(p, "layers", QRectF(right - w - 20, cy - 8, 16, 16), pal.text_muted)
        right -= w + 20 + 12
    if st is not IslandState.IDLE:
        w = tw("00:00", TYPE.small, tab=True) + 2
        text(p, mmss(v.elapsed()), right - w, hy, w, 28, TYPE.small, pal.text_muted, align=_VR, tab=True)
        right -= w + 12
    yl = v.yolo_left()
    if yl is not None:
        right -= yolo_chip(v, p, right, cy, S.yolo.format(t=mmss(yl))) + 8
    if v.muted:
        right -= chip(p, S.muted, right, cy, pal.text, QColor(255, 255, 255, 20), col("#FFFFFF", 0.22)) + 8
    if v.perm_mode:
        right -= chip(p, v.perm_mode, right, cy, pal.text_muted, QColor(255, 255, 255, 10), col("#FFFFFF", 0.12)) + 8
    x0 = T.PAD + T.L_BADGE + 12
    text(p, elide(v.label(), right - x0, TYPE.heading, TYPE.semibold), x0, hy, right - x0, 28, TYPE.heading, pal.text, TYPE.semibold)

    confirming = st is IslandState.CONFIRMING
    if confirming or st is IslandState.ERROR:
        _question(v, p, W)
    else:
        _conversation(v, p, W)
        _action_row(v, p, W)
    p.setPen(QPen(col("#FFFFFF", 0.08), 1.0))                         # filete antes dos botoes
    p.drawLine(T.PAD, T.L_RULE_Y, W - T.PAD, T.L_RULE_Y)
    if confirming:
        text(p, S.confirm_timeout.format(s=max(v.confirm_left, 0)), W - T.PAD - 260, T.L_CONFIRM_Y, 260, T.L_CONFIRM_H,
             TYPE.caption, pal.warn, TYPE.regular, _VR, True)


def _conversation(v, p: QPainter, W: int) -> None:
    pal = T.PALETTE
    x_text = T.PAD + 48
    wtxt = W - x_text - T.PAD - 6
    rows: list[tuple[str, str, str]] = []
    for role, s in ((S.you, v.transcript), (S.jarvis, v.reply)):
        if not s:
            continue
        for i, ln in enumerate(wrap(s, wtxt, TYPE.small)):
            rows.append((role if i == 0 else "", ln, pal.text))
    if not rows:
        rows = [("", S.waiting_speech if v.state is IslandState.LISTENING else sub_line(v), pal.text_muted)]
    n = T.L_TEXT_LINES
    max_scroll = max(0, len(rows) - n)
    v.scroll = min(v.scroll, max_scroll)
    end = len(rows) - v.scroll
    for i, (role, ln, c) in enumerate(rows[max(0, end - n):end]):
        y = T.L_TEXT_Y + i * T.L_LINE_H
        if role:
            text(p, role, T.PAD, y, 44, T.L_LINE_H, TYPE.caption, T.accent() if role == S.jarvis else pal.text_muted, TYPE.semibold)
        text(p, ln, x_text, y, wtxt, T.L_LINE_H, TYPE.small, c)
    if max_scroll > 0:
        track = n * T.L_LINE_H
        th = max(8.0, track * n / len(rows))
        y0 = T.L_TEXT_Y + (track - th) * (1 - v.scroll / max_scroll)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col("#FFFFFF", 0.22))
        p.drawRoundedRect(QRectF(W - T.PAD - 3, y0, 3, th), 1.5, 1.5)


def _action_row(v, p: QPainter, W: int) -> None:
    pal = T.PALETTE
    y = T.L_ACTION_Y
    a = v.action
    if a is None:
        glyphs.draw(p, "tool", QRectF(T.PAD, y, 16, 16), pal.text_muted, alpha=0.7)
        text(p, S.no_action, T.PAD + 24, y, W - 2 * T.PAD, 16, TYPE.small, pal.text_muted)
        return
    status = a["status"]
    icon, color, word = {"ok": ("check", pal.ok, S.action_ok), "error": ("alert", pal.error, S.action_error),
                         "denied": ("alert", pal.warn, S.action_denied)}.get(status, ("tool", pal.text_muted, S.action_running))
    glyphs.draw(p, icon, QRectF(T.PAD, y, 16, 16), color)
    ww = tw(word, TYPE.small, TYPE.semibold)
    text(p, word, W - T.PAD - ww, y, ww, 16, TYPE.small, color, TYPE.semibold, _VR)
    s = f"{a['tool']}: {a['text']}" if a["tool"] else a["text"]
    if a["result"] and status in ("ok", "error"):
        s += f"  ({a['result']})"
    avail = W - T.PAD - ww - 12 - (T.PAD + 24)
    text(p, elide(s, avail, TYPE.small), T.PAD + 24, y, avail, 16, TYPE.small, pal.text)


STATIC = {"compact": static_compact, "medium": static_medium, "large": static_large}


# ------------------------------------------------------------------ pecas dinamicas
def state_key(v) -> str:
    st = v.state
    if st is IslandState.IDLE:
        return "muted" if v.muted else "idle"
    return {IslandState.LISTENING: "listening", IslandState.TRANSCRIBING: "transcribing",
            IslandState.THINKING: "thinking", IslandState.ACTING: "acting", IslandState.SPEAKING: "speaking",
            IslandState.CONFIRMING: "confirming", IslandState.ERROR: "error"}[st]


def _badge(v, p: QPainter, x: float, y: float, d: int, icon: int, dpr: float) -> None:
    """Emblema circular + icone de estado: um pixmap por quadro de animacao (ver glyphs.state_pixmap)."""
    p.drawPixmap(QPointF(x, y), glyphs.state_pixmap(state_key(v), T.state_color(v.state), icon, dpr, v.t,
                                                     alpha=v.breath(), badge=d, motion=v.motion))


def dyn_compact(v, p: QPainter, dpr: float) -> None:
    H = T.CH
    cy = H / 2.0
    color = T.state_color(v.state)
    p.drawPixmap(QPointF(T.C_PAD, cy - T.C_ICON / 2), glyphs.state_pixmap(state_key(v), color, T.C_ICON, dpr, v.t,
                                                                          alpha=v.breath(), motion=v.motion))
    if v.state not in (IslandState.IDLE, IslandState.ERROR, IslandState.CONFIRMING):
        wv = v.waves["compact"]
        c, a = wave_color(v)
        wv.draw(p, T.CW - T.C_PAD - wv.width, cy, c, alpha=a, dpr=dpr)


def wave_color(v) -> tuple[str, float]:
    voice = v.state in T.VOICE_STATES
    return T.state_color(v.state) if voice else T.PALETTE.text, (1.0 if voice else 0.5)


def dyn_medium(v, p: QPainter, dpr: float) -> None:
    _badge(v, p, T.PAD - 4, 12, T.M_BADGE, T.M_ICON, dpr)
    wv = v.waves["medium"]
    c, a = wave_color(v)
    x = T.MW - T.PAD - wv.width
    if v.state in (IslandState.ERROR, IslandState.CONFIRMING, IslandState.IDLE):
        return
    if v.state is IslandState.ACTING:                              # progresso circular indeterminado
        cx, cy = T.MW - T.PAD - 14, T.MH / 2
        p.setPen(QPen(col(T.PALETTE.text, 0.18), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - 11, cy - 11, 22, 22))
        pen = QPen(col(T.accent()), 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(cx - 11, cy - 11, 22, 22), int(-(v.t * 240.0 % 360.0) * 16) if v.motion else 0, int(-110 * 16))
        return
    wv.draw(p, x, T.MH / 2, c, alpha=a, dpr=dpr)


def dyn_large(v, p: QPainter, dpr: float) -> None:
    pal = T.PALETTE
    _badge(v, p, T.PAD, T.L_HEAD_Y, T.L_BADGE, 18, dpr)
    st = v.state
    if st not in (IslandState.CONFIRMING, IslandState.ERROR):
        wv = v.waves["large"]
        c, a = wave_color(v)
        wv.draw(p, T.PAD + (T.LW - 2 * T.PAD - wv.width) / 2, T.L_WAVE_Y + T.L_WAVE_H / 2, c, alpha=a, dpr=dpr)
        act = v.action
        if act is not None and act["status"] == "start" and st is IslandState.ACTING:   # progresso linear
            x0, w = T.PAD, T.LW - 2 * T.PAD
            y = T.L_ACTION_Y + 20
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col("#FFFFFF", 0.08))
            p.drawRoundedRect(QRectF(x0, y, w, 2), 1, 1)
            ph = (v.t * 0.8) % 1.0 if v.motion else 0.3
            seg = w * 0.28
            sx = x0 - seg + (w + seg) * ph
            p.save()
            p.setClipRect(QRectF(x0, y - 1, w, 4))
            p.setBrush(col(T.accent()))
            p.drawRoundedRect(QRectF(sx, y, seg, 2), 1, 1)
            p.restore()
    elif st is IslandState.CONFIRMING:                              # contagem regressiva (sem resposta = Nao)
        x0, w = T.PAD, T.LW - 2 * T.PAD
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col("#FFFFFF", 0.08))
        p.drawRoundedRect(QRectF(x0, T.L_COUNT_Y, w, 4), 2, 2)
        p.setBrush(col(pal.warn))
        p.drawRoundedRect(QRectF(x0, T.L_COUNT_Y, max(4.0, w * v.confirm_frac()), 4), 2, 2)
