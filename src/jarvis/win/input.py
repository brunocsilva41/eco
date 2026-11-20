"""Injeção de teclado e mouse via SendInput (ctypes, sem pyautogui).

Pontos de atenção:
- A struct INPUT precisa ter o tamanho certo (40 bytes em x64): a união inclui MOUSEINPUT, a maior.
  Se o tamanho estiver errado, o Windows rejeita a chamada; por isso há uma verificação no import.
- SendInput devolve quantos eventos foram injetados. Menos que o pedido = bloqueio (UIPI: janela
  elevada/administrador, desktop seguro/UAC). Isso vira `InputBlockedError` com mensagem clara.
- Tudo que o módulo deixa pressionado fica registrado; `release_all()` solta o que sobrou
  (usada pela tecla de emergência) sem tocar em teclas que o usuário esteja segurando de verdade.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import Final, Sequence

from ..core.cancel import CancelToken
from .keys import Combo

log = logging.getLogger(__name__)

# ----------------------------------------------------------------- constantes do Win32
INPUT_MOUSE: Final = 0
INPUT_KEYBOARD: Final = 1

KEYEVENTF_EXTENDEDKEY: Final = 0x0001
KEYEVENTF_KEYUP: Final = 0x0002
KEYEVENTF_UNICODE: Final = 0x0004

MOUSEEVENTF_LEFTDOWN: Final = 0x0002
MOUSEEVENTF_LEFTUP: Final = 0x0004
MOUSEEVENTF_RIGHTDOWN: Final = 0x0008
MOUSEEVENTF_RIGHTUP: Final = 0x0010
MOUSEEVENTF_MIDDLEDOWN: Final = 0x0020
MOUSEEVENTF_MIDDLEUP: Final = 0x0040

SM_XVIRTUALSCREEN: Final = 76
SM_YVIRTUALSCREEN: Final = 77
SM_CXVIRTUALSCREEN: Final = 78
SM_CYVIRTUALSCREEN: Final = 79

VK_RETURN: Final = 0x0D
VK_TAB: Final = 0x09
VK_MENU: Final = 0x12
VK_LWIN: Final = 0x5B

# Teclas que exigem o flag EXTENDEDKEY (setas, navegação, Win, etc.).
_EXTENDED_VKS: Final = frozenset({
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,   # PgUp, PgDn, End, Home, setas
    0x2C, 0x2D, 0x2E,                                  # PrintScreen, Insert, Delete
    0x5B, 0x5C, 0x5D,                                  # Win esquerda/direita, menu de contexto
    0xA3, 0xA5,                                        # Ctrl/Alt direitos
    0xAD, 0xAE, 0xAF,                                  # mudo, volume -, volume +
})

_CHUNK_CHARS: Final = 16        # caracteres por SendInput em send_text
_CHUNK_PAUSE_S: Final = 0.008   # respiro entre pedaços (e ponto de checagem do cancelamento)
_KEY_GAP_S: Final = 0.012       # intervalo entre teclas de um atalho
_CLICK_HOLD_S: Final = 0.03


class InputBlockedError(OSError):
    """O Windows recusou (total ou parcialmente) a injeção de entrada."""

    def __init__(self, message: str, injected: int = 0, expected: int = 0) -> None:
        super().__init__(message)
        self.injected = injected
        self.expected = expected


# ----------------------------------------------------------------- structs
ULONG_PTR = wintypes.WPARAM  # inteiro do tamanho de um ponteiro


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD))


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


_EXPECTED_SIZE = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
if ctypes.sizeof(INPUT) != _EXPECTED_SIZE:  # pragma: no cover - proteção contra struct errada
    raise ImportError(f"INPUT com tamanho {ctypes.sizeof(INPUT)}, esperado {_EXPECTED_SIZE}")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT
_user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
_user32.SetCursorPos.restype = wintypes.BOOL
_user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
_user32.GetSystemMetrics.restype = ctypes.c_int

# ----------------------------------------------------------------- estado do que ficou pressionado
_state_lock = threading.Lock()
_held_keys: set[int] = set()
_held_buttons: set[str] = set()

_BUTTONS: Final[dict[str, tuple[int, int]]] = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


# ----------------------------------------------------------------- baixo nível
def _key_event(vk: int, up: bool = False) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED_VKS else 0)
    ev = INPUT(type=INPUT_KEYBOARD)
    ev.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return ev


def _unicode_event(unit: int, up: bool) -> INPUT:
    ev = INPUT(type=INPUT_KEYBOARD)
    ev.ki = KEYBDINPUT(wVk=0, wScan=unit, dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0),
                       time=0, dwExtraInfo=0)
    return ev


def _mouse_event(flags: int) -> INPUT:
    ev = INPUT(type=INPUT_MOUSE)
    ev.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return ev


def _send(events: Sequence[INPUT]) -> None:
    """Injeta os eventos e confere quantos o Windows aceitou."""
    n = len(events)
    if n == 0:
        return
    array = (INPUT * n)(*events)
    injected = int(_user32.SendInput(n, array, ctypes.sizeof(INPUT)))
    if injected != n:
        err = ctypes.get_last_error()
        raise InputBlockedError(
            "O Windows bloqueou a entrada simulada (provável janela de administrador, tela de "
            f"permissão do UAC ou tela bloqueada). Eventos aceitos: {injected} de {n}; erro {err}.",
            injected, n)


def _press(vk: int) -> None:
    _send([_key_event(vk)])
    with _state_lock:
        _held_keys.add(vk)


def _release(vk: int) -> None:
    try:
        _send([_key_event(vk, up=True)])
    finally:
        with _state_lock:
            _held_keys.discard(vk)


# ----------------------------------------------------------------- API pública
def _sanitize(text: str) -> str:
    """Remove caracteres de controle (exceto quebra de linha e tab) e normaliza CRLF."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text if ch in "\n\t" or (ch >= " " and ch != "\x7f"))


def send_text(text: str, cancel: CancelToken) -> int:
    """Digita `text` na janela em foco, em pedaços, checando `cancel` entre eles.

    Devolve quantos caracteres foram digitados (menos que len(text) se cancelou ou se havia
    caracteres de controle descartados). Levanta `InputBlockedError` se o Windows recusar.
    """
    clean = _sanitize(text)
    typed = 0
    for start in range(0, len(clean), _CHUNK_CHARS):
        if cancel.cancelled:
            break
        chunk = clean[start:start + _CHUNK_CHARS]
        events: list[INPUT] = []
        for ch in chunk:
            if ch == "\n":
                events += [_key_event(VK_RETURN), _key_event(VK_RETURN, up=True)]
            elif ch == "\t":
                events += [_key_event(VK_TAB), _key_event(VK_TAB, up=True)]
            else:
                data = ch.encode("utf-16-le")           # pares substitutos viram 2 unidades
                for i in range(0, len(data), 2):
                    unit = int.from_bytes(data[i:i + 2], "little")
                    events += [_unicode_event(unit, up=False), _unicode_event(unit, up=True)]
        try:
            _send(events)
        except InputBlockedError as exc:
            log.warning("send_text bloqueado após %d caracteres: %s", typed, exc)
            raise InputBlockedError(f"{exc} Digitei {typed} caracteres antes de parar.",
                                    exc.injected, exc.expected) from exc
        typed += len(chunk)
        if cancel.wait(_CHUNK_PAUSE_S):
            break
    return typed


def tap_key(vk: int) -> None:
    """Aperta e solta uma tecla (a tecla é solta mesmo se a injeção do 'up' falhar uma vez)."""
    _press(vk)
    _release(vk)


def send_combo(combo: Combo) -> None:
    """Aperta modificadores + tecla principal e solta tudo na ordem inversa, mesmo se falhar."""
    pressed: list[int] = []
    failure: BaseException | None = None
    try:
        for vk in (*combo.mod_vks(), combo.vk):
            _press(vk)
            pressed.append(vk)
            time.sleep(_KEY_GAP_S)
    except BaseException as exc:  # noqa: BLE001 - guardada e relevantada após soltar as teclas
        failure = exc
    finally:
        for vk in reversed(pressed):
            try:
                _release(vk)
            except InputBlockedError as exc:
                log.error("não consegui soltar a tecla 0x%02X: %s", vk, exc)
                failure = failure or exc
    if failure is not None:
        raise failure


def click(x: int, y: int, button: str = "left") -> None:
    """Move o cursor para (x, y) em coordenadas de tela e clica. Rejeita pontos fora da tela virtual."""
    if button not in _BUTTONS:
        raise ValueError(f"botão inválido: {button!r}")
    left = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if not (left <= x < left + width and top <= y < top + height):
        raise ValueError(f"ponto ({x}, {y}) fora da tela")
    if not _user32.SetCursorPos(x, y):
        raise InputBlockedError(f"Não consegui mover o cursor (erro {ctypes.get_last_error()}).")
    down, up = _BUTTONS[button]
    _send([_mouse_event(down)])
    with _state_lock:
        _held_buttons.add(button)
    try:
        time.sleep(_CLICK_HOLD_S)
    finally:
        try:
            _send([_mouse_event(up)])
        finally:
            with _state_lock:
                _held_buttons.discard(button)


def release_all() -> None:
    """Solta o que este módulo deixou pressionado. Nunca levanta (serve à tecla de emergência)."""
    with _state_lock:
        keys = sorted(_held_keys)
        buttons = sorted(_held_buttons)
        _held_keys.clear()
        _held_buttons.clear()
    events = [_key_event(vk, up=True) for vk in keys] + [_mouse_event(_BUTTONS[b][1]) for b in buttons]
    if not events:
        return
    try:
        _send(events)
        log.info("release_all: soltou %d teclas e %d botões", len(keys), len(buttons))
    except InputBlockedError:
        log.exception("release_all falhou")
