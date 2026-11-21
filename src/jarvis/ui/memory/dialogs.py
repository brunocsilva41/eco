"""Diálogos de entrada do painel (adicionar/editar memória e renomear conversa), montados só com peças do kit.

Eles apenas COLETAM uma decisão: quem grava no banco é o controlador. Confirmações destrutivas usam
``kit.ConfirmDialog`` (mostra o texto real). Esc cancela; Ctrl+Enter confirma.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from ...memory import MemoryError_
from ...memory.longterm import KINDS, MAX_CHARS, MAX_PINNED, LongTermMemory
from ..kit import Button, ComboField, FieldRow, Label, NumberField, TextField, ToggleSwitch
from ..kit.base import set_a11y
from ..theme import SIZE, SPACE
from .texts import tr

MAX_TITLE = 80
MAX_DAYS = 3650


@dataclass(frozen=True, slots=True)
class NewMemory:
    text: str
    kind: str
    pinned: bool
    expires_days: int | None


class _FormDialog(QDialog):
    """Casca comum: título, corpo (``self.body``), botões Cancelar e confirmar."""

    def __init__(self, parent: QWidget | None, title: str, ok_text: str) -> None:
        super().__init__(parent)
        self.setProperty("kit", "dialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(SIZE.target * 16)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
        self.root.setSpacing(SPACE.md)
        self.root.addWidget(Label(title, "heading", wrap=True))
        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE.md)
        self.root.addLayout(self.body)
        self.cancel_button = Button(tr().common.cancel)
        self.ok_button = Button(ok_text, variant="primary", shortcut="Ctrl+Return")
        for b in (self.cancel_button, self.ok_button):
            b.setAutoDefault(False)
            b.setDefault(False)
        row = QHBoxLayout()
        row.setSpacing(SPACE.sm)
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        row.addWidget(self.ok_button)
        self.root.addSpacing(SPACE.sm)
        self.root.addLayout(row)
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self._submit)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._submit)
        set_a11y(self, title)

    def _submit(self) -> None:          # pragma: no cover - cada diálogo implementa
        raise NotImplementedError


class MemoryEditDialog(_FormDialog):
    """Texto (3 a 1000 caracteres, sem segredos). No modo 'novo' também pede tipo, fixar e validade."""

    def __init__(self, parent: QWidget | None, *, new: bool, text: str = "") -> None:
        d = tr().dialogs
        super().__init__(parent, d.add_title if new else d.edit_title, d.save_new if new else d.save_edit)
        self._new = new
        self._result: NewMemory | None = None
        self._edit = QPlainTextEdit()
        self._edit.setPlainText(text)
        self._edit.setTabChangesFocus(True)
        self._edit.setMinimumHeight(SIZE.target * 4)
        self._text_row = FieldRow(d.text_label, self._edit, help=d.text_help, stacked=True)
        self._count = Label("", "help")
        self.body.addWidget(self._text_row)
        self.body.addWidget(self._count)
        self._kind: ComboField | None = None
        self._pin: ToggleSwitch | None = None
        self._days: NumberField | None = None
        if new:                                  # editar só muda o texto; tipo, fixar e validade ficam como estão
            self._kind = ComboField([(tr().memories.kinds[k], k) for k in KINDS])
            self._pin = ToggleSwitch(False, accessible_name=d.pin_label)
            self._days = NumberField(0, minimum=0, maximum=MAX_DAYS, suffix=d.days_suffix)
            self.body.addWidget(FieldRow(d.kind_label, self._kind))
            self.body.addWidget(FieldRow(d.pin_label, self._pin, help=d.pin_help.format(max=MAX_PINNED)))
            self.body.addWidget(FieldRow(d.expire_label, self._days, help=d.expire_help))
        self._edit.textChanged.connect(self._on_text)
        self._on_text()
        self._edit.setFocus()

    def _on_text(self) -> None:
        n = len(" ".join(self._edit.toPlainText().split()))
        self._count.setText(tr().dialogs.char_count.format(n=n, max=MAX_CHARS))
        if self._text_row.error():
            self._text_row.set_error(None)

    def _submit(self) -> None:
        try:
            clean = LongTermMemory.validate_text(self._edit.toPlainText())
        except MemoryError_ as exc:
            self._text_row.set_error(f"{exc}.")
            self._edit.setFocus()
            return
        if self._kind is None or self._pin is None or self._days is None:
            self._result = NewMemory(clean, "nota", False, None)
        else:
            days = int(self._days.value()) or None
            self._result = NewMemory(clean, str(self._kind.value() or "nota"), self._pin.value(), days)
        self.accept()

    def result_value(self) -> NewMemory | None:
        return self._result


class RenameDialog(_FormDialog):
    """Novo título da conversa (até 80 caracteres)."""

    def __init__(self, parent: QWidget | None, current: str) -> None:
        d = tr().dialogs
        super().__init__(parent, d.rename_title, d.rename_ok)
        self._field = TextField(current, accessible_name=d.rename_label)
        self._field.setMaxLength(MAX_TITLE)
        self._row = FieldRow(d.rename_label, self._field, help=d.rename_help, stacked=True)
        self.body.addWidget(self._row)
        self._field.valueChanged.connect(lambda _t: self._row.set_error(None) if self._row.error() else None)
        self._field.returnPressed.connect(self._submit)
        self._field.selectAll()
        self._field.setFocus()

    def _submit(self) -> None:
        if not self._field.text().strip():
            self._row.set_error(tr().dialogs.rename_empty)
            return
        self.accept()

    def result_title(self) -> str:
        return " ".join(self._field.text().split())
