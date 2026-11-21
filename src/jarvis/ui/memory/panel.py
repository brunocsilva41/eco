"""MemoryPanel: a casca do painel "O que o Jarvis sabe de mim" (faixa de áreas + as três áreas + avisos).

Uso (API pública estável)::

    panel = MemoryPanel(cfg, parent=None)      # QWidget; abre o banco sozinho, em segundo plano
    panel.memory()                              # Memory aberto, ou None (abrindo, sem histórico ou fechado)
    panel.close_memory()                        # fecha a conexão (idempotente); também ao fechar/destruir o painel

Embutido (nas Configurações) o título some; como janela própria ele aparece (decidido no ``showEvent``).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ...config import Config
from ...memory import Memory
from ..kit import Button, Label, Toast
from ..kit.base import set_a11y, strs
from ..theme import MOTION, SPACE
from .areabar import AreaBar
from .banners import BannerSlot
from .controller import ErrorReport, PanelController
from .conversations_area import ConversationsArea
from .conversations_ctl import ConversationsController
from .memories_area import MemoriesArea
from .memories_ctl import MemoriesController
from .storage_area import StorageArea
from .storage_ctl import StorageController
from .texts import tr

log = logging.getLogger(__name__)
_MEMORIES, _CONVERSATIONS, _STORAGE = 0, 1, 2


class MemoryPanel(QWidget):
    """Painel completo. Todo acesso ao banco roda fora da thread da interface e a conexão fecha com o painel."""

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        h = tr().header
        self.cfg = cfg
        set_a11y(self, h.panel_name, h.panel_desc)
        self._ctl = PanelController(cfg, self)

        self._title = Label(h.title, "title")
        self._subtitle = Label(h.subtitle, "help", wrap=True)
        self._head = QWidget()
        head = QVBoxLayout(self._head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(SPACE.xs)
        head.addWidget(self._title)
        head.addWidget(self._subtitle)
        self._fixed = BannerSlot()          # aviso fixo do modo sem histórico
        self._alerts = BannerSlot()         # erros com 'Tentar de novo'
        self._bar = AreaBar()
        self._bar.set_areas([h.tab_memories, h.tab_conversations, h.tab_storage])
        set_a11y(self._bar, h.areas_name)
        self._busy = Label(h.busy, "help")
        self._busy.setVisible(False)
        self._refresh_button = Button(h.refresh, icon_name="refresh", icon_only=True, variant="text", shortcut="F5")
        bar_row = QHBoxLayout()
        bar_row.setSpacing(SPACE.sm)
        bar_row.addWidget(self._bar, 1)               # a faixa vai até o fim: a linha de base cruza a largura toda
        bar_row.addWidget(self._busy)
        bar_row.addWidget(self._refresh_button)

        self.memories_area = MemoriesArea()
        self.conversations_area = ConversationsArea()
        self.storage_area = StorageArea()
        self._stack = QStackedWidget()
        for area in (self.memories_area, self.conversations_area, self.storage_area):
            self._stack.addWidget(area)
        self._controllers = (MemoriesController(self._ctl, self.memories_area, self),
                             ConversationsController(self._ctl, self.conversations_area, self),
                             StorageController(self._ctl, self.storage_area, self))
        self._dirty: set[int] = {_MEMORIES, _CONVERSATIONS, _STORAGE}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.md)
        lay.addWidget(self._head)
        lay.addWidget(self._fixed)
        lay.addWidget(self._alerts)
        lay.addLayout(bar_row)
        lay.addWidget(self._stack, 1)
        QWidget.setTabOrder(self._bar, self._refresh_button)

        self._bar.currentChanged.connect(self._on_area)
        self._refresh_button.clicked.connect(self._reload_current)
        self._ctl.stateChanged.connect(self._on_state)
        self._ctl.failed.connect(self._show_error)
        self._ctl.notice.connect(self._show_notice)
        self._ctl.busyChanged.connect(self._busy.setVisible)
        self._ctl.dataChanged.connect(self._on_data_changed)
        find = QShortcut(QKeySequence.StandardKey.Find, self)
        find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)   # só com o foco aqui dentro: não briga com a busca das Configurações
        find.activated.connect(self.focus_search)

        self._on_state()
        self._ctl.open()

    # --- API pública
    def memory(self) -> Memory | None:
        """O ``Memory`` aberto (None enquanto abre, no modo sem histórico ou depois de fechar)."""
        return self._ctl.memory()

    def close_memory(self) -> None:
        """Fecha a conexão com o banco (idempotente). Chamado ao fechar ou destruir o painel."""
        self._ctl.close()

    @property
    def controller(self) -> PanelController:
        return self._ctl

    # --- ciclo de vida
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.close_memory()
        super().closeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._head.setVisible(self.isWindow())
        if self._ctl.persistent and self._ctl.holder.closed and self._ctl.memory() is None:
            e = tr().errors
            self._alerts.show_banner("warn", e.closed_what, "", e.closed_todo)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.isWindow():
            self.close()
            return
        super().keyPressEvent(event)

    # --- reações do controlador
    def _on_state(self) -> None:
        n = tr().no_history
        if self._ctl.persistent:
            self._fixed.clear()
        else:
            self._fixed.show_banner("warn", n.what, n.why, n.todo)
        self.storage_area.set_editable(self._ctl.editable)
        self._dirty = {_MEMORIES, _CONVERSATIONS, _STORAGE}
        self._refresh_current()

    def _on_data_changed(self) -> None:
        self._alerts.clear()
        self._dirty = {_MEMORIES, _CONVERSATIONS, _STORAGE}
        self._refresh_current()

    def _show_error(self, report: ErrorReport) -> None:
        err = report.error
        self._alerts.show_banner("error", err.what, err.why, err.todo, action_text=strs().common.retry,
                                 on_action=report.retry, dismissible=True)

    def _show_notice(self, state: str, title: str, detail: str) -> None:
        Toast.show_message(self, state, title, detail, timeout_ms=MOTION.toast * 2 if detail else MOTION.toast)

    # --- áreas
    def _on_area(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._refresh_current()

    def _refresh_current(self) -> None:
        index = self._stack.currentIndex()
        if index in self._dirty:
            self._dirty.discard(index)
            self._controllers[index].refresh()

    def _reload_current(self) -> None:
        self._dirty.add(self._stack.currentIndex())
        self._alerts.clear()
        self._refresh_current()

    def focus_search(self) -> None:
        """Foca a busca da área aberta (Ctrl+F). A área Armazenamento não tem busca."""
        index = self._stack.currentIndex()
        if index == _MEMORIES:
            self.memories_area.focus_search()
        elif index == _CONVERSATIONS:
            self.conversations_area.focus_search()
