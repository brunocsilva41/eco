"""Detalhe de uma memória (coluna da direita da área Memórias). Só apresentação: os botões emitem sinais."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from ...memory import MemoryItem
from ..kit import Button, EmptyState, Label, StatusChip
from ..kit.base import set_a11y
from ..kit.status import ChipState
from ..theme import SPACE
from .banners import BannerSlot
from .logic import expiry_text, fmt_ts
from .texts import tr

_LONG_TEXT = 160                       # acima disso o texto usa o corpo normal em vez do título de seção
_ORIGIN_CHIP: dict[str, tuple[ChipState, str]] = {"usuario": ("neutral", "edit"), "modelo": ("neutral", "brain"),
                                                  "externo": ("warn", "alert")}


def _selectable(label: Label) -> Label:
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class MemoryDetail(QWidget):
    editRequested = Signal(int)
    pinToggled = Signal(int, bool)         # (id, novo estado de fixada)
    deleteRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        m = tr().memories
        set_a11y(self, m.detail_name)
        self._item: MemoryItem | None = None
        self._stack = QStackedWidget()
        self._idle: QWidget = EmptyState(m.detail_none_title, m.detail_none_body, icon_name="memory")
        self._stack.addWidget(self._idle)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._stack.addWidget(self._scroll)

        self._edit = Button(m.edit, icon_name="edit")
        self._pin = Button(m.pin, icon_name="pin")
        self._pin.setToolTip(m.pin_tip)
        self._delete = Button(m.delete, icon_name="trash", variant="danger")
        self._delete.setToolTip(m.delete_tip)
        self._actions = QWidget()
        row = QHBoxLayout(self._actions)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE.sm)
        row.addWidget(self._edit)
        row.addWidget(self._pin)
        row.addStretch(1)
        row.addSpacing(SPACE.xl)               # a ação destrutiva fica longe das outras
        row.addWidget(self._delete)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.lg)
        lay.addWidget(self._stack, 1)
        lay.addWidget(self._actions)
        self._edit.clicked.connect(lambda: self._item is not None and self.editRequested.emit(self._item.id))
        self._pin.clicked.connect(lambda: self._item is not None and self.pinToggled.emit(self._item.id, not self._item.pinned))
        self._delete.clicked.connect(lambda: self._item is not None and self.deleteRequested.emit(self._item.id))
        QWidget.setTabOrder(self._edit, self._pin)
        QWidget.setTabOrder(self._pin, self._delete)
        self._actions.setVisible(False)

    def current_id(self) -> int | None:
        return self._item.id if self._item is not None else None

    def set_idle(self, title: str, body: str) -> None:
        """Texto de quando não há memória selecionada (ex.: ainda não há nenhuma)."""
        old, self._idle = self._idle, EmptyState(title, body, icon_name="memory")
        self._stack.insertWidget(0, self._idle)
        self._stack.removeWidget(old)
        old.deleteLater()

    def first_action(self) -> QWidget:
        """Primeiro botão de ação (para ligar a ordem de Tab com a lista ao lado)."""
        return self._edit

    def show_item(self, item: MemoryItem | None, editable: bool) -> None:
        m = tr().memories
        self._item = item
        self._actions.setVisible(item is not None)
        if item is None:
            self._stack.setCurrentIndex(0)
            return
        self._pin.setText(m.unpin if item.pinned else m.pin)
        for b in (self._edit, self._pin, self._delete):
            b.setEnabled(editable)
        self._scroll.setWidget(self._build(item))
        self._stack.setCurrentIndex(1)

    def _build(self, item: MemoryItem) -> QWidget:
        m = tr().memories
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, SPACE.md, 0)
        col.setSpacing(SPACE.lg)
        chips = QHBoxLayout()
        chips.setSpacing(SPACE.sm)
        chips.addWidget(Label(m.kinds.get(item.kind, item.kind), "label"))
        state, icon = _ORIGIN_CHIP.get(item.origin, ("neutral", "info"))
        chips.addWidget(StatusChip(state, m.origins.get(item.origin, item.origin), icon_name=icon))
        if item.pinned:
            chips.addWidget(StatusChip("neutral", m.pinned_chip, icon_name="pin"))
        chips.addStretch(1)
        col.addLayout(chips)
        text = _selectable(Label(item.text, "heading" if len(item.text) <= _LONG_TEXT else "body", wrap=True))
        text.setAccessibleName(item.text[:200])
        col.addWidget(text)
        note = m.origin_notes.get(item.origin, "")
        if item.origin == "externo":
            slot = BannerSlot()
            slot.show_banner("warn", m.origins["externo"], note)
            col.addWidget(slot)
        elif note:
            col.addWidget(Label(note, "help", wrap=True))
        col.addLayout(self._facts(item))
        col.addStretch(1)
        return page

    @staticmethod
    def _facts(item: MemoryItem) -> QGridLayout:
        m = tr().memories
        expiry, expired = expiry_text(item.expires_at)
        rows = [(m.field_created, fmt_ts(item.created), False), (m.field_updated, fmt_ts(item.updated), False),
                (m.field_expires, expiry, expired)]
        if item.origin != "usuario":
            rows.append((m.field_confidence, f"{round(item.confidence * 100)}%", False))
        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE.xl)
        grid.setVerticalSpacing(SPACE.sm)
        grid.setColumnStretch(1, 1)
        for i, (name, value, warn) in enumerate(rows):
            grid.addWidget(Label(name, "help"), i, 0, Qt.AlignmentFlag.AlignTop)
            val = _selectable(Label(value, "body", wrap=True))
            if warn:
                val.set_state("warn")
            grid.addWidget(val, i, 1)
        return grid
