"""Efeito vidro da Ilha: fundo semitransparente com contraste AA calculado sobre o PIOR CASO (fundo branco atras).

Sem Qt. O fundo e pintado com alfa no QPainter (``window._render_chrome``); nada de QGraphicsEffect. Como o que esta
atras da Ilha e desconhecido, o pior caso e branco puro: ``worst_bg(alfa)`` = branco misturado com o preto da Ilha mais o
brilho do gradiente. O alfa efetivo nunca desce do piso em que o texto branco ainda tem 4,5:1; e os tons de texto
(secundario, destaque, ok, aviso, erro) sao clareados na medida certa ate alcancarem 4,5:1 (3:1 no destaque, que e
mais icone que texto). Com fundo escuro atras o contraste so melhora.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..kit.color import contrast, luminance, mix
from ..theme import DARK, Palette
from . import tokens as T

SHEEN = 0.06                      # brilho do gradiente no alto (branco)
TEXT_MIN = 4.5
GRAPHIC_MIN = 3.0
OPACITY_MIN, OPACITY_MAX = 0.35, 1.0


def worst_bg(alpha: float) -> str:
    """Cor do fundo da Ilha quando ha branco puro atras (pior caso)."""
    top = mix(T.BG, "#FFFFFF", SHEEN)
    return mix("#FFFFFF", top, alpha)


def floor_alpha() -> float:
    """Menor alfa em que o texto branco ainda alcanca 4,5:1 no pior caso."""
    lo, hi = OPACITY_MIN, OPACITY_MAX
    for _ in range(24):
        mid = (lo + hi) / 2
        if contrast("#FFFFFF", worst_bg(mid)) >= TEXT_MIN:
            hi = mid
        else:
            lo = mid
    return round(hi + 0.005, 3)


def _lift(fg: str, bg: str, target: float) -> str:
    """Clareia ``fg`` (mistura com branco) ate ``target`` contra ``bg``."""
    if contrast(fg, bg) >= target:
        return fg
    for i in range(1, 41):
        c = mix(fg, "#FFFFFF", i / 40)
        if contrast(c, bg) >= target:
            return c
    return "#FFFFFF"


@dataclass(frozen=True)
class Glass:
    requested: float
    alpha: float                  # alfa efetivo do fundo (>= piso)
    clamped: bool
    bg_worst: str
    palette: Palette
    report: tuple[tuple[str, str, float, float], ...]    # (nome, cor, contraste, minimo)


def compute(opacity: float) -> Glass:
    req = max(OPACITY_MIN, min(OPACITY_MAX, float(opacity)))
    floor = floor_alpha()
    a = max(req, floor)
    bg = worst_bg(a)
    base = DARK
    pal = replace(base, text=_lift(base.text, bg, TEXT_MIN), text_muted=_lift(base.text_muted, bg, TEXT_MIN),
                  accent_ink=_lift(base.accent_ink, bg, GRAPHIC_MIN), ok=_lift(base.ok, bg, TEXT_MIN),
                  warn=_lift(base.warn, bg, TEXT_MIN), error=_lift(base.error, bg, TEXT_MIN))
    rep = tuple((n, getattr(pal, n), round(contrast(getattr(pal, n), bg), 2), m) for n, m in
                (("text", TEXT_MIN), ("text_muted", TEXT_MIN), ("accent_ink", GRAPHIC_MIN), ("ok", TEXT_MIN),
                 ("warn", TEXT_MIN), ("error", TEXT_MIN)))
    return Glass(req, a, a > req + 1e-6, bg, pal, rep)


_CUR: Glass | None = None


def apply(opacity: float) -> Glass:
    """Calcula e instala a paleta de vidro em ``tokens.PALETTE`` (render.py le a paleta a cada pintura)."""
    global _CUR
    g = compute(opacity)
    if _CUR is None or _CUR.palette != g.palette or _CUR.alpha != g.alpha:
        T.PALETTE = g.palette
    _CUR = g
    return g


def current() -> Glass:
    return _CUR or apply(0.92)


def edge_alpha(alpha: float) -> int:
    """Borda um pouco mais forte quanto mais transparente (define o contorno sobre fundo claro)."""
    return round(T.EDGE_ALPHA + (1.0 - alpha) * 70)


__all__ = ["Glass", "apply", "compute", "current", "floor_alpha", "worst_bg", "edge_alpha", "luminance"]
