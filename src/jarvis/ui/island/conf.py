"""Configuracao que o nucleo envia a Ilha (mensagem ``config``): modo de posicao, esconder sozinha e atalhos.

Sem Qt. Valores invalidos caem no padrao (a Ilha nunca quebra por causa de config).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_HOTKEYS = {"yes": "ctrl+alt+y", "no": "ctrl+alt+n", "stop": "ctrl+alt+f12", "mute": "ctrl+alt+m",
                   "talk": "f9", "yolo": "ctrl+alt+shift+y"}
_NAMES = {"esc": "Esc", "escape": "Esc", "enter": "Enter", "return": "Enter", "delete": "Del", "insert": "Ins",
          "pageup": "PgUp", "pagedown": "PgDn", "printscreen": "PrtSc", "space": "Space", "win": "Win",
          "control": "Ctrl", "tab": "Tab", "backspace": "Bksp"}


def display(combo: str) -> str:
    """``ctrl+alt+f12`` -> ``Ctrl+Alt+F12``; vazio -> vazio (botao sem dica)."""
    out = []
    for part in str(combo or "").lower().split("+"):
        part = part.strip()
        if not part:
            continue
        if part in _NAMES:
            out.append(_NAMES[part])
        elif len(part) == 1 or (part[0] == "f" and part[1:].isdigit()):
            out.append(part.upper())
        else:
            out.append(part.capitalize())
    return "+".join(out)


@dataclass
class IslandConfig:
    mode: str = "docked"                    # docked | floating
    float_gap_px: int = 10                  # 0..64
    autohide: bool = True
    hide_delay_s: float = 3.0
    hover_reveal: bool = True
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))

    @classmethod
    def from_message(cls, d: dict[str, Any]) -> "IslandConfig":
        c = cls()
        try:
            c.mode = "floating" if str(d.get("mode")) == "floating" else "docked"
            c.float_gap_px = max(0, min(64, int(d.get("float_gap_px", c.float_gap_px))))
            c.autohide = bool(d.get("autohide", c.autohide))
            c.hide_delay_s = max(0.5, min(60.0, float(d.get("hide_delay_s", c.hide_delay_s))))
            c.hover_reveal = bool(d.get("hover_reveal", c.hover_reveal))
            hk = d.get("hotkeys")
            if isinstance(hk, dict):
                for k in DEFAULT_HOTKEYS:
                    if k in hk:
                        c.hotkeys[k] = str(hk[k] or "")
        except (TypeError, ValueError):
            pass
        return c
