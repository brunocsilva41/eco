"""Trabalho em segundo plano para a interface: `run_async(fn, owner, on_done, on_fail)`.

Roda `fn` numa thread do pool e entrega o resultado NA THREAD DA INTERFACE, só se `owner` ainda existir (sem callback
em widget destruído). Qualquer exceção vira uma mensagem de texto para o usuário e fica no log com o detalhe técnico.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

try:  # shiboken sempre acompanha o PySide6
    from shiboken6 import isValid as _is_valid
except ImportError:  # pragma: no cover
    def _is_valid(obj: object) -> bool:
        return True

log = logging.getLogger(__name__)


class _TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            try:
                result = self.fn()
            except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem para o usuário
                log.exception("tarefa em segundo plano falhou")
                self.signals.failed.emit(str(exc) or exc.__class__.__name__)
                return
            self.signals.finished.emit(result)
        except RuntimeError:                      # aplicativo já encerrando: ninguém mais espera o resultado
            log.debug("resultado descartado: a interface já foi destruída")


class _Receiver(QObject):
    """Vive na thread da interface: recebe o resultado (conexão enfileirada) e chama os callbacks se o dono ainda existe."""
    _alive: set["_Receiver"] = set()

    def __init__(self, task: _Task, owner: QObject, on_done: Callable[[Any], None], on_fail: Callable[[str], None]) -> None:
        super().__init__()
        self._task, self._owner, self._on_done, self._on_fail = task, owner, on_done, on_fail
        _Receiver._alive.add(self)
        task.signals.finished.connect(self._done)
        task.signals.failed.connect(self._failed)

    def _release(self) -> None:
        _Receiver._alive.discard(self)

    def _done(self, result: object) -> None:
        try:
            if _is_valid(self._owner):
                self._on_done(result)
        finally:
            self._release()

    def _failed(self, message: str) -> None:
        try:
            if _is_valid(self._owner):
                self._on_fail(message)
        finally:
            self._release()


def run_async(fn: Callable[[], Any], owner: QObject, on_done: Callable[[Any], None], on_fail: Callable[[str], None]) -> None:
    """Roda ``fn`` numa thread do pool e entrega o resultado na thread da interface (só se ``owner`` ainda existir)."""
    task = _Task(fn)
    _Receiver(task, owner, on_done, on_fail)
    QThreadPool.globalInstance().start(task)
