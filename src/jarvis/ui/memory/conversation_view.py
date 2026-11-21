"""Coluna da direita da área Conversas: cabeçalho, aviso da lixeira, mensagens (somente leitura) e ações.

Só apresentação: cada botão emite um sinal com o id da conversa; quem pergunta, grava e avisa é o controlador.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, SignalInstance
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ..kit import Button, EmptyState, ErrorState, Label, LoadingState, StatusChip
from ..kit.base import set_a11y
from ..kit.status import ChipState
from ..theme import SPACE
from .banners import BannerSlot
from .logic import fmt_ts, trash_days_left
from .reader import ReadScroll, build_reader_page
from .service import ConversationData
from .texts import tr

_NONE, _MESSAGE, _CONTENT = 0, 1, 2


class ConversationView(QWidget):
    resumeRequested = Signal(int)
    exportRequested = Signal(int)
    renameRequested = Signal(int)
    trashRequested = Signal(int)
    restoreRequested = Signal(int)
    retryRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        c = tr().conversations
        set_a11y(self, c.viewer_name)
        self._sid: int | None = None
        self._stack = QStackedWidget()
        self._idle: QWidget = EmptyState(c.viewer_none_title, c.viewer_none_body, icon_name="log")
        self._stack.addWidget(self._idle)
        self._message = QWidget()
        self._message_lay = QVBoxLayout(self._message)
        self._message_lay.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._message)
        self._stack.addWidget(self._build_content())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stack)

    def _build_content(self) -> QWidget:
        c = tr().conversations
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.md)
        self._title = Label("", "title", wrap=True)
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._meta = QHBoxLayout()
        self._meta.setSpacing(SPACE.sm)
        self._banner = BannerSlot()
        self._reader = ReadScroll()
        set_a11y(self._reader, c.messages_name, c.messages_desc)
        self._resume = Button(c.resume, variant="primary", icon_name="record")
        self._restore = Button(c.restore, variant="primary", icon_name="refresh")
        self._restore.setToolTip(c.restore_tip)
        self._export = Button(c.export, icon_name="log")
        self._export.setToolTip(c.export_tip)
        self._rename = Button(c.rename, icon_name="edit")
        self._trash = Button(c.trash, icon_name="trash", variant="danger")
        self._trash.setToolTip(c.trash_tip)
        self._hint = Label("", "help", wrap=True)
        actions = QHBoxLayout()
        actions.setSpacing(SPACE.sm)
        for b in (self._resume, self._restore, self._export, self._rename):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addSpacing(SPACE.xl)             # a ação destrutiva fica longe das outras
        actions.addWidget(self._trash)
        col.addWidget(self._title)
        col.addLayout(self._meta)
        col.addWidget(self._banner)
        col.addWidget(self._reader, 1)
        col.addLayout(actions)
        col.addWidget(self._hint)
        for button, signal in ((self._resume, self.resumeRequested), (self._restore, self.restoreRequested),
                               (self._export, self.exportRequested), (self._rename, self.renameRequested),
                               (self._trash, self.trashRequested)):
            button.clicked.connect(lambda _=False, s=signal: self._emit(s))
        for a, b in zip((self._reader, self._resume, self._restore, self._export, self._rename, self._trash),
                        (self._resume, self._restore, self._export, self._rename, self._trash)):
            QWidget.setTabOrder(a, b)
        return page

    def _emit(self, signal: SignalInstance) -> None:
        if self._sid is not None:
            signal.emit(self._sid)

    def current_id(self) -> int | None:
        return self._sid

    # --- estados
    def _show_message(self, widget: QWidget) -> None:
        while (item := self._message_lay.takeAt(0)) is not None:
            old = item.widget()
            if old is not None:
                old.hide()
                old.deleteLater()
        self._message_lay.addWidget(widget)
        widget.show()
        self._stack.setCurrentIndex(_MESSAGE)

    def set_idle(self, title: str, body: str) -> None:
        """Texto de quando não há conversa selecionada (ex.: ainda não há nenhuma)."""
        old, self._idle = self._idle, EmptyState(title, body, icon_name="log")
        self._stack.insertWidget(_NONE, self._idle)
        self._stack.removeWidget(old)
        old.deleteLater()

    def show_none(self) -> None:
        self._sid = None
        self._stack.setCurrentIndex(_NONE)

    def show_loading(self) -> None:
        self._show_message(LoadingState(tr().conversations.viewer_loading))

    def show_error(self, what: str, why: str, todo: str) -> None:
        err = ErrorState(what, why, todo)
        err.retryRequested.connect(self.retryRequested)
        self._show_message(err)

    def show_data(self, data: ConversationData, trash_days: float, editable: bool) -> None:
        c = tr().conversations
        s = data.session
        self._sid = s.id
        self._title.setText(s.title)
        while (item := self._meta.takeAt(0)) is not None:
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        state: ChipState = "ok" if s.state == "ativa" else ("warn" if s.state == "lixeira" else "neutral")
        icon = {"ativa": "record", "lixeira": "trash"}.get(s.state, "log")
        label = {"ativa": c.state_active, "lixeira": c.state_trash}.get(s.state, c.state_ended)
        self._meta.addWidget(StatusChip(state, label, icon_name=icon))
        self._meta.addWidget(StatusChip("neutral", tr().common.read_only, icon_name="lock"))
        self._meta.addWidget(Label(f"{c.meta_messages(data.total_messages)} · {fmt_ts(s.last_active)}", "help"))
        self._meta.addStretch(1)
        in_trash = s.state == "lixeira"
        if in_trash:
            left = trash_days_left(s.deleted_at, trash_days)
            self._banner.show_banner("warn", c.trash_banner_what, c.trash_banner_why(left), c.trash_banner_todo())
        else:
            self._banner.clear()
        self._reader.setWidget(build_reader_page(data))
        self._resume.setVisible(not in_trash)
        self._rename.setVisible(not in_trash)
        self._trash.setVisible(not in_trash)
        self._restore.setVisible(in_trash)
        self._resume.setEnabled(editable and s.state == "encerrada")
        self._resume.setToolTip(c.resume_is_active if s.state == "ativa" else c.resume_tip)
        for b in (self._rename, self._trash, self._restore):
            b.setEnabled(editable)
        self._export.setEnabled(editable)
        self._hint.setText(c.resume_is_active if s.state == "ativa" else "")
        self._hint.setVisible(s.state == "ativa")
        self._stack.setCurrentIndex(_CONTENT)
