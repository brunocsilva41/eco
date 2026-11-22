"""Configuracao que o nucleo envia a Ilha (mensagem ``config``): modo de posicao, esconder sozinha, fixar, vidro e atalhos.

Sem Qt. Valores invalidos caem no padrao (a Ilha nunca quebra por causa de config).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_HOTKEYS = {"yes": "ctrl+alt+y", "no": "ctrl+alt+n", "stop": "ctrl+alt+f12", "mute": "ctrl+alt+m",
                   "talk": "f9", "yolo": "ctrl+alt+shift+y", "open_listen": "ctrl+alt+l"}
MODES = ("docked", "floating", "dock_right", "dock_left")
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
    mode: str = "docked"                    # docked | floating | dock_right | dock_left
    float_gap_px: int = 10                  # 0..64
    autohide: bool = True
    hide_delay_s: float = 3.0
    hover_reveal: bool = True
    pinned: bool | None = None              # None = a mensagem nao trouxe o campo (mantem o estado local)
    opacity: float = 0.92                   # 0.35..1.0 (fundo de vidro)
    side_y_pct: int = 50                    # 0..100 (altura do trilho lateral)
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))

    @property
    def side(self) -> str:
        """'right' | 'left' no dock lateral; '' no topo."""
        return {"dock_right": "right", "dock_left": "left"}.get(self.mode, "")

    @classmethod
    def from_message(cls, d: dict[str, Any]) -> "IslandConfig":
        c = cls()
        try:
            m = str(d.get("mode"))
            c.mode = m if m in MODES else "docked"
            c.float_gap_px = max(0, min(64, int(d.get("float_gap_px", c.float_gap_px))))
            c.autohide = bool(d.get("autohide", c.autohide))
            c.hide_delay_s = max(0.5, min(60.0, float(d.get("hide_delay_s", c.hide_delay_s))))
            c.hover_reveal = bool(d.get("hover_reveal", c.hover_reveal))
            if "pinned" in d:
                c.pinned = bool(d["pinned"])
            c.opacity = max(0.35, min(1.0, float(d.get("opacity", c.opacity))))
            c.side_y_pct = max(0, min(100, int(d.get("side_y_pct", c.side_y_pct))))
            hk = d.get("hotkeys")
            if isinstance(hk, dict):
                for k in DEFAULT_HOTKEYS:
                    if k in hk:
                        c.hotkeys[k] = str(hk[k] or "")
        except (TypeError, ValueError):
            pass
        return c
