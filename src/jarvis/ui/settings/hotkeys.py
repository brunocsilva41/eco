"""Traducao entre o texto de tecla do Qt (``Ctrl+Alt+F12``, ``Esc``, ``PgUp``) e o formato da config do Eco
(``ctrl+alt+f12``, ``esc``, ``pageup``). Puro: sem widget, sem disco."""
from __future__ import annotations

_QT_TO_CONFIG: dict[str, str] = {
    "return": "enter", "enter": "enter", "esc": "esc", "del": "delete", "ins": "insert", "pgup": "pageup",
    "pgdown": "pagedown", "print": "printscreen", "meta": "win",
}
_CONFIG_TO_QT: dict[str, str] = {
    "enter": "Enter", "esc": "Esc", "escape": "Esc", "delete": "Del", "insert": "Ins", "pageup": "PgUp",
    "pagedown": "PgDown", "printscreen": "Print", "control": "Ctrl",
}


def _pretty(part: str) -> str:
    if part in _CONFIG_TO_QT:
        return _CONFIG_TO_QT[part]
    if len(part) == 1 or (part[:1] == "f" and part[1:].isdigit()):
        return part.upper()
    return part.capitalize()


def _parts(text: str) -> list[str]:
    return [p.strip().lower() for p in str(text or "").split("+") if p.strip()]


def to_config(qt_text: str) -> str:
    """Texto do KeyCaptureField -> formato da config (minusculo, nomes do Eco)."""
    return "+".join(_QT_TO_CONFIG.get(p, p) for p in _parts(qt_text))


def to_display(config_text: str) -> str:
    """Formato da config -> texto que o KeyCaptureField mostra (``ctrl+alt+f12`` -> ``Ctrl+Alt+F12``)."""
    return "+".join(_pretty(p) for p in _parts(config_text))
