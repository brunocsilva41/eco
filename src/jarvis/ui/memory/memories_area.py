"""Vista da área Memórias: lista à esquerda (busca, tipo, fixadas no topo) e detalhe à direita. Sem regra de negócio."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ..kit import Button
from ..theme import SIZE, SPACE
from .listpane import ListPane
from .memory_detail import MemoryDetail
from .texts import tr

_LIST_STRETCH, _DETAIL_STRETCH = 5, 7


class MemoriesArea(QWidget):
    """``pane`` e ``detail`` são públicos para o controlador. Sinais: ``addRequested`` e os do detalhe repassados."""

    addRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        m = tr().memories
        self.add_button = Button(m.add, icon_name="plus", variant="primary")
        self.add_button.setToolTip(m.add_tip)
        self.add_button.setAccessibleName(m.add_name)
        kinds = [(m.kind_all, None), *((label, key) for key, label in m.kinds.items())]
        self.pane = ListPane(search_placeholder=m.search_placeholder, search_name=m.search_name, filters=kinds,
                             filter_name=m.kind_name, list_name=m.list_name, list_desc=m.list_desc,
                             toolbar=[self.add_button])
        self.pane.setMaximumWidth(SIZE.target * 14)
        self.detail = MemoryDetail()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, SPACE.lg, 0, 0)
        lay.setSpacing(SPACE.xl)
        lay.addWidget(self.pane, _LIST_STRETCH)
        lay.addWidget(self.detail, _DETAIL_STRETCH)
        self.add_button.clicked.connect(self.addRequested)
        QWidget.setTabOrder(self.pane.list_widget(), self.detail.first_action())

    def focus_search(self) -> None:
        self.pane.focus_search()
