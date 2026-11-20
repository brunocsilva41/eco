"""Estado do Jarvis em DUAS camadas, porque voz e agente rodam em threads diferentes:

- estado do agente: IDLE -> LISTENING -> TRANSCRIBING -> THINKING <-> ACTING -> IDLE (ou ERROR);
- fala: um indicador `speaking` independente (a voz fala enquanto o agente ainda pensa/age).

O estado PUBLICADO (evento `state`) é a combinação: ACTING e ERROR/LISTENING/TRANSCRIBING mandam; senão SPEAKING se
estiver falando; senão o estado do agente. Assim a Ilha nunca mostra "falando" enquanto o PC é controlado, e nunca fica
presa em "falando" depois que a voz termina. Transições inválidas do agente são recusadas (retornam False e são logadas).
"""
from __future__ import annotations

import logging
import threading

from .events import EventBus, State

log = logging.getLogger(__name__)

_ALLOWED: dict[State, frozenset[State]] = {
    State.IDLE: frozenset({State.LISTENING, State.THINKING}),                       # THINKING: entrada por texto
    State.LISTENING: frozenset({State.TRANSCRIBING}),
    State.TRANSCRIBING: frozenset({State.THINKING}),
    State.THINKING: frozenset({State.ACTING}),
    State.ACTING: frozenset({State.THINKING}),
    State.ERROR: frozenset(),
}
_ALWAYS = frozenset({State.IDLE, State.ERROR})                                      # cancelamento/falha: de qualquer estado
_AGENT_STATES = frozenset({State.IDLE, State.LISTENING, State.TRANSCRIBING, State.THINKING, State.ACTING, State.ERROR})


class StateMachine:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._agent = State.IDLE
        self._speaking = False
        self._published = State.IDLE
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        """Estado combinado (o que a interface mostra)."""
        return self._published

    @property
    def agent_state(self) -> State:
        return self._agent

    @property
    def speaking(self) -> bool:
        return self._speaking

    def go(self, new: State, **info: object) -> bool:
        """Muda o estado do agente. `State.SPEAKING` é aceito por compatibilidade e equivale a set_speaking(True)."""
        if new == State.SPEAKING:
            self.set_speaking(True)
            return True
        with self._lock:
            old = self._agent
            if new == old:
                return True
            if new not in _ALLOWED[old] and new not in _ALWAYS:
                log.warning("transição recusada: %s -> %s", old.value, new.value)
                return False
            self._agent = new
            event = self._recompute(info)
        if event:
            self._bus.publish("state", **event)
        return True

    def set_speaking(self, speaking: bool) -> None:
        with self._lock:
            if self._speaking == speaking:
                return
            self._speaking = speaking
            event = self._recompute({})
        if event:
            self._bus.publish("state", **event)

    def reset(self) -> None:
        """Volta ao repouso (cancelamento): agente IDLE; a fala é regida pela própria voz."""
        self.go(State.IDLE)

    # ------------------------------------------------------------- interno
    def _combined(self) -> State:
        a = self._agent
        if a in (State.ACTING, State.ERROR, State.LISTENING, State.TRANSCRIBING):
            return a
        if self._speaking:
            return State.SPEAKING
        return a

    def _recompute(self, info: dict[str, object]) -> dict[str, object] | None:
        """Chamar com o lock. Devolve os dados do evento se o estado combinado mudou."""
        new = self._combined()
        old = self._published
        if new == old:
            return None
        self._published = new
        log.debug("estado: %s -> %s (agente=%s, falando=%s)", old.value, new.value, self._agent.value, self._speaking)
        return {"state": new.value, "previous": old.value, "agent": self._agent.value, "speaking": self._speaking, **info}
