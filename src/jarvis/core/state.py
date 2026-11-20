"""Máquina de estados do Jarvis: IDLE -> LISTENING -> TRANSCRIBING -> THINKING/ACTING -> SPEAKING -> IDLE.

Transições inválidas são recusadas (retornam False e são logadas) em vez de corromper o fluxo.
Qualquer estado pode ir para IDLE (cancelamento) ou ERROR. Publica o evento `state` no barramento.
"""
from __future__ import annotations

import logging
import threading

from .events import EventBus, State

log = logging.getLogger(__name__)

_ALLOWED: dict[State, frozenset[State]] = {
    State.IDLE: frozenset({State.LISTENING, State.THINKING, State.SPEAKING}),       # THINKING: entrada por texto; SPEAKING: say()
    State.LISTENING: frozenset({State.TRANSCRIBING, State.IDLE}),
    State.TRANSCRIBING: frozenset({State.THINKING, State.IDLE}),
    State.THINKING: frozenset({State.ACTING, State.SPEAKING, State.IDLE}),
    State.ACTING: frozenset({State.THINKING, State.SPEAKING, State.IDLE}),
    State.SPEAKING: frozenset({State.LISTENING, State.THINKING, State.IDLE}),      # LISTENING: barge-in futuro
    State.ERROR: frozenset({State.IDLE}),
}
_ALWAYS = frozenset({State.IDLE, State.ERROR})


class StateMachine:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._state = State.IDLE
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        return self._state

    def go(self, new: State, **info: object) -> bool:
        with self._lock:
            old = self._state
            if new == old:
                return True
            if new not in _ALLOWED[old] and new not in _ALWAYS:
                log.warning("transição recusada: %s -> %s", old.value, new.value)
                return False
            self._state = new
        log.debug("estado: %s -> %s", old.value, new.value)
        self._bus.publish("state", state=new.value, previous=old.value, **info)
        return True

    def reset(self) -> None:
        self.go(State.IDLE)
