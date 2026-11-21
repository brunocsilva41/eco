"""Controlador da área Conversas: lista ou trechos de busca, leitor somente leitura e as ações sobre a conversa."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QDialog

from ...memory import Hit
from ..kit import ConfirmDialog
from .controller import PanelController, choose_save_path
from .conversations_area import TRASH, ConversationsArea
from .dialogs import RenameDialog
from .logic import FriendlyError, safe_file_stem
from .rows import hit_rows, session_rows
from .rowview import NO_KEY
from .service import (ConversationData, SessionRow, load_conversation, load_session_rows, search_conversations)
from .texts import plural, tr

log = logging.getLogger(__name__)
SELECT_DELAY_MS = 150                 # setas rápidas na lista não disparam uma leitura do banco por conversa
_TITLES_SHOWN = 15


class ConversationsController(QObject):
    def __init__(self, ctl: PanelController, view: ConversationsArea, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctl = ctl
        self._view = view
        self._seq = 0
        self._vseq = 0
        self._rows: list[SessionRow] = []
        self._data: ConversationData | None = None
        self._pending_key = NO_KEY
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SELECT_DELAY_MS)
        self._timer.timeout.connect(self._load_selected)
        pane, viewer = view.pane, view.viewer
        pane.searchChanged.connect(self.refresh)
        pane.filterChanged.connect(self.refresh)
        pane.retryRequested.connect(self.refresh)
        pane.currentKeyChanged.connect(self._on_select)
        pane.deleteRequested.connect(self.trash)
        view.emptyTrashRequested.connect(self.empty_trash)
        viewer.retryRequested.connect(self._load_selected)
        viewer.resumeRequested.connect(self.resume)
        viewer.exportRequested.connect(self.export)
        viewer.renameRequested.connect(self.rename)
        viewer.trashRequested.connect(self.trash)
        viewer.restoreRequested.connect(self.restore)

    # --- lista
    def refresh(self, *_ignored: object) -> None:
        t, pane = tr(), self._view.pane
        pane.set_inputs_enabled(self._ctl.can_read)
        if not self._ctl.persistent:
            self._rows = []
            pane.set_count("")
            pane.show_empty(t.no_history.empty_title, t.no_history.empty_conversations, icon_name="alert")
            self._view.viewer.show_none()
            self._view.show_trash_footer(False, self._ctl.trash_days, False)
            return
        if not self._ctl.can_read:
            pane.show_loading(t.conversations.loading)
            return
        self._seq += 1
        seq, query, state, keep = self._seq, pane.search_text().strip(), pane.filter_value(), pane.current_key()
        in_trash = state == TRASH
        self._view.show_trash_footer(in_trash, self._ctl.trash_days, False)
        if pane.row_count() == 0:
            pane.show_loading(t.conversations.loading)
        if query and not in_trash:
            self._ctl.submit(lambda mem: search_conversations(mem, query), lambda hits: self._hits_loaded(seq, query, hits),
                             on_error=self._load_failed)
        else:
            self._ctl.submit(lambda mem: load_session_rows(mem, state, query), lambda rows: self._rows_loaded(seq, query, rows, keep),
                             on_error=self._load_failed)

    def _rows_loaded(self, seq: int, query: str, rows: list[SessionRow], keep: int) -> None:
        if seq != self._seq:
            return
        c, pane = tr().conversations, self._view.pane
        in_trash = pane.filter_value() == TRASH
        self._rows = rows
        self._view.viewer.set_idle(c.viewer_none_title if rows else c.viewer_idle_title,
                                   c.viewer_none_body if rows else c.viewer_idle_body)
        pane.set_count(c.count(len(rows)))
        self._view.show_trash_footer(in_trash, self._ctl.trash_days, bool(rows) and self._ctl.editable)
        if rows:
            pane.set_rows(session_rows(rows, self._ctl.trash_days), keep if keep != NO_KEY else None)
        elif in_trash:
            pane.show_empty(c.trash_empty_title, c.trash_empty_body, icon_name="trash")
        elif query:
            pane.show_empty(c.no_match_title, c.no_match_body, icon_name="search")
        else:
            pane.show_empty(c.empty_title, c.empty_body, icon_name="log")

    def _hits_loaded(self, seq: int, query: str, hits: list[Hit]) -> None:
        if seq != self._seq:
            return
        c, pane = tr().conversations, self._view.pane
        self._rows = []
        pane.set_count(c.hits_count(len(hits), query))
        if hits:
            pane.set_rows(hit_rows(hits), None)
        else:
            pane.show_empty(c.no_match_title, c.no_match_body, icon_name="search")

    def _load_failed(self, err: FriendlyError) -> None:
        self._rows = []
        self._view.pane.set_count("")
        self._view.pane.show_error(err.what, err.why, err.todo)

    # --- leitor
    def _on_select(self, key: int) -> None:
        self._pending_key = key
        if key == NO_KEY:
            self._timer.stop()
            self._vseq += 1
            self._data = None
            self._view.viewer.show_none()
        else:
            self._timer.start()

    def _load_selected(self) -> None:
        key = self._pending_key
        if key == NO_KEY or not self._ctl.can_read:
            return
        self._vseq += 1
        vseq, viewer = self._vseq, self._view.viewer
        if viewer.current_id() is None:
            viewer.show_loading()
        self._ctl.submit(lambda mem: load_conversation(mem, key), lambda data: self._viewer_loaded(vseq, data),
                         on_error=lambda err: viewer.show_error(err.what, err.why, err.todo))

    def _viewer_loaded(self, vseq: int, data: ConversationData | None) -> None:
        if vseq != self._vseq:
            return
        if data is None:
            self._data = None
            self._view.viewer.show_none()
            self._ctl.notify("warn", tr().conversations.gone_title, tr().conversations.gone_detail)
            self.refresh()
            return
        self._data = data
        self._view.viewer.show_data(data, self._ctl.trash_days, self._ctl.editable)

    def _title_of(self, sid: int) -> str:
        return self._data.session.title if self._data is not None and self._data.session.id == sid else ""

    # --- ações
    def rename(self, sid: int) -> None:
        dlg = RenameDialog(self._view, self._title_of(sid))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        title = dlg.result_title()
        self._ctl.submit(lambda mem: mem.sessions.rename(sid, title), lambda _r: self._ctl.changed(tr().notices.renamed_title))

    def export(self, sid: int) -> None:
        d, n = tr().dialogs, tr().notices
        picked = choose_save_path(self._view, d.export_conv_title, f"{safe_file_stem(self._title_of(sid) or 'conversa')}.md",
                                  d.export_conv_filter, (".md", ".json"), ".md")
        if picked is None:
            return
        fmt = "json" if picked.suffix.lower() == ".json" else "md"
        self._ctl.submit(lambda mem: mem.sessions.export(sid, picked, fmt),
                         lambda p: self._ctl.notify("ok", n.exported_title, f"{p}. {n.exported_note}"))

    def trash(self, sid: int) -> None:
        if self._data is None or self._data.session.id != sid or self._data.session.state == "lixeira" or not self._ctl.editable:
            return
        d, s, days = tr().dialogs, self._data.session, self._ctl.trash_days
        msg = d.trash_msg(days, self._data.total_messages) + (d.trash_active_extra if s.state == "ativa" else "")
        if not ConfirmDialog.ask(self._view, title=d.trash_title, message=msg, target=s.title, confirm_text=d.trash_ok):
            return
        self._ctl.submit(lambda mem: mem.sessions.delete(sid, to_trash=True), lambda _r: self._ctl.changed(tr().notices.trashed_title))

    def resume(self, sid: int) -> None:
        d, n = tr().dialogs, tr().notices
        if not ConfirmDialog.ask(self._view, title=d.resume_title, message=d.resume_msg, target=self._title_of(sid),
                                 confirm_text=d.resume_ok):
            return
        self._ctl.submit(lambda mem: mem.sessions.resume(sid), lambda _s: self._ctl.changed(n.resumed_title, n.resumed_detail))

    def restore(self, sid: int) -> None:
        n = tr().notices
        self._ctl.submit(lambda mem: mem.sessions.restore(sid), lambda _r: self._ctl.changed(n.restored_title, n.restored_detail))

    def empty_trash(self) -> None:
        if not self._rows or not self._ctl.editable:
            return
        d, n = tr().dialogs, tr().notices
        titles = [r.session.title for r in self._rows[:_TITLES_SHOWN]]
        if len(self._rows) > _TITLES_SHOWN:
            titles.append(plural(len(self._rows) - _TITLES_SHOWN, "outra conversa", "outras conversas"))
        if not ConfirmDialog.ask(self._view, title=d.empty_trash_title, message=d.empty_trash_msg, target="\n".join(titles),
                                 confirm_text=d.empty_trash_ok, destructive=True):
            return
        self._ctl.submit(lambda mem: mem.sessions.empty_trash(None),
                         lambda cnt: self._ctl.changed(n.trash_emptied_title, plural(int(cnt), "conversa apagada", "conversas apagadas")))
