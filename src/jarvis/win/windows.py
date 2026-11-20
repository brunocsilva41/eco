"""Janelas do Windows: listar, achar a ativa, focar, fechar e descobrir o processo dono.

Só enumera janelas "de verdade" (visíveis, com título, não encobertas/fantasmas de UWP).
Títulos vêm de programas externos: quem os repassa ao modelo deve tratá-los como dado não confiável.
"""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Final

from .input import VK_MENU, tap_key

log = logging.getLogger(__name__)

GWL_EXSTYLE: Final = -20
WS_EX_TOOLWINDOW: Final = 0x00000080
WS_EX_APPWINDOW: Final = 0x00040000
SW_RESTORE: Final = 9
WM_CLOSE: Final = 0x0010
DWMWA_CLOAKED: Final = 14
PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000

_IGNORED_CLASSES: Final = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"})
_FOCUS_WAIT_S: Final = 0.5

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.EnumWindows.argtypes = (_WNDENUMPROC, wintypes.LPARAM)
_user32.EnumWindows.restype = wintypes.BOOL
_user32.IsWindow.argtypes = (wintypes.HWND,)
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = (wintypes.HWND,)
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.IsIconic.argtypes = (wintypes.HWND,)
_user32.IsIconic.restype = wintypes.BOOL
_user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetWindowLongW.restype = wintypes.LONG
_user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetForegroundWindow.argtypes = ()
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.BringWindowToTop.argtypes = (wintypes.HWND,)
_user32.BringWindowToTop.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.ShowWindow.restype = wintypes.BOOL
_user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
_user32.AttachThreadInput.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.PostMessageW.restype = wintypes.BOOL
_kernel32.GetCurrentThreadId.argtypes = ()
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_dwmapi.DwmGetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process: str | None      # nome do executável (ex.: "notepad.exe"); None se sem permissão


# ----------------------------------------------------------------- leitura de propriedades
def _title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.strip()


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _is_cloaked(hwnd: int) -> bool:
    """Janelas UWP 'fantasma' e de outras áreas de trabalho virtuais ficam 'cloaked'."""
    value = wintypes.DWORD(0)
    hr = _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return hr == 0 and value.value != 0


def _pid_of(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def process_name(hwnd: int) -> str | None:
    """Nome do executável dono da janela (QueryFullProcessImageNameW), ou None se não der para ler."""
    return _process_name_of_pid(_pid_of(hwnd))


def _process_name_of_pid(pid: int) -> str | None:
    if pid <= 0:
        return None
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return PureWindowsPath(buf.value).name or None
    finally:
        _kernel32.CloseHandle(handle)


def _is_real_window(hwnd: int) -> bool:
    if not _user32.IsWindowVisible(hwnd) or _is_cloaked(hwnd):
        return False
    if _class_name(hwnd) in _IGNORED_CLASSES:
        return False
    ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    return not (ex & WS_EX_TOOLWINDOW and not ex & WS_EX_APPWINDOW)


def _describe(hwnd: int) -> WindowInfo | None:
    title = _title(hwnd)
    if not title:
        return None
    pid = _pid_of(hwnd)
    return WindowInfo(hwnd, title, pid, _process_name_of_pid(pid))


# ----------------------------------------------------------------- API pública
def list_windows() -> list[WindowInfo]:
    """Janelas visíveis e com título, na ordem Z (a de cima primeiro)."""
    found: list[WindowInfo] = []

    @_WNDENUMPROC
    def _callback(hwnd: int, _lparam: int) -> bool:
        try:
            if _is_real_window(hwnd):
                info = _describe(hwnd)
                if info is not None:
                    found.append(info)
        except Exception:  # noqa: BLE001 - uma janela ruim não pode derrubar a enumeração
            log.debug("janela 0x%X ignorada na enumeração", hwnd or 0, exc_info=True)
        return True

    if not _user32.EnumWindows(_callback, 0):
        raise OSError(f"EnumWindows falhou (erro {ctypes.get_last_error()})")
    return found


def foreground_window() -> WindowInfo | None:
    """Janela em primeiro plano, ou None (sem foco, área de trabalho ou janela sem título)."""
    hwnd = _user32.GetForegroundWindow()
    return _describe(hwnd) if hwnd else None


def foreground_hwnd() -> int:
    """Handle da janela em primeiro plano (0 se não há; barato, serve de guarda a cada bloco digitado)."""
    return int(_user32.GetForegroundWindow() or 0)


def pid_of(hwnd: int) -> int:
    """PID do processo dono da janela (0 se a janela não existe mais)."""
    return _pid_of(hwnd)


def describe_window(hwnd: int) -> WindowInfo | None:
    """Estado ATUAL de uma janela pelo handle (None se não existe mais ou ficou sem título)."""
    if not hwnd or not is_window(hwnd):
        return None
    return _describe(hwnd)


def is_window(hwnd: int) -> bool:
    return bool(_user32.IsWindow(hwnd))


def _is_foreground(hwnd: int) -> bool:
    return (_user32.GetForegroundWindow() or 0) == hwnd


def _wait_foreground(hwnd: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        if _is_foreground(hwnd):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.03)


def focus_window(hwnd: int) -> bool:
    """Traz a janela para frente (restaura se minimizada). False se o Windows recusar.

    Tenta SetForegroundWindow direto; se falhar, anexa a fila de entrada à thread da janela em
    primeiro plano (AttachThreadInput); como último recurso, um toque de ALT libera a trava.
    """
    if not is_window(hwnd):
        return False
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)

    _user32.SetForegroundWindow(hwnd)
    if _wait_foreground(hwnd, 0.1):
        return True

    fg = _user32.GetForegroundWindow()
    fg_thread = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = _kernel32.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and _user32.AttachThreadInput(me, fg_thread, True))
    try:
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(me, fg_thread, False)
    if _wait_foreground(hwnd, _FOCUS_WAIT_S):
        return True

    try:
        tap_key(VK_MENU)
    except OSError as exc:
        log.debug("toque de ALT bloqueado: %s", exc)
    _user32.SetForegroundWindow(hwnd)
    ok = _wait_foreground(hwnd, _FOCUS_WAIT_S)
    if not ok:
        log.warning("o Windows recusou focar a janela 0x%X", hwnd)
    return ok


def close_window(hwnd: int) -> bool:
    """Pede o fechamento educado (WM_CLOSE): o programa pode perguntar se quer salvar.

    True se a mensagem foi postada. Não garante que a janela fechou: use `is_window` depois.
    """
    if not is_window(hwnd):
        return False
    if not _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
        log.warning("PostMessage(WM_CLOSE) falhou para 0x%X (erro %d)", hwnd, ctypes.get_last_error())
        return False
    return True
