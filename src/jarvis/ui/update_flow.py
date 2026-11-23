"""Fluxo de atualização para a interface (sem desenho): verificação, download com progresso, instalação e escolhas do usuário.

`UpdateSession` é compartilhado pelo pop-up (processo da Ilha/bandeja) e pela página «Atualizações» das Configurações.
Tudo que é lento roda em thread; os resultados voltam por sinais Qt (entregues na thread da interface).
A lógica de segurança (HTTPS, SHA-256, instalação) vive em `core.updater`; aqui só se orquestra.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import updater, updates
from ..core.updates import UpdateInfo

log = logging.getLogger(__name__)

STARTUP_DELAY_MS = 20_000          # espera o Eco terminar de subir antes de consultar a rede
POLL_MS = 30 * 60 * 1000           # confere de 30 em 30 min se já passou o intervalo configurado


def _load_cfg():
    from .. import config as cfgmod
    return cfgmod.load()


class UpdateSession(QObject):
    """Estados: idle -> checking -> (uptodate | error | available) -> downloading -> ready -> installing."""

    checked = Signal(object, bool)          # (UpdateInfo, manual)
    progress = Signal(int, int)             # bytes, total
    ready = Signal(str)                     # caminho do instalador verificado
    failed = Signal(str)                    # mensagem pt-BR
    installing = Signal()
    state_changed = Signal(str)

    def __init__(self, parent: QObject | None = None, *, cfg_loader: Callable[[], object] | None = None,
                 quit_cb: Callable[[], object] | None = None, current_override: str | None = None,
                 target_dir: Path | None = None, relaunch: bool = True) -> None:
        super().__init__(parent)
        self._cfg_loader = cfg_loader or _load_cfg
        self._quit_cb = quit_cb
        self._current = current_override          # só testes: finge uma versão antiga
        self._target = target_dir
        self._relaunch = relaunch
        self.info: UpdateInfo | None = None
        self.exe: Path | None = None
        self.state = "idle"
        self._cancel = threading.Event()
        self._busy = False
        self.retry = False                         # install() recusado no UAC: botão vira «Tentar de novo»

    # ------------------------------------------------------------ util
    def cfg(self):
        return self._cfg_loader()

    def _set(self, state: str) -> None:
        self.state = state
        self.state_changed.emit(state)

    def can_install(self) -> tuple[bool, str]:
        """(pode instalar automático?, motivo se não)."""
        try:
            root = self._target or updater.install_root()
        except Exception:  # noqa: BLE001
            root = None
        if root is None:
            return False, "Este Eco está rodando da pasta de desenvolvimento (não instalado): a atualização automática vale para a versão instalada."
        return True, ""

    # ------------------------------------------------------------ verificar
    def check(self, manual: bool = False) -> None:
        if self._busy:
            return
        self._busy = True
        self._set("checking")

        def work() -> None:
            try:
                cfg = self.cfg()
                info = updater.run_check(cfg, current=self._current)
            except Exception as exc:  # noqa: BLE001
                log.exception("verificação de atualização falhou")
                info = UpdateInfo(self._current or updates.current_version(), error=f"erro inesperado: {exc}")
            self._busy = False
            self.info = info
            self._set("error" if info.error else "available" if info.available else "uptodate")
            self.checked.emit(info, manual)

        threading.Thread(target=work, name="eco-update-check", daemon=True).start()

    # ------------------------------------------------------------ baixar / instalar
    def download(self, then_install: bool = False) -> None:
        info = self.info
        if info is None or not info.available or self._busy:
            return
        self._busy = True
        self._cancel.clear()
        self._set("downloading")

        def work() -> None:
            try:
                cfg = self.cfg()
                dest = Path(cfg.paths.data) / "updates" / "download"
                exe = updater.download(info, dest, lambda a, b: self.progress.emit(int(a), int(b)), self._cancel)
                self.exe = exe
                self._busy = False
                self._set("ready")
                self.ready.emit(str(exe))
                if then_install:
                    self.install()
            except updater.UpdateError as exc:
                self._busy = False
                self._set("available")
                self.failed.emit(str(exc))
            except Exception as exc:  # noqa: BLE001
                log.exception("download da atualização falhou")
                self._busy = False
                self._set("available")
                self.failed.emit(f"erro inesperado no download: {exc}")

        threading.Thread(target=work, name="eco-update-download", daemon=True).start()

    def cancel(self) -> None:
        self._cancel.set()

    def install(self) -> None:
        info, exe = self.info, self.exe
        if info is None or exe is None:
            return
        ok, why = self.can_install()
        if not ok:
            self.failed.emit(why)
            return
        self.retry = False
        try:
            cfg = self.cfg()
            self._set("installing")
            self.installing.emit()
            updater.install(exe, info, cfg.paths.data, quit_cb=self._quit_cb, target_dir=self._target,
                            relaunch=self._relaunch, wait_pids=(os.getpid(), os.getppid()))
        except updater.UacDeclined as exc:
            self.retry = True
            self._set("ready")
            self.failed.emit(str(exc))
        except updater.UpdateError as exc:
            self._set("ready")
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("instalação da atualização falhou")
            self._set("ready")
            self.failed.emit(f"erro inesperado: {exc}")

    # ------------------------------------------------------------ escolhas
    def ignore(self) -> None:
        if self.info and self.info.latest:
            updater.ignore_version(self.cfg().paths.data, self.info.latest)

    def remind_later(self, hours: float = 24.0) -> None:
        updater.snooze(self.cfg().paths.data, hours)


class UpdateScheduler(QObject):
    """Verificação ao iniciar e a cada N horas (configurável e desligável). Emite `notify(info)` só quando vale avisar."""

    notify = Signal(object)

    def __init__(self, session: UpdateSession, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._s = session
        self._startup_done = False
        session.checked.connect(self._on_checked)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        QTimer.singleShot(STARTUP_DELAY_MS, self._startup)
        self._timer.start()

    def _startup(self) -> None:
        self._startup_done = True
        self._maybe(startup=True)

    def _tick(self) -> None:
        if self._startup_done:
            self._maybe(startup=False)

    def _maybe(self, *, startup: bool) -> None:
        try:
            cfg = self._s.cfg()
            st = updater.load_state(cfg.paths.data)
            if updater.should_check_now(cfg, st, startup=startup):
                self._s.check(manual=False)
        except Exception:  # noqa: BLE001
            log.exception("agenda de atualizações falhou")

    def _on_checked(self, info: UpdateInfo, manual: bool) -> None:
        if manual:
            return
        try:
            st = updater.load_state(self._s.cfg().paths.data)
            if updater.should_notify(info, st):
                self.notify.emit(info)
        except Exception:  # noqa: BLE001
            log.exception("decisão de aviso de atualização falhou")
