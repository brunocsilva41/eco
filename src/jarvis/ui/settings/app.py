"""Pontos de entrada da tela de Configuracoes: abrir dentro de um app Qt ou como programa proprio."""
from __future__ import annotations

import logging
import sys
from typing import Any

from PySide6.QtCore import Qt, QTimer
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


def open_settings(cfg: Config | None = None, parent: QWidget | None = None,
                  open_section: str | None = None) -> SettingsWindow:
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
                existing.open_section(open_section)
                return existing
        except RuntimeError:               # objeto Qt ja destruido
            _instance = None
    window = SettingsWindow(cfg, parent)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    _instance = window
    from ..kit.visibility import show_after_first_paint
    show_after_first_paint(window)                  # sem o instante em branco antes de pintar
    window.raise_()
    window.activateWindow()
    QTimer.singleShot(0, lambda: window.open_section(open_section))   # depois do primeiro layout
    return window


_mutex_handle = None


def _another_instance_running() -> bool:
    """Trava entre processos: se já há uma tela de Configurações aberta, traz ela para a frente e devolve True."""
    global _mutex_handle
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    import os
    suffix = os.environ.get("JARVIS_TEST_INSTANCE", "")                       # testes usam trava própria: nunca tocam a janela do usuário
    handle = k32.CreateMutexW(None, False, "Local\\JarvisSettingsSingleton" + suffix)
    if ctypes.get_last_error() == 183 or ctypes.GetLastError() == 183:      # ERROR_ALREADY_EXISTS
        from .texts import T
        hwnd = u32.FindWindowW(None, T.window.title)
        if hwnd:
            u32.ShowWindow(ctypes.c_void_p(hwnd), 9)                       # SW_RESTORE
            u32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        return True
    _mutex_handle = handle                                                   # fica aberto até o processo sair
    return False


def main_settings(open_section: str | None = None) -> int:
    """Executa a tela como programa proprio (cria o QApplication se preciso). Devolve o codigo de saida."""
    if QApplication.instance() is None and _another_instance_running():
        return 0
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        try:                                                    # barra de tarefas própria (não agrupa com o Python) e ícone do app
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Eco.Settings")
        except (AttributeError, OSError):
            pass
        app = QApplication(sys.argv[:1])
        try:
            from ..tray import make_icon
            app.setWindowIcon(make_icon())
        except Exception:                                       # noqa: BLE001  (ícone é só enfeite)
            log.debug("sem ícone do app", exc_info=True)
    if owns_app:
        UiPrefs().apply_saved_theme()
        ThemeManager.instance().apply(app)  # type: ignore[arg-type]
    try:
        window = open_settings(open_section=open_section)
    except Exception:  # noqa: BLE001
        log.exception("nao consegui abrir as configuracoes")
        return 1
    if not owns_app:
        return 0
    return int(app.exec()) if window is not None else 1
