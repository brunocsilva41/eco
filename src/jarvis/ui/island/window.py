"""IslandWindow: a Ilha do Jarvis (estilo Dynamic Island), colada ao topo do monitor principal.

Janela sem moldura, sempre no topo, sem roubar foco, do tamanho exato da pilula (fora dela o clique
passa para a janela de baixo). Tres tamanhos com layouts proprios (tabela em ``tokens.py``):
COMPACTA (repouso), MEDIA (conversa), GRANDE (expandida). Pintada por CPU (QPainter); o timer so roda
quando ha algo animado a mostrar. 'Reduzir animacoes' do Windows: sem mola/pulso/respiracao e troca
de tamanho instantanea; as barras de nivel (informacao, nao enfeite) seguem a 12 fps.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QFontMetrics, QGuiApplication, QIcon, QMouseEvent, QPainter, QPainterPath,
                           QPaintEvent, QPen, QPixmap, QResizeEvent, QWheelEvent)
from PySide6.QtWidgets import QWidget

from ..kit import icons
from ..kit.base import set_a11y
from ..kit.buttons import Button
from ..kit.platform import motion_enabled
from ..theme import SPACE, TYPE, duration, make_font
from . import tokens as T
from . import winapi
from .dsp import LevelSource
from .micicon import MicKind, draw_mic, pulse_phase
from .strings import S
from .tokens import IslandSize, IslandState
from .waves import WaveBars

_STOP_STATES = (IslandState.LISTENING, IslandState.TRANSCRIBING, IslandState.THINKING, IslandState.ACTING,
                IslandState.SPEAKING, IslandState.CONFIRMING)


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _wrap(fm: QFontMetrics, text: str, width: int) -> list[str]:
    """Quebra gulosa por palavras em ``width`` px (palavra maior que a linha e cortada)."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if fm.horizontalAdvance(trial) <= width:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            while fm.horizontalAdvance(word) > width and len(word) > 1:
                cut = len(word) - 1
                while cut > 1 and fm.horizontalAdvance(word[:cut]) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
        lines.append(cur)
    return lines


class IslandWindow(QWidget):
    """API para o nucleo (via ``bridge.py`` na fase I1): ``set_state``, ``set_transcript``,
    ``set_reply``/``append_reply``, ``set_action``, ``ask_confirmation``, ``set_context_pct``,
    ``set_mute``, ``set_yolo``, ``set_permission_mode``, ``set_error``, ``pin_size``.
    Sinais para o nucleo: ``confirm_answered(bool)``, ``stop_requested()``, ``mute_toggled(bool)``,
    ``settings_requested()``, ``size_changed(str)``."""

    confirm_answered = Signal(bool)
    stop_requested = Signal()
    mute_toggled = Signal(bool)
    settings_requested = Signal()
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
        self._reply = ""
        self._action: dict[str, str] | None = None
        self._error_text = ""
        self._confirm_text = ""
        self.confirm_id = ""
        self._confirm_left = 0
        self._muted = False
        self._yolo_deadline: float | None = None
        self._perm_mode = ""
        self._context_pct: float | None = None
        self._scroll = 0
        self._pinned: IslandSize | None = None
        self._target = IslandSize.COMPACT
        self._cur = (float(T.CW), float(T.CH))
        self._anim: QVariantAnimation | None = None
        self._t = 0.0
        self._state_since = time.monotonic()
        self._elapsed_override: float | None = None
        self._last = time.monotonic()
        self._level = 0.0
        self._motion = motion_enabled()
        self._guard_hid = False
        self._ver = 0
        self._static: QPixmap | None = None
        self._static_key: tuple | None = None
        self._native = QGuiApplication.platformName() == "windows"
        self._waves = {
            IslandSize.COMPACT: WaveBars(T.C_BARS, 3, 3, 16.0),
            IslandSize.MEDIUM: WaveBars(T.M_BARS, 3, 3, float(T.M_WAVE_H)),
            IslandSize.LARGE: WaveBars(T.L_BARS, T.L_BAR_W, T.L_BAR_GAP, float(T.L_WAVE_H)),
        }

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._clock = QTimer(self)                      # 1 s: cronometro, contagem do YOLO e da confirmacao
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._clock_tick)
        self._guard = QTimer(self)
        self._guard.setInterval(T.FULLSCREEN_POLL_MS)
        self._guard.timeout.connect(self._poll_fullscreen)

        self.btn_yes = Button(S.yes, variant="primary", icon_name="check", parent=self)
        self.btn_no = Button(S.no, variant="secondary", icon_name="close", parent=self)
        self.btn_mute = Button(S.mute_btn, variant="secondary", icon_name="mic", icon_only=True, parent=self)
        self.btn_stop = Button(S.stop, variant="danger", icon_name="stop", icon_only=True, parent=self)
        self.btn_cfg = Button(S.settings, variant="secondary", icon_name="settings", icon_only=True, parent=self)
        self.btn_mute.setCheckable(True)
        self.btn_yes.clicked.connect(lambda: self._answer(True))
        self.btn_no.clicked.connect(lambda: self._answer(False))
        self.btn_stop.clicked.connect(self.stop_requested)
        self.btn_cfg.clicked.connect(self.settings_requested)
        self.btn_mute.clicked.connect(self._on_mute_clicked)
        for b in self._buttons():
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.hide()
        self._refresh_mute_button()

        self._apply_geometry()
        self._sync_a11y()
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            scr.geometryChanged.connect(lambda *_: self._apply_geometry())
        QGuiApplication.instance().primaryScreenChanged.connect(self._on_primary_changed)  # type: ignore[union-attr]

    def _dirty(self) -> None:
        """Invalida a camada estatica (texto, icones, chips) e agenda repintura."""
        self._ver += 1
        self.update()

    def _buttons(self) -> tuple[Button, ...]:
        return (self.btn_yes, self.btn_no, self.btn_mute, self.btn_stop, self.btn_cfg)

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
                self._confirm_left = 0
            self._state = state
            self._state_since = time.monotonic()
            for w in self._waves.values():
                w.reset()
            self._level = 0.0
            if state is not IslandState.CONFIRMING:
                self._confirm_text = ""
            if state is not IslandState.ERROR:
                self._error_text = ""
        self._after_change()

    def set_transcript(self, text: str) -> None:
        self._transcript = text
        self._scroll = 0
        self._after_change(retarget=False)

    def set_reply(self, text: str) -> None:
        self._reply = text
        self._scroll = 0
        self._after_change(retarget=False)

    def append_reply(self, sentence: str) -> None:
        self.set_reply((self._reply + " " + sentence).strip())

    def set_action(self, tool: str, text: str, status: str, result: str = "") -> None:
        """status: start | ok | error | denied (mesmos valores do evento ``action_step``)."""
        self._action = {"tool": tool, "text": text, "status": status, "result": result}
        if status == "start":
            self._state_since = time.monotonic()
        self._after_change(retarget=False)

    def set_error(self, text: str) -> None:
        self._error_text = text
        self.set_state(IslandState.ERROR)

    def set_mute(self, muted: bool) -> None:
        self._muted = muted
        self.btn_mute.setChecked(muted)
        self._refresh_mute_button()
        self._after_change(retarget=False)

    def set_yolo(self, remaining_s: float | None) -> None:
        """Modo YOLO ligado com ``remaining_s`` segundos restantes; ``None`` desliga."""
        self._yolo_deadline = None if remaining_s is None else time.monotonic() + max(0.0, remaining_s)
        self._after_change(retarget=False)

    def set_permission_mode(self, mode: str) -> None:
        self._perm_mode = {"balanced": S.perm_balanced, "strict": S.perm_strict}.get(mode, mode)
        self._dirty()

    def set_context_pct(self, pct: float | None) -> None:
        self._context_pct = None if pct is None else max(0.0, min(100.0, float(pct)))
        self._dirty()

    def ask_confirmation(self, text: str, timeout_s: int = T.CONFIRM_TIMEOUT_S, confirm_id: str = "") -> None:
        self._confirm_text = text
        self.confirm_id = confirm_id
        self._confirm_left = timeout_s
        self.set_state(IslandState.CONFIRMING)

    def pin_size(self, size: IslandSize | None) -> None:
        """Fixa um tamanho (clique/atalho); ``None`` volta ao automatico."""
        self._pinned = size
        self._retarget()

    def set_preview_clock(self, seconds: float | None) -> None:
        """Congela o cronometro (capturas reprodutiveis)."""
        self._elapsed_override = seconds
        self._dirty()

    # ------------------------------------------------------------------ estado derivado
    def _elapsed(self) -> float:
        return self._elapsed_override if self._elapsed_override is not None else time.monotonic() - self._state_since

    def _yolo_left(self) -> float | None:
        if self._yolo_deadline is None:
            return None
        if self._elapsed_override is not None:
            return max(0.0, self._yolo_deadline - self._state_since)
        left = self._yolo_deadline - time.monotonic()
        return left if left > 0 else None

    def _mic_kind(self) -> MicKind:
        if self._state is IslandState.ERROR:
            return MicKind.ERROR
        if self._muted:
            return MicKind.MUTED
        return MicKind.LISTENING if self._state is IslandState.LISTENING else MicKind.REST

    def _label(self, short: bool = False) -> str:
        if self._state is IslandState.ACTING and not short and self._action and self._action["text"]:
            return S.acting_prefix.format(what=self._action["text"])
        if self._muted and self._state is IslandState.IDLE:
            return S.muted
        return T.state_label(self._state)

    def _after_change(self, retarget: bool = True) -> None:
        self._motion = motion_enabled()
        if retarget:
            self._retarget()
        self._sync_timers()
        self._sync_buttons()
        self._sync_a11y()
        self._dirty()

    # ------------------------------------------------------------------ tamanho e posicao
    def _auto_size(self) -> IslandSize:
        if self._state is IslandState.CONFIRMING:
            return IslandSize.LARGE
        if self._pinned is not None:
            return self._pinned
        return IslandSize.COMPACT if self._state is IslandState.IDLE else IslandSize.MEDIUM

    def _retarget(self) -> None:
        target = self._auto_size()
        if target is self._target:
            return
        self._target = target
        start, end = self._cur, T.SIZES[target]
        if self._anim is not None:
            try:
                self._anim.stop()
            except RuntimeError:
                pass
            self._anim = None
        self._sync_buttons()
        growing = end[0] * end[1] > start[0] * start[1]
        ms = duration(T.RESIZE_MS)
        if ms == 0:
            self._morph(start, end, 1.0)
            self._on_morph_done()
        else:
            anim = QVariantAnimation(self)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setDuration(ms)
            curve = QEasingCurve(QEasingCurve.Type.OutBack if growing else QEasingCurve.Type.OutCubic)
            if growing:
                curve.setOvershoot(T.OVERSHOOT)
            anim.setEasingCurve(curve)
            anim.valueChanged.connect(lambda v: self._morph(start, end, float(v)))
            anim.finished.connect(self._on_morph_done)
            self._anim = anim
            anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
        self.size_changed.emit(target.value)

    def _morph(self, a: tuple[float, float], b: tuple[int, int], v: float) -> None:
        self._cur = (a[0] + (b[0] - a[0]) * v, a[1] + (b[1] - a[1]) * v)
        self._apply_geometry()

    def _on_morph_done(self) -> None:
        self._anim = None
        self._cur = (float(T.SIZES[self._target][0]), float(T.SIZES[self._target][1]))
        self._apply_geometry()
        self._sync_buttons()
        self._sync_timers()
        self._dirty()

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
    def _visible_sizes(self) -> set[IslandSize]:
        w, h = self._cur
        out: set[IslandSize] = set()
        if w < T.MW - 0.5:
            out.add(IslandSize.COMPACT)
        if w > T.CW + 0.5 and h < T.LH - 0.5:
            out.add(IslandSize.MEDIUM)
        if h > T.MH + 0.5:
            out.add(IslandSize.LARGE)
        return out

    def _wants_timer(self) -> bool:
        if not self.isVisible():
            return False
        if self._anim is not None:
            return True
        if self._motion:
            return self._state in T.ANIMATED_STATES
        return self._state in T.VOICE_STATES

    def _sync_timers(self) -> None:
        if self._wants_timer():
            if not self._motion:
                fps = T.FPS_REDUCED
            else:
                fps = T.FPS_VOICE if self._state in T.VOICE_STATES else T.FPS
            self._timer.setInterval(round(1000 / fps))
            if not self._timer.isActive():
                self._last = time.monotonic()
                self._timer.start()
        else:
            self._timer.stop()
        clock = self.isVisible() and (self._state is not IslandState.IDLE or self._yolo_deadline is not None)
        if clock and not self._clock.isActive():
            self._clock.start()
        elif not clock:
            self._clock.stop()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last, 0.1)
        self._last = now
        self._t += dt
        voice = self._state in T.VOICE_STATES
        bands = None
        if voice and self._levels is not None:
            bands, self._level = self._levels.read(self._state is IslandState.SPEAKING, dt)
        breathe = self._motion and (not voice or bands is None or self._level < 0.04)
        for size in self._visible_sizes():
            self._waves[size].advance(bands, dt, self._t, breathe=breathe)
        self.update()

    def _clock_tick(self) -> None:
        if self._state is IslandState.CONFIRMING and self._confirm_left > 0:
            self._confirm_left -= 1
            if self._confirm_left <= 0:
                self._answer(False)                       # sem resposta = NAO
                return
        self._dirty()

    def _answer(self, yes: bool) -> None:
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
            winapi.set_no_activate(int(self.winId()))
            if not self._guard.isActive():
                self._guard.start()
        self._sync_timers()

    def hideEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().hideEvent(e)
        self._timer.stop()
        self._clock.stop()

    def closeEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        for t in (self._timer, self._clock, self._guard):
            t.stop()
        super().closeEvent(e)

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        self._sync_buttons()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        """Clique alterna e FIXA o tamanho: automatico -> grande -> media -> compacta -> automatico."""
        if e.button() == Qt.MouseButton.LeftButton:
            order = {None: IslandSize.LARGE, IslandSize.LARGE: IslandSize.MEDIUM,
                     IslandSize.MEDIUM: IslandSize.COMPACT, IslandSize.COMPACT: None}
            self.pin_size(order.get(self._pinned))
        e.accept()

    def wheelEvent(self, e: QWheelEvent) -> None:
        """Rolagem da transcricao no tamanho grande."""
        if self._target is IslandSize.LARGE:
            step = 1 if e.angleDelta().y() > 0 else -1
            self._scroll = max(0, self._scroll + step)
            self._dirty()
        e.accept()

    # ------------------------------------------------------------------ botoes
    def _on_mute_clicked(self, checked: bool) -> None:
        self._muted = checked
        self._refresh_mute_button()
        self.mute_toggled.emit(checked)
        self._dirty()

    def _refresh_mute_button(self) -> None:
        kind = MicKind.MUTED if self._muted else MicKind.REST
        pal = T.PALETTE
        size = 16
        ratio = self.devicePixelRatioF()
        pm = QPixmap(round(size * ratio), round(size * ratio))
        pm.setDevicePixelRatio(ratio)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        draw_mic(p, QRectF(0, 0, size, size), kind, pal.text, bg=pal.raised)
        p.end()
        self.btn_mute.setIcon(QIcon(pm))
        label = S.unmute if self._muted else S.mute_btn
        self.btn_mute.setToolTip(label)
        set_a11y(self.btn_mute, label)

    def _sync_buttons(self) -> None:
        ready = self._target is IslandSize.LARGE and self._anim is None and self.height() >= T.LH - 1
        confirming = self._state is IslandState.CONFIRMING
        for b in (self.btn_yes, self.btn_no):
            b.setVisible(ready and confirming)
        self.btn_mute.setVisible(ready)
        self.btn_cfg.setVisible(ready)
        stop_vis = ready and self._state in _STOP_STATES
        self.btn_stop.setVisible(stop_vis)
        x = self.width() - T.PAD
        order = [self.btn_cfg, self.btn_mute] + ([self.btn_stop] if stop_vis else [])
        order += [self.btn_no, self.btn_yes] if confirming else []
        for b in order:
            b.adjustSize()
            x -= b.width()
            b.move(x, T.L_ROW_Y)
            x -= SPACE.sm

    def _sync_a11y(self) -> None:
        line = self._confirm_text or self._error_text or self._transcript
        extra = f" {S.muted}." if self._muted else ""
        set_a11y(self, S.window_name, f"{self._label()}.{extra} {line}".strip())

    # ------------------------------------------------------------------ pintura
    def _body_path(self, w: int, h: int) -> tuple[QRectF, float]:
        r = min(h / 2.0, float(T.CORNER_MAX))
        return QRectF(0.5, -r, w - 1.0, h + r - 0.5), r          # a parte de cima fica fora da janela

    def _fractions(self, w: int, h: int) -> tuple[float, float, float]:
        u = _clamp01((w - T.CW) / (T.MW - T.CW))
        v = _clamp01((h - T.MH) / (T.LH - T.MH))
        return (1.0 - u) ** 2, u * (1.0 - v), v * v

    def _render_static(self, w: int, h: int, dpr: float) -> QPixmap:
        """Fundo + tudo que nao se mexe por quadro (texto, icones, chips): pintado UMA vez por mudanca."""
        pal = T.PALETTE
        pm = QPixmap(round(w * dpr), round(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body, r = self._body_path(w, h)
        p.setPen(QPen(QColor(pal.border), 1.0))
        p.setBrush(QColor(pal.bg))
        p.drawRoundedRect(body, r, r)
        clip = QPainterPath()
        clip.addRoundedRect(body, r, r)
        p.setClipPath(clip)
        a_c, a_m, a_l = self._fractions(w, h)
        for a, fn in ((a_c, lambda: self._paint_compact(p, w, h, dpr, False)),
                      (a_m, lambda: self._paint_medium(p, w, dpr, False)),
                      (a_l, lambda: self._paint_large(p, w, dpr, False))):
            if a > 0.01:
                p.setOpacity(a)
                fn()
        p.end()
        return pm

    def paintEvent(self, _e: QPaintEvent) -> None:
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        key = (w, h, dpr, self._ver)
        if self._static is None or self._static_key != key:
            self._static, self._static_key = self._render_static(w, h, dpr), key
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawPixmap(0, 0, self._static)
        body, r = self._body_path(w, h)
        clip = QPainterPath()
        clip.addRoundedRect(body, r, r)
        p.setClipPath(clip)
        a_c, a_m, a_l = self._fractions(w, h)
        for a, fn in ((a_c, lambda: self._paint_compact(p, w, h, dpr, True)),
                      (a_m, lambda: self._paint_medium(p, w, dpr, True)),
                      (a_l, lambda: self._paint_large(p, w, dpr, True))):
            if a > 0.01:
                p.setOpacity(a)
                fn()
        p.end()

    def _wave_color(self) -> tuple[str, float]:
        voice = self._state in T.VOICE_STATES
        return T.state_color(self._state), (1.0 if voice else 0.55)

    def _draw_mic(self, p: QPainter, rect: QRectF) -> None:
        color = T.state_color(self._state)
        phase = pulse_phase(self._t) if (self._motion and self._state is IslandState.LISTENING and not self._muted) else 0.0
        draw_mic(p, rect, self._mic_kind(), color, bg=T.PALETTE.bg, phase=phase)

    def _paint_compact(self, p: QPainter, w: int, h: int, dpr: float, dyn: bool) -> None:
        pal = T.PALETTE
        pad = T.C_PAD
        cy = h / 2
        if dyn:
            self._draw_mic(p, QRectF(pad, cy - T.C_MIC / 2, T.C_MIC, T.C_MIC))
            wave = self._waves[IslandSize.COMPACT]
            col, al = self._wave_color()
            wave.draw(p, w - pad - T.C_DOT - SPACE.sm - wave.width, cy, col, alpha=al, dpr=dpr)
            return
        # ponto de status (forma: cheio = ativo, vazado = repouso; cor do estado)
        dot_x = w - pad - T.C_DOT
        color = QColor(T.state_color(self._state))
        p.setPen(QPen(color, 1.5))
        p.setBrush(color if self._state is not IslandState.IDLE else Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(dot_x + 0.75, cy - T.C_DOT / 2 + 0.75, T.C_DOT - 1.5, T.C_DOT - 1.5))
        wave = self._waves[IslandSize.COMPACT]
        wave_x = dot_x - SPACE.sm - wave.width
        right = wave_x - SPACE.sm
        f = make_font(TYPE.small, TYPE.semibold)
        if self._state is IslandState.ACTING:                   # tempo da acao em curso
            tf = make_font(TYPE.small, tabular=True)
            p.setFont(tf)
            tw = QFontMetrics(tf).horizontalAdvance("0:00") + 2
            p.setPen(QColor(pal.text_muted))
            p.drawText(QRectF(right - tw, 0, tw, h), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                       _mmss(self._elapsed()))
            right -= tw + SPACE.sm
        p.setFont(f)
        x = pad + T.C_MIC + SPACE.sm
        tw = max(0, int(right - x))
        p.setPen(QColor(pal.text))
        p.drawText(QRectF(x, 0, tw, h), int(Qt.AlignmentFlag.AlignVCenter),
                   QFontMetrics(f).elidedText(self._label(short=True), Qt.TextElideMode.ElideRight, tw))

    def _paint_medium(self, p: QPainter, w: int, dpr: float, dyn: bool) -> None:
        pal = T.PALETTE
        pad = T.PAD
        h = T.MH
        wave = self._waves[IslandSize.MEDIUM]
        wave_x = w - pad - wave.width
        if dyn:
            self._draw_mic(p, QRectF(pad, (h - T.M_MIC) / 2, T.M_MIC, T.M_MIC))
            col, al = self._wave_color()
            wave.draw(p, wave_x, h / 2, col, alpha=al, dpr=dpr)
            return
        x = T.M_TEXT_X
        right = wave_x - SPACE.md
        tf = make_font(TYPE.small, tabular=True)
        timer_w = QFontMetrics(tf).horizontalAdvance("00:00") + 2
        show_timer = self._state is not IslandState.IDLE
        title_w = max(0, int(right - x - (timer_w + SPACE.sm if show_timer else 0)))
        f = make_font(TYPE.body, TYPE.semibold)
        p.setFont(f)
        p.setPen(QColor(pal.text))
        p.drawText(QRectF(x, 10, title_w, 20), int(Qt.AlignmentFlag.AlignVCenter),
                   QFontMetrics(f).elidedText(self._label(), Qt.TextElideMode.ElideRight, title_w))
        if show_timer:
            p.setFont(tf)
            p.setPen(QColor(pal.text_muted))
            p.drawText(QRectF(right - timer_w, 10, timer_w, 20),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), _mmss(self._elapsed()))
        if self._state is IslandState.SPEAKING and self._reply:
            line = self._reply
        elif self._state is IslandState.CONFIRMING:
            line = self._confirm_text
        elif self._state is IslandState.ERROR:
            line = self._error_text
        else:
            line = self._transcript
        small = make_font(TYPE.small)
        p.setFont(small)
        shown = line or (S.waiting_speech if self._state is IslandState.LISTENING else "")
        p.setPen(QColor(pal.text_muted))
        tw = max(0, int(right - x))
        p.drawText(QRectF(x, 32, tw, 20), int(Qt.AlignmentFlag.AlignVCenter),
                   QFontMetrics(small).elidedText(shown, Qt.TextElideMode.ElideRight, tw))

    def _paint_large(self, p: QPainter, w: int, dpr: float, dyn: bool) -> None:
        pal = T.PALETTE
        pad = T.PAD
        inner = w - 2 * pad
        confirming = self._state is IslandState.CONFIRMING
        hy = T.L_HEADER_Y
        if dyn:
            self._draw_mic(p, QRectF(pad, hy + 2, 24, 24))
            wave = self._waves[IslandSize.LARGE]
            col, al = self._wave_color()
            wave.draw(p, pad + (inner - wave.width) / 2, T.L_WAVE_Y + T.L_WAVE_H / 2, col, alpha=al, dpr=dpr)
            return
        f = make_font(TYPE.heading, TYPE.semibold)
        right = w - pad
        chips: list[tuple[str, str, str, str]] = []     # (texto, cor do texto, fundo, borda)
        left = self._yolo_left()
        if left is not None:
            chips.append((S.yolo.format(t=_mmss(left)), pal.error, pal.error_bg, pal.error))
        if self._muted:
            chips.append((S.muted, pal.text, pal.raised, pal.border_strong))
        if self._perm_mode:
            chips.append((self._perm_mode, pal.text_muted, pal.surface, pal.border))
        cf = make_font(TYPE.caption, TYPE.semibold, tabular=True)
        fm = QFontMetrics(cf)
        tf = make_font(TYPE.small, tabular=True)
        if self._state is not IslandState.IDLE:
            tw = QFontMetrics(tf).horizontalAdvance("00:00") + 2
            p.setFont(tf)
            p.setPen(QColor(pal.text_muted))
            p.drawText(QRectF(right - tw, hy, tw, 28), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                       _mmss(self._elapsed()))
            right -= tw + SPACE.md
        for text, fg, bg, edge in chips:
            cw = fm.horizontalAdvance(text) + 2 * SPACE.md
            rect = QRectF(right - cw, hy + 4, cw, 20)
            p.setPen(QPen(QColor(edge), 1.0))
            p.setBrush(QColor(bg))
            p.drawRoundedRect(rect, 10, 10)                 # chip de estado: pilula permitida pelo DESIGN.md
            p.setFont(cf)
            p.setPen(QColor(fg))
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
            right -= cw + SPACE.sm
        p.setFont(f)
        p.setPen(QColor(pal.text))
        title_w = max(0, int(right - (pad + 36)))
        p.drawText(QRectF(pad + 36, hy, title_w, 28), int(Qt.AlignmentFlag.AlignVCenter),
                   QFontMetrics(f).elidedText(self._label(), Qt.TextElideMode.ElideRight, title_w))
        self._paint_text_block(p, w, confirming)
        self._paint_action(p, w)
        self._paint_context(p)

    def _paint_text_block(self, p: QPainter, w: int, confirming: bool) -> None:
        pal = T.PALETTE
        pad = T.PAD
        x_label, x_text = pad, pad + 44
        tw = w - x_text - pad - 6
        top = T.L_TEXT_Y
        if confirming or self._state is IslandState.ERROR:
            f = make_font(TYPE.heading, TYPE.semibold)
            p.setFont(f)
            p.setPen(QColor(pal.text))
            fm = QFontMetrics(f)
            text = self._confirm_text if confirming else self._error_text
            lines = _wrap(fm, text, w - 2 * pad)
            more = len(lines) > 2
            lines = lines[:2]
            if more:
                lines[-1] = fm.elidedText(lines[-1] + " …", Qt.TextElideMode.ElideRight, w - 2 * pad)
            for i, ln in enumerate(lines):
                p.drawText(QRectF(pad, top + i * 24, w - 2 * pad, 24), int(Qt.AlignmentFlag.AlignVCenter), ln)
            return
        f = make_font(TYPE.small)
        cap = make_font(TYPE.caption, TYPE.semibold)
        fm = QFontMetrics(f)
        rows: list[tuple[str, str, str]] = []            # (rotulo, texto, cor do texto)
        for role, text in ((S.you, self._transcript), (S.jarvis, self._reply)):
            if not text:
                continue
            for i, ln in enumerate(_wrap(fm, text, tw)):
                rows.append((role if i == 0 else "", ln, pal.text))
        if not rows:
            rows = [("", S.waiting_speech, pal.text_muted)]
        n = T.L_TEXT_LINES
        max_scroll = max(0, len(rows) - n)
        self._scroll = min(self._scroll, max_scroll)
        end = len(rows) - self._scroll
        for i, (role, ln, color) in enumerate(rows[max(0, end - n):end]):
            y = top + i * T.L_LINE_H
            if role:
                p.setFont(cap)
                p.setPen(QColor(pal.text_muted))
                p.drawText(QRectF(x_label, y, 42, T.L_LINE_H), int(Qt.AlignmentFlag.AlignVCenter), role)
            p.setFont(f)
            p.setPen(QColor(color))
            p.drawText(QRectF(x_text, y, tw, T.L_LINE_H), int(Qt.AlignmentFlag.AlignVCenter), ln)
        if max_scroll > 0:                               # indicador de rolagem (a roda do mouse rola)
            track_h = n * T.L_LINE_H
            thumb_h = max(8.0, track_h * n / len(rows))
            y0 = top + (track_h - thumb_h) * (1 - self._scroll / max_scroll)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal.border_strong))
            p.drawRoundedRect(QRectF(w - pad - 3, y0, 3, thumb_h), 1.5, 1.5)

    def _paint_action(self, p: QPainter, w: int) -> None:
        pal = T.PALETTE
        pad = T.PAD
        y = T.L_ACTION_Y
        f = make_font(TYPE.small)
        p.setFont(f)
        fm = QFontMetrics(f)
        a = self._action
        if a is None:
            p.setPen(QColor(pal.text_muted))
            p.drawText(QRectF(pad, y, w - 2 * pad, 16), int(Qt.AlignmentFlag.AlignVCenter), S.no_action)
            return
        status = a["status"]
        icon, color, word = {"ok": ("ok", pal.ok, S.action_ok), "error": ("error", pal.error, S.action_error),
                             "denied": ("alert", pal.warn, S.action_denied)}.get(
            status, ("info", pal.text_muted, S.action_running))
        p.drawPixmap(QPointF(pad, y), icons.pixmap(icon, color, 16, self))
        wf = make_font(TYPE.small, TYPE.semibold)
        word_w = QFontMetrics(wf).horizontalAdvance(word)
        x = pad + 16 + SPACE.sm
        p.setFont(wf)
        p.setPen(QColor(color))
        p.drawText(QRectF(w - pad - word_w, y, word_w, 16),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), word)
        text = f"{a['tool']}: {a['text']}" if a["tool"] else a["text"]
        if a["result"] and status in ("ok", "error"):
            text += f"  ({a['result']})"
        avail = max(0, int(w - pad - word_w - SPACE.md - x))
        p.setFont(f)
        p.setPen(QColor(pal.text))
        p.drawText(QRectF(x, y, avail, 16), int(Qt.AlignmentFlag.AlignVCenter),
                   fm.elidedText(text, Qt.TextElideMode.ElideRight, avail))

    def _paint_context(self, p: QPainter) -> None:
        pal = T.PALETTE
        pad = T.PAD
        pct = self._context_pct
        y = T.L_ROW_Y
        p.setFont(make_font(TYPE.caption, tabular=True))
        p.setPen(QColor(pal.text_muted))
        if self._state is IslandState.CONFIRMING:           # no lugar do contexto: aviso do prazo (sem resposta = Nao)
            p.setPen(QColor(pal.warn))
            p.drawText(QRectF(pad, y, 190, 32), int(Qt.AlignmentFlag.AlignVCenter),
                       S.confirm_timeout.format(s=max(self._confirm_left, 0)))
            return
        label = S.context.format(pct=int(round(pct)) if pct is not None else "--")
        p.drawText(QRectF(pad, y, 92, 32), int(Qt.AlignmentFlag.AlignVCenter), label)
        bx, bw, bh = pad + 96, 96.0, 4.0
        by = y + 16 - bh / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal.border))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 2, 2)
        if pct is not None:
            p.setBrush(QColor(pal.warn if pct >= 80 else T.accent()))
            p.drawRoundedRect(QRectF(bx, by, max(bh, bw * pct / 100.0), bh), 2, 2)
