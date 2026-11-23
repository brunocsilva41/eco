"""Layout e pintura do DOCK LATERAL (trilho vertical colado a borda direita ou esquerda).

Tres tamanhos, cada um com layout proprio na grade de 4 px (px logicos; origem = canto do corpo daquele tamanho):

  RECOLHIDO  56 x (8 + n*48): trilho de itens redondos de 40 px empilhados: icone de estado (animado), Escuta aberta,
             Mudo, Parar, [YOLO quando ativo], Configuracoes, Fixar.
  MEDIO      320 x 296: estado + tempo, ondas horizontais, conversa (3 a 5 linhas), acao atual, botoes em linha.
  GRANDE     320 x 560: estado + tempo + alfinete, chips, ondas, conversa com rolagem, cartao da acao, contexto,
             Sim/Nao (confirmacao), e botoes em coluna com os atalhos em keycaps.

``layout(v, size)`` posiciona os botoes (``v.b_*``); ``STATIC``/``DYN`` pintam (camada estatica em cache e camada por quadro).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from ..theme import TYPE
from . import glyphs
from . import render as R
from . import tokens as T
from .render import col, elide, mmss, text, tw, wrap
from .strings import S
from .tokens import IslandSize, IslandState

PAD = 16
RAIL_X = (T.SIDE_W - T.SIDE_ITEM) // 2


def rail_items(v) -> int:
    return 6 + (1 if v.yolo_left() is not None else 0)


def dims(v, size: IslandSize) -> tuple[int, int]:
    return T.side_dims(size, rail_items(v))


def _place(b: R.Btn, x: float, y: float, w: float, h: float, vis: bool = True) -> None:
    b.x, b.y, b.w, b.h, b.visible = x, y, w, h, vis


def layout(v, size: IslandSize) -> None:
    """Posiciona e mostra os botoes do tamanho ``size`` (os demais ficam invisiveis)."""
    for b in v.btns:
        b.visible = False
        b.isize = 16.0
    confirming = v.state is IslandState.CONFIRMING
    if size is IslandSize.COMPACT:
        rail = [v.b_listen, v.b_mute, v.b_stop] + ([v.b_yolo] if v.yolo_left() is not None else []) + [v.b_cfg, v.b_pin]
        for i, b in enumerate(rail, start=1):
            b.label = b.hk = ""
            _place(b, RAIL_X, T.SIDE_PAD + i * (T.SIDE_ITEM + T.SIDE_GAP), T.SIDE_ITEM, T.SIDE_ITEM)
            b.isize = 20.0
        return
    W = T.SIDE_MW
    if size is IslandSize.MEDIUM:
        y, gap = 252.0, 6.0
        v.b_listen.label, v.b_listen.hk = (S.listen if v.listen_open else S.listen_off), ""
        v.b_listen.isize = 16.0
        v.b_listen.w = v.b_listen.measure()
        x = PAD
        _place(v.b_listen, x, y, v.b_listen.w, 32)
        x = W - PAD
        for b in (v.b_pin, v.b_cfg, v.b_stop, v.b_mute):
            b.label = b.hk = ""
            _place(b, x - 32, y, 32, 32)
            x -= 38
        return
    # GRANDE
    hk = v.cfg.hotkeys
    from .conf import display
    full = W - 2 * PAD
    _place(v.b_pin, W - PAD - 28, 12, 28, 28)
    v.b_pin.label = v.b_pin.hk = ""
    rows = ((v.b_listen, S.listen if v.listen_open else S.listen_off, display(hk.get("open_listen", ""))),
            (v.b_mute, S.unmute_short if v.muted else S.mute_short, display(hk.get("mute", ""))),
            (v.b_stop, S.stop, display(hk.get("stop", ""))))
    y = 394.0
    for b, label, key in rows:
        b.label, b.hk = label, key
        _place(b, PAD, y, full, 32)
        y += 38
    _place(v.b_yolo, W - PAD - 32 * 2 - 6, 508, 32, 32)
    _place(v.b_cfg, W - PAD - 32, 508, 32, 32)
    v.b_yolo.label = v.b_yolo.hk = ""
    v.b_cfg.label = v.b_cfg.hk = ""
    v.b_yes.label, v.b_yes.hk = S.yes, display(hk.get("yes", ""))
    v.b_no.label, v.b_no.hk = S.no, display(hk.get("no", ""))
    _place(v.b_yes, PAD, 252, full, 36, confirming)
    _place(v.b_no, PAD, 296, full, 36, confirming)


# ------------------------------------------------------------------ pecas
def _header(v, p: QPainter, W: int, big: bool) -> None:
    pal = T.PALETTE
    x0 = PAD + 40 + 12
    right = W - PAD - (32 if big else 0)
    if v.state is not IslandState.IDLE:
        w = tw("00:00", TYPE.small, tab=True) + 2
        text(p, mmss(v.elapsed()), right - w, 12, w, 20, TYPE.small, pal.text_muted, align=R._VR, tab=True)
        right -= w + 8
    if v.pinned and not big:
        glyphs.draw(p, "pin", QRectF(right - 12, 16, 12, 12), T.accent(), fill=True)
        right -= 20
    text(p, elide(v.label(), right - x0, TYPE.heading if big else TYPE.body + 1, TYPE.semibold), x0, 12, right - x0, 22,
         TYPE.heading if big else TYPE.body + 1, pal.text, TYPE.semibold)
    line = R.sub_line(v)
    text(p, elide(line, W - PAD - x0, TYPE.small), x0, 34, W - PAD - x0, 18, TYPE.small, pal.text_muted)


def _conv(v, p: QPainter, W: int, y0: int, n: int, line_h: int = 18) -> None:
    pal = T.PALETTE
    x_text = PAD + 48
    wtxt = W - x_text - PAD - 6
    rows: list[tuple[str, str, str]] = []
    for role, s in ((S.you, v.transcript), (S.eco, v.reply)):
        if not s:
            continue
        for i, ln in enumerate(wrap(s, wtxt, TYPE.small)):
            rows.append((role if i == 0 else "", ln, pal.text))
    if not rows:
        rows = [("", S.waiting_speech if v.state is IslandState.LISTENING else S.nothing_said, pal.text_muted)]
    max_scroll = max(0, len(rows) - n)
    v.scroll = min(v.scroll, max_scroll)
    end = len(rows) - v.scroll
    for i, (role, ln, c) in enumerate(rows[max(0, end - n):end]):
        y = y0 + i * line_h
        if role:
            text(p, role, PAD, y, 44, line_h, TYPE.caption, T.accent() if role == S.eco else pal.text_muted, TYPE.semibold)
        text(p, ln, x_text, y, wtxt, line_h, TYPE.small, c)
    if max_scroll > 0:
        track = n * line_h
        th = max(8.0, track * n / len(rows))
        yy = y0 + (track - th) * (1 - v.scroll / max_scroll)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col("#FFFFFF", 0.22))
        p.drawRoundedRect(QRectF(W - PAD - 3, yy, 3, th), 1.5, 1.5)


def _action_line(v, p: QPainter, W: int, y: int, h: int = 16) -> None:
    pal = T.PALETTE
    a = v.action
    if a is None:
        glyphs.draw(p, "tool", QRectF(PAD, y, 16, 16), pal.text_muted, alpha=0.7)
        text(p, S.no_action, PAD + 24, y, W - 2 * PAD, h, TYPE.small, pal.text_muted)
        return
    status = a["status"]
    icon, color, word = {"ok": ("check", pal.ok, S.action_ok), "error": ("alert", pal.error, S.action_error),
                         "denied": ("alert", pal.warn, S.action_denied)}.get(status, ("tool", pal.text_muted, S.action_running))
    glyphs.draw(p, icon, QRectF(PAD, y, 16, 16), color)
    ww = tw(word, TYPE.small, TYPE.semibold)
    text(p, word, W - PAD - ww, y, ww, h, TYPE.small, color, TYPE.semibold, R._VR)
    s = f"{a['tool']}: {a['text']}" if a["tool"] else a["text"]
    if a["result"] and status in ("ok", "error"):
        s += f"  ({a['result']})"
    avail = W - PAD - ww - 12 - (PAD + 24)
    text(p, elide(s, avail, TYPE.small), PAD + 24, y, avail, h, TYPE.small, pal.text)


def static_compact(v, p: QPainter) -> None:
    """Trilho: so os separadores sutis (itens sao botoes/dinamicos)."""
    p.setPen(QPen(col("#FFFFFF", 0.08), 1.0))
    y = T.SIDE_PAD + (T.SIDE_ITEM + T.SIDE_GAP) - T.SIDE_GAP // 2
    p.drawLine(RAIL_X + 8, y, RAIL_X + T.SIDE_ITEM - 8, y)


def static_medium(v, p: QPainter) -> None:
    pal = T.PALETTE
    W = T.SIDE_MW
    _header(v, p, W, False)
    _conv(v, p, W, 108, 5)
    _action_line(v, p, W, 204)
    p.setPen(QPen(col("#FFFFFF", 0.08), 1.0))
    p.drawLine(PAD, 240, W - PAD, 240)
    if v.yolo_left() is not None:
        R.yolo_chip(v, p, W - PAD, 228, S.yolo.format(t=mmss(v.yolo_left() or 0)))


def static_large(v, p: QPainter) -> None:
    pal = T.PALETTE
    W = T.SIDE_LW
    _header(v, p, W, True)
    right = W - PAD
    y = 60
    chips = []
    if v.pinned:
        chips.append((S.pinned_chip, T.accent(), "pin"))
    if v.muted:
        chips.append((S.muted, pal.text, ""))
    if v.perm_mode:
        chips.append((v.perm_mode, pal.text_muted, ""))
    x = PAD
    for label, fg, g in chips:
        w = tw(label, TYPE.caption, TYPE.semibold, True) + 16 + (14 if g else 0)
        R.chip(p, label, x + w, y + 10, fg, R.QColor(255, 255, 255, 14), col("#FFFFFF", 0.16), g, bool(g))
        x += w + 6
    yl = v.yolo_left()
    if yl is not None:
        R.yolo_chip(v, p, right, y + 10, S.yolo.format(t=mmss(yl)))
    confirming = v.state is IslandState.CONFIRMING
    if confirming or v.state is IslandState.ERROR:
        s = v.confirm_text if confirming else v.error_text
        lines = wrap(s, W - 2 * PAD, TYPE.heading, TYPE.semibold)[:2]
        for i, ln in enumerate(lines):
            text(p, ln, PAD, 148 + i * 24, W - 2 * PAD, 24, TYPE.heading, pal.text, TYPE.semibold)
        if confirming:
            text(p, S.confirm_timeout.format(s=max(v.confirm_left, 0)), PAD, 204, W - 2 * PAD, 18, TYPE.caption, pal.warn,
                 TYPE.regular, R._VC, True)
    else:
        text(p, S.side_conversation, PAD, 144, 120, 16, TYPE.caption, pal.text_muted, TYPE.semibold)
        _conv(v, p, W, 164, 7)
        # cartao da acao atual
        p.setPen(QPen(col("#FFFFFF", 0.10), 1.0))
        p.setBrush(col("#FFFFFF", 0.05))
        p.drawRoundedRect(QRectF(PAD + 0.5, 300.5, W - 2 * PAD - 1, 40), 10, 10)
        _action_line(v, p, W, 312)
    # contexto
    glyphs.draw(p, "layers", QRectF(PAD, 354, 16, 16), pal.text_muted)
    pct = v.context_pct
    lab = f"{S.side_context} {int(round(pct))}%" if pct is not None else S.side_context
    text(p, lab, PAD + 24, 354, 160, 16, TYPE.small, pal.warn if (pct or 0) >= 80 else pal.text_muted)
    p.setPen(QPen(col("#FFFFFF", 0.08), 1.0))
    p.drawLine(PAD, 386, W - PAD, 386)


STATIC = {"compact": static_compact, "medium": static_medium, "large": static_large}


# ------------------------------------------------------------------ dinamico
def listen_ring(v, p: QPainter, b: R.Btn) -> None:
    """Escuta aberta ligada: anel pulsante em volta do botao (estatico com 'reduzir movimento')."""
    if not (b.visible and v.listen_open):
        return
    ac = T.accent()
    r = b.rect()
    rad = b.h / 2.0
    p.setBrush(Qt.BrushStyle.NoBrush)
    if v.motion:
        ph = (v.t / 1.6) % 1.0
        g = 1.0 + 5.0 * ph
        p.setPen(QPen(col(ac, 0.7 * (1.0 - ph)), 1.5))
        p.drawRoundedRect(r.adjusted(-g, -g, g, g), rad + g, rad + g)
    else:
        p.setPen(QPen(col(ac, 0.5), 1.5))
        p.drawRoundedRect(r.adjusted(-2.5, -2.5, 2.5, 2.5), rad + 2.5, rad + 2.5)


def dyn_compact(v, p: QPainter, dpr: float) -> None:
    p.drawPixmap(QPointF(RAIL_X, T.SIDE_PAD), glyphs.state_pixmap(R.state_key(v), T.state_color(v.state), 22, dpr, v.t,
                                                                  alpha=v.breath(), badge=T.SIDE_ITEM, motion=v.motion))
    listen_ring(v, p, v.b_listen)


def _waves(v, p: QPainter, y: float, dpr: float) -> None:
    wv = v.waves["side"]
    c, a = R.wave_color(v)
    wv.draw(p, PAD + (T.SIDE_MW - 2 * PAD - wv.width) / 2, y, c, alpha=a, dpr=dpr)


def dyn_medium(v, p: QPainter, dpr: float) -> None:
    p.drawPixmap(QPointF(PAD - 4, 12), glyphs.state_pixmap(R.state_key(v), T.state_color(v.state), 24, dpr, v.t,
                                                           alpha=v.breath(), badge=40, motion=v.motion))
    if v.state not in (IslandState.ERROR, IslandState.CONFIRMING):
        _waves(v, p, 84.0, dpr)
    listen_ring(v, p, v.b_listen)


def dyn_large(v, p: QPainter, dpr: float) -> None:
    pal = T.PALETTE
    W = T.SIDE_LW
    p.drawPixmap(QPointF(PAD - 4, 12), glyphs.state_pixmap(R.state_key(v), T.state_color(v.state), 24, dpr, v.t,
                                                           alpha=v.breath(), badge=40, motion=v.motion))
    st = v.state
    if st is IslandState.CONFIRMING:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col("#FFFFFF", 0.08))
        p.drawRoundedRect(QRectF(PAD, 228, W - 2 * PAD, 4), 2, 2)
        p.setBrush(col(pal.warn))
        p.drawRoundedRect(QRectF(PAD, 228, max(4.0, (W - 2 * PAD) * v.confirm_frac()), 4), 2, 2)
    elif st is not IslandState.ERROR:
        wv = v.waves["side"]
        c, a = R.wave_color(v)
        wv.draw(p, PAD + (W - 2 * PAD - wv.width) / 2, 112.0, c, alpha=a, dpr=dpr)
    # barra de contexto
    pct = (v.context_pct or 0.0) / 100.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col("#FFFFFF", 0.08))
    p.drawRoundedRect(QRectF(PAD + 24, 376, W - 2 * PAD - 24, 4), 2, 2)
    if v.context_pct is not None:
        p.setBrush(col(pal.warn if pct >= 0.8 else T.accent()))
        p.drawRoundedRect(QRectF(PAD + 24, 376, max(4.0, (W - 2 * PAD - 24) * pct), 4), 2, 2)
    listen_ring(v, p, v.b_listen)


DYN = {"compact": dyn_compact, "medium": dyn_medium, "large": dyn_large}

__all__ = ["layout", "STATIC", "DYN", "dims", "rail_items", "math"]
