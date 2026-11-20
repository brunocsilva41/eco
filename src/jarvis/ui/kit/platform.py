"""Preferencias do Windows lidas pelo tema: 'reduzir animacoes' e tema claro/escuro do sistema."""
from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

_motion_override: bool | None = None


def set_motion_override(enabled: bool | None) -> None:
    """Forca animacoes ligadas/desligadas (None = seguir o Windows). Para Configuracoes e capturas."""
    global _motion_override
    _motion_override = enabled


def motion_enabled() -> bool:
    """False se o usuario pediu 'reduzir animacoes' no Windows (SPI_GETCLIENTAREAANIMATION)."""
    if _motion_override is not None:
        return _motion_override
    if os.environ.get("JARVIS_REDUCE_MOTION") == "1":
        return False
    if sys.platform != "win32":
        return True
    flag = ctypes.c_int(1)
    ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)  # type: ignore[attr-defined]
    return bool(flag.value) if ok else True


def system_prefers_dark() -> bool:
    """Tema do Windows: QStyleHints.colorScheme (Qt 6.5+), com o registro como reserva."""
    hints = QGuiApplication.styleHints() if QGuiApplication.instance() else None
    scheme = hints.colorScheme() if hints is not None else Qt.ColorScheme.Unknown
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            return True
    return True
