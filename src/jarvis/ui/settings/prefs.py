"""Preferencias de interface guardadas no Windows (QSettings): tema e posicao/tamanho da janela.

Ficam FORA do config do Jarvis de proposito: sao gosto desta tela neste computador, nao comportamento do
assistente. O tema usa a mesma chave para todas as janelas do Jarvis (``load_theme_mode``).
"""
from __future__ import annotations

import logging
from typing import Final, cast

from PySide6.QtCore import QByteArray, QSettings
from PySide6.QtWidgets import QWidget

from ..theme import Mode, ThemeManager

log = logging.getLogger(__name__)

ORGANIZATION: Final = "Jarvis"
APPLICATION: Final = "Jarvis"
_THEME_KEY: Final = "ui/theme_mode"
_GEOMETRY_KEY: Final = "settings/geometry"
_MODES: Final = ("dark", "light", "system")


class UiPrefs:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._s = settings or QSettings(ORGANIZATION, APPLICATION)

    def theme_mode(self) -> Mode:
        raw = str(self._s.value(_THEME_KEY, "system"))
        return cast(Mode, raw if raw in _MODES else "system")

    def set_theme_mode(self, mode: Mode) -> None:
        self._s.setValue(_THEME_KEY, mode)
        self._s.sync()

    def apply_saved_theme(self) -> None:
        """Poe o tema guardado no ThemeManager (chame antes de ``ThemeManager.apply``)."""
        ThemeManager.instance().set_mode(self.theme_mode())

    def restore_geometry(self, window: QWidget) -> bool:
        data = self._s.value(_GEOMETRY_KEY)
        if isinstance(data, QByteArray) and not data.isEmpty():
            return bool(window.restoreGeometry(data))
        return False

    def save_geometry(self, window: QWidget) -> None:
        self._s.setValue(_GEOMETRY_KEY, window.saveGeometry())
        self._s.sync()


def load_theme_mode() -> Mode:
    """Modo de tema guardado (para qualquer janela do Jarvis)."""
    return UiPrefs().theme_mode()
