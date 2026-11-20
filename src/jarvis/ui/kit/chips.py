"""ChipList: editor de lista de textos (etiquetas removiveis + campo para adicionar)."""
from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLayout, QLayoutItem, QSizePolicy, QWidget

from ..theme import SIZE, SPACE
from .base import Label, set_a11y, strs, watch_theme
from .buttons import Button
from .fields import TextField


class FlowLayout(QLayout):
    """Layout que quebra linha (itens da esquerda para a direita), com altura por largura."""

    def __init__(self, parent: QWidget | None = None, spacing: int = SPACE.sm) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect: QRect, *, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = area.x(), area.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > area.right() + 1 and row_h > 0:
                x, y, row_h = area.x(), y + row_h + self.spacing(), 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y() + m.bottom()


class _Chip(QFrame):
    """Etiqueta removivel (raio 4: pilula fica reservada ao StatusChip)."""

    removed = Signal(str)

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self.setProperty("kit", "chip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE.md, 0, 0, 0)
        lay.setSpacing(SPACE.xs)
        lay.addWidget(Label(text, "body"))
        self._x = Button(strs().fields.chip_remove.format(item=text), icon_name="close", icon_only=True, variant="text")
        self._x.clicked.connect(lambda: self.removed.emit(self._text))
        lay.addWidget(self._x)
        self.setFixedHeight(SIZE.target)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        set_a11y(self, text)


class ChipList(QWidget):
    """Lista editavel de textos. Enter adiciona, o botao x remove, Backspace no campo vazio remove o ultimo.

    Sinais: ``valueChanged(list)`` (lista de str) e ``duplicateRejected(str)``.
    """

    valueChanged = Signal(list)
    duplicateRejected = Signal(str)

    def __init__(self, items: list[str] | None = None, *, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[str] = []
        self._flow = FlowLayout(self)
        self._input = TextField(placeholder=placeholder or strs().fields.chip_placeholder)
        self._input.setMinimumWidth(SIZE.target * 5)
        self._input.returnPressed.connect(self._commit)
        self._input.installEventFilter(self)
        self.setFocusProxy(self._input)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.set_value(items or [])
        watch_theme(self)

    def value(self) -> list[str]:
        return list(self._items)

    def set_value(self, items: list[str]) -> None:
        self._items = list(dict.fromkeys(items))
        self._rebuild()

    def set_invalid(self, invalid: bool) -> None:
        self._input.set_invalid(invalid)

    def is_invalid(self) -> bool:
        return self._input.is_invalid()

    def _rebuild(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item is not None and item.widget() is not None and item.widget() is not self._input:
                item.widget().setParent(None)
                item.widget().deleteLater()
        for text in self._items:
            chip = _Chip(text)
            chip.removed.connect(self._remove)
            self._flow.addWidget(chip)
        self._flow.addWidget(self._input)
        self.updateGeometry()

    def _commit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if text in self._items:
            self.duplicateRejected.emit(text)
            return
        self._items.append(text)
        self._input.clear()
        self._rebuild()
        self._input.setFocus()
        self.valueChanged.emit(self.value())

    def _remove(self, text: str) -> None:
        if text in self._items:
            self._items.remove(text)
            self._rebuild()
            self._input.setFocus()
            self.valueChanged.emit(self.value())

    def eventFilter(self, obj, event) -> bool:  # type: ignore[no-untyped-def]
        if obj is self._input and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Backspace \
                and not self._input.text() and self._items:
            self._remove(self._items[-1])
            return True
        return super().eventFilter(obj, event)
