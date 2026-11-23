"""Controlador da área Armazenamento e privacidade: números reais, cópia, exportação e as exclusões em massa."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject

from ..kit import ConfirmDialog
from .controller import PanelController, choose_save_path
from .logic import FriendlyError, fmt_mb
from .service import Stats, delete_all_sessions, file_size_bytes, load_stats
from .storage_area import StorageArea
from .texts import plural, tr

log = logging.getLogger(__name__)


class StorageController(QObject):
    def __init__(self, ctl: PanelController, view: StorageArea, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctl = ctl
        self._view = view
        self._seq = 0
        view.backupRequested.connect(self.backup)
        view.exportAllRequested.connect(self.export_all)
        view.refreshRequested.connect(self.refresh)
        view.wipeMemoriesRequested.connect(self.wipe_memories)
        view.wipeConversationsRequested.connect(self.wipe_conversations)

    def refresh(self, *_ignored: object) -> None:
        s, ctl, view = tr().storage, self._ctl, self._view
        mcfg = ctl.cfg.memory
        view.show_mode(ctl.persistent)
        view.set_facts(str(ctl.db_path), s.retention(mcfg.conversation_ttl_days, ctl.trash_days))
        view.set_editable(ctl.editable)
        if not ctl.persistent:
            view.show_counts_message(s.none_stored)
            view.set_size_text(s.calculating)
            path = ctl.db_path
            ctl.submit_plain(lambda: file_size_bytes(path), self._old_file)
            return
        if not ctl.can_read:
            view.show_counts_message(s.opening)
            view.set_size_text(s.opening)
            return
        self._seq += 1
        seq, path = self._seq, ctl.db_path
        view.show_counts_message(s.calculating)
        view.set_size_text(s.calculating)
        ctl.submit(lambda mem: load_stats(mem, path), lambda st: self._stats(seq, st), on_error=self._failed)

    def _stats(self, seq: int, st: Stats) -> None:
        if seq == self._seq:
            self._view.show_stats(st)

    def _old_file(self, size: object) -> None:
        s = tr().storage
        n = int(size) if isinstance(size, int) else 0
        self._view.set_size_text(s.old_file.format(size=fmt_mb(n)) if n > 0 else s.no_file)

    def _failed(self, err: FriendlyError) -> None:
        self._view.show_counts_message(f"{err.what}. {err.why}")
        self._view.set_size_text("-")

    # --- cópia e exportação
    def backup(self) -> None:
        d, n = tr().dialogs, tr().notices
        picked = choose_save_path(self._view, d.backup_title, f"eco-backup-{time.strftime('%Y%m%d-%H%M')}.db",
                                  d.backup_filter, (".db", ".sqlite", ".sqlite3"), ".db")
        if picked is not None:
            self._ctl.submit(lambda mem: mem.backup_to(picked), lambda p: self._ctl.notify("ok", n.backup_title, f"{p}. {n.backup_note}"))

    def export_all(self) -> None:
        d, n = tr().dialogs, tr().notices
        picked: Path | None = choose_save_path(self._view, d.export_all_title, f"eco-dados-{time.strftime('%Y%m%d')}.json",
                                               d.export_all_filter, (".json",), ".json")
        if picked is not None:
            self._ctl.submit(lambda mem: mem.export_all_json(picked),
                             lambda p: self._ctl.notify("ok", n.exported_all_title, f"{p}. {n.exported_note}"))

    # --- exclusões em massa: leem os números na hora, mostram o alvo real e exigem a palavra APAGAR
    def wipe_memories(self) -> None:
        if self._ctl.editable:
            self._ctl.submit(lambda mem: load_stats(mem, None), self._confirm_wipe_memories)

    def _confirm_wipe_memories(self, st: Stats) -> None:
        d, n = tr().dialogs, tr().notices
        if not ConfirmDialog.ask(self._view, title=d.wipe_memories_title, message=d.wipe_memories_msg(st.memories, st.pinned),
                                 target=d.wipe_memories_target(st.memories, st.pinned), confirm_text=d.wipe_memories_ok,
                                 destructive=True, require_word=d.word):
            return
        self._ctl.submit(lambda mem: mem.longterm.purge_all(vacuum=True),
                         lambda cnt: self._ctl.changed(n.wiped_memories_title, plural(int(cnt), "memória apagada", "memórias apagadas")))

    def wipe_conversations(self) -> None:
        if self._ctl.editable:
            self._ctl.submit(lambda mem: load_stats(mem, None), self._confirm_wipe_conversations)

    def _confirm_wipe_conversations(self, st: Stats) -> None:
        d, n = tr().dialogs, tr().notices
        if not ConfirmDialog.ask(self._view, title=d.wipe_conversations_title, message=d.wipe_conversations_msg,
                                 target=d.wipe_conversations_target(st.sessions, st.trashed, st.messages),
                                 confirm_text=d.wipe_conversations_ok, destructive=True, require_word=d.word):
            return
        self._ctl.submit(delete_all_sessions, lambda cnt: self._ctl.changed(
            n.wiped_conversations_title, plural(int(cnt), "conversa apagada", "conversas apagadas")))
