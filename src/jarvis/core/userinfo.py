"""Nome do usuário para falas e prompts: o que está em Configurações; vazio = nome de exibição da conta do Windows."""
from __future__ import annotations

import ctypes
import getpass
import re

_override = ""
_cached = ""


def set_name(name: str) -> None:
    """Chamado ao carregar a configuração (ui.user_name). Vazio = usar o nome da conta do Windows."""
    global _override
    _override = _clean(name)


def _clean(name: str) -> str:
    return re.sub(r"[^\w .'-]", "", (name or "").strip(), flags=re.UNICODE)[:40].strip()


def _windows_first_name() -> str:
    global _cached
    if _cached:
        return _cached
    full = ""
    try:                                                           # NameDisplay = 3
        size = ctypes.c_ulong(0)
        ctypes.windll.secur32.GetUserNameExW(3, None, ctypes.byref(size))
        if size.value:
            buf = ctypes.create_unicode_buffer(size.value)
            if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size)):
                full = buf.value
    except Exception:  # noqa: BLE001 - sem API (não Windows): cai no login
        full = ""
    if not full:
        try:
            full = getpass.getuser()
        except Exception:  # noqa: BLE001
            full = ""
    first = _clean(full.split()[0] if full.split() else full)
    _cached = first
    return first


def user_name() -> str:
    """Nome para tratar o usuário; 'você' se nada estiver disponível."""
    return _override or _windows_first_name() or "você"
