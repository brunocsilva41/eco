"""Chamadas Win32 da Ilha (ctypes): nao roubar foco, click-through no repouso e deteccao de tela cheia.

Tudo e no-op fora do Windows. Nenhuma funcao levanta excecao: em falha, devolve o valor neutro.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_WIN = sys.platform == "win32"
GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_CAPTION = 0x00C00000
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

if _WIN:
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _s32 = ctypes.WinDLL("shell32", use_last_error=True)
    _u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _u32.GetForegroundWindow.restype = wintypes.HWND
    _u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u32.MonitorFromWindow.restype = wintypes.HANDLE
    _u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _u32.IsWindowVisible.argtypes = [wintypes.HWND]
    _u32.IsIconic.argtypes = [wintypes.HWND]
    _u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    _u32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]


def _hwnd(h: int) -> wintypes.HWND:
    return wintypes.HWND(h)


def ex_style(hwnd: int) -> int:
    return int(_u32.GetWindowLongPtrW(_hwnd(hwnd), GWL_EXSTYLE)) if _WIN and hwnd else 0


def _set_ex(hwnd: int, add: int = 0, remove: int = 0) -> None:
    if not (_WIN and hwnd):
        return
    cur = ex_style(hwnd)
    new = (cur | add) & ~remove
    if new != cur:
        _u32.SetWindowLongPtrW(_hwnd(hwnd), GWL_EXSTYLE, new)


def set_no_activate(hwnd: int) -> None:
    """A Ilha nunca ativa nem pega foco (o Jarvis digita/clica em outros apps)."""
    _set_ex(hwnd, add=WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)


def set_click_through(hwnd: int, on: bool) -> None:
    """Repouso: cliques passam para a janela de baixo; ativa: a Ilha recebe cliques."""
    if on:
        _set_ex(hwnd, add=WS_EX_LAYERED | WS_EX_TRANSPARENT)
    else:
        _set_ex(hwnd, add=WS_EX_LAYERED, remove=WS_EX_TRANSPARENT)


def fullscreen_app_active(own_hwnd: int = 0) -> bool:
    """True se ha app em tela cheia (jogo, video, F11) no primeiro plano.

    Combina SHQueryUserNotificationState (2 ocupado/tela cheia, 3 D3D exclusivo, 4 apresentacao)
    com uma checagem de retangulo da janela em primeiro plano (cobre tela cheia sem borda).
    """
    if not _WIN:
        return False
    try:
        state = ctypes.c_int(0)
        if _s32.SHQueryUserNotificationState(ctypes.byref(state)) == 0 and state.value in (2, 3, 4):
            return True
        fg = _u32.GetForegroundWindow()
        if not fg or int(fg) == own_hwnd or not _u32.IsWindowVisible(fg) or _u32.IsIconic(fg):
            return False
        cls = ctypes.create_unicode_buffer(64)
        _u32.GetClassNameW(fg, cls, 64)
        if cls.value in _SHELL_CLASSES:
            return False
        if int(_u32.GetWindowLongPtrW(fg, GWL_STYLE)) & WS_CAPTION == WS_CAPTION:
            return False            # janela normal/maximizada tem barra de titulo
        rect = wintypes.RECT()
        _u32.GetWindowRect(fg, ctypes.byref(rect))
        mon = _u32.MonitorFromWindow(fg, 2)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not mon or not _u32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return False
        m = info.rcMonitor
        return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom
    except Exception:
        return False
