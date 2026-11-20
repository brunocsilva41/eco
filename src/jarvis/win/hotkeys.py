"""Atalhos globais do Windows.

- `HotkeyListener`: RegisterHotKey em thread própria com laço de mensagens (preferível a hook de baixo nível).
  O retorno é checado: combinações reservadas pelo Windows falham e o erro é reportado, nunca silencioso.
- `KeyHold`: consulta do estado de uma tecla (push-to-talk "segurar para falar") sem hook.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import queue
import threading
from typing import Callable

from .keys import MOD_NOREPEAT, Combo, parse_combo

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
_user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
_user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
_kernel32.GetCurrentThreadId.restype = wt.DWORD

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_REGISTER = 0x8001      # pedido interno: registrar combinações pendentes na thread do laço
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class HotkeyError(RuntimeError):
    pass


class HotkeyListener:
    """Uso: l = HotkeyListener(); l.add("ctrl+alt+f12", callback); l.start(); ...; l.stop().

    Contrato de threads: `add` pode ser chamado antes de `start` ou depois (thread-safe).
    Os callbacks rodam na thread do laço de mensagens: devem ser RÁPIDOS e não bloquear
    (ex.: apenas cancelar um token ou enfileirar um evento). Exceções do callback são logadas.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._pending: "queue.Queue[tuple[int, Combo, Callable[[], None], queue.Queue[str | None]]]" = queue.Queue()
        self._callbacks: dict[int, tuple[Combo, Callable[[], None]]] = {}
        self._next_id = 1

    def add(self, combo_text: str, callback: Callable[[], None], timeout: float = 3.0) -> Combo:
        """Registra o atalho. Levanta HotkeyError se o Windows recusar (ex.: já em uso/reservado)."""
        combo = parse_combo(combo_text)
        if self._thread is None or not self._thread.is_alive():
            raise HotkeyError("o ouvinte de atalhos não está rodando; chame start() antes")
        with self._lock:
            hid = self._next_id
            self._next_id += 1
        reply: "queue.Queue[str | None]" = queue.Queue(maxsize=1)
        self._pending.put((hid, combo, callback, reply))
        if not _user32.PostThreadMessageW(self._tid, WM_APP_REGISTER, 0, 0):
            raise HotkeyError("não consegui falar com a thread de atalhos")
        try:
            err = reply.get(timeout=timeout)
        except queue.Empty:
            raise HotkeyError(f"tempo esgotado ao registrar {combo.norm}") from None
        if err:
            raise HotkeyError(f"atalho {combo.norm} recusado pelo Windows: {err}. Escolha outra combinação.")
        return combo

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, name="hotkeys", daemon=True)
        self._thread.start()
        if not self._ready.wait(3.0):
            raise HotkeyError("a thread de atalhos não iniciou")

    def stop(self) -> None:
        t = self._thread
        if t is None:
            return
        if t.is_alive() and self._tid:
            _user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        t.join(3.0)
        self._thread = None

    # ------------------------------------------------------------- thread do laço
    def _loop(self) -> None:
        self._tid = _kernel32.GetCurrentThreadId()
        msg = wt.MSG()
        _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)    # cria a fila de mensagens da thread
        self._ready.set()
        try:
            while True:
                r = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r in (0, -1):
                    break
                if msg.message == WM_APP_REGISTER:
                    self._drain_pending()
                elif msg.message == WM_HOTKEY:
                    entry = self._callbacks.get(int(msg.wParam))
                    if entry:
                        try:
                            entry[1]()
                        except Exception:  # noqa: BLE001
                            log.exception("callback do atalho %s falhou", entry[0].norm)
        finally:
            for hid in list(self._callbacks):
                _user32.UnregisterHotKey(None, hid)
            self._callbacks.clear()

    def _drain_pending(self) -> None:
        while True:
            try:
                hid, combo, cb, reply = self._pending.get_nowait()
            except queue.Empty:
                return
            ok = _user32.RegisterHotKey(None, hid, combo.mods | MOD_NOREPEAT, combo.vk)
            if ok:
                self._callbacks[hid] = (combo, cb)
                reply.put(None)
            else:
                code = ctypes.get_last_error()
                reply.put("já está em uso por outro programa" if code == ERROR_HOTKEY_ALREADY_REGISTERED else f"erro {code}")


class KeyHold:
    """Diz se uma tecla está pressionada agora (para push-to-talk). Sem hook, sem thread."""

    def __init__(self, combo_text: str) -> None:
        self.combo = parse_combo(combo_text)
        if self.combo.mods:
            raise HotkeyError("a tecla de falar deve ser uma tecla simples, sem modificadores (ex.: f9)")

    def __call__(self) -> bool:
        return bool(_user32.GetAsyncKeyState(self.combo.vk) & 0x8000)
