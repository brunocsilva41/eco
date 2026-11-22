"""IslandWindow: a Ilha do Jarvis (estilo Dynamic Island). ESCONDIDA por padrao: so aparece quando importa.

Presenca (ver ``_policy``/``_present``): aparece com o mouse na zona do topo (``zone.py``), quando o nucleo entra em
LISTENING (tecla F9 e, no futuro, palavra de ativacao), em confirmacao (sempre, ate responder), erro/emergencia e em
avisos breves (YOLO, mudo). Some sozinha depois de ``hide_delay_s`` em repouso, NUNCA com o mouse em cima, em
confirmacao, falando/agindo ou fixada pelo alfinete. Escondida = janela oculta (SW_HIDE), zero timers, zero repinturas.

Modos de posicao: 'docked' (colada ao topo, so os cantos de baixo redondos) e 'floating' (pilula, afastada do topo
por N px, sombra suave e borda sutil). Tres tamanhos (compacta/media/grande) com morfose por camadas em cache: cada
tamanho e pintado UMA vez no tamanho nativo e a troca e um cross-fade com escala leve (sem repintar texto por quadro).

Quadros: um unico QTimer de quadros, ativo so enquanto ha algo animando (60 fps voz/transicoes, 30 fps pensando e
afins, 15 fps respiracao do repouso nos primeiros segundos, 0 fps no repouso estatico). 'Reduzir animacoes' do
Windows: tudo instantaneo; so as barras de nivel (informacao) seguem a 12 fps.
"""
from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen,
                           QPixmap, QWheelEvent)
from PySide6.QtWidgets import QWidget

from ..kit.base import set_a11y
from ..kit.platform import motion_enabled
from . import glyphs, waves
from . import render as R
from . import tokens as T
from . import winapi
from .conf import IslandConfig, display
from .strings import S
from .tokens import IslandSize, IslandState
from .waves import WaveBars

_STOP_STATES = (IslandState.LISTENING, IslandState.TRANSCRIBING, IslandState.THINKING, IslandState.ACTING,
                IslandState.SPEAKING, IslandState.CONFIRMING)
ZONE_MODE = os.environ.get("JARVIS_ISLAND_ZONE", "window")          # window | poll (ver zone.py e docs/ILHA-SPEC.md)
_NAME = {IslandSize.COMPACT: "compact", IslandSize.MEDIUM: "medium", IslandSize.LARGE: "large"}


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _curve(kind: QEasingCurve.Type, overshoot: float | None = None) -> QEasingCurve:
    c = QEasingCurve(kind)
    if overshoot is not None:
        c.setOvershoot(overshoot)
    return c


_C_GROW = _curve(QEasingCurve.Type.OutBack, T.OVERSHOOT)
_C_SHRINK = _curve(QEasingCurve.Type.OutCubic)
_C_IN = _curve(QEasingCurve.Type.OutCubic)
_C_OUT = _curve(QEasingCurve.Type.InCubic)


class IslandWindow(QWidget):
    """API para o nucleo (via ``bridge.py``): ``set_state``, ``set_transcript``, ``set_reply``/``append_reply``,
    ``set_action``, ``ask_confirmation``, ``set_context_pct``, ``set_mute``, ``set_yolo``, ``set_permission_mode``,
    ``set_error``, ``flash``, ``apply_config``, ``pin_size``, ``start``.
    Sinais para o nucleo: ``confirm_answered(bool)``, ``stop_requested()``, ``mute_toggled(bool)``,
    ``settings_requested(str)`` (secao; vazio = geral), ``size_changed(str)``."""

    confirm_answered = Signal(bool)
    stop_requested = Signal()
    mute_toggled = Signal(bool)
    settings_requested = Signal(str)
    size_changed = Signal(str)

    def __init__(self, levels=None, parent: QWidget | None = None, cfg: IslandConfig | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.cfg = cfg or IslandConfig()
        self._levels = levels
        # --- estado de conteudo (lido por render.py)
        self.state = IslandState.IDLE
        self.transcript = ""
        self.reply = ""
        self.action: dict[str, str] | None = None
        self.error_text = ""
        self.confirm_text = ""
        self.confirm_id = ""
        self.confirm_left = 0
        self.muted = False
        self.perm_mode = ""
        self.context_pct: float | None = None
        self.scroll = 0
        self.t = 0.0
        self.motion = motion_enabled()
        self._yolo_deadline: float | None = None
        self._flash_label = ""
        self._confirm_total = T.CONFIRM_TIMEOUT_S
        self._confirm_deadline = 0.0
        # --- tamanho / morfose
        self._pinned: IslandSize | None = None
        self._target = IslandSize.COMPACT
        self._cur = (float(T.CW), float(T.CH))
        self._morph: tuple[tuple[float, float], tuple[float, float], float, QEasingCurve] | None = None
        # --- presenca
        self._pres = 0.0
        self._pres_dir = 0
        self._keep = False                         # alfinete
        self._hover = False
        self._hold_until = 0.0
        self._idle_since = time.monotonic()
        self._guard_hid = False
        self._fs_hits = 0
        self._fs_miss = 0
        self._noact = False
        self._zone = None
        # --- camadas / quadros
        self._btn_pm: QPixmap | None = None
        self._btn_key: tuple | None = None
        self._layers: dict[IslandSize, QPixmap] = {}
        self._old: dict[IslandSize, QPixmap] = {}
        self._layer_dpr = 0.0
        self._fade_p = 1.0
        self._chrome: QPixmap | None = None
        self._chrome_key: tuple | None = None
        self._elapsed_override: float | None = None
        self._state_since = time.monotonic()
        self._last = time.monotonic()
        self._level = 0.0
        self._native = QGuiApplication.platformName() == "windows"
        self.waves = {"compact": WaveBars(T.C_BARS, 3, 3, 16.0), "medium": WaveBars(T.M_BARS, 3, 3, float(T.M_WAVE_H)),
                      "large": WaveBars(T.L_BARS, T.L_BAR_W, T.L_BAR_GAP, float(T.L_WAVE_H))}
        # --- botoes (pintados, sem QWidget)
        self.b_yes = R.Btn("yes", "check", S.yes, "", "primary", 36)
        self.b_no = R.Btn("no", "close", S.no, "", "neutral", 36)
        self.b_mute = R.Btn("mute", "mic", S.mute_short, "", "neutral")
        self.b_yolo = R.Btn("yolo", "bolt", "", "", "neutral", name=S.yolo_btn)
        self.b_stop = R.Btn("stop", "stop", S.stop, "", "danger")
        self.b_cfg = R.Btn("cfg", "gear", "", "", "neutral", name=S.settings)
        self.b_pin = R.Btn("pin", "pin", "", "", "ghost", 28, name=S.pin)
        self.b_talk = R.Btn("talk", "mic", S.talk, "", "ghost")
        self.btns = [self.b_yes, self.b_no, self.b_mute, self.b_yolo, self.b_stop, self.b_cfg, self.b_pin, self.b_talk]
        self._hover_btn: R.Btn | None = None
        self._press_btn: R.Btn | None = None
        self._focus_btn: R.Btn | None = None
        # --- timers (todos parados enquanto escondida)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._clock_tick)
        self._guard = QTimer(self)
        self._guard.setInterval(T.FULLSCREEN_POLL_MS)
        self._guard.timeout.connect(self._poll_fullscreen)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_hide_timer)
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)

        self._layout_buttons()
        self._apply_geometry()
        self._sync_a11y()
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            scr.geometryChanged.connect(lambda *_: self._on_screen_changed())
        QGuiApplication.instance().primaryScreenChanged.connect(self._on_primary_changed)  # type: ignore[union-attr]

    # ================================================================== API publica
    def start(self) -> None:
        """Ponto de partida: escondida (zona do topo armada) ou, com autohide desligado, visivel."""
        if self.cfg.autohide:
            self._arm_zone()
            QTimer.singleShot(1500, winapi.trim_working_set)       # partida escondida: devolve as paginas da inicializacao
        else:
            self._present(True)

    def set_levels_source(self, source) -> None:
        self._levels = source

    @property
    def size_target(self) -> IslandSize:
        return self._target

    @property
    def presence(self) -> float:
        return self._pres if self.isVisible() else 0.0

    def set_state(self, state: IslandState) -> None:
        if state is not self.state:
            if self.state is IslandState.CONFIRMING:
                self.confirm_left = 0
            self.state = state
            self._state_since = time.monotonic()
            for w in self.waves.values():
                w.reset()
            self._level = 0.0
            if state is not IslandState.CONFIRMING:
                self.confirm_text = ""
            if state is not IslandState.ERROR:
                self.error_text = ""
            if state is IslandState.IDLE:
                self._idle_since = time.monotonic()
                self._touch(self.cfg.hide_delay_s)
            elif state is IslandState.ERROR:
                self._touch(T.ERROR_S)
        self._after_change()
        self._policy()

    def set_transcript(self, text: str) -> None:
        self.transcript = text
        self.scroll = 0
        self._after_change(retarget=False)

    def set_reply(self, text: str) -> None:
        self.reply = text
        self.scroll = 0
        self._after_change(retarget=False)

    def append_reply(self, sentence: str) -> None:
        self.set_reply((self.reply + " " + sentence).strip())

    def set_action(self, tool: str, text: str, status: str, result: str = "") -> None:
        """status: start | ok | error | denied (mesmos valores do evento ``action_step``)."""
        self.action = {"tool": tool, "text": text, "status": status, "result": result}
        if status == "start":
            self._state_since = time.monotonic()
        self._after_change(retarget=False)

    def set_error(self, text: str) -> None:
        self.error_text = text
        self.set_state(IslandState.ERROR)
        self._touch(T.ERROR_S)
        self._policy()

    def flash(self, label: str, hold: float = T.FLASH_S, error: bool = False) -> None:
        """Aviso breve (YOLO, mudo, emergencia): mostra a Ilha e esconde sozinha."""
        if error:
            self.set_error(label)
            return
        self._flash_label = label
        self._flash_timer.start(int(hold * 1000) + 40)
        self._touch(hold)
        self._after_change(retarget=False)
        self._present(True)

    def _clear_flash(self) -> None:
        self._flash_label = ""
        self._dirty(fade=True)
        self._reschedule()

    def set_mute(self, muted: bool, flash: bool = False) -> None:
        changed = muted != self.muted
        self.muted = muted
        self._after_change(retarget=False)
        if flash and changed:
            self.flash(S.flash_muted if muted else S.flash_mic_on)

    def set_yolo(self, remaining_s: float | None, flash: bool = False) -> None:
        """Modo YOLO ligado com ``remaining_s`` segundos restantes; ``None`` desliga."""
        was = self._yolo_deadline is not None
        self._yolo_deadline = None if remaining_s is None else time.monotonic() + max(0.0, remaining_s)
        self._after_change(retarget=False)
        if flash and was != (self._yolo_deadline is not None):
            self.flash(S.flash_yolo_on if self._yolo_deadline is not None else S.flash_yolo_off)

    def set_permission_mode(self, mode: str) -> None:
        self.perm_mode = {"balanced": S.perm_balanced, "strict": S.perm_strict}.get(mode, mode)
        self._dirty()

    def set_context_pct(self, pct: float | None) -> None:
        self.context_pct = None if pct is None else max(0.0, min(100.0, float(pct)))
        self._dirty()

    def ask_confirmation(self, text: str, timeout_s: int = T.CONFIRM_TIMEOUT_S, confirm_id: str = "") -> None:
        self.confirm_text = text
        self.confirm_id = confirm_id
        self.confirm_left = timeout_s
        self._confirm_total = max(1, timeout_s)
        self._confirm_deadline = time.monotonic() + timeout_s
        self.set_state(IslandState.CONFIRMING)

    def apply_config(self, cfg: IslandConfig) -> None:
        """Aplicada ao vivo (mensagem ``config`` do nucleo): modo, folga, esconder sozinha, atalhos."""
        old = self.cfg
        self.cfg = cfg
        self._layout_buttons()
        self._dirty()
        self._apply_geometry()
        if not cfg.autohide:
            self._disarm_zone()
            self._present(True)
        elif self.isVisible():
            self._touch(cfg.hide_delay_s)
            self._reschedule()
        elif cfg.hover_reveal:
            self._arm_zone()
        else:
            self._disarm_zone()
        if old.mode != cfg.mode:
            self._chrome = None

    def pin_size(self, size: IslandSize | None) -> None:
        """Fixa um tamanho (clique); ``None`` volta ao automatico."""
        self._pinned = size
        self._retarget()

    def set_preview_clock(self, seconds: float | None) -> None:
        """Congela o cronometro (capturas reprodutiveis)."""
        self._elapsed_override = seconds
        self._dirty()

    # ================================================================== estado derivado (render.py)
    def elapsed(self) -> float:
        return self._elapsed_override if self._elapsed_override is not None else time.monotonic() - self._state_since

    def yolo_left(self) -> float | None:
        if self._yolo_deadline is None:
            return None
        if self._elapsed_override is not None:
            return max(0.0, self._yolo_deadline - self._state_since)
        left = self._yolo_deadline - time.monotonic()
        return left if left > 0 else None

    def confirm_frac(self) -> float:
        if self._elapsed_override is not None:
            return _clamp01(self.confirm_left / self._confirm_total)
        return _clamp01((self._confirm_deadline - time.monotonic()) / self._confirm_total)

    def label(self, short: bool = False) -> str:
        if self._flash_label and self.state is IslandState.IDLE:
            return self._flash_label
        if self.state is IslandState.ACTING and not short and self.action and self.action["text"]:
            return S.acting_prefix.format(what=self.action["text"])
        if self.muted and self.state is IslandState.IDLE:
            return S.muted
        return T.state_label(self.state)

    def breath(self) -> float:
        """Respiracao do repouso: 0,72..1 de opacidade do icone, so nos primeiros segundos visiveis."""
        if self.motion and self.state is IslandState.IDLE and self._breath_active():
            return 0.86 + 0.14 * math.sin(self.t * 2.4)
        return 1.0

    def _breath_active(self) -> bool:
        return time.monotonic() - self._idle_since < T.BREATH_S

    # ================================================================== presenca
    def _fs_active(self) -> bool:
        return T.HIDE_ON_FULLSCREEN and winapi.fullscreen_app_active(int(self.winId()))

    def _touch(self, hold: float) -> None:
        self._hold_until = max(self._hold_until, time.monotonic() + hold)

    def _needs_visible(self) -> bool:
        if not self.cfg.autohide or self._keep or self.state is IslandState.CONFIRMING or self.state in T.ACTIVE_STATES:
            return True
        if self._hover or self.geometry().contains(QCursor.pos()):
            return True
        return False

    def _policy(self) -> None:
        """Depois de qualquer mudanca de estado: mostrar, manter ou agendar o sumico."""
        st = self.state
        if st is IslandState.CONFIRMING:
            self._present(True, force=True)                   # confirmacao SEMPRE aparece (ate em tela cheia)
        elif st in T.ACTIVE_STATES or st is IslandState.ERROR:
            self._present(True)
        self._reschedule()

    def _reschedule(self) -> None:
        if not self.isVisible() or not self.cfg.autohide or self._needs_visible():
            self._hide_timer.stop()
            return
        remain = self._hold_until - time.monotonic()
        self._hide_timer.start(max(60, int(remain * 1000)))

    def _on_hide_timer(self) -> None:
        if self._needs_visible():
            return
        if time.monotonic() < self._hold_until:
            self._reschedule()
            return
        self._present(False)

    def _present(self, want: bool, force: bool = False) -> None:
        if want:
            if not force and not self.isVisible() and self._fs_active():
                return
            self._guard_hid = False
            if not self.isVisible():
                self._do_show()
            elif self._pres_dir < 0 or self._pres < 1.0:
                self._pres_dir = 1 if self.motion else 0
                if not self.motion:
                    self._pres = 1.0
                    self._apply_geometry()
                self._sync_timers()
        elif self.isVisible() and self.state is not IslandState.CONFIRMING:
            if self.motion:
                self._pres_dir = -1
                self._sync_timers()
            else:
                self._finish_hide()

    def _do_show(self) -> None:
        self._disarm_zone()
        self._cur = (float(T.SIZES[self._auto_size()][0]), float(T.SIZES[self._auto_size()][1]))
        self._target = self._auto_size()
        self._morph = None
        self._layers.clear()
        self._old.clear()
        self._fade_p = 1.0
        self._last = time.monotonic()
        self._pres = 0.0 if self.motion else 1.0
        self._pres_dir = 1 if self.motion else 0
        self._layout_buttons()
        self._apply_geometry()
        self.show()
        self._reschedule()
        self._sync_timers()

    def _finish_hide(self) -> None:
        self._pres, self._pres_dir = 0.0, 0
        self._timer.stop()
        self._clock.stop()
        self._hide_timer.stop()
        self._hover = False
        self._hover_btn = self._press_btn = None
        self.hide()
        self._layers.clear()
        self._old.clear()
        self._chrome = None
        self._chrome_key = None
        self._btn_pm = None
        self._btn_key = None
        glyphs.clear_caches()
        waves.clear_cache()
        if self.cfg.autohide and self.cfg.hover_reveal:
            self._arm_zone()
        QTimer.singleShot(500, winapi.trim_working_set)          # devolve paginas ociosas ao Windows

    def _arm_zone(self) -> None:
        if not self.cfg.hover_reveal or not self.cfg.autohide or self.isVisible():
            return
        if self._zone is None:
            from .zone import CursorPoller, HotZone
            self._zone = CursorPoller() if ZONE_MODE == "poll" else HotZone()
            self._zone.triggered.connect(self._on_zone)
        self._zone.arm()

    def _disarm_zone(self) -> None:
        if self._zone is not None:
            self._zone.disarm()

    def _on_zone(self) -> None:
        if self.isVisible() or self._fs_active():
            return
        self._touch(self.cfg.hide_delay_s)
        self._present(True)

    def enterEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().enterEvent(e)
        self._hover = True
        self._hide_timer.stop()

    def leaveEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().leaveEvent(e)
        self._hover = False
        self._set_hover_btn(None)
        self._touch(self.cfg.hide_delay_s)
        self._reschedule()

    # ================================================================== mudancas e camadas
    def _after_change(self, retarget: bool = True) -> None:
        self.motion = motion_enabled()
        if retarget:
            self._retarget()
        self._layout_buttons()
        self._sync_timers()
        self._sync_a11y()
        self._dirty(fade=True)

    def _dirty(self, fade: bool = False) -> None:
        """Invalida as camadas estaticas (texto, chips). ``fade``: cross-fade de 150 ms com a versao anterior."""
        if fade and self.motion and self.isVisible() and self._pres_dir == 0 and self._layers:
            self._old = dict(self._layers)
            self._fade_p = 0.0
        self._layers.clear()
        if self.isVisible():
            self.update()
            self._sync_timers()

    def _layer(self, size: IslandSize, dpr: float) -> QPixmap:
        if dpr != self._layer_dpr:
            self._layers.clear()
            self._old.clear()
            self._layer_dpr = dpr
        pm = self._layers.get(size)
        if pm is None:
            w, h = T.SIZES[size]
            pm = QPixmap(round(w * dpr), round(h * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
            R.STATIC[_NAME[size]](self, p)
            p.end()
            self._layers[size] = pm
        return pm

    # ================================================================== tamanho, geometria
    def _auto_size(self) -> IslandSize:
        if self.state is IslandState.CONFIRMING:
            return IslandSize.LARGE
        if self._pinned is not None:
            return self._pinned
        return IslandSize.COMPACT if self.state is IslandState.IDLE else IslandSize.MEDIUM

    def _retarget(self) -> None:
        target = self._auto_size()
        if target is self._target:
            return
        end = T.SIZES[target]
        start = self._cur
        self._target = target
        if not self.isVisible() or not self.motion:
            self._cur = (float(end[0]), float(end[1]))
            self._morph = None
            self._apply_geometry()
        else:
            grow = end[0] * end[1] > start[0] * start[1]
            self._morph = (start, (float(end[0]), float(end[1])), 0.0, _C_GROW if grow else _C_SHRINK)
        self._layout_buttons()
        self.size_changed.emit(target.value)
        self._sync_timers()

    @property
    def _floating(self) -> bool:
        return self.cfg.mode == "floating"

    def _margin(self) -> int:
        return T.SHADOW_M if self._floating else 0

    def _apply_geometry(self) -> None:
        scr = QGuiApplication.primaryScreen()
        m = self._margin()
        bw, bh = round(self._cur[0]), round(self._cur[1])
        w, h = bw + 2 * m, bh + 2 * m
        if scr is None:
            self.resize(w, h)
            return
        g = scr.geometry()
        top = self.cfg.float_gap_px if self._floating else 0
        e = (_C_IN if self._pres_dir >= 0 else _C_OUT).valueForProgress(self._pres) if self.motion else 1.0
        slide = (1.0 - e) * (bh + top + 8)
        rect = QRect(g.x() + (g.width() - bw) // 2 - m, round(g.y() + top - m - slide), w, h)
        if rect != self.geometry():
            self.setGeometry(rect)
        op = _clamp01(e * 1.15)
        if abs(self.windowOpacity() - op) > 0.004:
            self.setWindowOpacity(op)

    def _on_screen_changed(self) -> None:
        if self.isVisible():
            self._apply_geometry()
        else:
            self._arm_zone()

    def _on_primary_changed(self, scr) -> None:  # type: ignore[no-untyped-def]
        if scr is not None:
            scr.geometryChanged.connect(lambda *_: self._on_screen_changed())
        self._on_screen_changed()

    # ================================================================== quadros
    def _needs_frames(self) -> bool:
        if not self.isVisible():
            return False
        if self._pres_dir or self._morph is not None or self._fade_p < 1.0:
            return True
        for b in self.btns:
            if b.visible and abs(b.hover - (1.0 if b is self._hover_btn else 0.0)) > 0.01:
                return True
        if self.state in T.VOICE_STATES:
            return True
        if self.motion:
            return self.state in T.ANIMATED_STATES or (self.state is IslandState.IDLE and self._breath_active())
        return False

    def _interval(self) -> int:
        transient = bool(self._pres_dir or self._morph is not None or self._fade_p < 1.0)
        if not transient:
            transient = any(b.visible and abs(b.hover - (1.0 if b is self._hover_btn else 0.0)) > 0.01 for b in self.btns)
        if transient:
            return round(1000 / T.FPS_FAST)
        if self.state in T.VOICE_STATES:
            return round(1000 / (T.FPS_FAST if self.motion else T.FPS_REDUCED))
        if self.state in T.ANIMATED_STATES:
            return round(1000 / T.FPS)
        return round(1000 / T.FPS_BREATH)

    def _sync_timers(self) -> None:
        if self._needs_frames():
            iv = self._interval()
            if self._timer.interval() != iv:
                self._timer.setInterval(iv)
            if not self._timer.isActive():
                self._last = time.monotonic()
                self._timer.start()
        else:
            self._timer.stop()
        clock = self.isVisible() and (self.state is not IslandState.IDLE or self._yolo_deadline is not None)
        if clock and not self._clock.isActive():
            self._clock.start()
        elif not clock:
            self._clock.stop()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last, 0.1)
        self._last = now
        self.t += dt
        geo = False
        if self._pres_dir:
            dur = (T.ENTER_MS if self._pres_dir > 0 else T.EXIT_MS) / 1000.0
            self._pres += self._pres_dir * dt / dur
            if self._pres >= 1.0:
                self._pres, self._pres_dir = 1.0, 0
                self._reschedule()
            elif self._pres <= 0.0:
                self._finish_hide()
                return
            geo = True
        if self._morph is not None:
            a, b, pr, curve = self._morph
            pr += dt / (T.RESIZE_MS / 1000.0)
            if pr >= 1.0:
                self._cur = b
                self._morph = None
                self._layout_buttons()
            else:
                v = curve.valueForProgress(pr)
                self._cur = (a[0] + (b[0] - a[0]) * v, a[1] + (b[1] - a[1]) * v)
                self._morph = (a, b, pr, curve)
            geo = True
        if geo:
            self._apply_geometry()
        if self._fade_p < 1.0:
            self._fade_p = min(1.0, self._fade_p + dt / (T.FADE_MS / 1000.0))
            if self._fade_p >= 1.0:
                self._old.clear()
        k = 1.0 - math.exp(-dt / (T.HOVER_MS / 1000.0 / 2.2))
        for b in self.btns:
            if b.visible:
                tgt = 1.0 if b is self._hover_btn else 0.0
                b.hover = tgt if not self.motion else b.hover + (tgt - b.hover) * k
        voice = self.state in T.VOICE_STATES
        bands = None
        if voice and self._levels is not None:
            bands, self._level = self._levels.read(self.state is IslandState.SPEAKING, dt)
        breathe = self.motion and (not voice or bands is None or self._level < 0.04)
        for name in self._visible_waves():
            self.waves[name].advance(bands, dt, self.t, breathe=breathe)
        self.update()
        self._sync_timers()

    def _visible_waves(self) -> tuple[str, ...]:
        fc, fm, fl = self._fractions(*self._cur)
        out = []
        if fc > 0.01:
            out.append("compact")
        if fm > 0.01:
            out.append("medium")
        if fl > 0.01:
            out.append("large")
        return tuple(out)

    def _clock_tick(self) -> None:
        if self.state is IslandState.CONFIRMING:
            self.confirm_left = max(0, int(self._confirm_deadline - time.monotonic() + 0.999))
            if self.confirm_left <= 0:
                self._answer(False)                           # sem resposta = NAO
                return
        self._dirty()

    def _answer(self, yes: bool) -> None:
        self.confirm_answered.emit(yes)

    def _poll_fullscreen(self) -> None:
        if not T.HIDE_ON_FULLSCREEN:
            return
        if winapi.fullscreen_app_active(int(self.winId())):
            self._fs_hits, self._fs_miss = self._fs_hits + 1, 0
        else:
            self._fs_hits, self._fs_miss = 0, self._fs_miss + 1
        if self._fs_hits >= T.FULLSCREEN_HIDE_HITS and self.isVisible() and self.state is not IslandState.CONFIRMING:
            self._guard_hid = not self.cfg.autohide             # sem autohide: volta quando a tela cheia acabar
            self._finish_hide()
            if not self._guard_hid:
                self._guard.stop()
        elif self._fs_miss >= T.FULLSCREEN_SHOW_MISSES and self._guard_hid:
            self._guard_hid = False
            self._present(True)

    # ================================================================== ciclo de vida da janela
    def showEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(e)
        if self._native and not self._noact:
            winapi.set_no_activate(int(self.winId()))
            self._noact = True
        if self._native and not self._guard.isActive():
            self._guard.start()
        self._sync_timers()

    def hideEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().hideEvent(e)
        self._timer.stop()
        self._clock.stop()
        if not self._guard_hid:
            self._guard.stop()

    def closeEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        for t in (self._timer, self._clock, self._guard, self._hide_timer, self._flash_timer):
            t.stop()
        if self._zone is not None:
            self._zone.disarm()
        super().closeEvent(e)

    # ================================================================== botoes
    def _layout_buttons(self) -> None:
        hk = self.cfg.hotkeys
        confirming = self.state is IslandState.CONFIRMING
        self.b_yes.hk, self.b_no.hk = display(hk.get("yes", "")), display(hk.get("no", ""))
        self.b_mute.hk, self.b_stop.hk = display(hk.get("mute", "")), display(hk.get("stop", ""))
        self.b_yolo.hk, self.b_talk.hk = display(hk.get("yolo", "")), display(hk.get("talk", ""))
        self.b_mute.glyph = "mic_off" if self.muted else "mic"
        self.b_mute.label = S.unmute_short if self.muted else S.mute_short
        self.b_mute.name = S.unmute if self.muted else S.mute_btn
        self.b_yolo.fill = self.yolo_left() is not None
        self.b_yolo.variant = "danger" if self.b_yolo.fill else "neutral"
        self.b_pin.fill = self._keep
        self.b_pin.name = S.unpin if self._keep else S.pin
        self.b_stop.name = S.stop
        self.b_talk.enabled = True
        W = T.LW
        x = W - T.PAD
        for b in (self.b_cfg, self.b_stop, self.b_yolo, self.b_mute):
            b.h, b.y = T.L_BTN_H, T.L_ROW_Y
            b.w = b.measure()
            x -= b.w
            b.x = x
            x -= 6
        self.b_talk.h, self.b_talk.y, self.b_talk.x = T.L_BTN_H, T.L_ROW_Y, T.PAD - 6
        self.b_talk.w = self.b_talk.measure()
        self.b_pin.x, self.b_pin.y, self.b_pin.w = W - T.PAD - 28, T.L_HEAD_Y, 28.0
        self.b_yes.y = self.b_no.y = T.L_CONFIRM_Y
        self.b_yes.x = T.PAD
        self.b_yes.w = max(self.b_yes.measure(), 120.0)
        self.b_no.x = self.b_yes.x + self.b_yes.w + 8
        self.b_no.w = max(self.b_no.measure(), 120.0)
        for b in self.btns:
            b.visible = False
        if self._target is IslandSize.LARGE and self._morph is None:
            for b in (self.b_cfg, self.b_stop, self.b_yolo, self.b_mute, self.b_pin):
                b.visible = True
            self.b_talk.visible = not confirming
            self.b_yes.visible = self.b_no.visible = confirming
        for b in self.btns:
            if not b.visible:
                b.hover, b.press, b.focus = 0.0, False, False

    def _btn_at(self, pos) -> R.Btn | None:
        if not (self._target is IslandSize.LARGE and self._morph is None):
            return None
        m = self._margin()
        x, y = pos.x() - m, pos.y() - m
        for b in self.btns:
            if b.key != "talk" and b.contains(x, y):
                return b
        return None

    def _set_hover_btn(self, b: R.Btn | None) -> None:
        if b is self._hover_btn:
            return
        self._hover_btn = b
        self.setCursor(Qt.CursorShape.PointingHandCursor if b is not None else Qt.CursorShape.ArrowCursor)
        self._sync_timers()
        self.update()

    def _activate(self, b: R.Btn) -> None:
        k = b.key
        if k == "yes":
            self._answer(True)
        elif k == "no":
            self._answer(False)
        elif k == "mute":
            self.muted = not self.muted
            self._after_change(retarget=False)
            self.mute_toggled.emit(self.muted)
        elif k == "stop":
            self.stop_requested.emit()
        elif k == "cfg":
            self.settings_requested.emit("")
        elif k == "yolo":
            self.settings_requested.emit("permissions")           # o YOLO nunca liga por clique: abre a tela dele
        elif k == "pin":
            self._keep = not self._keep
            self._layout_buttons()
            self._dirty()
            self._reschedule()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        self._set_hover_btn(self._btn_at(e.position()))
        e.accept()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        """Botao do mouse sobre um botao da Ilha o aciona (ao soltar); no resto do corpo alterna e FIXA o tamanho:
        automatico -> grande -> media -> compacta -> automatico."""
        if e.button() == Qt.MouseButton.LeftButton:
            b = self._btn_at(e.position())
            if b is not None:
                b.press = True
                self._press_btn = b
                self.update()
            else:
                order = {None: IslandSize.LARGE, IslandSize.LARGE: IslandSize.MEDIUM,
                         IslandSize.MEDIUM: IslandSize.COMPACT, IslandSize.COMPACT: None}
                self.pin_size(order.get(self._pinned))
        e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        b, self._press_btn = self._press_btn, None
        if b is not None:
            b.press = False
            self.update()
            if e.button() == Qt.MouseButton.LeftButton and self._btn_at(e.position()) is b:
                self._activate(b)
        e.accept()

    def wheelEvent(self, e: QWheelEvent) -> None:
        if self._target is IslandSize.LARGE:
            self.scroll = max(0, self.scroll + (1 if e.angleDelta().y() > 0 else -1))
            self._dirty()
        e.accept()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        """Teclado LOCAL (so com o foco da Ilha; ela nunca rouba foco nem captura teclas globais): Enter = Sim e
        Esc = Nao durante a confirmacao; Tab/Shift+Tab percorrem os botoes (anel de foco), Espaco/Enter acionam."""
        k = e.key()
        vis = [b for b in self.btns if b.visible and b.key != "talk"]
        if k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and vis:
            cur = vis.index(self._focus_btn) if self._focus_btn in vis else -1
            step = -1 if k == Qt.Key.Key_Backtab else 1
            self._focus_btn = vis[(cur + step) % len(vis)]
            for b in self.btns:
                b.focus = b is self._focus_btn
            self.update()
            self._sync_timers()
            e.accept()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._focus_btn is not None and self._focus_btn.visible:
                self._activate(self._focus_btn)
                e.accept()
                return
            if self.state is IslandState.CONFIRMING and k != Qt.Key.Key_Space:
                self._answer(True)
                e.accept()
                return
        if k == Qt.Key.Key_Escape and self.state is IslandState.CONFIRMING:
            self._answer(False)
            e.accept()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().focusOutEvent(e)
        self._focus_btn = None
        for b in self.btns:
            b.focus = False
        self.update()

    def _sync_a11y(self) -> None:
        line = self.confirm_text or self.error_text or self.transcript
        extra = f" {S.muted}." if self.muted else ""
        set_a11y(self, S.window_name, f"{self.label()}.{extra} {line}".strip())

    # ================================================================== pintura
    def _fractions(self, w: float, h: float) -> tuple[float, float, float]:
        u = _clamp01((w - T.CW) / (T.MW - T.CW))
        v = _clamp01((h - T.MH) / (T.LH - T.MH))
        return (1.0 - u) ** 2, u * (1.0 - v), v * v

    def _body(self, cw: float, ch: float, m: int) -> tuple[QRectF, float]:
        r = min(ch / 2.0, float(T.CORNER_MAX))
        if self._floating:
            return QRectF(m + 0.5, m + 0.5, cw - 1.0, ch - 1.0), r
        return QRectF(0.5, -r, cw - 1.0, ch + r - 0.5), r             # a parte de cima fica fora da janela

    def _render_chrome(self, w: int, h: int, cw: int, ch: int, dpr: float) -> QPixmap:
        """Sombra (so flutuante: camadas translucidas, uma vez por tamanho), fundo preto e borda sutil."""
        m = self._margin()
        pm = QPixmap(round(w * dpr), round(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body, r = self._body(cw, ch, m)
        p.setPen(Qt.PenStyle.NoPen)
        if self._floating:
            steps = 8
            for i in range(steps):
                grow = (steps - i) * 2.6
                a = T.SHADOW_ALPHA * 0.055 * (1.0 + i / steps)
                p.setBrush(QColor(0, 0, 0, min(255, round(a))))
                p.drawRoundedRect(body.adjusted(-grow, -grow + 5.0, grow, grow + 5.0), r + grow, r + grow)
        p.setPen(QPen(self._edge(), 1.0))
        p.setBrush(QColor(T.BG))
        p.drawRoundedRect(body, r, r)
        p.end()
        return pm

    @staticmethod
    def _edge() -> QColor:
        c = QColor(T.EDGE)
        c.setAlpha(T.EDGE_ALPHA)
        return c

    def paintEvent(self, _e) -> None:
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        cw, ch = self._cur
        iw, ih = round(cw), round(ch)
        m = self._margin()
        key = (w, h, iw, ih, dpr, self._floating)
        if self._chrome is None or self._chrome_key != key:
            self._chrome, self._chrome_key = self._render_chrome(w, h, iw, ih, dpr), key
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawPixmap(0, 0, self._chrome)
        body, r = self._body(iw, ih, m)
        clip = QPainterPath()
        clip.addRoundedRect(body, r, r)
        if self._morph is not None or self._pres_dir:       # no repouso nada passa do corpo: sem recorte (mais barato)
            p.setClipPath(clip)
        ox, oy = m, m
        fr = self._fractions(cw, ch)
        for size, a in zip((IslandSize.COMPACT, IslandSize.MEDIUM, IslandSize.LARGE), fr):
            if a > 0.01:
                self._draw_size(p, size, a, ox + iw / 2.0, oy, dpr)
        p.end()

    def _draw_size(self, p: QPainter, size: IslandSize, a: float, cx: float, top: float, dpr: float) -> None:
        nw, _nh = T.SIZES[size]
        s = 0.94 + 0.06 * a if a < 0.99 else 1.0
        p.save()
        p.translate(cx, top)
        if s != 1.0:
            p.scale(s, s)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(-nw / 2.0, 0)
        new = self._layer(size, dpr)
        old = self._old.get(size) if self._fade_p < 1.0 else None
        fp = self._fade_p
        if old is not None:
            p.setOpacity(a * (1.0 - fp))
            p.drawPixmap(QPointF(0, -2.0 * fp), old)
            p.setOpacity(a * fp)
            p.drawPixmap(QPointF(0, 3.0 * (1.0 - fp)), new)
        else:
            p.setOpacity(a)
            p.drawPixmap(0, 0, new)
        p.setOpacity(a)
        {IslandSize.COMPACT: R.dyn_compact, IslandSize.MEDIUM: R.dyn_medium, IslandSize.LARGE: R.dyn_large}[size](self, p, dpr)
        if size is IslandSize.LARGE:
            p.drawPixmap(0, 0, self._buttons_pixmap(dpr))
        p.restore()

    def _buttons_pixmap(self, dpr: float) -> QPixmap:
        """Botoes pintados numa camada cacheada: so e refeita quando algum botao muda (hover, pressao, foco, rotulo)."""
        key = (dpr, tuple((b.key, round(b.hover * 12), b.press, b.focus, b.fill, b.hk, b.label, b.glyph, b.x, b.w, b.variant,
                           b.enabled) for b in self.btns if b.visible))
        if self._btn_pm is None or self._btn_key != key:
            w, h = T.SIZES[IslandSize.LARGE]
            pm = self._btn_pm
            if pm is None or pm.devicePixelRatio() != dpr:
                pm = self._btn_pm = QPixmap(round(w * dpr), round(h * dpr))
                pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
            for b in self.btns:
                if b.visible:
                    R.paint_button(q, b, dpr)
            q.end()
            self._btn_key = key
        return self._btn_pm
