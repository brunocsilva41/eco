"""KeyCaptureField: captura uma combinacao de teclas (ex. tecla de atalho global)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from ..theme import SIZE, repolish
from .base import set_a11y, strs

_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr}


class KeyCaptureField(QPushButton):
    """Mostra a combinacao atual; Enter/Espaco/clique entram em modo captura.

    Em captura: qualquer combinacao com tecla nao modificadora e gravada, Esc cancela, Backspace
    limpa, perder o foco cancela. Tab sai normalmente quando NAO esta capturando.
    Valor: texto portavel do Qt (``"Ctrl+Alt+J"``, ``""`` = nenhuma). Sinais: ``valueChanged(str)``,
    ``capturingChanged(bool)``.
    """

    valueChanged = Signal(str)
    capturingChanged = Signal(bool)

    def __init__(self, value: str = "", *, accessible_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = value
        self._capturing = False
        self.setProperty("kit", "keycapture")
        self.setMinimumHeight(SIZE.target)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self._begin)
        self._sync()
        if accessible_name:
            set_a11y(self, accessible_name, strs().fields.key_hint)

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        if value != self._value:
            self._value = value
            self._sync()
            self.valueChanged.emit(value)

    def set_invalid(self, invalid: bool) -> None:
        self.setProperty("invalid", invalid)
        repolish(self)

    def is_invalid(self) -> bool:
        return bool(self.property("invalid"))

    def is_capturing(self) -> bool:
        return self._capturing

    # --- captura
    def begin_capture(self) -> None:
        """Entra em modo captura (o mesmo que Enter/Espaco/clique)."""
        self._begin()

    def _begin(self) -> None:
        if not self._capturing:
            self._set_capturing(True)

    def _set_capturing(self, on: bool) -> None:
        self._capturing = on
        self.setProperty("capturing", on)
        self._sync()
        repolish(self)
        self.capturingChanged.emit(on)

    def _sync(self) -> None:
        f = strs().fields
        if self._capturing:
            self.setText(f.key_capturing)
        else:
            self.setText(self._value.replace("+", " + ") if self._value else f.key_none)

    def event(self, e: QEvent) -> bool:
        if self._capturing and e.type() == QEvent.Type.ShortcutOverride:
            e.accept()          # impede que atalhos da janela consumam a combinacao
            return True
        return super().event(e)

    def focusNextPrevChild(self, nxt: bool) -> bool:  # noqa: N802
        return False if self._capturing else super().focusNextPrevChild(nxt)

    def focusOutEvent(self, e: QFocusEvent) -> None:
        if self._capturing:
            self._set_capturing(False)
        super().focusOutEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if not self._capturing:
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._begin()
                return
            super().keyPressEvent(e)       # Espaco aciona clicked -> _begin
            return
        key = Qt.Key(e.key())
        if key == Qt.Key.Key_Escape:
            self._set_capturing(False)
        elif key == Qt.Key.Key_Backspace and not e.modifiers():
            self._set_capturing(False)
            self.set_value("")
        elif key not in _MODIFIER_KEYS:
            combo = QKeySequence(e.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText)
            self._set_capturing(False)
            self.set_value(combo)
        e.accept()
