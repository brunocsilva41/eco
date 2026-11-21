"""ListPane: a coluna da esquerda de cada área (busca, filtro, contagem e a lista com seus estados).

Estados escritos para humanos: lista, carregando, vazio e erro. Só apresentação: quem decide o texto e as linhas é
o controlador.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ..kit import ComboField, EmptyState, ErrorState, Label, LoadingState, SearchField
from ..kit.base import set_a11y
from ..theme import SIZE, SPACE
from .rows import ListRow
from .rowview import NO_KEY, RowList

_ROWS, _MESSAGE = 0, 1


class ListPane(QWidget):
    searchChanged = Signal(str)
    filterChanged = Signal(object)
    currentKeyChanged = Signal(int)
    itemActivated = Signal(int)
    deleteRequested = Signal(int)
    retryRequested = Signal()
    emptyActionTriggered = Signal()

    def __init__(self, *, search_placeholder: str, search_name: str, filters: Sequence[tuple[str, Any]], filter_name: str,
                 list_name: str, list_desc: str, toolbar: Sequence[QWidget] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(SIZE.target * 9)
        self._search = SearchField(placeholder=search_placeholder, accessible_name=search_name)
        self._filter = ComboField(list(filters))
        set_a11y(self._filter, filter_name)
        self._count = Label("", "help", wrap=True)
        self._count.setAccessibleName(list_name)
        self._list = RowList()
        set_a11y(self._list, list_name, list_desc)
        self._message = QWidget()
        self._message_lay = QVBoxLayout(self._message)
        self._message_lay.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._list)
        self._stack.addWidget(self._message)
        self.footer = QVBoxLayout()
        self.footer.setContentsMargins(0, 0, 0, 0)
        self.footer.setSpacing(SPACE.sm)

        bar = QHBoxLayout()
        bar.setSpacing(SPACE.sm)
        bar.addWidget(self._filter, 1)
        for w in toolbar:
            bar.addWidget(w)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        lay.addWidget(self._search)
        lay.addLayout(bar)
        lay.addWidget(self._count)
        lay.addWidget(self._stack, 1)
        lay.addLayout(self.footer)

        chain: list[QWidget] = [self._search, self._filter, *toolbar, self._list]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)
        self._search.searchChanged.connect(self.searchChanged)
        self._search.escaped.connect(lambda: self._list.setFocus(Qt.FocusReason.TabFocusReason))
        self._filter.valueChanged.connect(self.filterChanged)
        self._list.currentKeyChanged.connect(self.currentKeyChanged)
        self._list.itemActivated.connect(self.itemActivated)
        self._list.deleteRequested.connect(self.deleteRequested)

    # --- entradas
    def search_text(self) -> str:
        return self._search.text()

    def set_search_text(self, text: str) -> None:
        self._search.setText(text)

    def filter_value(self) -> Any:
        return self._filter.value()

    def set_filter_value(self, value: Any) -> None:
        self._filter.set_value(value)

    def focus_search(self) -> None:
        self._search.focus_search()

    def list_widget(self) -> QWidget:
        """A lista (para ligar a ordem de Tab com o painel ao lado)."""
        return self._list

    def focus_list(self) -> None:
        self._list.setFocus(Qt.FocusReason.TabFocusReason)

    def set_inputs_enabled(self, enabled: bool) -> None:
        for w in (self._search, self._filter):
            w.setEnabled(enabled)

    def is_filtering(self) -> bool:
        return bool(self._search.text().strip())

    # --- conteúdo
    def set_count(self, text: str) -> None:
        self._count.setText(text)
        self._count.setVisible(bool(text))

    def set_rows(self, rows: list[ListRow], keep_key: int | None = None) -> None:
        self._list.set_rows(rows, keep_key)
        self._stack.setCurrentIndex(_ROWS)

    def current_key(self) -> int:
        return self._list.current_key()

    def has_selection(self) -> bool:
        return self._list.current_key() != NO_KEY

    def row_count(self) -> int:
        return self._list.row_count()

    def _show_message(self, widget: QWidget) -> None:
        while (item := self._message_lay.takeAt(0)) is not None:
            old = item.widget()
            if old is not None:
                old.hide()
                old.deleteLater()
        self._message_lay.addWidget(widget)
        widget.show()
        self._stack.setCurrentIndex(_MESSAGE)
        self._list.set_rows([])

    def show_loading(self, what: str) -> None:
        self._show_message(LoadingState(what))

    def show_empty(self, title: str, body: str = "", action_text: str = "", icon_name: str = "info") -> None:
        empty = EmptyState(title, body, action_text=action_text, icon_name=icon_name)
        empty.actionTriggered.connect(self.emptyActionTriggered)
        self._show_message(empty)

    def show_error(self, what: str, why: str, todo: str) -> None:
        err = ErrorState(what, why, todo)
        err.retryRequested.connect(self.retryRequested)
        self._show_message(err)
