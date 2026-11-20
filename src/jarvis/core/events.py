"""Barramento de eventos interno (publicar/assinar), thread-safe e à prova de assinante ruim.

Os eventos são o contrato com a futura "Ilha" (ILHA-SPEC §2): state, transcript, reply_text,
action_step, confirm_request, level. Um assinante que levanta exceção não derruba os demais.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

log = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    ACTING = "acting"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    kind: str                      # "state" | "transcript" | "reply_text" | "action_step" | "confirm_request" | "level" | "error"
    data: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[tuple[str | None, Handler]] = []

    def subscribe(self, handler: Handler, kind: str | None = None) -> Callable[[], None]:
        """Assina eventos (todos, ou só de um `kind`). Devolve função que cancela a assinatura."""
        item = (kind, handler)
        with self._lock:
            self._subs.append(item)

        def unsubscribe() -> None:
            with self._lock:
                if item in self._subs:
                    self._subs.remove(item)

        return unsubscribe

    def publish(self, kind: str, **data: Any) -> None:
        ev = Event(kind, data)
        with self._lock:
            targets = [h for k, h in self._subs if k is None or k == kind]
        for h in targets:
            try:
                h(ev)
            except Exception:  # um assinante com defeito nunca pode quebrar o núcleo
                log.exception("assinante de evento falhou (kind=%s)", kind)
