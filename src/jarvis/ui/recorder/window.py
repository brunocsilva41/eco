"""Janela do gravador ("Minha voz"): monta vista e controlador, roteia o teclado e lembra posicao e tamanho."""
from __future__ import annotations

import logging

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QVBoxLayout, QWidget

from ...config import Config
from .controller import RecorderController
from .model import check_set_name
from .services import Services
from .texts import T
from .view import RecorderView

log = logging.getLogger(__name__)

MIN_SIZE = (900, 620)          # menor tamanho sem corte (pedido do dono, DESIGN.md)
DEFAULT_SIZE = (1080, 720)
_SETTINGS_ORG, _SETTINGS_APP, _GEOMETRY_KEY = "Jarvis", "Gravador", "geometry"


class RecorderWindow(QWidget):
    """Janela de topo. ``set_name``: "frases" ou "jarvis" (``ValueError`` se for outro).

    Teclado: Espaco grava/para, Enter proxima, Esc cancela a gravacao ou fecha, setas navegam, O/R/P ouvem,
    regravam e pulam. Espaco e Enter agem no botao focado (Tab) e, sem botao focado, na acao da tela.
    """

    closed = Signal()

    def __init__(self, cfg: Config, parent: QWidget | None = None, set_name: str = "frases", *,
                 services: Services | None = None, settings: QSettings | None = None) -> None:
        check_set_name(set_name)
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle(T.window.title)
        self.setMinimumSize(*MIN_SIZE)
        self._settings = settings or QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        if not self._restore_geometry():
            self.resize(*DEFAULT_SIZE)
        self._view = RecorderView()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._view)
        self._controller = RecorderController(cfg, self._view, self, services)
        self._build_keys()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus(Qt.FocusReason.OtherFocusReason)       # nenhum controle mostra anel de foco ao abrir
        self._controller.start(set_name)

    # --- API publica
    @property
    def is_recording(self) -> bool:
        return self._controller.is_recording

    def show_set(self, set_name: str) -> bool:
        """Troca para "frases" ou "jarvis". False se nao der agora (gravando); ``ValueError`` se o nome for invalido."""
        check_set_name(set_name)
        if set_name == self._view.current_set():
            return True
        return self._controller.load_set(set_name)

    # --- teclado
    def _build_keys(self) -> None:
        for keys, slot in (("Space", self._on_space), ("Return", self._on_enter), ("Enter", self._on_enter),
                           ("Escape", self._on_escape)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(slot)

    def _acting_on_focus(self) -> bool:
        """Se um botao (ou seletor) tem o foco, a tecla age nele e nao na acao da tela. True se tratou."""
        focus = QApplication.focusWidget()
        if isinstance(focus, QAbstractButton):
            if focus.isEnabled():
                focus.click()
            return True
        if isinstance(focus, QComboBox):
            focus.showPopup()
            return True
        return False

    def _on_space(self) -> None:
        if not self._acting_on_focus():
            self._view.actions.record.click()

    def _on_enter(self) -> None:
        if not self._acting_on_focus():
            self._view.actions.next.click()

    def _on_escape(self) -> None:
        if self._controller.is_recording:
            self._controller.cancel_recording()
        else:
            self.close()

    # --- geometria lembrada
    def _restore_geometry(self) -> bool:
        data = self._settings.value(_GEOMETRY_KEY)
        return bool(data) and self.restoreGeometry(data)

    # --- ciclo de vida
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._controller.confirm_close():
            event.ignore()
            return
        self._controller.shutdown()
        self._settings.setValue(_GEOMETRY_KEY, self.saveGeometry())
        self._settings.sync()
        self.closed.emit()
        log.info("janela do gravador fechada")
        event.accept()

