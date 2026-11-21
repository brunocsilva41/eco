"""Acoes do editor de frases: dialogos e confirmacoes. A regra (validar, gravar, sincronizar) e do ``PhraseEditor``."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

from PySide6.QtWidgets import QWidget

from ...recording.phrasebook import PhraseError
from ...recording.session import RecordingSession
from ..kit.dialogs import ConfirmDialog
from .model import PhraseEditor
from .phrase_dialog import PhraseDialog
from .presenter import failure
from .state import Notice
from .texts import T

log = logging.getLogger(__name__)

EditKind = Literal["add", "edit", "remove", "move"]


class PhraseActions:
    """Cada metodo devolve a posicao a selecionar depois da mudanca, ou ``None`` se foi cancelado ou falhou.

    ``source`` entrega a sessao e o editor atuais; ``idle`` diz se pode editar agora (nao grava nem salva).
    """

    def __init__(self, host: QWidget, notify: Callable[[Notice], None],
                 source: Callable[[], tuple[RecordingSession | None, PhraseEditor | None]],
                 idle: Callable[[], bool]) -> None:
        self._host = host
        self._notify = notify
        self._source = source
        self._idle = idle

    def _filename(self, index: int) -> str:
        session, _editor = self._source()
        return session.recording_set.filename(index) if session else ""

    def run(self, kind: EditKind, delta: int = 0) -> int | None:
        """Executa a edicao pedida no item atual. Devolve o item a selecionar ou ``None`` (nada mudou)."""
        session, editor = self._source()
        if editor is None or session is None or not self._idle():
            return None
        if kind == "add":
            return self.add(editor)
        if not session.count:
            return None
        if kind == "edit":
            return self.edit(editor, session.index)
        if kind == "remove":
            return self.remove(editor, session.index)
        return self.move(editor, session.index, delta) if 0 <= session.index + delta < session.count else None

    def _blocked(self, editor: PhraseEditor) -> bool:
        if editor.writable:
            return False
        self._notify(failure(T.failures.edit_blocked))
        return True

    def _confirm_paired(self, editor: PhraseEditor, indexes: list[int], action: str) -> bool:
        """Pede confirmacao quando algum dos itens ja tem gravacao ligada pelo numero."""
        recorded = [i for i in indexes if editor.has_recording(i)]
        if not recorded:
            return True
        e = T.editor
        files = ", ".join(self._filename(i) for i in recorded)
        return ConfirmDialog.ask(self._host, title=e.paired_title, message=e.paired_message(files, action),
                                 target=editor.phrase(recorded[0]), confirm_text=e.paired_confirm, destructive=True)

    def _attempt(self, work: Callable[[], int | None]) -> int | None:
        try:
            return work()
        except PhraseError as exc:
            log.warning("edicao de frase recusada: %s", exc)
            self._notify(Notice("warn", str(exc)))
            return None

    def add(self, editor: PhraseEditor) -> int | None:
        if self._blocked(editor):
            return None
        text = PhraseDialog.ask(self._host, title=T.editor.add_title, validator=editor.check)
        return None if text is None else self._attempt(lambda: editor.add(text))

    def edit(self, editor: PhraseEditor, index: int) -> int | None:
        if self._blocked(editor) or not self._confirm_paired(editor, [index], T.editor.paired_edit):
            return None
        text = PhraseDialog.ask(self._host, title=T.editor.edit_title, initial=editor.phrase(index),
                                validator=lambda t: editor.check(t, ignore=index))
        return None if text is None else self._attempt(lambda: editor.edit(index, text))

    def remove(self, editor: PhraseEditor, index: int) -> int | None:
        if self._blocked(editor) or not self._confirm_paired(editor, [index], T.editor.paired_remove):
            return None
        e = T.editor
        if not ConfirmDialog.ask(self._host, title=e.remove_title, message=e.remove_message,
                                 target=editor.phrase(index), confirm_text=e.remove_confirm, destructive=True):
            return None
        return self._attempt(lambda: editor.remove(index))

    def move(self, editor: PhraseEditor, index: int, delta: int) -> int | None:
        """``index + delta`` precisa estar dentro da lista (quem chama garante)."""
        if self._blocked(editor):
            return None
        if not self._confirm_paired(editor, [index, index + delta], T.editor.paired_move):
            return None
        return self._attempt(lambda: editor.move(index, delta))
