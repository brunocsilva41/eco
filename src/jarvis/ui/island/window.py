"""IslandWindow: a janela da Ilha (sem moldura, sempre no topo, sem roubar foco, 3 tamanhos).

Pintada por CPU (QPainter). O timer de animacao so roda quando ha algo animado a mostrar: em
repouso nao ha timer de pintura. Com "reduzir animacoes" do Windows: sem pulso nem espectro em
barras (so uma barra simples de nivel, a 12 fps) e troca de tamanho instantanea.
"""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import QWidget

from ..kit import icons
from ..kit.base import animate, set_a11y
from ..kit.buttons import Button
from ..theme import SPACE, TYPE, make_font
from ..kit.platform import motion_enabled
from . import tokens as T
from . import winapi
from .dsp import LevelSource
from .strings import S
from .tokens import IslandSize, IslandState

_ANG = [(-math.pi / 2 + 2 * math.pi * j / T.RING_DOTS) for j in range(T.RING_DOTS)]
_COS = [math.cos(a) for a in _ANG]
_SIN = [math.sin(a) for a in _ANG]
# ponto j do anel -> banda do espectro (espelhado no eixo vertical: graves embaixo, agudos em cima)
_DOT_BAND = [min(T.BANDS - 1, int(abs((j / T.RING_DOTS) * 2 - 1) * (T.BANDS - 1))) for j in range(T.RING_DOTS)]
_EXP_HEADER_H = SPACE.xxl + SPACE.lg      # 48: linha de cabecalho
_TRANSCRIPT_Y, _TRANSCRIPT_H = 52, 54
_SPECTRUM_Y, _SPECTRUM_H = 112, 32
_BOTTOM_Y = T.SIZES[IslandSize.EXPANDED][1] - T.PAD - 32
_STOP_STATES = (IslandState.TRANSCRIBING, IslandState.THINKING, IslandState.ACTING, IslandState.SPEAKING)


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _fit_wrapped(fm: QFontMetrics, text: str, width: int, height: int) -> str:
    """Corta ``text`` com reticencias para caber em ``height`` quando quebrado em ``width``."""
    rect = QRect(0, 0, width, 10_000)
    flags = int(Qt.TextFlag.TextWordWrap)
    full = text
    while text and fm.boundingRect(rect, flags, text).height() > height:
        full = full[: max(0, len(full) - 6)].rstrip()
        text = full + "…"
    return text


class IslandWindow(QWidget):
    """API para o nucleo (fase I1): ``set_state``, ``set_transcript``, ``set_detail``,
    ``ask_confirmation``, ``pin_size``. Sinais para o nucleo: ``confirm_answered(bool)``,
    ``stop_requested()``, ``size_changed(str)``."""

    confirm_answered = Signal(bool)
    stop_requested = Signal()
    size_changed = Signal(str)

    def __init__(self, levels: LevelSource | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._levels = levels
        self._state = IslandState.IDLE
        self._transcript = ""
        self._detail = ""
        self._confirm_text = ""
        self._confirm_left = 0
        self._pinned: IslandSize | None = None
        self._target = IslandSize.REST
        self._cur = (float(T.SIZES[IslandSize.REST][0]), float(T.SIZES[IslandSize.REST][1]))
        self._anim = None
        self._bands = np.zeros(T.BANDS, dtype=np.float32)
        self._level = 0.0
        self._t = 0.0
        self._last = time.monotonic()
        self._motion = motion_enabled()
        self._guard_hid = False
        self._native = QGuiApplication.platformName() == "windows"

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)   # 30 fps reais (o grosso tem ~15 ms de passo)
        self._timer.timeout.connect(self._tick)
        self._confirm_timer = QTimer(self)
        self._confirm_timer.setInterval(1000)
        self._confirm_timer.timeout.connect(self._confirm_second)
        self._guard = QTimer(self)
        self._guard.setInterval(T.FULLSCREEN_POLL_MS)
        self._guard.timeout.connect(self._poll_fullscreen)

        self.btn_yes = Button(S.yes, variant="primary", icon_name="check", parent=self)
        self.btn_no = Button(S.no, variant="secondary", icon_name="close", parent=self)
        self.btn_stop = Button(S.stop, variant="secondary", icon_name="stop", parent=self)
        self.btn_yes.clicked.connect(lambda: self._answer(True))
        self.btn_no.clicked.connect(lambda: self._answer(False))
        self.btn_stop.clicked.connect(self.stop_requested)
        for b in (self.btn_yes, self.btn_no, self.btn_stop):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.hide()

        self._apply_geometry()
        self._sync_a11y()
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            scr.geometryChanged.connect(lambda *_: self._apply_geometry())
        QGuiApplication.instance().primaryScreenChanged.connect(self._on_primary_changed)  # type: ignore[union-attr]

    # ------------------------------------------------------------------ API publica
    @property
    def state(self) -> IslandState:
        return self._state

    @property
    def size_target(self) -> IslandSize:
        return self._target

    def set_levels_source(self, source: LevelSource | None) -> None:
        self._levels = source

    def set_state(self, state: IslandState) -> None:
        if state is not self._state:
            if self._state is IslandState.CONFIRMING:
                self._confirm_timer.stop()
            self._state = state
            self._bands[:] = 0.0
            self._level = 0.0
            if state is not IslandState.CONFIRMING:
                self._confirm_text = ""
        self._motion = motion_enabled()
        self._retarget()
        self._sync_timer()
        self._sync_a11y()
        self.update()

    def set_transcript(self, text: str) -> None:
        self._transcript = text
        self._sync_a11y()
        self.update()

    def set_detail(self, text: str) -> None:
        self._detail = text
        self._sync_a11y()
        self.update()

    def ask_confirmation(self, text: str, timeout_s: int = T.CONFIRM_TIMEOUT_S) -> None:
        self._confirm_text = text
        self._confirm_left = timeout_s
        self._confirm_timer.start()
        self.set_state(IslandState.CONFIRMING)

    def pin_size(self, size: IslandSize | None) -> None:
        """Fixa um tamanho (clique/atalho); ``None`` volta ao automatico."""
        self._pinned = size
        self._retarget()

    # ------------------------------------------------------------------ tamanho e posicao
    def _auto_size(self) -> IslandSize:
        if self._state is IslandState.CONFIRMING:
            return IslandSize.EXPANDED
        if self._pinned is not None:
            return self._pinned
        return IslandSize.REST if self._state is IslandState.IDLE else IslandSize.ACTIVE

    def _retarget(self) -> None:
        target = self._auto_size()
        if target is self._target:
            self._sync_buttons()
            return
        self._target = target
        if self._native and self.isVisible():
            winapi.set_click_through(int(self.winId()), target is IslandSize.REST)
        start = self._cur
        end = T.SIZES[target]
        if self._anim is not None:
            try:
                self._anim.stop()
            except RuntimeError:
                pass
            self._anim = None
        self._sync_buttons()
        self._anim = animate(self, 0.0, 1.0, T.RESIZE_MS,
                             lambda v: self._morph(start, end, v), self._on_morph_done)
        self.size_changed.emit(target.value)

    def _morph(self, a: tuple[float, float], b: tuple[int, int], v: float) -> None:
        self._cur = (a[0] + (b[0] - a[0]) * v, a[1] + (b[1] - a[1]) * v)
        self._apply_geometry()

    def _on_morph_done(self) -> None:
        self._anim = None
        self._cur = tuple(float(x) for x in T.SIZES[self._target])  # type: ignore[assignment]
        self._apply_geometry()
        self._sync_buttons()
        self._sync_timer()

    def _apply_geometry(self) -> None:
        scr = QGuiApplication.primaryScreen()
        w, h = round(self._cur[0]), round(self._cur[1])
        if scr is None:
            self.resize(w, h)
            return
        g = scr.geometry()
        self.setGeometry(QRect(g.x() + (g.width() - w) // 2, g.y() + T.TOP_MARGIN, w, h))

    def _on_primary_changed(self, scr) -> None:  # type: ignore[no-untyped-def]
        if scr is not None:
            scr.geometryChanged.connect(lambda *_: self._apply_geometry())
        self._apply_geometry()

    # ------------------------------------------------------------------ timers
    def _wants_timer(self) -> bool:
        if not self.isVisible() or self._target is IslandSize.REST and self._anim is None:
            return False
        if self._motion:
            return self._state in T.ANIMATED_STATES
        return self._state in T.VOICE_STATES

    def _sync_timer(self) -> None:
        if self._wants_timer():
            self._timer.setInterval(round(1000 / (T.FPS if self._motion else T.FPS_REDUCED)))
            if not self._timer.isActive():
                self._last = time.monotonic()
                self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last, 0.1)
        self._last = now
        self._t += dt
        if self._levels is not None and self._state in T.VOICE_STATES:
            self._bands, self._level = self._levels.read(self._state is IslandState.SPEAKING, dt)
        self.update()

    def _confirm_second(self) -> None:
        self._confirm_left -= 1
        if self._confirm_left <= 0:
            self._answer(False)          # sem resposta = NAO
        else:
            self.update()

    def _answer(self, yes: bool) -> None:
        self._confirm_timer.stop()
        self.confirm_answered.emit(yes)

    def _poll_fullscreen(self) -> None:
        if not T.HIDE_ON_FULLSCREEN:
            return
        full = winapi.fullscreen_app_active(int(self.winId()))
        if full and self.isVisible():
            self._guard_hid = True
            self.hide()
        elif not full and self._guard_hid:
            self._guard_hid = False
            self.show()

    # ------------------------------------------------------------------ ciclo de vida
    def showEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(e)
        if self._native:
            hwnd = int(self.winId())
            winapi.set_no_activate(hwnd)
            winapi.set_click_through(hwnd, self._target is IslandSize.REST)
            if not self._guard.isActive():
                self._guard.start()
        self._sync_timer()

    def hideEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().hideEvent(e)
        self._timer.stop()

    def closeEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        for t in (self._timer, self._confirm_timer, self._guard):
            t.stop()
        super().closeEvent(e)

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        self._sync_buttons()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        """Clique alterna e FIXA o tamanho: automatico -> expandido -> ativo -> automatico."""
        if e.button() == Qt.MouseButton.LeftButton and self._target is not IslandSize.REST:
            order = {None: IslandSize.EXPANDED, IslandSize.EXPANDED: IslandSize.ACTIVE, IslandSize.ACTIVE: None}
            self.pin_size(order.get(self._pinned))
        e.accept()

    # ------------------------------------------------------------------ botoes
    def _sync_buttons(self) -> None:
        ready = self._target is IslandSize.EXPANDED and self._anim is None and self.height() >= T.SIZES[IslandSize.EXPANDED][1] - 1
        confirming = self._state is IslandState.CONFIRMING
        self.btn_yes.setVisible(ready and confirming)
        self.btn_no.setVisible(ready and confirming)
        self.btn_stop.setVisible(ready and not confirming and self._state in _STOP_STATES)
        x = self.width() - T.PAD
        for b in ((self.btn_no, self.btn_yes) if confirming else (self.btn_stop,)):
            b.adjustSize()
            x -= b.width()
            b.move(x, _BOTTOM_Y)
            x -= SPACE.sm

    def _sync_a11y(self) -> None:
        line = self._confirm_text or self._detail or self._transcript
        set_a11y(self, S.window_name, f"{T.state_label(self._state)}. {line}".strip())

    # ------------------------------------------------------------------ pintura
    def paintEvent(self, _e: QPaintEvent) -> None:
        pal = T.PALETTE
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        radius = min(h / 2.0, float(T.CORNER_MAX))
        body = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        p.setPen(QPen(QColor(pal.border), 1.0))
        p.setBrush(QColor(pal.bg))
        p.drawRoundedRect(body, radius, radius)
        clip = QPainterPath()
        clip.addRoundedRect(body, radius, radius)
        p.setClipPath(clip)

        aw, ah = T.SIZES[IslandSize.ACTIVE]
        rw = T.SIZES[IslandSize.REST][0]
        fa = _clamp01((w - rw) / (aw - rw))
        fe = _clamp01((h - ah) / (T.SIZES[IslandSize.EXPANDED][1] - ah))
        if fa < 1.0:                                   # repouso: linha fina, neutra
            p.setOpacity(1.0 - fa)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal.text_muted))
            p.drawRoundedRect(QRectF(w / 2 - 12, h / 2 - 1, 24, 2), 1, 1)
        if fa > 0.0:
            p.setOpacity(fa * fa)
            self._paint_header(p, w)
        if fe > 0.0:
            p.setOpacity(fe)
            self._paint_expanded(p, w)
        p.end()

    def _line_text(self) -> str:
        return self._detail or self._transcript

    def _paint_header(self, p: QPainter, w: int) -> None:
        pal = T.PALETTE
        color = T.state_color(self._state)
        cx, cy = T.PAD + 20, 24
        self._paint_ring(p, cx, cy, color)
        p.drawPixmap(QPointF(cx - 8, cy - 8), icons.pixmap(T.STATE_ICON[self._state], color, 16, self))
        x = cx + 20 + T.PAD
        tw = max(0, w - x - T.PAD)
        title_f = make_font(TYPE.body, TYPE.semibold)
        line_f = make_font(TYPE.small)
        line = self._line_text() if self._state is not IslandState.CONFIRMING else ""
        if w >= T.SIZES[IslandSize.EXPANDED][0] - 1 and self._state is not IslandState.CONFIRMING:
            line = ""                                  # no expandido a fala aparece no bloco de baixo
        p.setFont(title_f)
        fm = QFontMetrics(title_f)
        p.setPen(QColor(pal.text))
        ty = 8 if line else 14
        p.drawText(QRectF(x, ty, tw, 18), int(Qt.AlignmentFlag.AlignVCenter),
                   fm.elidedText(T.state_label(self._state), Qt.TextElideMode.ElideRight, tw))
        if line:
            p.setFont(line_f)
            p.setPen(QColor(pal.text_muted))
            p.drawText(QRectF(x, 26, tw, 16), int(Qt.AlignmentFlag.AlignVCenter),
                       QFontMetrics(line_f).elidedText(line, Qt.TextElideMode.ElideRight, tw))

    def _paint_ring(self, p: QPainter, cx: float, cy: float, color: str) -> None:
        st = self._state
        if st is IslandState.IDLE:
            return
        n, t, bands = T.RING_DOTS, self._t, self._bands
        col = QColor(color)
        p.setPen(Qt.PenStyle.NoPen)
        voice = st in T.VOICE_STATES
        still = not self._motion
        if st is IslandState.THINKING and not still:      # "neuronios": conexoes piscam entre pontos distantes
            pen = QPen(col, 0.75)
            for j in range(0, n, 3):
                k = (j + n // 3) % n
                a = 0.10 + 0.22 * max(0.0, math.sin(t * 3.0 + j * 1.7))
                col.setAlphaF(a)
                pen.setColor(col)
                p.setPen(pen)
                p.drawLine(QPointF(cx + _COS[j] * T.RING_R, cy + _SIN[j] * T.RING_R),
                           QPointF(cx + _COS[k] * T.RING_R, cy + _SIN[k] * T.RING_R))
            p.setPen(Qt.PenStyle.NoPen)
        head = (t * 1.2) % 1.0
        for j in range(n):
            if still:
                v = 0.8
            elif voice:
                v = float(bands[_DOT_BAND[j]])
            elif st is IslandState.THINKING:
                v = (0.5 + 0.5 * math.sin(2 * math.pi * (2.0 * j / n) - t * 2 * math.pi * 0.9)) ** 2
            elif st is IslandState.TRANSCRIBING:
                v = 1.0 if j / n <= head else 0.2
            elif st is IslandState.ACTING:
                v = (1.0 - ((head - j / n) % 1.0)) ** 3
            else:                                          # CONFIRMING: respira devagar
                v = 0.65 + 0.2 * math.sin(t * 2.2)
            r = T.RING_R + (4.0 * v if voice else 0.0)
            col.setAlphaF(0.30 + 0.70 * v)
            p.setBrush(col)
            rad = 1.1 + 1.3 * v
            p.drawEllipse(QPointF(cx + _COS[j] * r, cy + _SIN[j] * r), rad, rad)

    def _paint_expanded(self, p: QPainter, w: int) -> None:
        pal = T.PALETTE
        inner = w - 2 * T.PAD
        confirming = self._state is IslandState.CONFIRMING
        # bloco de texto: pergunta (confirmando) ou fala transcrita
        if confirming:
            f, text, color = make_font(TYPE.heading, TYPE.semibold), self._confirm_text, pal.text
        elif self._transcript:
            f, text, color = make_font(TYPE.body), self._transcript, pal.text
        else:
            f, text, color = make_font(TYPE.body), S.waiting_speech, pal.text_muted
        p.setFont(f)
        p.setPen(QColor(color))
        text = _fit_wrapped(QFontMetrics(f), text, inner, _TRANSCRIPT_H)
        p.drawText(QRectF(T.PAD, _TRANSCRIPT_Y, inner, _TRANSCRIPT_H),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), text)
        self._paint_spectrum(p, w, inner)
        # linha de baixo: passo atual ou contagem da confirmacao
        small = make_font(TYPE.small)
        p.setFont(small)
        p.setPen(QColor(pal.text_muted))
        if confirming:
            bottom = S.confirm_timeout.format(s=max(self._confirm_left, 0))
        else:
            bottom = self._detail
        right = min((b.x() for b in (self.btn_yes, self.btn_no, self.btn_stop) if b.isVisible()), default=w) - SPACE.md
        bw = max(0, right - T.PAD)
        p.drawText(QRectF(T.PAD, _BOTTOM_Y, bw, 32), int(Qt.AlignmentFlag.AlignVCenter),
                   QFontMetrics(small).elidedText(bottom, Qt.TextElideMode.ElideRight, bw))

    def _paint_spectrum(self, p: QPainter, w: int, inner: int) -> None:
        pal = T.PALETTE
        voice = self._state in T.VOICE_STATES
        color = QColor(T.state_color(self._state) if voice else pal.border_strong)
        top, hh = _SPECTRUM_Y, _SPECTRUM_H
        mid = top + hh / 2
        p.setPen(Qt.PenStyle.NoPen)
        if not self._motion:                               # reduzir movimento: uma barra simples de nivel
            if voice:
                p.setFont(make_font(TYPE.caption))
                p.setBrush(QColor(pal.border_strong))
                p.drawRoundedRect(QRectF(T.PAD, mid - 3, inner, 6), 3, 3)
                p.setBrush(color)
                p.drawRoundedRect(QRectF(T.PAD, mid - 3, max(6.0, inner * self._level), 6), 3, 3)
            return
        n = T.BANDS
        gap = 2.0
        bw = (inner - gap * (n - 1)) / n
        for i in range(n):
            v = float(self._bands[i]) if voice else 0.0
            bh = 2.0 + (hh - 2.0) * v
            col = QColor(color)
            col.setAlphaF(0.45 + 0.55 * v if voice else 0.6)
            p.setBrush(col)
            x = T.PAD + i * (bw + gap)
            p.drawRoundedRect(QRectF(x, mid - bh / 2, bw, bh), min(1.5, bw / 2), min(1.5, bw / 2))
