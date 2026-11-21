"""Lista de microfones do seletor: leitura em segundo plano e escolha preservada entre leituras."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject

from ...audio.devices import DeviceSpec
from ...recording.recorder import InputChoice
from ..kit.tasks import run_async
from . import model
from .services import Services
from .view import RecorderView

log = logging.getLogger(__name__)


class MicPicker(QObject):
    """Preenche o seletor da vista. Nao grava nem abre microfone: so lista (``Services.list_choices``)."""

    def __init__(self, view: RecorderView, services: Services, configured: DeviceSpec, owner: QObject) -> None:
        super().__init__(owner)
        self._view = view
        self._services = services
        self._configured = configured
        self._ready = False
        self._token = 0

    def refresh(self, rescan: bool, on_done: Callable[[], None] | None = None,
                on_fail: Callable[[str], None] | None = None) -> None:
        """Le a lista (``rescan`` forca o PortAudio a reler). Chame so com microfone e som parados."""
        previous = self._view.mic_spec() if self._ready else self._configured
        self._token += 1
        token = self._token
        lister = self._services.list_choices

        def done(choices: list[InputChoice]) -> None:
            if token == self._token:
                self._show(choices, previous)
                if on_done is not None:
                    on_done()

        def failed(detail: str) -> None:
            if token == self._token:
                log.warning("nao consegui listar os microfones: %s", detail)
                self._show([], previous)
                if on_fail is not None:
                    on_fail(detail)

        run_async(lambda: lister(rescan), self, done, failed)

    def invalidate(self) -> None:
        """Descarta o que ainda estiver sendo lido (janela fechando)."""
        self._token += 1

    def _show(self, choices: list[InputChoice], previous: DeviceSpec) -> None:
        items, selected = model.build_mic_items(choices, previous)
        self._view.set_mics(items, selected)
        self._ready = True
