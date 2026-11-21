"""Confirmacoes do gravador (substituir gravacao, fechar gravando) sempre com o alvo real na caixa."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ...recording.session import RecordingSession
from ..kit.dialogs import ConfirmDialog
from .texts import T


def confirm_overwrite(host: QWidget, session: RecordingSession, index: int) -> bool:
    c = T.confirms
    name = session.recording_set.filename(index)
    return ConfirmDialog.ask(host, title=c.overwrite_title, message=c.overwrite_message(name),
                             target=f"{name}: {session.recording_set.label(index)}", destructive=True,
                             confirm_text=c.overwrite_confirm, cancel_text=c.overwrite_cancel)


def confirm_close_recording(host: QWidget, phrase: str) -> bool:
    c = T.confirms
    return ConfirmDialog.ask(host, title=c.close_title, message=c.close_message, target=phrase, destructive=True,
                             confirm_text=c.close_confirm, cancel_text=c.close_cancel)
