"""Envio para a Lixeira do Windows (SHFileOperationW). NUNCA apaga de forma permanente.

Cuidado conhecido do Windows: com FOF_NOCONFIRMATION, item grande demais para a Lixeira, unidade sem Lixeira
(rede/removível) ou Lixeira desativada (NukeOnDelete) seria apagado PARA SEMPRE sem perguntar. Por isso, antes de
chamar a API, este módulo recusa esses casos (unidade fixa, Lixeira ligada, tamanho dentro da capacidade).
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import stat
import sys
import time
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger(__name__)

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
_FLAGS = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
DRIVE_FIXED = 3
MAX_SCAN_ITEMS = 100_000
_MAX_PATH_CHARS = 259
_ABS = re.compile(r"^[A-Za-z]:\\")
_BIN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume"

_ERRORS: dict[int, str] = {
    0x71: "o item de origem e o destino são o mesmo",
    0x72: "há vários itens de origem e um só destino",
    0x74: "não dá para apagar a raiz da unidade",
    0x7C: "o caminho é inválido",
    0x7E: "o caminho de origem é longo demais",
    0xB7: "o item já está sendo usado",
    0x10000: "erro no destino",
    0x402: "o Windows não conseguiu enviar para a Lixeira",
}


class RecycleError(Exception):
    """Não foi possível mandar para a Lixeira (nada foi apagado de forma permanente)."""


class _ShFileOpStruct(ctypes.Structure):
    _pack_ = 1 if ctypes.sizeof(ctypes.c_void_p) == 4 else 8
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_void_p),
        ("pTo", ctypes.c_void_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_void_p),
    ]


def measure_tree(path: str, deadline_s: float | None = None) -> tuple[int, int]:
    """(bytes, itens) sem seguir links; recusa árvores gigantes, lentas demais ou com atalhos/links dentro."""
    limit = None if deadline_s is None else time.monotonic() + deadline_s
    st = os.lstat(path)
    if _is_link(st):
        raise RecycleError("O item é um atalho/link; não envio links para a Lixeira.")
    if not stat.S_ISDIR(st.st_mode):
        return st.st_size, 1
    total = 0
    seen = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        with os.scandir(cur) as it:
            for e in it:
                seen += 1
                if seen > MAX_SCAN_ITEMS or (limit is not None and time.monotonic() > limit):
                    raise RecycleError("A pasta é grande demais para eu conferir; apague pelo Explorador de Arquivos.")
                est = e.stat(follow_symlinks=False)
                if _is_link(est):
                    raise RecycleError("A pasta contém atalhos/links; apague pelo Explorador de Arquivos.")
                if stat.S_ISDIR(est.st_mode):
                    stack.append(e.path)
                else:
                    total += est.st_size
    return total, seen


def _is_link(st: os.stat_result) -> bool:
    return bool(stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400)


def _volume_key(shell_root: str) -> str | None:
    """Nome '{GUID}' do volume, usado nas configurações da Lixeira."""
    buf = ctypes.create_unicode_buffer(64)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetVolumeNameForVolumeMountPointW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    k32.GetVolumeNameForVolumeMountPointW.restype = wintypes.BOOL
    if not k32.GetVolumeNameForVolumeMountPointW(shell_root, buf, 64):
        return None
    m = re.search(r"\{[0-9A-Fa-f-]+\}", buf.value)
    return m.group(0) if m else None


def _check_bin_accepts(root: str, size: int) -> None:
    """Recusa se a Lixeira estiver desativada para o volume ou se o item não couber com folga."""
    import winreg

    total = shutil.disk_usage(root).total
    limit = total // 10                              # padrão do Windows: 10% do volume
    key_name = _volume_key(root)
    if key_name:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{_BIN_KEY}\{key_name}") as key:
                try:
                    if int(winreg.QueryValueEx(key, "NukeOnDelete")[0]) == 1:
                        raise RecycleError("A Lixeira está configurada para apagar direto neste disco; não apago.")
                except FileNotFoundError:
                    pass
                try:
                    limit = int(winreg.QueryValueEx(key, "MaxCapacity")[0]) * 1024 * 1024
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("lixeira: não consegui ler a configuração do volume: %s", exc)
    if size > limit // 2:
        raise RecycleError("O item é grande demais para a Lixeira deste disco; ele seria apagado de vez. "
                           "Apague pelo Explorador de Arquivos se quiser mesmo.")


def send_to_recycle_bin(path: str | os.PathLike[str], *, size_hint: int | None = None) -> None:
    """Envia um arquivo ou pasta para a Lixeira. Levanta RecycleError se não puder garantir que irá para a Lixeira."""
    if sys.platform != "win32":
        raise RecycleError("A Lixeira só está disponível no Windows.")
    text = os.fspath(path)
    if not _ABS.match(text) or any(c in text for c in "*?\0<>|\""):
        raise RecycleError("Caminho inválido para a Lixeira.")
    if len(text) > _MAX_PATH_CHARS:
        raise RecycleError("O caminho é longo demais para a Lixeira.")
    if not os.path.lexists(text):
        raise RecycleError("O item não existe mais.")
    root = text[:3]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    k32.GetDriveTypeW.restype = wintypes.UINT
    if k32.GetDriveTypeW(root) != DRIVE_FIXED:
        raise RecycleError("Esse disco (rede ou removível) não tem Lixeira; não apago de forma permanente.")
    try:
        size = size_hint if size_hint is not None else measure_tree(text)[0]
        if size_hint is not None and _is_link(os.lstat(text)):
            raise RecycleError("O item é um atalho/link; não envio links para a Lixeira.")
        _check_bin_accepts(root, size)
    except OSError as exc:
        raise RecycleError(f"Não consegui conferir o item: {exc.strerror or type(exc).__name__}.") from exc

    buf = ctypes.create_unicode_buffer(text + "\0\0")        # lista de origens terminada em duplo nulo
    op = _ShFileOpStruct()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_void_p).value
    op.pTo = None
    op.fFlags = _FLAGS
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(_ShFileOpStruct)]
    shell32.SHFileOperationW.restype = ctypes.c_int
    rc = shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        why = _ERRORS.get(rc, f"código 0x{rc:X}")
        log.warning("lixeira: SHFileOperationW falhou rc=0x%X", rc)
        raise RecycleError(f"A Lixeira recusou: {why}.")
    if op.fAnyOperationsAborted:
        raise RecycleError("A operação da Lixeira foi interrompida; confira o item.")
    if os.path.lexists(text):
        raise RecycleError("O item continua no lugar; o Windows não o enviou para a Lixeira.")
    log.info("lixeira: enviado %s (%d bytes)", Path(text).name, size)
