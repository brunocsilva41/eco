"""Barra de acoes: Gravar em destaque, navegacao nas pontas e Ouvir/Regravar/Pular em baixo."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from ..theme import SPACE
from .keyed_button import KeyedButton
from .state import Controls
from .texts import Action, T


class ActionRow(QWidget):
    """Seis botoes com a tecla escrita em cada um. A regra de quem pode o que vem pronta em ``Controls``.

    Atalhos de letra e seta sao do proprio botao; Espaco e Enter dependem do foco e ficam no roteador da janela.
    """

    recordClicked = Signal()
    listenClicked = Signal()
    redoClicked = Signal()
    skipClicked = Signal()
    nextClicked = Signal()
    prevClicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        a = T.actions
        self.record = KeyedButton(a.record.label, a.record.key, variant="primary", icon_name="record", large=True)
        self.prev = KeyedButton(a.prev.label, a.prev.key, icon_name="prev", shortcut="Left")
        self.next = KeyedButton(a.next.label, a.next.key, icon_name="next", shortcut="Right")
        self.listen = KeyedButton(a.listen.label, a.listen.key, icon_name="listen", shortcut="O")
        self.redo = KeyedButton(a.redo.label, a.redo.key, icon_name="record", shortcut="R")
        self.skip = KeyedButton(a.skip.label, a.skip.key, icon_name="skip", shortcut="P")
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(SPACE.sm)
        grid.setVerticalSpacing(SPACE.sm)
        for col, stretch in enumerate((2, 3, 2)):
            grid.setColumnStretch(col, stretch)
        grid.addWidget(self.prev, 0, 0)
        grid.addWidget(self.record, 0, 1)
        grid.addWidget(self.next, 0, 2)
        grid.addWidget(self.listen, 1, 0)
        grid.addWidget(self.redo, 1, 1)
        grid.addWidget(self.skip, 1, 2)
        for b in (self.record, self.prev, self.next, self.listen, self.redo, self.skip):
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.record.clicked.connect(self.recordClicked)
        self.listen.clicked.connect(self.listenClicked)
        self.redo.clicked.connect(self.redoClicked)
        self.skip.clicked.connect(self.skipClicked)
        self.next.clicked.connect(self.nextClicked)
        self.prev.clicked.connect(self.prevClicked)
        self.setTabOrder(self.record, self.listen)
        self.setTabOrder(self.listen, self.redo)
        self.setTabOrder(self.redo, self.skip)
        self.setTabOrder(self.skip, self.prev)
        self.setTabOrder(self.prev, self.next)

    def apply(self, c: Controls) -> None:
        a = T.actions
        act: Action = a.saving if c.busy else (a.stop if c.recording else a.record)
        self.record.set_action(act.label, act.key)
        self.record.set_icon_name("stop" if c.recording else "record")
        self.record.set_variant("primary" if not c.primary_next or c.recording else "secondary")
        self.record.setToolTip(f"{act.label} ({act.key}). " + (a.stop_tip if c.recording else a.record_tip))
        self.record.setEnabled(c.can_record)
        listen = a.stop_audio if c.playing else a.listen
        self.listen.set_action(listen.label, listen.key)
        self.listen.set_icon_name("stop" if c.playing else "listen")
        self.listen.setEnabled(c.can_listen)
        self.redo.setEnabled(c.can_redo)
        self.skip.setEnabled(c.can_skip)
        self.prev.setEnabled(c.can_prev)
        self.next.setEnabled(c.can_next)
        self.next.set_variant("primary" if c.primary_next and not c.recording else "secondary")
