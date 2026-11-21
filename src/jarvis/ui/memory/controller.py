"""Controlador-base do painel: dono da conexão, do trabalho em segundo plano e dos avisos.

Regras: todo acesso ao banco passa por ``submit`` (``ui.kit.tasks.run_async``), então a interface nunca trava. O banco
só abre se o histórico estiver ligado (modo sem histórico: ``Memory`` nem é criado). Erros viram ``ErrorReport`` em
português (o que houve, por que importa, o que fazer); o detalhe técnico vai para o log. A conexão fecha em ``close()``.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog, QWidget

from ...config import Config
from ...memory import Memory, MemoryError_
from ..kit.tasks import run_async
from .logic import FriendlyError, default_save_dir, friendly_error, with_suffix_default
from .service import DB_NAME, ConnectionHolder, open_database
from .texts import tr

log = logging.getLogger(__name__)

R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class ErrorReport:
    error: FriendlyError
    retry: Callable[[], None] | None


class PanelController(QObject):
    """Estado compartilhado das três áreas. Sinais: ``stateChanged`` (abriu ou fechou), ``busyChanged``,
    ``failed(ErrorReport)``, ``notice(estado, título, detalhe)`` e ``dataChanged`` (uma escrita terminou)."""

    stateChanged = Signal()
    busyChanged = Signal(bool)
    failed = Signal(object)
    notice = Signal(str, str, str)
    dataChanged = Signal()

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.persistent: bool = bool(cfg.memory.enabled)
        self.db_path: Path = Path(cfg.paths.data) / DB_NAME
        self.trash_days: int = int(cfg.memory.trash_days)
        self.holder = ConnectionHolder()
        self.destroyed.connect(self.holder.close)
        self._opening = False
        self._pending = 0

    # --- estado
    @property
    def opening(self) -> bool:
        return self._opening

    @property
    def can_read(self) -> bool:
        return self.persistent and self.holder.memory is not None

    @property
    def editable(self) -> bool:
        return self.can_read

    def memory(self) -> Memory | None:
        """O ``Memory`` aberto (None enquanto abre, no modo sem histórico ou depois de fechar)."""
        return self.holder.memory

    # --- abrir e fechar
    def open(self) -> None:
        """Abre o banco em segundo plano (nunca no modo sem histórico). Emite ``stateChanged`` ao terminar."""
        if not self.persistent or self._opening or self.holder.memory is not None:
            return
        self._opening = True
        holder, path, mcfg = self.holder, self.db_path, self.cfg.memory

        def done(persistent: object) -> None:
            self._opening = False
            if not persistent:
                self.persistent = False
            self.stateChanged.emit()

        def fail(message: str) -> None:
            self._opening = False
            log.warning("painel de memória não abriu o banco: %s", message)
            self.report(message, self.open, what=tr().errors.open_what, todo=tr().errors.open_todo)
            self.stateChanged.emit()

        run_async(lambda: open_database(holder, path, mcfg), self, done, fail)

    def close(self) -> None:
        """Fecha a conexão (idempotente)."""
        self.holder.close()
        self.stateChanged.emit()

    # --- trabalho em segundo plano
    def submit(self, fn: Callable[[Memory], R], done: Callable[[R], None], retry: Callable[[], None] | None = None,
               on_error: Callable[[FriendlyError], None] | None = None) -> None:
        """Roda ``fn(memory)`` numa thread; ``done`` roda na interface. Falha: ``on_error`` (a tela mostra o erro no
        lugar do conteúdo) ou, sem ele, o aviso do painel; banco ocupado oferece 'Tentar de novo'."""
        holder = self.holder

        def job() -> R:
            mem = holder.memory
            if mem is None:
                raise MemoryError_(tr().errors.closed_what)
            return fn(mem)

        self.submit_plain(job, done, retry, on_error)

    def submit_plain(self, job: Callable[[], R], done: Callable[[R], None], retry: Callable[[], None] | None = None,
                     on_error: Callable[[FriendlyError], None] | None = None) -> None:
        """Como ``submit``, para trabalho que não precisa do banco (ex.: medir o arquivo)."""
        self._set_pending(+1)

        def ok(result: object) -> None:
            self._set_pending(-1)
            try:
                done(result)                                          # type: ignore[arg-type]
            except Exception:  # noqa: BLE001 - erro de apresentação não derruba a tela
                log.exception("falha ao mostrar o resultado no painel de memória")
                self.report("", None, what=tr().errors.show_what)

        def fail(message: str) -> None:
            self._set_pending(-1)
            if on_error is not None:
                log.warning("painel de memória: %s", message)
                on_error(friendly_error(message, what=tr().errors.load_what))
                return
            again = retry
            if again is None and friendly_error(message).busy:
                again = lambda: self.submit_plain(job, done, None)    # noqa: E731
            self.report(message, again)

        run_async(job, self, ok, fail)

    def _set_pending(self, delta: int) -> None:
        before = self._pending > 0
        self._pending = max(0, self._pending + delta)
        if (self._pending > 0) != before:
            self.busyChanged.emit(self._pending > 0)

    # --- avisos
    def report(self, message: str, retry: Callable[[], None] | None, *, what: str = "", todo: str = "") -> None:
        err = friendly_error(message, what=what)
        if todo and not err.busy:
            err = FriendlyError(err.what, err.why, todo, False)
        log.warning("painel de memória: %s", message)
        self.failed.emit(ErrorReport(err, retry))

    def notify(self, state: str, title: str, detail: str = "") -> None:
        self.notice.emit(state, title, detail)

    def changed(self, title: str, detail: str = "") -> None:
        """Depois de uma escrita: avisa e pede que as áreas recarreguem."""
        self.notice.emit("ok", title, detail)
        self.dataChanged.emit()


def choose_save_path(parent: QWidget, title: str, default_name: str, filters: str, suffixes: tuple[str, ...],
                     default_suffix: str) -> Path | None:
    """Janela 'Salvar como' do Windows; devolve o caminho com a extensão padrão ou ``None`` se cancelou."""
    chosen, _flt = QFileDialog.getSaveFileName(parent, title, str(default_save_dir() / default_name), filters)
    return with_suffix_default(chosen, suffixes, default_suffix) if chosen else None
