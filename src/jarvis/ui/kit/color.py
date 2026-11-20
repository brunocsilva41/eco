"""Matematica de cor (WCAG 2.x) usada para DERIVAR e AUDITAR a paleta. Sem Qt, sem estado."""
from __future__ import annotations

import colorsys
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from ..theme import Palette


def _rgb(h: str) -> tuple[float, float, float]:
    return int(h[1:3], 16) / 255, int(h[3:5], 16) / 255, int(h[5:7], 16) / 255


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c * 255))) for c in (r, g, b)))


def luminance(h: str) -> float:
    """Luminancia relativa WCAG de ``#RRGGBB``."""
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """Razao de contraste WCAG (1 a 21) entre duas cores ``#RRGGBB``."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """Mistura linear: ``t`` e a parcela de ``b`` (0 devolve ``a``)."""
    (ar, ag, ab), (br, bg, bb) = _rgb(a), _rgb(b)
    return _hex(ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t)


def ensure_contrast(fg: str, bgs: Iterable[str], target: float) -> str:
    """Move a luminosidade de ``fg`` (mesmo matiz) ate atingir ``target`` contra todos os ``bgs``."""
    bg_list = list(bgs)
    if all(contrast(fg, bg) >= target for bg in bg_list):
        return fg
    go_dark = sum(luminance(bg) for bg in bg_list) / len(bg_list) > 0.4
    h, lig, s = colorsys.rgb_to_hls(*_rgb(fg))
    for _ in range(100):
        lig = max(0.0, lig - 0.01) if go_dark else min(1.0, lig + 0.01)
        cand = _hex(*colorsys.hls_to_rgb(h, lig, s))
        if all(contrast(cand, bg) >= target for bg in bg_list):
            return cand
    return "#000000" if go_dark else "#FFFFFF"


def contrast_pairs(p: "Palette") -> list[tuple[str, str, str, float, float]]:
    """Pares (rotulo, primeiro plano, fundo, razao, minimo exigido) para auditoria WCAG AA."""
    rows: list[tuple[str, str, str, float]] = []
    for sname, s in {"fundo": p.bg, "superficie": p.surface, "elevada": p.raised}.items():
        rows += [(f"texto / {sname}", p.text, s, 7.0), (f"texto secundario / {sname}", p.text_muted, s, 4.5),
                 (f"acento (tinta) / {sname}", p.accent_ink, s, 4.5), (f"borda de campo / {sname}", p.border_strong, s, 3.0)]
        rows += [(f"{k} / {sname}", getattr(p, k), s, 4.5) for k in ("ok", "warn", "error")]
    rows += [("texto sobre acento / botao primario", p.on_accent, p.accent, 4.5),
             ("texto sobre acento (hover)", p.on_accent, p.accent_hover, 4.5),
             ("texto sobre acento (pressionado)", p.on_accent, p.accent_pressed, 4.5),
             ("texto sobre perigo / botao perigo", p.on_error, p.error, 4.5),
             ("anel de foco / fundo", p.accent_ink, p.bg, 3.0),
             ("borda do botao primario / fundo (componente)", p.accent_ink, p.bg, 3.0),
             ("texto secundario / chip neutro", p.text_muted, p.hover, 4.5)]
    rows += [(f"{k} / chip {k}", getattr(p, k), getattr(p, f"{k}_bg"), 4.5) for k in ("ok", "warn", "error")]
    return [(lbl, fg, bg, round(contrast(fg, bg), 2), req) for lbl, fg, bg, req in rows]
