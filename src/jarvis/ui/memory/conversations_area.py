"""Vista da área Conversas: lista à esquerda (busca, estado, lixeira) e o leitor somente leitura à direita."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ..kit import Button, Label
from ..theme import SIZE, SPACE
from .conversation_view import ConversationView
from .listpane import ListPane
from .texts import tr

_LIST_STRETCH, _VIEW_STRETCH = 5, 8
TRASH = "lixeira"


class ConversationsArea(QWidget):
    """``pane`` e ``viewer`` são públicos para o controlador. ``emptyTrashRequested`` vem do rodapé da lista."""

    emptyTrashRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        c = tr().conversations
        self.pane = ListPane(search_placeholder=c.search_placeholder, search_name=c.search_name, filters=list(c.filters),
                             filter_name=c.filter_name, list_name=c.list_name, list_desc=c.list_desc)
        self.pane.setMaximumWidth(SIZE.target * 14)
        self._trash_note = Label("", "help", wrap=True)
        self._trash_note.setAccessibleName(c.trash_note_name)
        self._empty_trash = Button(c.empty_trash, icon_name="trash", variant="danger")
        self._empty_trash.setToolTip(c.empty_trash_tip)
        self.pane.footer.addSpacing(SPACE.xs)
        self.pane.footer.addWidget(self._trash_note)
        self.pane.footer.addWidget(self._empty_trash, 0, Qt.AlignmentFlag.AlignLeft)
        self.viewer = ConversationView()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, SPACE.lg, 0, 0)
        lay.setSpacing(SPACE.xl)
        lay.addWidget(self.pane, _LIST_STRETCH)
        lay.addWidget(self.viewer, _VIEW_STRETCH)
        self._empty_trash.clicked.connect(self.emptyTrashRequested)
        QWidget.setTabOrder(self.pane.list_widget(), self._empty_trash)
        self.show_trash_footer(False, 0, False)

    def show_trash_footer(self, in_trash: bool, trash_days: int, can_empty: bool) -> None:
        """Rodapé da lixeira: prazo escrito e, separado das outras ações, o botão de esvaziar."""
        self._trash_note.setVisible(in_trash)
        self._trash_note.setText(tr().conversations.trash_note(trash_days))
        self._empty_trash.setVisible(in_trash)
        self._empty_trash.setEnabled(can_empty)

    def focus_search(self) -> None:
        self.pane.focus_search()
