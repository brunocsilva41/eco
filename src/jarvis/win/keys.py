"""Nomes de teclas -> códigos virtuais do Windows. Só tabelas e parsing (sem efeitos colaterais)."""
from __future__ import annotations

from dataclasses import dataclass

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
MOD_NOREPEAT = 0x4000

_MODS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}

_NAMED: dict[str, int] = {
    "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "pause": 0x13, "printscreen": 0x2C,
}
_NAMED.update({f"f{i}": 0x6F + i for i in range(1, 25)})   # F1=0x70
_NAMED.update({chr(c).lower(): c for c in range(0x41, 0x5B)})   # a-z -> VK 0x41..0x5A
_NAMED.update({str(d): 0x30 + d for d in range(10)})


class KeyError_(ValueError):
    """Combinação inválida."""


@dataclass(frozen=True)
class Combo:
    mods: int          # MOD_* combinados
    vk: int            # código virtual da tecla principal
    norm: str          # forma normalizada, ex.: "ctrl+alt+f12"

    def mod_vks(self) -> list[int]:
        """VKs das teclas modificadoras (para SendInput)."""
        out = []
        if self.mods & MOD_CONTROL:
            out.append(0x11)
        if self.mods & MOD_ALT:
            out.append(0x12)
        if self.mods & MOD_SHIFT:
            out.append(0x10)
        if self.mods & MOD_WIN:
            out.append(0x5B)
        return out


def parse_combo(text: str) -> Combo:
    """'Ctrl+Alt+F12' -> Combo. Exatamente uma tecla principal; modificadores opcionais."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        raise KeyError_("combinação vazia")
    mods = 0
    main: str | None = None
    for p in parts:
        if p in _MODS:
            if mods & _MODS[p]:
                raise KeyError_(f"modificador repetido em {text!r}")
            mods |= _MODS[p]
        elif p in _NAMED:
            if main is not None:
                raise KeyError_(f"mais de uma tecla principal em {text!r}")
            main = p
        else:
            raise KeyError_(f"tecla desconhecida {p!r} em {text!r}")
    if main is None:
        raise KeyError_(f"falta a tecla principal em {text!r}")
    order = [n for n, m in (("ctrl", MOD_CONTROL), ("alt", MOD_ALT), ("shift", MOD_SHIFT), ("win", MOD_WIN)) if mods & m]
    return Combo(mods, _NAMED[main], "+".join(order + [main]))
