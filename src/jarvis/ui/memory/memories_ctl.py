"""Controlador da área Memórias: carrega a lista em segundo plano, liga a seleção ao detalhe e executa as ações."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog

from ...memory import MemoryItem
from ..kit import ConfirmDialog
from .controller import PanelController
from .dialogs import MemoryEditDialog
from .logic import FriendlyError
from .memories_area import MemoriesArea
from .rows import memory_rows
from .rowview import NO_KEY
from .service import MemoryList, delete_memory_for_good, load_memories
from .texts import tr

log = logging.getLogger(__name__)
_DAY = 86400


class MemoriesController(QObject):
    def __init__(self, ctl: PanelController, view: MemoriesArea, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctl = ctl
        self._view = view
        self._seq = 0
        self._items: dict[int, MemoryItem] = {}
        pane = view.pane
        pane.searchChanged.connect(self.refresh)
        pane.filterChanged.connect(self.refresh)
        pane.retryRequested.connect(self.refresh)
        pane.emptyActionTriggered.connect(self._empty_action)
        pane.currentKeyChanged.connect(self._on_select)
        pane.itemActivated.connect(self.edit)
        pane.deleteRequested.connect(self.delete)
        view.addRequested.connect(self.add)
        view.detail.editRequested.connect(self.edit)
        view.detail.pinToggled.connect(self.toggle_pin)
        view.detail.deleteRequested.connect(self.delete)

    # --- carga
    def refresh(self, *_ignored: object) -> None:
        t, pane = tr(), self._view.pane
        editable = self._ctl.editable
        self._view.add_button.setEnabled(editable)
        pane.set_inputs_enabled(self._ctl.can_read)
        if not self._ctl.persistent:
            self._items = {}
            pane.set_count("")
            pane.show_empty(t.no_history.empty_title, t.no_history.empty_memories, icon_name="alert")
            return
        if not self._ctl.can_read:
            pane.show_loading(t.memories.loading)               # o banco ainda abre; stateChanged recarrega
            return
        self._seq += 1
        seq, query, kind, keep = self._seq, pane.search_text(), pane.filter_value(), pane.current_key()
        if pane.row_count() == 0:
            pane.show_loading(t.memories.loading)
        self._ctl.submit(lambda mem: load_memories(mem, query, kind), lambda data: self._loaded(seq, data, keep),
                         on_error=self._load_failed)

    def _loaded(self, seq: int, data: MemoryList, keep: int) -> None:
        if seq != self._seq:
            return                                               # resposta velha: já pediram outra busca
        m, pane = tr().memories, self._view.pane
        self._items = {i.id: i for i in data.items}
        self._view.detail.set_idle(m.detail_none_title if data.items else m.detail_idle_title,
                                   m.detail_none_body if data.items else m.detail_idle_body)
        filtering = pane.is_filtering() or pane.filter_value() is not None
        pane.set_count(m.count_filtered(len(data.items), data.total) if filtering else m.count(data.total, data.pinned))
        if data.items:
            pane.set_rows(memory_rows(data.items, time.time()), keep if keep != NO_KEY else None)
        elif filtering:
            pane.show_empty(m.no_match_title, m.no_match_body, m.no_match_action, icon_name="search")
        else:
            pane.show_empty(m.empty_title, m.empty_body, m.empty_action, icon_name="memory")

    def _load_failed(self, err: FriendlyError) -> None:
        self._items = {}
        self._view.pane.set_count("")
        self._view.pane.show_error(err.what, err.why, err.todo)

    def _on_select(self, key: int) -> None:
        self._view.detail.show_item(self._items.get(key) if key != NO_KEY else None, self._ctl.editable)

    def _empty_action(self) -> None:
        pane = self._view.pane
        if pane.is_filtering() or pane.filter_value() is not None:
            pane.set_search_text("")
            pane.set_filter_value(None)
        else:
            self.add()

    # --- ações
    def add(self) -> None:
        if not self._ctl.editable:
            return
        dlg = MemoryEditDialog(self._view, new=True)
        if dlg.exec() != QDialog.DialogCode.Accepted or (v := dlg.result_value()) is None:
            return
        expires = time.time() + v.expires_days * _DAY if v.expires_days else None
        self._ctl.submit(lambda mem: mem.longterm.remember(v.text, v.kind, "usuario", expires_at=expires, pinned=v.pinned),
                         lambda _id: self._ctl.changed(tr().notices.saved_title))

    def edit(self, key: int) -> None:
        item = self._items.get(key)
        if item is None or not self._ctl.editable:
            return
        dlg = MemoryEditDialog(self._view, new=False, text=item.text)
        if dlg.exec() != QDialog.DialogCode.Accepted or (v := dlg.result_value()) is None:
            return
        self._ctl.submit(lambda mem: mem.longterm.edit(item.id, v.text), lambda _r: self._ctl.changed(tr().notices.edited_title))

    def toggle_pin(self, key: int, pinned: bool) -> None:
        n = tr().notices
        self._ctl.submit(lambda mem: mem.longterm.pin(key, pinned),
                         lambda _r: self._ctl.changed(n.pinned_title if pinned else n.unpinned_title))

    def delete(self, key: int) -> None:
        item = self._items.get(key)
        if item is None or not self._ctl.editable:
            return
        d = tr().dialogs
        if not ConfirmDialog.ask(self._view, title=d.delete_memory_title, message=d.delete_memory_msg, target=item.text,
                                 confirm_text=d.delete_memory_ok, destructive=True):
            return
        self._ctl.submit(lambda mem: delete_memory_for_good(mem, item.id),
                         lambda _r: self._ctl.changed(tr().notices.deleted_title))

