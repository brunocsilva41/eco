"""Faixa de avisos no topo do conteudo: resultado da gravacao (o que ja vale e o que exige reiniciar), erro de
gravacao, arquivo mudou em disco e arquivo ilegivel. Cada aviso ocupa um "slot" e substitui o anterior.
Sem regra de negocio: recebe fatos prontos e emite pedidos.
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from jarvis.settings.control import Runtime

from ..kit.buttons import Button
from ..kit.feedback import InlineBanner
from ..theme import SPACE
from .model import SaveOutcome
from .texts import T

_MAX_LISTED = 8
SLOT_RESULT, SLOT_DISK, SLOT_LOAD = "result", "disk", "load"


def summarize(keys: Iterable[str]) -> str:
    names = [T.label_for(k) for k in keys]
    shown = ", ".join(names[:_MAX_LISTED])
    extra = len(names) - _MAX_LISTED
    return f"{shown} {T.banner.more.format(n=extra)}" if extra > 0 else shown


class Banners(QWidget):
    applyRequested = Signal()
    restartRequested = Signal()
    reloadRequested = Signal()
    keepRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(SPACE.xl, SPACE.lg, SPACE.xl, 0)
        self._lay.setSpacing(SPACE.sm)
        self._slots: dict[str, QWidget] = {}
        self._actions: QWidget | None = None
        self._apply: Button | None = None
        self._restart: Button | None = None
        self.hide()

    # ---- slots
    def _put(self, slot: str, widget: QWidget | None) -> None:
        old = self._slots.pop(slot, None)
        if old is not None:
            if slot == SLOT_RESULT:
                self._actions = self._apply = self._restart = None
            old.setParent(None)
            old.deleteLater()
        if widget is not None:
            self._slots[slot] = widget
            self._lay.addWidget(widget)
        self.setVisible(bool(self._slots))

    def clear(self) -> None:
        for slot in list(self._slots):
            self._put(slot, None)

    def has(self, slot: str) -> bool:
        return slot in self._slots

    # ---- avisos
    def show_saved(self, outcome: SaveOutcome) -> None:
        b, ch, running = T.banner, outcome.result.changes, outcome.running
        why = todo = ""
        if not ch.any:
            why = b.nothing
        elif running:
            why = b.live_after.format(items=summarize(ch.live)) if ch.live else ""
            todo = b.needs_restart.format(items=summarize(ch.restart)) if ch.restart else ""
        else:
            why = b.next_open.format(items=summarize((*ch.live, *ch.restart)))
        if not running:
            todo = b.closed
        if outcome.pending_restart:
            todo = f"{todo} {b.pending.format(items=summarize(outcome.pending_restart))}".strip()
        state = "warn" if running and ch.restart else "ok"
        title = b.reset_done if outcome.reset else b.saved
        banner = InlineBanner(state, title, why, todo, dismissible=True)
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.sm)
        col.addWidget(banner)
        self._put(SLOT_RESULT, box)
        banner.dismissed.connect(lambda: self._put(SLOT_RESULT, None))
        if running:
            self._actions = QWidget()
            row = QHBoxLayout(self._actions)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(SPACE.sm)
            self._apply = Button(b.apply_now, variant="primary", icon_name="refresh")
            self._apply.setEnabled(bool(ch.live))
            self._apply.clicked.connect(self.applyRequested)
            self._restart = Button(b.restart)
            self._restart.clicked.connect(self.restartRequested)
            row.addWidget(self._apply)
            row.addWidget(self._restart)
            row.addStretch(1)
            col.addWidget(self._actions)

    def set_runtime(self, rt: Runtime | None) -> None:
        """O Jarvis fechou depois de salvar: some 'Aplicar agora' e 'Reiniciar'."""
        if rt is None and self._actions is not None:
            self._actions.hide()

    def mark_requested(self, kind: str) -> None:
        button = self._apply if kind == "reload" else self._restart
        if button is not None:
            button.setEnabled(False)

    def show_error(self, what: str, why: str, todo: str, *, slot: str = SLOT_RESULT) -> None:
        banner = InlineBanner.error(what, why, todo, dismissible=True)
        banner.dismissed.connect(lambda: self._put(slot, None))
        self._put(slot, banner)

    def show_write_error(self, kind: str, detail: str) -> None:
        b = T.banner
        why = {"permission": b.write_permission, "disk": b.write_disk.format(detail=detail)}.get(
            kind, b.write_other.format(detail=detail))
        self.show_error(b.write_what, why, b.write_todo)

    def show_load_error(self, detail: str) -> None:
        b = T.banner
        self.show_error(b.load_what, b.load_why, b.load_todo.format(detail=detail), slot=SLOT_LOAD)

    def show_reload_error(self, detail: str) -> None:
        b = T.banner
        self.show_error(b.reload_what, b.reload_why.format(detail=detail), b.reload_todo)

    def show_request_error(self, detail: str) -> None:
        b = T.banner
        self.show_error(b.request_what, detail, b.request_todo)

    def show_blocked(self) -> None:
        self.show_error(T.window.fix_before_save, T.window.fix_before_save_why, "")

    def show_disk(self, changed: bool) -> None:
        if not changed:
            self._put(SLOT_DISK, None)
            return
        b = T.banner
        banner = InlineBanner("warn", b.disk_what, b.disk_why, b.disk_todo, action_text=b.disk_reload, dismissible=True)
        banner.actionTriggered.connect(self.reloadRequested)
        banner.dismissed.connect(self.keepRequested)
        self._put(SLOT_DISK, banner)
