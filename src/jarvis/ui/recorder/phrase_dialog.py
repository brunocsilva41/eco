"""Dialogo para escrever ou editar uma frase, com validacao enquanto digita (a regra vem do modelo)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget

from ...recording.phrasebook import MAX_PHRASE_LEN, PhraseError
from ..kit.base import Label, set_a11y
from ..kit.buttons import Button
from ..kit.fields import TextField
from ..kit.layout import FieldRow
from ..theme import SIZE, SPACE
from .texts import T

Validator = Callable[[str], str]


class PhraseDialog(QDialog):
    """Pede o texto da frase. ``validator`` devolve a frase limpa ou levanta ``PhraseError`` (mostrada junto do campo).

    Enter confirma (quando valida), Esc cancela. O botao Salvar so habilita com texto valido.
    """

    def __init__(self, parent: QWidget | None, *, title: str, validator: Validator, initial: str = "") -> None:
        super().__init__(parent)
        e = T.editor
        self._validator = validator
        self._result = ""
        self.setProperty("kit", "dialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(SIZE.target * 14)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
        lay.setSpacing(SPACE.md)
        lay.addWidget(Label(title, "heading", wrap=True))
        self._field = TextField(initial, placeholder=e.placeholder, accessible_name=e.field_label)
        self._field.setMaxLength(MAX_PHRASE_LEN * 2)       # o limite real e validado e explicado, nao cortado calado
        self._row = FieldRow(e.field_label, self._field, help=e.field_help, stacked=True)
        lay.addWidget(self._row)
        self._counter = Label("", "caption")
        lay.addWidget(self._counter)
        lay.addSpacing(SPACE.sm)
        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE.sm)
        buttons.addStretch(1)
        self._cancel = Button(e.cancel)
        self._save = Button(e.save, variant="primary")
        self._cancel.clicked.connect(self.reject)
        self._save.clicked.connect(self._accept)
        self._save.setDefault(True)
        buttons.addWidget(self._cancel)
        buttons.addWidget(self._save)
        lay.addLayout(buttons)
        self._field.returnPressed.connect(self._save.click)
        self._field.valueChanged.connect(self._check)
        set_a11y(self, title)
        self._check(initial, quiet=True)

    @property
    def text(self) -> str:
        return self._result

    def _check(self, text: str, *, quiet: bool = False) -> None:
        self._counter.setText(T.editor.counter(len(" ".join(text.split())), MAX_PHRASE_LEN))
        try:
            self._validator(text)
        except PhraseError as exc:
            self._save.setEnabled(False)
            self._row.set_error(None if quiet or not text.strip() else str(exc))
            return
        self._row.set_error(None)
        self._save.setEnabled(True)

    def _accept(self) -> None:
        try:
            self._result = self._validator(self._field.text())
        except PhraseError as exc:
            self._row.set_error(str(exc))
            return
        self.accept()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._field.setFocus(Qt.FocusReason.PopupFocusReason))

    @classmethod
    def ask(cls, parent: QWidget | None, *, title: str, validator: Validator, initial: str = "") -> str | None:
        dialog = cls(parent, title=title, validator=validator, initial=initial)
        return dialog.text if dialog.exec() == QDialog.DialogCode.Accepted else None
