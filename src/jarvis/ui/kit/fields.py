"""Campos de entrada: TextField, NumberField, ComboField, PathField.

Contrato comum dos controles de valor do kit (tambem em ToggleSwitch, ChipList, KeyCaptureField):
``value()``, ``set_value(v)``, sinal ``valueChanged(<tipo>)``, ``set_invalid(bool)``, ``is_invalid()``.
Mensagem de erro em texto fica no ``FieldRow``; o campo so mostra a borda de erro.
"""
from __future__ import annotations

from typing import Any, Literal, Sequence

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QListView, QSizePolicy, QWidget

from ..theme import SIZE, SPACE, pal, repolish
from . import icons
from .base import set_a11y, strs, watch_theme
from .buttons import Button


def _set_invalid(widget: QWidget, invalid: bool) -> None:
    widget.setProperty("invalid", invalid)
    repolish(widget)


class TextField(QLineEdit):
    """Campo de texto de uma linha. ``valueChanged(str)`` a cada edicao."""

    valueChanged = Signal(str)

    def __init__(self, value: str = "", *, placeholder: str = "", accessible_name: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(value, parent)
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(SIZE.target)
        self.textChanged.connect(self.valueChanged)
        if accessible_name:
            set_a11y(self, accessible_name)

    def value(self) -> str:
        return self.text()

    def set_value(self, value: str) -> None:
        self.setText(value)

    def set_invalid(self, invalid: bool) -> None:
        _set_invalid(self, invalid)

    def is_invalid(self) -> bool:
        return bool(self.property("invalid"))


class NumberField(QWidget):
    """Numero com botoes menos/mais (alvos de 32 px). Setas Cima/Baixo mudam 1 passo, PageUp/PageDown 10.

    Digite e saia do campo (ou Enter) para confirmar; texto invalido volta ao ultimo valor. Aceita
    virgula ou ponto. ``valueChanged(float)`` so dispara quando o valor muda de fato.
    """

    valueChanged = Signal(float)

    def __init__(self, value: float = 0.0, *, minimum: float = 0.0, maximum: float = 100.0, step: float = 1.0,
                 decimals: int = 0, suffix: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._min, self._max, self._step, self._dec, self._suffix = minimum, maximum, step, decimals, suffix
        self._value = min(max(value, minimum), maximum)
        self._edit = TextField()
        self._edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._edit.setMinimumWidth(SIZE.target * 3)
        self._edit.editingFinished.connect(self._commit_text)
        self._edit.installEventFilter(self)
        self._minus = Button(strs().common.decrease, icon_name="minus", icon_only=True, variant="text")
        self._plus = Button(strs().common.increase, icon_name="plus", icon_only=True, variant="text")
        for b, sign in ((self._minus, -1), (self._plus, 1)):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # o teclado usa as setas dentro do campo
            b.setAutoRepeat(True)
            b.clicked.connect(lambda _=False, sg=sign: self._bump(sg))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.xs)
        lay.addWidget(self._minus)
        lay.addWidget(self._edit, 1)
        lay.addWidget(self._plus)
        self.setFocusProxy(self._edit)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._show()

    def value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        self._apply(value)

    def set_range(self, minimum: float, maximum: float) -> None:
        self._min, self._max = minimum, maximum
        self._apply(self._value)

    def set_invalid(self, invalid: bool) -> None:
        self._edit.set_invalid(invalid)

    def is_invalid(self) -> bool:
        return self._edit.is_invalid()

    def setAccessibleName(self, name: str) -> None:  # noqa: N802 (API Qt)
        super().setAccessibleName(name)
        self._edit.setAccessibleName(name)

    def _show(self) -> None:
        txt = f"{self._value:.{self._dec}f}".replace(".", ",")
        self._edit.setText(f"{txt} {self._suffix}" if self._suffix else txt)

    def _apply(self, value: float) -> None:
        value = round(min(max(value, self._min), self._max), self._dec)
        changed = value != self._value
        self._value = value
        self._show()
        if changed:
            self.valueChanged.emit(value)

    def _bump(self, direction: int, factor: int = 1) -> None:
        self._apply(self._value + direction * self._step * factor)

    def _commit_text(self) -> None:
        raw = self._edit.text().replace(",", ".")
        digits = "".join(ch for ch in raw if ch.isdigit() or ch in ".-")
        try:
            self._apply(float(digits))
        except ValueError:
            self._show()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[no-untyped-def]
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            keys = {Qt.Key.Key_Up: (1, 1), Qt.Key.Key_Down: (-1, 1), Qt.Key.Key_PageUp: (1, 10), Qt.Key.Key_PageDown: (-1, 10)}
            if event.key() in keys:
                self._commit_text()
                self._bump(*keys[event.key()])
                return True
        return super().eventFilter(obj, event)


class ComboField(QComboBox):
    """Lista de opcoes ``(rotulo, valor)``. ``valueChanged(object)`` com o valor associado."""

    valueChanged = Signal(object)

    def __init__(self, items: Sequence[tuple[str, Any]] = (), *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setView(QListView())
        self.setMinimumHeight(SIZE.target)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        for label, data in items:
            self.addItem(label, data)
        self.currentIndexChanged.connect(lambda _i: self.valueChanged.emit(self.currentData()))
        watch_theme(self)

    def value(self) -> Any:
        return self.currentData()

    def set_value(self, value: Any) -> None:
        idx = self.findData(value)
        if idx >= 0:
            self.setCurrentIndex(idx)

    def set_invalid(self, invalid: bool) -> None:
        _set_invalid(self, invalid)

    def is_invalid(self) -> bool:
        return bool(self.property("invalid"))

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        color = pal().text if self.isEnabled() else pal().text_disabled
        pm = icons.pixmap("chevron_down", color, SIZE.icon, self)
        area = QRect(self.width() - SPACE.xl - SPACE.xs, 0, SPACE.xl, self.height())
        p.drawPixmap(area.center().x() - SIZE.icon // 2, area.center().y() - SIZE.icon // 2 + 1, pm)
        p.end()


PathMode = Literal["file", "dir", "save"]


class PathField(QWidget):
    """Caminho de arquivo/pasta: campo editavel + botao Procurar. ``valueChanged(str)``."""

    valueChanged = Signal(str)

    def __init__(self, value: str = "", *, mode: PathMode = "file", file_filter: str = "",
                 placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode: PathMode = mode
        self._filter = file_filter
        self._edit = TextField(value, placeholder=placeholder)
        self._edit.valueChanged.connect(self.valueChanged)
        label = strs().fields.path_choose_dir if mode == "dir" else strs().fields.path_choose_file
        self._browse = Button(strs().common.browse, icon_name="folder")
        self._browse.setToolTip(label)
        self._browse.clicked.connect(self._choose)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        lay.addWidget(self._edit, 1)
        lay.addWidget(self._browse)
        self.setFocusProxy(self._edit)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def value(self) -> str:
        return self._edit.text()

    def set_value(self, value: str) -> None:
        self._edit.setText(value)

    def set_invalid(self, invalid: bool) -> None:
        self._edit.set_invalid(invalid)

    def is_invalid(self) -> bool:
        return self._edit.is_invalid()

    def setAccessibleName(self, name: str) -> None:  # noqa: N802
        super().setAccessibleName(name)
        self._edit.setAccessibleName(name)

    def sizeHint(self) -> QSize:
        return QSize(SIZE.target * 10, SIZE.target)

    def _choose(self) -> None:
        start = self._edit.text()
        if self._mode == "dir":
            chosen = QFileDialog.getExistingDirectory(self, strs().fields.path_choose_dir, start)
        elif self._mode == "save":
            chosen, _ = QFileDialog.getSaveFileName(self, strs().fields.path_choose_file, start, self._filter)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, strs().fields.path_choose_file, start, self._filter)
        if chosen:
            self._edit.setText(chosen)
