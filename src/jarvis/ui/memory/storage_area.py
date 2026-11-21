"""Vista da área Armazenamento e privacidade: aviso de que o banco não é criptografado (sempre visível), números reais,
cópia e exportação, e uma faixa própria, separada, para as ações de apagar. Sem regra de negócio."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..kit import Button, FieldRow, Label, Section, StatusChip
from ..kit.base import set_a11y
from ..theme import SIZE, SPACE
from .banners import BannerSlot
from .logic import fmt_mb
from .service import Stats
from .texts import tr


class _Stat(QWidget):
    """Um número real do banco (28 px, tabular) com o nome e uma nota. Sem borda: hierarquia por tipografia."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.value = Label("", "display")
        self.caption = Label(caption, "label")
        self.note = Label("", "help")
        for w in (self.value, self.caption, self.note):
            col.addWidget(w)

    def set_values(self, value: str, note: str = "") -> None:
        self.value.setText(value)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        set_a11y(self, f"{self.caption.text()}: {value}", note)


def _selectable(label: Label) -> Label:
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class StorageArea(QWidget):
    backupRequested = Signal()
    exportAllRequested = Signal()
    refreshRequested = Signal()
    wipeMemoriesRequested = Signal()
    wipeConversationsRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        s = tr().storage
        set_a11y(self, s.area_name)
        self.warning = BannerSlot()          # "O banco não é criptografado": fixo, sem botão de dispensar
        self.warning.show_banner("warn", s.unencrypted_what, s.unencrypted_why, s.unencrypted_todo)
        self._chip_slot = QHBoxLayout()
        self._chip_slot.setSpacing(SPACE.md)
        self._mode_note = Label("", "help", wrap=True)
        self._stats = (_Stat(s.memories), _Stat(s.conversations), _Stat(s.messages))
        self._stats_message = Label("", "body", wrap=True)
        self._stats_row = QHBoxLayout()
        self._stats_row.setSpacing(SPACE.xxl)
        for st in self._stats:
            self._stats_row.addWidget(st, 0, Qt.AlignmentFlag.AlignTop)
        self._stats_row.addStretch(1)
        self._path = _selectable(Label("", "body", wrap=True))
        self._size = _selectable(Label("", "body", wrap=True))
        self._retention = _selectable(Label("", "body", wrap=True))
        self.backup = Button(s.backup, icon_name="folder", variant="primary")
        self.backup.setToolTip(s.backup_tip)
        self.export_all = Button(s.export_all, icon_name="log")
        self.export_all.setToolTip(s.export_all_tip)
        self.refresh_button = Button(s.refresh, icon_name="refresh", variant="text")
        self.wipe_memories = Button(s.wipe_memories, icon_name="trash", variant="danger")
        self.wipe_conversations = Button(s.wipe_conversations, icon_name="trash", variant="danger")

        left = QVBoxLayout()
        left.setSpacing(SPACE.md)
        left.addLayout(self._chip_slot)
        left.addWidget(self._mode_note)
        stored = Section(s.stored_title, level=2)
        stored.add(self._stats_message)
        holder = QWidget()
        holder.setLayout(self._stats_row)
        stored.add(holder)
        left.addWidget(stored)
        facts = QGridLayout()
        facts.setHorizontalSpacing(SPACE.xl)
        facts.setVerticalSpacing(SPACE.sm)
        facts.setColumnStretch(1, 1)
        for i, (name, value) in enumerate(((s.path_label, self._path), (s.size_label, self._size),
                                           (s.retention_label, self._retention))):
            facts.addWidget(Label(name, "help"), i, 0, Qt.AlignmentFlag.AlignTop)
            facts.addWidget(value, i, 1)
        left.addSpacing(SPACE.sm)
        left.addLayout(facts)
        left.addStretch(1)

        right = Section(s.copy_title, s.copy_desc, level=2)
        right.setFixedWidth(SIZE.target * 10)
        for b in (self.backup, self.export_all, self.refresh_button):
            right.add(b)

        top = QHBoxLayout()
        top.setSpacing(SPACE.xxl)
        top.addLayout(left, 1)
        top.addWidget(right, 0, Qt.AlignmentFlag.AlignTop)

        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, SPACE.lg, SPACE.md, 0)
        col.setSpacing(SPACE.lg)
        col.addWidget(self.warning)
        col.addLayout(top)
        col.addStretch(1)
        col.addWidget(self._danger_band(), 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)

        self.backup.clicked.connect(self.backupRequested)
        self.export_all.clicked.connect(self.exportAllRequested)
        self.refresh_button.clicked.connect(self.refreshRequested)
        self.wipe_memories.clicked.connect(self.wipeMemoriesRequested)
        self.wipe_conversations.clicked.connect(self.wipeConversationsRequested)
        chain = [self.backup, self.export_all, self.refresh_button, self.wipe_memories, self.wipe_conversations]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

    def _danger_band(self) -> QWidget:
        """Faixa própria, com o tom de superfície e a borda de cima do kit: as ações sem volta ficam longe das outras."""
        s = tr().storage
        band = QFrame()
        band.setProperty("kit", "bar")
        col = QVBoxLayout(band)
        col.setContentsMargins(SPACE.xl, SPACE.lg, SPACE.xl, SPACE.lg)
        col.setSpacing(SPACE.sm)
        col.addWidget(Label(s.danger_title, "heading"))
        col.addWidget(Label(s.danger_desc, "help", wrap=True))
        col.addWidget(FieldRow(s.wipe_memories_label, self.wipe_memories, help=s.wipe_memories_help))
        col.addWidget(FieldRow(s.wipe_conversations_label, self.wipe_conversations, help=s.wipe_conversations_help))
        return band

    # --- conteúdo
    def show_mode(self, persistent: bool) -> None:
        s = tr().storage
        while (item := self._chip_slot.takeAt(0)) is not None:
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self._chip_slot.addWidget(StatusChip("ok" if persistent else "warn", s.on_chip if persistent else s.off_chip))
        self._chip_slot.addStretch(1)
        self._mode_note.setText(s.on_note if persistent else s.off_note)

    def set_facts(self, path: str, retention: str) -> None:
        self._path.setText(path)
        self._retention.setText(retention)

    def set_size_text(self, text: str) -> None:
        self._size.setText(text)

    def show_counts_message(self, text: str) -> None:
        """Texto no lugar dos números (calculando, abrindo, nada guardado)."""
        self._stats_message.setText(text)
        self._stats_message.setVisible(True)
        for st in self._stats:
            st.setVisible(False)

    def show_stats(self, stats: Stats) -> None:
        s = tr().storage
        self._stats_message.setVisible(False)
        values = ((str(stats.memories), s.pinned_note(stats.pinned)), (str(stats.sessions), s.trashed_note(stats.trashed)),
                  (str(stats.messages), ""))
        for st, (value, note) in zip(self._stats, values):
            st.set_values(value, note)
            st.setVisible(True)
        self.set_size_text(fmt_mb(stats.size_bytes))

    def set_editable(self, editable: bool) -> None:
        for b in (self.backup, self.export_all, self.wipe_memories, self.wipe_conversations):
            b.setEnabled(editable)
