"""Pontos de entrada da tela de Configuracoes: abrir dentro de um app Qt ou como programa proprio."""
from __future__ import annotations

import logging
import sys
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from jarvis.config import Config

from ..theme import ThemeManager
from .prefs import UiPrefs
from .window import SettingsWindow

log = logging.getLogger(__name__)
_instance: SettingsWindow | None = None


def collect_values(window: SettingsWindow) -> dict[str, Any]:
    """Valores atuais da tela como {'secao.campo': valor}."""
    return window.collect_values()


def apply_values(window: SettingsWindow, values: dict[str, Any]) -> None:
    """Preenche a tela com {'secao.campo': valor}; o que diferir do salvo aparece como alterado."""
    window.apply_values(values)


def open_settings(cfg: Config | None = None, parent: QWidget | None = None) -> SettingsWindow:
    """Abre (ou traz a frente) a tela de Configuracoes. Exige um ``QApplication`` ativo."""
    global _instance
    if QApplication.instance() is None:
        raise RuntimeError("open_settings precisa de um QApplication; use main_settings() fora da interface")
    existing = _instance
    if existing is not None:
        try:
            if existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return existing
        except RuntimeError:               # objeto Qt ja destruido
            _instance = None
    window = SettingsWindow(cfg, parent)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    _instance = window
    window.show()
    window.raise_()
    window.activateWindow()
    return window


def main_settings() -> int:
    """Executa a tela como programa proprio (cria o QApplication se preciso). Devolve o codigo de saida."""
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    if owns_app:
        UiPrefs().apply_saved_theme()
        ThemeManager.instance().apply(app)  # type: ignore[arg-type]
    try:
        window = open_settings()
    except Exception:  # noqa: BLE001
        log.exception("nao consegui abrir as configuracoes")
        return 1
    if not owns_app:
        return 0
    return int(app.exec()) if window is not None else 1
