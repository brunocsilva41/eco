"""Token de cancelamento cooperativo, com cadeia pai -> filho.

Cancelar o pai cancela todos os filhos. Usado para: tecla de emergência, "para tudo",
timeout de ferramenta e barge-in. Thread-safe.
"""
from __future__ import annotations

import threading


class Cancelled(Exception):
    """Levantada quando uma operação cooperativa percebe que foi cancelada."""

    def __init__(self, reason: str = "cancelado") -> None:
        super().__init__(reason)
        self.reason = reason


class CancelToken:
    def __init__(self, parent: "CancelToken | None" = None) -> None:
        self._event = threading.Event()
        self._reason = ""
        self._lock = threading.Lock()
        self._children: list[CancelToken] = []
        self._parent = parent
        if parent is not None:
            parent._add_child(self)

    def _add_child(self, child: "CancelToken") -> None:
        with self._lock:
            already = self._event.is_set()
            reason = self._reason
            if not already:
                self._children.append(child)
        if already:
            child.cancel(reason)

    def child(self) -> "CancelToken":
        return CancelToken(self)

    def cancel(self, reason: str = "cancelado") -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._reason = reason
            self._event.set()
            children, self._children = self._children, []
        for c in children:
            c.cancel(reason)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Cancelled(self._reason)

    def wait(self, timeout: float | None = None) -> bool:
        """Espera até cancelar ou estourar o tempo. True se foi cancelado."""
        return self._event.wait(timeout)

    def release(self) -> None:
        """Solta a ligação com o pai (evita acumular filhos de longa vida)."""
        parent = self._parent
        if parent is not None:
            with parent._lock:
                try:
                    parent._children.remove(self)
                except ValueError:
                    pass
