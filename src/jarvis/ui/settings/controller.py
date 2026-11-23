"""Controlador das Configuracoes: liga o modelo ao ``SettingsStore`` e ao canal de controle do Eco.

Responsabilidades: validacao ao vivo com debounce, salvar, descartar, restaurar o padrao, aplicar agora e
reiniciar (``settings.control``), e detectar que o config.toml mudou em disco. Tudo que toca disco ou pode
demorar roda fora da thread da interface (``ui.kit.tasks.run_async``) e volta por sinais tipados. Nenhum
widget e criado aqui. ``shutdown()`` para os timers e faz resultados atrasados serem ignorados.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Final

from PySide6.QtCore import QObject, QTimer, Signal

from jarvis.config import Config, ConfigError
from jarvis.settings import control, schema
from jarvis.settings.control import Runtime
from jarvis.settings.store import Problem, SaveResult, SettingsError, SettingsStore

from ..kit.tasks import run_async
from .categories import category_of
from .model import FormModel, SaveOutcome

log = logging.getLogger(__name__)

VALIDATE_DELAY_MS: Final = 250
DISK_POLL_MS: Final = 2000


@dataclass
class Attempt:
    """Resultado de uma operacao de disco, sem excecao: ``run_async`` so devolve texto de erro, e a tela precisa do tipo."""
    value: Any = None
    problems: list[Problem] = field(default_factory=list)
    config_error: str = ""
    os_error: OSError | None = None
    other: str = ""

    @property
    def ok(self) -> bool:
        return not (self.problems or self.config_error or self.os_error or self.other)


def attempt(fn: Callable[[], Any]) -> Attempt:
    try:
        return Attempt(value=fn())
    except SettingsError as exc:
        return Attempt(problems=list(exc.problems))
    except ConfigError as exc:
        return Attempt(config_error=str(exc))
    except OSError as exc:
        log.error("falha de disco nas configuracoes: %s", exc)
        return Attempt(os_error=exc)
    except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem para a pessoa e fica no log
        log.exception("falha inesperada nas configuracoes")
        return Attempt(other=str(exc) or exc.__class__.__name__)


class SettingsController(QObject):
    stateChanged = Signal()               # alteracoes ou erros mudaram (barra e navegacao se atualizam)
    valuesReplaced = Signal()             # o modelo trocou TODOS os valores (carga, descartar, restaurar, recarregar)
    saveBlocked = Signal()                # tentou salvar com erros
    saved = Signal(object)                # SaveOutcome
    writeFailed = Signal(str, str)        # tipo ("permission", "disk", "other"), detalhe
    loadFailed = Signal(str)              # config.toml ilegivel ao abrir
    reloadFailed = Signal(str)            # config.toml ilegivel ao recarregar do disco
    diskChanged = Signal(bool)            # o arquivo mudou em disco (True) ou o aviso deixou de valer (False)
    runtimeChanged = Signal(object)       # Runtime | None
    requestDone = Signal(str, bool, str)  # "reload"/"restart", deu certo, detalhe do erro
    busyChanged = Signal(bool)

    def __init__(self, store: SettingsStore | None = None, cfg: Config | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store or SettingsStore()
        self._load_error = ""
        if cfg is None:
            try:
                cfg = self.store.load()
            except ConfigError as exc:
                log.warning("config.toml com erro; a tela abre com os padroes: %s", exc)
                self._load_error = str(exc)
                cfg = self.store.defaults()
        self.cfg: Config = cfg
        self.model = FormModel(schema.current_values(cfg))
        self.model.force_dirty = bool(self._load_error)
        self._busy = False
        self._closed = False
        self._seq = 0
        self._disk_mtime = control.config_mtime(self.store.path)
        self._dismissed_mtime: float | None = None
        self._announced_mtime: float | None = None
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(VALIDATE_DELAY_MS)
        self._validate_timer.timeout.connect(self._validate_now)
        self._disk_timer = QTimer(self)
        self._disk_timer.setInterval(DISK_POLL_MS)
        self._disk_timer.timeout.connect(self._check_disk)

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        """Chame depois de conectar os sinais: avisa erro de leitura, valida e passa a vigiar o disco."""
        if self._load_error:
            self.loadFailed.emit(self._load_error)
        self._validate_now()
        self._disk_timer.start()
        self.refresh_runtime()

    def shutdown(self) -> None:
        self._closed = True
        self._seq += 1
        self._validate_timer.stop()
        self._disk_timer.stop()

    @property
    def busy(self) -> bool:
        return self._busy

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busyChanged.emit(busy)

    # ------------------------------------------------------------------ valores
    def collect_values(self) -> dict[str, Any]:
        return self.model.snapshot()

    def apply_values(self, values: dict[str, Any]) -> None:
        """Preenche o formulario; o que diferir do gravado aparece como alterado."""
        self.model.update(values)
        self.valuesReplaced.emit()
        self.stateChanged.emit()
        self._validate_timer.start()

    def edit(self, key: str, value: Any) -> None:
        if self._busy:
            return
        self.model.set(key, value)
        self.stateChanged.emit()
        self._validate_timer.start()

    def page_counts(self) -> dict[str, tuple[int, int]]:
        """{pagina: (erros, alteracoes)} para os contadores da navegacao."""
        counts: dict[str, list[int]] = {}
        for key in self.model.errors:
            counts.setdefault(category_of(schema.BY_KEY[key]), [0, 0])[0] += 1
        for key in self.model.changed_keys():
            counts.setdefault(category_of(schema.BY_KEY[key]), [0, 0])[1] += 1
        return {page: (e, c) for page, (e, c) in counts.items()}

    # ------------------------------------------------------------------ validacao ao vivo
    def _validate_now(self) -> None:
        if self._closed:
            return
        self._seq += 1
        seq, values = self._seq, self.model.snapshot()
        run_async(lambda: self.store.validate(values), self,
                  lambda problems, s=seq: self._on_validated(s, problems), self._on_task_failed)

    def _on_validated(self, seq: int, problems: list[Problem]) -> None:
        if seq != self._seq or self._closed:
            return
        self.model.set_problems(problems)
        self.stateChanged.emit()

    @staticmethod
    def _on_task_failed(message: str) -> None:
        log.warning("tarefa de configuracoes falhou: %s", message)

    # ------------------------------------------------------------------ salvar, restaurar, descartar
    def save(self) -> None:
        if self._busy or not self.model.has_pending():
            return
        if self.model.error_count():
            self.saveBlocked.emit()
            return
        values = self.model.snapshot()
        self._write(lambda: self.store.save(values), reset=False)

    def reset_defaults(self) -> None:
        if not self._busy:
            self._write(self.store.reset_defaults, reset=True)

    def discard(self) -> None:
        self.model.revert()
        self.valuesReplaced.emit()
        self.stateChanged.emit()
        self._validate_timer.start()

    def _write(self, fn: Callable[[], SaveResult], *, reset: bool) -> None:
        self._set_busy(True)
        run_async(lambda: attempt(fn), self, lambda a: self._after_write(a, reset), self._write_crashed)

    def _write_crashed(self, message: str) -> None:
        self._set_busy(False)
        self.writeFailed.emit("other", message)

    def _after_write(self, att: Attempt, reset: bool) -> None:
        self._set_busy(False)
        if self._closed:
            return
        if att.problems:
            self.model.set_problems(att.problems)
            self.stateChanged.emit()
            self.saveBlocked.emit()
            return
        if att.os_error is not None:
            kind = "permission" if isinstance(att.os_error, PermissionError) else "disk"
            self.writeFailed.emit(kind, att.os_error.strerror or str(att.os_error))
            return
        if not att.ok:
            self.writeFailed.emit("other", att.config_error or att.other)
            return
        result: SaveResult = att.value
        self._adopt(result.config)
        self.valuesReplaced.emit()
        self.stateChanged.emit()
        self._publish(result, reset)

    def _adopt(self, cfg: Config) -> None:
        """A configuracao gravada passa a ser a base (original e atual) e o aviso de disco some."""
        self.cfg = cfg
        self.model.load(schema.current_values(cfg))
        self._disk_mtime = control.config_mtime(self.store.path)
        self._dismissed_mtime = self._announced_mtime = None
        self.diskChanged.emit(False)

    def _publish(self, result: SaveResult, reset: bool) -> None:
        """Le o estado do Eco e so entao anuncia o resultado (o banner precisa saber se ele esta aberto)."""
        data = self.cfg.paths.data

        def done(rt: Runtime | None) -> None:
            pending = rt.pending_restart if rt is not None else ()
            self.runtimeChanged.emit(rt)
            self.saved.emit(SaveOutcome(result, reset, rt is not None, pending))

        def failed(message: str) -> None:
            log.warning("nao consegui ler o estado do Eco: %s", message)
            self.saved.emit(SaveOutcome(result, reset, False, ()))

        run_async(lambda: control.read_runtime(data), self, done, failed)

    # ------------------------------------------------------------------ Eco em execucao
    def refresh_runtime(self) -> None:
        data = self.cfg.paths.data
        run_async(lambda: control.read_runtime(data), self, self.runtimeChanged.emit, self._on_task_failed)

    def request(self, kind: str) -> None:
        """Pede ao Eco em execucao para recarregar ("reload") ou reiniciar ("restart")."""
        try:
            control.request(self.cfg.paths.data, kind)
        except (OSError, ValueError) as exc:
            log.error("nao consegui pedir %s ao Eco: %s", kind, exc)
            self.requestDone.emit(kind, False, str(exc))
            return
        log.info("pedido de %s enviado ao Eco", kind)
        self.requestDone.emit(kind, True, "")

    # ------------------------------------------------------------------ config.toml mudou em disco
    def _check_disk(self) -> None:
        if self._busy or self._closed:
            return
        mtime = control.config_mtime(self.store.path)
        if mtime in (self._disk_mtime, self._dismissed_mtime, self._announced_mtime):
            return
        self._announced_mtime = mtime
        log.info("config.toml mudou em disco")
        self.diskChanged.emit(True)

    def reload_from_disk(self) -> None:
        run_async(lambda: attempt(self.store.load), self, self._after_reload, self._on_task_failed)

    def _after_reload(self, att: Attempt) -> None:
        if self._closed:
            return
        if att.ok:
            self._adopt(att.value)
            self.valuesReplaced.emit()
            self.stateChanged.emit()
            self._validate_timer.start()
            return
        detail = att.config_error or att.other or (att.os_error.strerror if att.os_error else "") or "erro desconhecido"
        self._dismissed_mtime = control.config_mtime(self.store.path)
        self.diskChanged.emit(False)
        self.reloadFailed.emit(detail)

    def keep_mine(self) -> None:
        self._dismissed_mtime = control.config_mtime(self.store.path)
        self.diskChanged.emit(False)
