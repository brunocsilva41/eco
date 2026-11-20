"""DPI-awareness do processo: sem ela, coordenadas de captura e de clique ficam virtualizadas (erradas com escala != 100%).

Deve ser chamada o mais cedo possível (antes de criar janelas e antes de importar captura/UIA).
O Windows só aceita definir a consciência de DPI UMA vez por processo; depois disso a chamada falha
com "acesso negado", o que aqui conta como sucesso (já está definida).
"""
from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Final

log = logging.getLogger(__name__)

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2: Final = -4
PROCESS_PER_MONITOR_DPI_AWARE: Final = 2
_ERROR_ACCESS_DENIED: Final = 5
_E_ACCESSDENIED: Final = 0x80070005

_AWARENESS_NAMES: Final = {0: "sem suporte a DPI", 1: "DPI do sistema", 2: "por monitor"}

_lock = threading.Lock()
_result: bool | None = None


def _current_awareness() -> str:
    """Descrição da consciência de DPI efetiva do processo (só para o log). Nunca levanta."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetThreadDpiAwarenessContext.argtypes = ()
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        user32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
        level = int(user32.GetAwarenessFromDpiAwarenessContext(user32.GetThreadDpiAwarenessContext()))
        return _AWARENESS_NAMES.get(level, f"nível {level}")
    except (AttributeError, OSError):
        return "desconhecida"


def _try_context_api() -> bool | None:
    """SetProcessDpiAwarenessContext (Windows 10 1703+). True = ok/já definido; False = falhou; None = API ausente."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        fn = user32.SetProcessDpiAwarenessContext
    except (AttributeError, OSError):
        return None
    fn.argtypes = (ctypes.c_void_p,)
    fn.restype = wintypes.BOOL
    if fn(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
        return True
    err = ctypes.get_last_error()
    if err == _ERROR_ACCESS_DENIED:
        log.info("DPI: a consciência de DPI do processo já estava definida")
        return True
    log.warning("SetProcessDpiAwarenessContext falhou (erro %d)", err)
    return False


def _try_shcore_api() -> bool:
    """SetProcessDpiAwareness(2) (Windows 8.1+), usada se a API de contexto não existir ou falhar."""
    try:
        shcore = ctypes.WinDLL("shcore")
        fn = shcore.SetProcessDpiAwareness
    except (AttributeError, OSError):
        return False
    fn.argtypes = (ctypes.c_int,)
    fn.restype = ctypes.c_long
    hr = int(fn(PROCESS_PER_MONITOR_DPI_AWARE)) & 0xFFFFFFFF
    if hr == 0:
        return True
    if hr == _E_ACCESSDENIED:
        log.info("DPI: a consciência de DPI do processo já estava definida")
        return True
    log.warning("SetProcessDpiAwareness falhou (HRESULT 0x%08X)", hr)
    return False


def ensure_per_monitor_v2() -> bool:
    """Deixa o processo DPI-aware por monitor (v2). Idempotente e seguro entre threads.

    Devolve True se a consciência de DPI está definida (agora ou antes) e False se nenhuma API funcionou.
    """
    global _result
    with _lock:
        if _result is not None:
            return _result
        ok = _try_context_api()
        if not ok:                                   # None (ausente) ou False (falhou): tenta a API antiga
            ok = _try_shcore_api()
        _result = bool(ok)
        if _result:
            log.info("DPI-awareness ativa: %s", _current_awareness())
        else:
            log.error("não consegui definir DPI-awareness; capturas e cliques podem errar com escala != 100%%")
        return _result
