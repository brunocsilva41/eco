"""Estrutura de tela: FieldRow, Section, Card.

Hierarquia por espaco, nao por caixas: uma tela de ajustes e uma coluna de ``Section`` com
``FieldRow`` empilhadas. ``Card`` so para uma unidade independente (ex.: um item que pode ser
movido, apagado ou lido sozinho). NUNCA um cartao por campo e nunca cartao dentro de cartao.
"""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..theme import SIZE, SPACE, repolish, pal
from . import icons
from .base import ElidedLabel, Label, set_a11y, strs, watch_theme
from .status import StatusChip


class FieldRow(QWidget):
    """Rotulo + ajuda de uma linha + controle + erro inline + selo "requer reinicio".

    ``control`` e qualquer controle do kit (ou QWidget). Lado a lado por padrao; ``stacked=True``
    poe o controle sob o texto (campos largos: caminhos, listas). ``locked_reason`` bloqueia o
    controle e explica o motivo com cadeado (campos protegidos). ``set_error(msg)`` mostra o
    erro junto do campo e marca a borda; ``set_error(None)`` limpa.
    """

    def __init__(self, label: str, control: QWidget, *, help: str = "", restart_required: bool = False,
                 locked_reason: str = "", stacked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._control = control
        self._help = help
        self._locked = locked_reason
        self._label_text = label
        self._error = ""
        f = strs().fields

        self._label = Label(label, "label")
        self._label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if isinstance(control, QWidget) and control.focusPolicy() != Qt.FocusPolicy.NoFocus:
            self._label.setBuddy(control)
        self._help_label = ElidedLabel(help)
        self._help_label.setVisible(bool(help) and not locked_reason)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(SPACE.sm)
        self._lock_icon = QLabel()
        self._lock_icon.setPixmap(icons.pixmap("lock", pal().text_muted, SIZE.icon, self))
        self._lock_icon.setVisible(bool(locked_reason))
        head.addWidget(self._lock_icon)
        head.addWidget(self._label)
        self._badge = StatusChip("warn", f.restart_required, icon_name="refresh")
        self._badge.setToolTip(f.restart_hint)
        self._badge.setVisible(restart_required)
        head.addWidget(self._badge)
        head.addStretch(1)
        self._lock_text = Label(f"{f.locked}: {locked_reason}" if locked_reason else "", "help", wrap=True)
        self._lock_text.setVisible(bool(locked_reason))

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(SPACE.xs)
        text_col.addLayout(head)
        text_col.addWidget(self._help_label)
        text_col.addWidget(self._lock_text)

        self._error_icon = QLabel()
        self._error_icon.setPixmap(icons.pixmap("error", pal().error, SIZE.icon, self))
        self._error_text = Label("", "help", wrap=True)
        self._error_text.set_state("error")
        self._error_text.setAccessibleName("")
        err = QHBoxLayout()
        err.setContentsMargins(0, 0, 0, 0)
        err.setSpacing(SPACE.sm)
        err.addWidget(self._error_icon, 0, Qt.AlignmentFlag.AlignTop)
        err.addWidget(self._error_text, 1)
        self._error_box = QWidget()
        self._error_box.setLayout(err)
        self._error_box.hide()

        grid = QGridLayout(self)
        grid.setContentsMargins(0, SPACE.xs, 0, SPACE.xs)
        grid.setHorizontalSpacing(SPACE.xl)
        grid.setVerticalSpacing(SPACE.sm)
        if stacked:
            grid.addLayout(text_col, 0, 0)
            grid.addWidget(control, 1, 0)
            grid.addWidget(self._error_box, 2, 0)
        else:
            grid.addLayout(text_col, 0, 0)
            grid.addWidget(control, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(self._error_box, 1, 0, 1, 2)
            grid.setColumnStretch(0, 5)
            grid.setColumnStretch(1, 4)
            grid.setColumnMinimumWidth(0, SIZE.target * 5)
        self._sync_a11y()
        if locked_reason:
            control.setEnabled(False)
        watch_theme(self, self._refresh_icons)

    @property
    def control(self) -> QWidget:
        return self._control

    def set_error(self, message: str | None) -> None:
        self._error = message or ""
        self._error_text.setText(self._error)
        self._error_box.setVisible(bool(self._error))
        invalid = bool(self._error)
        setter = getattr(self._control, "set_invalid", None)
        if callable(setter):
            setter(invalid)
        else:
            self._control.setProperty("invalid", invalid)
            repolish(self._control)
        self._sync_a11y()

    def error(self) -> str:
        return self._error

    def _sync_a11y(self) -> None:
        desc = " ".join(x for x in (self._help, self._locked, f"{strs().fields.error_prefix}: {self._error}" if self._error else "") if x)
        if not self._control.accessibleName():
            self._control.setAccessibleName(self._label_text)
        self._control.setAccessibleDescription(desc)

    def _refresh_icons(self) -> None:
        p = pal()
        self._lock_icon.setPixmap(icons.pixmap("lock", p.text_muted, SIZE.icon, self))
        self._error_icon.setPixmap(icons.pixmap("error", p.error, SIZE.icon, self))


class Section(QWidget):
    """Titulo de secao + descricao opcional + linhas. ``level`` varia o ritmo vertical.

    level 1: titulo 16/600, 32 px de respiro acima, 12 px entre linhas.
    level 2: subgrupo, titulo 13/600 secundario, 16 px acima, 8 px entre linhas.
    ``add(widget)`` acrescenta uma linha (normalmente ``FieldRow``).
    """

    def __init__(self, title: str, description: str = "", *, level: Literal[1, 2] = 1,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        major = level == 1
        root = QVBoxLayout(self)
        root.setContentsMargins(0, SPACE.xxl if major else SPACE.lg, 0, 0)
        root.setSpacing(SPACE.xs)
        self._title = Label(title, "heading" if major else "label")
        root.addWidget(self._title)
        self._desc = Label(description, "help", wrap=True)
        self._desc.setVisible(bool(description))
        root.addWidget(self._desc)
        root.addSpacing(SPACE.md if major else SPACE.sm)
        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(SPACE.md if major else SPACE.sm)
        root.addLayout(self._body)
        set_a11y(self, title, description)

    def add(self, widget: QWidget) -> QWidget:
        self._body.addWidget(widget)
        return widget

    def set_title(self, title: str) -> None:
        self._title.setText(title)
        self.setAccessibleName(title)


class Card(QFrame):
    """Superficie elevada para UMA unidade independente. ``body`` e o QVBoxLayout interno."""

    def __init__(self, title: str = "", *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("kit", "card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(SPACE.lg, SPACE.lg, SPACE.lg, SPACE.lg)
        self.body.setSpacing(SPACE.md)
        if title:
            self.body.addWidget(Label(title, "label"))
            set_a11y(self, title)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget
