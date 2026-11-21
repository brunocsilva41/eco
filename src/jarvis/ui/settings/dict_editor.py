"""Editor de tabela "nome falado -> programa" (aplicativos que o Jarvis pode abrir).

Contrato do kit: ``value()`` (dict), ``set_value(d)``, ``valueChanged(dict)``, ``set_invalid(bool)``.
Cada linha tem o nome falado, o programa (com Procurar) e um botao de remover. Nome repetido marca a linha
como invalida (o dicionario so guarda um programa por nome).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..kit.base import Label, set_a11y
from ..kit.buttons import Button
from ..kit.fields import PathField, TextField
from ..theme import SIZE, SPACE
from .texts import T

_NAME_STRETCH, _PROGRAM_STRETCH = 2, 3


class _Row(QWidget):
    changed = Signal()
    removeRequested = Signal(object)

    def __init__(self, name: str, program: str, number: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        d = T.dictionary
        self.name = TextField(name, placeholder=d.name_placeholder, accessible_name=d.row_name.format(n=number))
        self.program = PathField(program, mode="file", file_filter=d.filter, placeholder=d.program_placeholder)
        self.program.setAccessibleName(d.row_program.format(n=number))
        self.remove = Button(d.remove.format(name=name or number), icon_name="trash", icon_only=True, variant="text")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        lay.addWidget(self.name, _NAME_STRETCH)
        lay.addWidget(self.program, _PROGRAM_STRETCH)
        lay.addWidget(self.remove)
        self.name.valueChanged.connect(lambda _t: self.changed.emit())
        self.program.valueChanged.connect(lambda _t: self.changed.emit())
        self.remove.clicked.connect(lambda: self.removeRequested.emit(self))

    def pair(self) -> tuple[str, str]:
        return self.name.text().strip(), self.program.value().strip()

    def set_invalid(self, invalid: bool) -> None:
        self.name.set_invalid(invalid)


class DictEditor(QWidget):
    valueChanged = Signal(dict)

    def __init__(self, items: dict[str, str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        d = T.dictionary
        self._rows: list[_Row] = []
        self._invalid = False
        self._head = QWidget()
        head = QHBoxLayout(self._head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(SPACE.sm)
        head.addWidget(Label(d.name_header, "caption"), _NAME_STRETCH)
        head.addWidget(Label(d.program_header, "caption"), _PROGRAM_STRETCH)
        head.addSpacing(SIZE.target)
        self._empty = Label(d.empty, "help", wrap=True)
        self._rows_box = QVBoxLayout()
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(SPACE.sm)
        self._add = Button(d.add, icon_name="plus")
        self._add.clicked.connect(self._add_blank)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        lay.addWidget(self._head)
        lay.addWidget(self._empty)
        lay.addLayout(self._rows_box)
        lay.addWidget(self._add, 0, Qt.AlignmentFlag.AlignLeft)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setFocusProxy(self._add)
        set_a11y(self, T.label_for("apps.launch"))
        self.set_value(items or {})

    # ---- contrato do kit
    def value(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in self._rows:
            name, program = row.pair()
            if name or program:
                out[name] = program
        return out

    def set_value(self, items: dict[str, str]) -> None:
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        for name, program in items.items():
            self._append(name, program)
        self._refresh()

    def set_invalid(self, invalid: bool) -> None:
        self._invalid = invalid
        self._mark_duplicates()

    def is_invalid(self) -> bool:
        return self._invalid

    # ---- linhas
    def _append(self, name: str, program: str) -> _Row:
        row = _Row(name, program, len(self._rows) + 1)
        row.changed.connect(self._on_edit)
        row.removeRequested.connect(self._remove)
        self._rows.append(row)
        self._rows_box.addWidget(row)
        return row

    def _add_blank(self) -> None:
        row = self._append("", "")
        self._refresh()
        row.name.setFocus()
        self.valueChanged.emit(self.value())

    def _remove(self, row: object) -> None:
        if row in self._rows:
            self._rows.remove(row)  # type: ignore[arg-type]
            row.setParent(None)  # type: ignore[attr-defined]
            row.deleteLater()  # type: ignore[attr-defined]
            self._refresh()
            self._add.setFocus()
            self.valueChanged.emit(self.value())

    def _on_edit(self) -> None:
        self._mark_duplicates()
        self.valueChanged.emit(self.value())

    def _mark_duplicates(self) -> None:
        names = [r.pair()[0].casefold() for r in self._rows]
        for row, name in zip(self._rows, names):
            row.set_invalid(self._invalid or (bool(name) and names.count(name) > 1))

    def _refresh(self) -> None:
        has_rows = bool(self._rows)
        self._head.setVisible(has_rows)
        self._empty.setVisible(not has_rows)
        self._mark_duplicates()
