"""Cofre de Credenciais do Windows (Credential Manager) para o token SOMENTE-LEITURA das atualizações.

O token nunca vai para o config.toml, logs ou variáveis do Eco: fica no cofre do Windows, do usuário atual, e só é lido na
hora de consultar o GitHub. Fora do Windows (ou sem o cofre) as funções devolvem vazio/False, sem erro.
"""
from __future__ import annotations

import sys

TARGET = "Eco/GitHubUpdateToken"
_CRED_TYPE_GENERIC = 1
_PERSIST_LOCAL_MACHINE = 2


def available() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class _CRED(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", _FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CRED))]
    _adv.CredReadW.restype = wintypes.BOOL
    _adv.CredWriteW.argtypes = [ctypes.POINTER(_CRED), wintypes.DWORD]
    _adv.CredWriteW.restype = wintypes.BOOL
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredDeleteW.restype = wintypes.BOOL
    _adv.CredFree.argtypes = [ctypes.c_void_p]


def get_token() -> str:
    if not available():
        return ""
    p = ctypes.POINTER(_CRED)()
    if not _adv.CredReadW(TARGET, _CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return ""
    try:
        c = p.contents
        raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        return raw.decode("utf-16-le", "ignore").strip()
    finally:
        _adv.CredFree(p)


def has_token() -> bool:
    return bool(get_token())


def set_token(token: str) -> bool:
    """Guarda (ou troca) o token. Devolve False se o cofre recusar. Não registra o valor em lugar nenhum."""
    token = (token or "").strip()
    if not available() or not token:
        return False
    blob = token.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _CRED()
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = TARGET
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = _PERSIST_LOCAL_MACHINE
    cred.UserName = "eco-update-readonly"
    return bool(_adv.CredWriteW(ctypes.byref(cred), 0))


def clear_token() -> bool:
    if not available():
        return False
    return bool(_adv.CredDeleteW(TARGET, _CRED_TYPE_GENERIC, 0))
