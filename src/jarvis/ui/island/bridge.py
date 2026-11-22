"""Camada fina entre o EventBus do nucleo (``core/events.py``) e a IslandWindow (contrato da fase I1).

O barramento entrega eventos em threads proprias; aqui eles cruzam para a thread da UI por um sinal
Qt (conexao em fila). O evento ``level`` (alta frequencia) NAO passa pela UI: so atualiza o
``LevelFeed``, que a janela le a cada quadro.

Eventos tratados: state, transcript, reply_text, action_step, confirm_request/confirm_done,
context_usage, yolo, mute, emergency, error. Para I1: passar ``tts_rms`` (ex.:
``lambda: speaker._last_rms``) e ``yolo_remaining`` (ex.: ``YOLO.remaining_s``), e ligar
``on_confirm_answer`` ao confirmador do nucleo.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
from PySide6.QtCore import QObject, Signal

from . import tokens as T
from .dsp import LevelSource
from .strings import S
from .tokens import IslandState
from .window import IslandWindow

_STATE = {"idle": IslandState.IDLE, "listening": IslandState.LISTENING, "transcribing": IslandState.TRANSCRIBING,
          "thinking": IslandState.THINKING, "acting": IslandState.ACTING, "speaking": IslandState.SPEAKING,
          "error": IslandState.ERROR}


class LevelFeed:
    """LevelSource alimentada por niveis escalares do nucleo (mic e TTS, 0..1).

    O nucleo so publica o RMS; o formato das barras vem de uma modulacao suave por banda (energia real,
    detalhe espectral aproximado). Para o TTS usa ``tts_rms`` (leitura direta do Speaker) quando houver.
    """

    def __init__(self, bands: int = T.BANDS, tts_rms: Callable[[], float] | None = None) -> None:
        self._n = bands
        self._mic = 0.0
        self._tts = 0.0
        self._tts_rms = tts_rms
        self._t = 0.0
        self._shape = np.linspace(1.0, 0.35, bands).astype(np.float32)   # graves mais fortes que agudos
        self._phase = (np.arange(bands) * 1.9).astype(np.float32)

    def on_level(self, source: str, rms: float) -> None:     # chamado em thread do barramento
        if source == "tts":
            self._tts = float(rms)
        else:
            self._mic = float(rms)

    def read(self, speaking: bool, dt: float) -> tuple[np.ndarray, float]:
        self._t += dt
        if speaking and self._tts_rms is not None:
            level = min(1.0, max(0.0, 20.0 * float(self._tts_rms())))   # RMS linear 0..1 -> escala visual
        else:
            level = self._tts if speaking else self._mic
        mod = 0.65 + 0.35 * np.sin(self._t * 9.0 + self._phase)
        bands = np.clip(level * self._shape * mod * 1.2, 0.0, 1.0).astype(np.float32)
        return bands, float(level)


class IslandBridge(QObject):
    _event = Signal(object)

    def __init__(self, window: IslandWindow, bus: Any, *, feed: "LevelSource | LevelFeed | None" = None,
                 yolo_remaining: Callable[[], float] | None = None,
                 on_confirm_answer: Callable[[str, bool], None] | None = None,
                 on_stop: Callable[[], None] | None = None, on_mute: Callable[[bool], None] | None = None) -> None:
        super().__init__(window)
        self._w = window
        self._feed = feed or LevelFeed()
        window.set_levels_source(self._feed)
        self._yolo_remaining = yolo_remaining
        self._on_confirm = on_confirm_answer
        self._event.connect(self._apply)
        window.confirm_answered.connect(self._answered)
        if on_stop:
            window.stop_requested.connect(on_stop)
        if on_mute:
            window.mute_toggled.connect(on_mute)
        self._unsub = bus.subscribe(self._on_bus)

    @property
    def feed(self) -> LevelFeed:
        return self._feed

    def close(self) -> None:
        self._unsub()

    def _on_bus(self, ev: Any) -> None:                       # thread do barramento
        if ev.kind == "level":
            if not hasattr(self._feed, "on_level"):
                return
            self._feed.on_level(str(ev.data.get("source", "mic")), float(ev.data.get("rms", 0.0)))
        else:
            self._event.emit(ev)                              # cruza para a thread da UI

    def _answered(self, yes: bool) -> None:
        if self._on_confirm:
            self._on_confirm(self._w.confirm_id, yes)

    def _apply(self, ev: Any) -> None:                        # thread da UI
        d, w = ev.data, self._w
        k = ev.kind
        if k == "state":
            st = _STATE.get(str(d.get("state")), IslandState.IDLE)
            if st is IslandState.LISTENING:
                w.set_transcript("")
                w.set_reply("")
            if w.state is IslandState.CONFIRMING and st is not IslandState.ERROR:
                return                                         # a confirmacao so termina por resposta/confirm_done
            w.set_state(st)
        elif k == "transcript":
            w.set_reply("")                                    # fala nova: some a resposta anterior (tambem no modo texto)
            w.set_transcript(str(d.get("text", "")))
        elif k == "reply_text":
            w.append_reply(str(d.get("text", "")))
        elif k == "action_step":
            w.set_action(str(d.get("tool", "")), str(d.get("text", "")), str(d.get("status", "")), str(d.get("result", "")))
        elif k == "confirm_request":
            w.ask_confirmation(str(d.get("text", "")), int(d.get("timeout_s") or T.CONFIRM_TIMEOUT_S), str(d.get("id", "")))
        elif k == "confirm_done":
            if w.state is IslandState.CONFIRMING:
                w.set_state(IslandState.THINKING)
        elif k == "context_usage":
            w.set_context_pct(float(d.get("pct", 0)))
        elif k == "yolo":
            remaining = d.get("remaining_s")                  # o nucleo (processo pai) manda os segundos restantes
            if remaining is None and d.get("on") and self._yolo_remaining:
                remaining = self._yolo_remaining()
            w.set_yolo(float(remaining) if d.get("on") and remaining is not None else (3600.0 if d.get("on") else None))
        elif k == "mode":
            w.set_permission_mode(str(d.get("mode", "")))
        elif k == "mute":
            w.set_mute(bool(d.get("muted")))
        elif k == "emergency":
            w.set_error(S.state_error + ": parada de emergência")
        elif k == "error":
            w.set_error(str(d.get("text", "")))


