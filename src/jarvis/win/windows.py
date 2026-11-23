"""Janelas do Windows: listar, achar a ativa, focar, fechar e descobrir o processo dono.

Só enumera janelas "de verdade" (visíveis, com título, não encobertas/fantasmas de UWP).
Títulos vêm de programas externos: quem os repassa ao modelo deve tratá-los como dado não confiável.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, Final

from ..core.textutil import fold
from .input import VK_MENU, tap_key

if TYPE_CHECKING:
    from ..config import Config

log = logging.getLogger(__name__)

GWL_EXSTYLE: Final = -20
WS_EX_TOOLWINDOW: Final = 0x00000080
WS_EX_APPWINDOW: Final = 0x00040000
SW_RESTORE: Final = 9
WM_CLOSE: Final = 0x0010
DWMWA_CLOAKED: Final = 14
PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
GW_OWNER: Final = 4

OWN_WINDOW_MESSAGE: Final = "Essa é uma janela do próprio Eco; mexa nela você mesmo."
DIALOG_CLASS: Final = "#32770"       # classe padrão dos diálogos do Windows (Salvar como, Abrir, Imprimir, avisos)
# Títulos típicos de diálogos de arquivo/impressão, sem acento e em minúsculas (comparação com `fold`).
_DIALOG_TITLES: Final = frozenset({
    "salvar como", "salvar", "salvar arquivo", "salvar arquivo como", "abrir", "abrir arquivo", "imprimir",
    "save as", "save", "save file", "open", "open file", "print", "print setup", "configurar impressao",
})
_PYTHON_EXE: Final = re.compile(r"^pythonw?\d*(\.\d+)*\.exe$")

_IGNORED_CLASSES: Final = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"})
_FOCUS_WAIT_S: Final = 0.5

from .native import load_dll  # noqa: E402

_user32 = load_dll("user32")
_kernel32 = load_dll("kernel32")
_dwmapi = load_dll("dwmapi")

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
_user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_user32.GetWindowRect.restype = wintypes.BOOL
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


def _process_path_of_pid(pid: int) -> str | None:
    """Caminho completo do executável do processo, ou None se sem permissão/inexistente."""
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
        return buf.value or None
    finally:
        _kernel32.CloseHandle(handle)


def _process_name_of_pid(pid: int) -> str | None:
    path = _process_path_of_pid(pid)
    return (PureWindowsPath(path).name or None) if path else None


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


def class_name(hwnd: int) -> str:
    """Nome da classe da janela ('' se não existe)."""
    return _class_name(hwnd) if hwnd else ""


def owner_hwnd(hwnd: int) -> int:
    """Handle da janela DONA (GW_OWNER); 0 se não tem dono. Diálogos modais têm dono."""
    return int(_user32.GetWindow(hwnd, GW_OWNER) or 0) if hwnd else 0


def window_at(x: int, y: int) -> "WindowInfo | None":
    """Janela de nível superior sob o pixel físico (x, y), ou None (área de trabalho, janela sem título)."""
    _user32.WindowFromPoint.argtypes = (wintypes.POINT,)
    _user32.WindowFromPoint.restype = wintypes.HWND
    _user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    _user32.GetAncestor.restype = wintypes.HWND
    hwnd = _user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hwnd:
        return None
    root = _user32.GetAncestor(hwnd, 2) or hwnd                      # GA_ROOT
    return _describe(int(root))


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Retângulo (esquerda, topo, direita, base) da janela em pixels físicos, ou None se não deu para ler."""
    rect = wintypes.RECT()
    if not hwnd or not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def is_dialog_window(hwnd_or_info: "int | WindowInfo") -> bool:
    """True se a janela parece um diálogo (Salvar como, Abrir, Imprimir...): classe #32770, janela DONA ou título típico.

    Qualquer dos três basta (defesa em profundidade). Se não dá para ler a janela, devolve True (falha fechada).
    """
    info = hwnd_or_info if isinstance(hwnd_or_info, WindowInfo) else describe_window(int(hwnd_or_info))
    if info is None:
        return True
    if _class_name(info.hwnd) == DIALOG_CLASS or owner_hwnd(info.hwnd) != 0:
        return True
    title = fold(info.title)
    return title in _DIALOG_TITLES or title.split(" - ", 1)[0] in _DIALOG_TITLES


def is_own_process_window(hwnd_or_info: "int | WindowInfo", cfg: "Config") -> bool:
    """True se a janela é do próprio Eco (Configurações, Gravador, Painel de memória...).

    Vale se (a) o PID é o deste processo, OU (b) o executável está dentro de `<raiz do projeto>\\venv`, OU
    (c) o título começa com "Eco" e o processo é python/pythonw (cobre o relançador do venv). Se a janela
    não pode ser lida, devolve False (não há como afirmar); quem age deve ter outras guardas.
    """
    info = hwnd_or_info if isinstance(hwnd_or_info, WindowInfo) else describe_window(int(hwnd_or_info))
    if info is None:
        return False
    if info.pid == os.getpid():
        return True
    exe = _process_path_of_pid(info.pid)
    if exe:
        try:
            venv = tuple(p.casefold() for p in PureWindowsPath(os.path.abspath(cfg.paths.root / "venv")).parts)
            parts = tuple(p.casefold() for p in PureWindowsPath(os.path.abspath(exe)).parts)
            if len(parts) > len(venv) and parts[:len(venv)] == venv:
                return True
        except (OSError, ValueError):
            log.debug("não consegui comparar o executável da janela 0x%X com o venv", info.hwnd, exc_info=True)
    name = (info.process or "").casefold()
    return fold(info.title).startswith("eco") and bool(_PYTHON_EXE.match(name))


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


SW_MINIMIZE: Final = 6
SW_MAXIMIZE: Final = 3


def show_window(hwnd: int, cmd: int) -> bool:
    """ShowWindow (SW_MINIMIZE=6, SW_MAXIMIZE=3, SW_RESTORE=9)."""
    return bool(is_window(hwnd) and _user32.ShowWindow(ctypes.c_void_p(hwnd), cmd) is not None)


def work_area() -> tuple[int, int, int, int]:
    """Área útil do monitor principal (sem a barra de tarefas): (esquerda, topo, direita, base) em pixels físicos."""
    rect = wintypes.RECT()
    _user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)      # SPI_GETWORKAREA
    return rect.left, rect.top, rect.right, rect.bottom


def move_window(hwnd: int, x: int, y: int, w: int, h: int) -> bool:
    """Restaura (se maximizada/minimizada) e posiciona a janela. Sem mudar a ordem nem roubar foco."""
    if not is_window(hwnd):
        return False
    _user32.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
    return bool(_user32.SetWindowPos(ctypes.c_void_p(hwnd), None, int(x), int(y), int(w), int(h), 0x0014))   # NOZORDER|NOACTIVATE


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
