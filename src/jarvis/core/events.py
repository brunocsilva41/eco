"""Barramento de eventos interno (publicar/assinar), thread-safe e à prova de assinante lento ou ruim.

Os eventos são o contrato com a futura "Ilha" (ILHA-SPEC §2): state, transcript, reply_text, action_step,
confirm_request, level. Cada assinante tem a SUA fila e a SUA thread de despacho: `publish` nunca bloqueia
(as threads de áudio e de atalhos não podem esperar a interface). Um assinante com defeito não derruba os outros.
Eventos `level` repetidos são fundidos (só o mais recente importa); se a fila encher, descarta-se o mais antigo.
"""
from __future__ import annotations

import collections
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

log = logging.getLogger(__name__)

QUEUE_LIMIT = 512
_COALESCE = frozenset({"level"})


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
    kind: str                      # "state" | "transcript" | "reply_text" | "action_step" | "confirm_request" | "level" | "error" ...
    data: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Event], None]


class _Subscriber:
    def __init__(self, handler: Handler, kind: str | None) -> None:
        self.handler = handler
        self.kind = kind
        self._q: "collections.deque[Event]" = collections.deque()
        self._cv = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="events-" + getattr(handler, "__name__", "sub"), daemon=True)
        self._thread.start()

    def push(self, ev: Event) -> None:
        with self._cv:
            if self._closed:
                return
            if ev.kind in _COALESCE and self._q and self._q[-1].kind == ev.kind \
                    and self._q[-1].data.get("source") == ev.data.get("source"):
                self._q[-1] = ev                         # funde: só o último nível interessa
            else:
                if len(self._q) >= QUEUE_LIMIT:
                    dropped = self._q.popleft()
                    log.warning("assinante lento: evento '%s' descartado", dropped.kind)
                self._q.append(ev)
            self._cv.notify()

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join(1.0)

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._q and not self._closed:
                    self._cv.wait()
                if self._closed and not self._q:
                    return
                ev = self._q.popleft()
            try:
                self.handler(ev)
            except Exception:  # noqa: BLE001 - assinante com defeito não pode quebrar o núcleo
                log.exception("assinante de evento falhou (kind=%s)", ev.kind)


class EventBus:
    """Contrato de threads: `publish`/`subscribe` de qualquer thread; handlers rodam na thread própria de cada assinante."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[_Subscriber] = []

    def subscribe(self, handler: Handler, kind: str | None = None) -> Callable[[], None]:
        """Assina eventos (todos, ou só de um `kind`). Devolve função que cancela a assinatura."""
        sub = _Subscriber(handler, kind)
        with self._lock:
            self._subs.append(sub)

        def unsubscribe() -> None:
            with self._lock:
                if sub in self._subs:
                    self._subs.remove(sub)
            sub.close()

        return unsubscribe

    def publish(self, kind: str, **data: Any) -> None:
        ev = Event(kind, data)
        with self._lock:
            targets = [s for s in self._subs if s.kind is None or s.kind == kind]
        for s in targets:
            s.push(ev)

    def close(self) -> None:
        """Encerra as threads de despacho (no desligamento do app)."""
        with self._lock:
            subs, self._subs = self._subs, []
        for s in subs:
            s.close()
