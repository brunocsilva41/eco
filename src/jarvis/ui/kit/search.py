"""SearchField: busca com debounce, Ctrl+F para focar, Esc para limpar/sair."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QLineEdit, QWidget

from ..theme import SIZE, pal
from . import icons
from .base import set_a11y, strs, watch_theme
from .visibility import set_shown
from .fields import TextField

_DEBOUNCE_MS = 150


class SearchField(TextField):
    """Campo de busca. ``searchChanged(str)`` dispara 150 ms depois da ultima tecla (e na hora ao limpar).

    ``bind_shortcut(window)`` liga Ctrl+F a este campo na janela. Esc: limpa o texto; com o campo
    ja vazio, tira o foco e emite ``escaped()`` para a tela devolver o foco a lista.
    """

    searchChanged = Signal(str)
    escaped = Signal()

    def __init__(self, *, placeholder: str = "", accessible_name: str = "", parent: QWidget | None = None) -> None:
        f = strs().fields
        super().__init__(placeholder=placeholder or f"{strs().common.search} (Ctrl+F)", parent=parent)
        self._lead = QAction(self)
        self.addAction(self._lead, QLineEdit.ActionPosition.LeadingPosition)
        self._clear = QAction(f.search_clear, self)
        self._clear.triggered.connect(self.clear)
        self.addAction(self._clear, QLineEdit.ActionPosition.TrailingPosition)
        set_shown(self._clear, False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._emit)
        self.textChanged.connect(self._on_text)
        set_a11y(self, accessible_name or strs().common.search)
        self.setMinimumHeight(SIZE.target)
        watch_theme(self, self._refresh_icons)
        self._refresh_icons()

    def bind_shortcut(self, window: QWidget) -> QShortcut:
        sc = QShortcut(QKeySequence.StandardKey.Find, window)
        sc.activated.connect(self.focus_search)
        return sc

    def focus_search(self) -> None:
        self.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.selectAll()

    def _on_text(self, text: str) -> None:
        set_shown(self._clear, bool(text))
        if text:
            self._timer.start()
        else:
            self._timer.stop()
            self._emit()

    def _emit(self) -> None:
        self.searchChanged.emit(self.text())

    def _refresh_icons(self) -> None:
        p = pal()
        self._lead.setIcon(icons.icon("search", p.text_muted, SIZE.icon, widget=self))
        self._clear.setIcon(icons.icon("close", p.text_muted, SIZE.icon, widget=self))

    def event(self, e) -> bool:  # type: ignore[no-untyped-def]
        # Sem isto o atalho Esc da JANELA (fechar) roubava a tecla antes do campo: Esc na busca fechava as Configuracoes
        # (ou abria "descartar alteracoes?") em vez de limpar o texto. Aceitar o ShortcutOverride entrega a tecla ao campo.
        if e.type() == QEvent.Type.ShortcutOverride and isinstance(e, QKeyEvent) and e.key() == Qt.Key.Key_Escape:
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            if self.text():
                self.clear()
            else:
                self.clearFocus()
                self.escaped.emit()
            e.accept()
            return
        super().keyPressEvent(e)
