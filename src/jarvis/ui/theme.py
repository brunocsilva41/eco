"""Tokens de design do Jarvis (fonte unica) e gerenciador de tema em tempo de execucao.

Tudo que e cor, tamanho, raio, espacamento, fonte ou duracao mora aqui. O resto da UI
(``ui/kit`` e as telas) so le estes tokens; nada de cor ou numero solto em outro arquivo.

Uso rapido::

    from jarvis.ui.theme import ThemeManager, pal, SPACE, RADIUS, TYPE

    mgr = ThemeManager.instance()
    mgr.set_mode("system")          # "dark" | "light" | "system"
    mgr.apply(app)                  # estilo Fusion, fonte, QPalette e stylesheet gerada
    mgr.changed.connect(widget.update)   # sinal emitido a cada troca (str: "dark"|"light")
    color = pal().accent            # paleta do tema efetivo agora

Unidades: tamanhos de layout/QSS em pixels LOGICOS (o Qt 6 ja multiplica pelo fator de escala
do monitor); texto em pontos (px * 72 / 96), entao acompanha DPI e escala do Windows de 100% a
200%. ``dp(n)`` devolve pixels logicos inteiros; ``px(n, widget)`` devolve pixels FISICOS
(n * devicePixelRatio), para criar pixmaps nitidos; ``crisp(v, widget)`` alinha uma coordenada
a grade de pixels fisicos (linhas finas sem borrao).

Compatibilidade DEPRECATED (telas antigas ainda importam estes nomes): ``apply_theme``,
``build_stylesheet``, ``build_settings_stylesheet``, ``level_state``, ``state_color``,
``repolish`` e as constantes BG, SURFACE, SURFACE_ALT, BORDER, TEXT, TEXT_MUTED, ACCENT,
ACCENT_HOVER, ACCENT_PRESSED, ON_ACCENT, OK, WARN, ERROR, DISABLED_TEXT, SP1..SP4, RADIUS_*.
"""
from __future__ import annotations

import colorsys
import ctypes
import os
import sys
from dataclasses import dataclass
from typing import Any, Final, Iterable, Literal

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

Mode = Literal["dark", "light", "system"]
Effective = Literal["dark", "light"]
State = Literal["ok", "warn", "error"]

# ---------------------------------------------------------------- matematica de cor (WCAG 2.x)


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
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


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


# ---------------------------------------------------------------- paleta


@dataclass(frozen=True, slots=True)
class Palette:
    """Cores de um tema. ``*_ink`` = versao legivel como TEXTO/linha sobre as superficies."""

    name: Effective
    bg: str
    surface: str
    raised: str
    border: str            # separador decorativo (nao exigido 3:1)
    border_strong: str     # borda de campo/controle (>= 3:1)
    text: str
    text_muted: str
    text_disabled: str
    accent: str            # preenchimento do botao primario, gravacao ativa
    accent_hover: str
    accent_pressed: str
    on_accent: str
    accent_ink: str        # acento como texto/linha/marcador/anel de foco
    ok: str
    warn: str
    error: str
    ok_bg: str
    warn_bg: str
    error_bg: str
    on_error: str
    hover: str             # fundo de hover sobre ``raised``
    pressed: str

    def state(self, name: str) -> str:
        return {"ok": self.ok, "warn": self.warn, "error": self.error}.get(name, self.text_muted)

    def state_bg(self, name: str) -> str:
        return {"ok": self.ok_bg, "warn": self.warn_bg, "error": self.error_bg}.get(name, self.raised)


_ACCENT: Final = "#F5B544"
_ON_ACCENT: Final = "#1A1305"
_STATES: Final = {"ok": "#62C98A", "warn": "#FF8F5A", "error": "#FF5C6C"}
_NEUTRALS: Final[dict[str, dict[str, str]]] = {
    # escuro: valores do DESIGN.md. claro: mesma familia de matiz (grafite frio), elevacao invertida
    # (a superficie "sobe" em direcao ao branco) e texto na tinta do fundo escuro.
    "dark": {"bg": "#0E1013", "surface": "#151920", "raised": "#1C2129", "border": "#2A303B",
             "text": "#E8EAED", "muted": "#98A1AF"},
    "light": {"bg": "#EDEFF2", "surface": "#F7F8FA", "raised": "#FFFFFF", "border": "#D4D8DF",
              "text": "#14181E", "muted": "#5B6471"},
}


def _build(name: Effective) -> Palette:
    n = _NEUTRALS[name]
    surfaces = (n["bg"], n["surface"], n["raised"])
    text = ensure_contrast(n["text"], surfaces, 7.0)
    muted = ensure_contrast(n["muted"], surfaces, 4.5)
    inks: dict[str, str] = {}
    tints: dict[str, str] = {}
    for key, base in _STATES.items():
        ink = ensure_contrast(base, surfaces, 4.5)
        tint = mix(n["surface"], ink, 0.14)
        inks[key] = ensure_contrast(ink, (*surfaces, tint), 4.5)
        tints[key] = tint
    on_error = max((_ON_ACCENT, "#FFFFFF"), key=lambda c: contrast(c, inks["error"]))
    return Palette(
        name=name, bg=n["bg"], surface=n["surface"], raised=n["raised"], border=n["border"],
        border_strong=ensure_contrast(mix(n["border"], muted, 0.5), surfaces, 3.0),
        text=text, text_muted=muted, text_disabled=mix(text, n["surface"], 0.62),
        accent=_ACCENT, accent_hover=mix(_ACCENT, "#FFFFFF", 0.12), accent_pressed=mix(_ACCENT, "#000000", 0.14),
        on_accent=_ON_ACCENT, accent_ink=ensure_contrast(_ACCENT, surfaces, 4.5),
        ok=inks["ok"], warn=inks["warn"], error=inks["error"],
        ok_bg=tints["ok"], warn_bg=tints["warn"], error_bg=tints["error"], on_error=on_error,
        hover=mix(n["raised"], text, 0.07), pressed=mix(n["raised"], text, 0.13),
    )


DARK: Final = _build("dark")
LIGHT: Final = _build("light")


def contrast_pairs(p: Palette) -> list[tuple[str, str, str, float, float]]:
    """Pares (rotulo, primeiro plano, fundo, razao, minimo exigido) para auditoria WCAG AA."""
    rows: list[tuple[str, str, str, float]] = []
    surfaces = {"fundo": p.bg, "superficie": p.surface, "elevada": p.raised}
    for sname, s in surfaces.items():
        rows += [(f"texto / {sname}", p.text, s, 7.0), (f"texto secundario / {sname}", p.text_muted, s, 4.5),
                 (f"acento (tinta) / {sname}", p.accent_ink, s, 4.5), (f"borda de campo / {sname}", p.border_strong, s, 3.0)]
        rows += [(f"{k} / {sname}", getattr(p, k), s, 4.5) for k in ("ok", "warn", "error")]
    rows += [("texto sobre acento / botao primario", p.on_accent, p.accent, 4.5),
             ("texto sobre acento (hover)", p.on_accent, p.accent_hover, 4.5),
             ("texto sobre acento (pressionado)", p.on_accent, p.accent_pressed, 4.5),
             ("texto sobre perigo / botao perigo", p.on_error, p.error, 4.5),
             ("anel de foco / fundo", p.accent_ink, p.bg, 3.0),
             ("borda do botao primario / fundo (componente)", p.accent_ink, p.bg, 3.0)]
    rows += [(f"{k} / chip {k}", getattr(p, k), getattr(p, f"{k}_bg"), 4.5) for k in ("ok", "warn", "error")]
    return [(lbl, fg, bg, round(contrast(fg, bg), 2), req) for lbl, fg, bg, req in rows]


# ---------------------------------------------------------------- escalas


@dataclass(frozen=True, slots=True)
class Spacing:
    """Grade de 4 px. Dentro do grupo 12, entre grupos 24, margem de janela 24."""
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32
    huge: int = 48


@dataclass(frozen=True, slots=True)
class Radii:
    """4 campos/botoes, 8 cartoes/paineis, 12 dialogos. Pilula so em StatusChip/ChipList."""
    sm: int = 4
    md: int = 8
    lg: int = 12


@dataclass(frozen=True, slots=True)
class Typography:
    """Escala em px de design (convertida para pt). 13 e a base; 48 so para contador tabular."""
    caption: int = 11
    small: int = 12
    body: int = 13
    heading: int = 16
    title: int = 20
    display: int = 28
    counter: int = 48
    regular: int = 400
    semibold: int = 600
    bold: int = 700
    line_body: float = 1.4
    line_title: float = 1.2
    families: tuple[str, ...] = ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI")


@dataclass(frozen=True, slots=True)
class Motion:
    """Duracoes em ms (ease-out). 0 quando 'reduzir animacoes' do Windows esta ligado."""
    fast: int = 120
    base: int = 150
    slow: int = 180
    toast: int = 5000


@dataclass(frozen=True, slots=True)
class Sizes:
    """Alvos e tracos. Todo alvo de clique >= 32 px; foco = anel de 2 px com 2 px de folga."""
    target: int = 32
    icon: int = 16
    icon_lg: int = 20
    border: int = 1
    focus_ring: int = 2
    focus_gap: int = 2
    stroke: float = 1.5
    nav_width: int = 240
    reading_width: int = 720
    toggle_w: int = 40
    toggle_h: int = 22


SPACE: Final = Spacing()
RADIUS: Final = Radii()
TYPE: Final = Typography()
MOTION: Final = Motion()
SIZE: Final = Sizes()


def pt(px: float) -> float:
    """px de design a 96 dpi em pontos (o Qt escala pontos com o DPI do monitor)."""
    return px * 72.0 / 96.0


def make_font(size_px: float = TYPE.body, weight: int = TYPE.regular, *, tabular: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(list(TYPE.families))
    f.setPointSizeF(pt(size_px))
    f.setWeight(QFont.Weight(weight))
    if tabular:
        f.setFeature(QFont.Tag("tnum"), 1)
    return f


def dp(n: float) -> int:
    """Pixels LOGICOS inteiros (o Qt 6 ja aplica a escala do monitor a eles)."""
    return int(round(n))


def _dpr(widget: QWidget | None) -> float:
    if widget is not None:
        return widget.devicePixelRatioF()
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


def px(n: float, widget: QWidget | None = None) -> int:
    """Pixels FISICOS (n * devicePixelRatio): tamanho de pixmap/QImage para ficar nitido."""
    return max(1, int(round(n * _dpr(widget))))


def crisp(v: float, widget: QWidget | None = None) -> float:
    """Alinha ``v`` (logico) a grade de pixels fisicos, para tracos de 1 px sem borrao."""
    d = _dpr(widget)
    return round(v * d) / d


# ---------------------------------------------------------------- movimento e tema do sistema

_motion_override: bool | None = None


def set_motion_override(enabled: bool | None) -> None:
    """Forca animacoes ligadas/desligadas (None = seguir o Windows). Usado por testes e Configuracoes."""
    global _motion_override
    _motion_override = enabled


def motion_enabled() -> bool:
    """False se o usuario pediu 'reduzir animacoes' no Windows (SPI_GETCLIENTAREAANIMATION)."""
    if _motion_override is not None:
        return _motion_override
    if os.environ.get("JARVIS_REDUCE_MOTION") == "1":
        return False
    if sys.platform != "win32":
        return True
    flag = ctypes.c_int(1)
    ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)  # type: ignore[attr-defined]
    return bool(flag.value) if ok else True


def duration(ms: int) -> int:
    """``ms`` se animar, senao 0."""
    return ms if motion_enabled() else 0


def system_prefers_dark() -> bool:
    """Tema do Windows: QStyleHints.colorScheme (Qt 6.5+), com o registro como reserva."""
    hints = QGuiApplication.styleHints() if QGuiApplication.instance() else None
    scheme = hints.colorScheme() if hints is not None else Qt.ColorScheme.Unknown
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            return True
    return True


# ---------------------------------------------------------------- gerenciador


class ThemeManager(QObject):
    """Dono do modo de tema. ``changed(str)`` dispara com o tema EFETIVO quando ele muda."""

    changed = Signal(str)
    modeChanged = Signal(str)
    _instance: "ThemeManager | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._mode: Mode = "system"
        self._effective: Effective = "dark"
        self._app: QApplication | None = None
        self._legacy = False

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._effective = cls._instance._resolve()
        return cls._instance

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def effective(self) -> Effective:
        return self._effective

    @property
    def palette(self) -> Palette:
        return DARK if self._effective == "dark" else LIGHT

    def _resolve(self) -> Effective:
        if self._mode == "system":
            return "dark" if system_prefers_dark() else "light"
        return self._mode

    def set_mode(self, mode: Mode) -> None:
        """Troca em tempo de execucao; reaplica a stylesheet no app e emite ``changed`` se mudou."""
        if mode not in ("dark", "light", "system"):
            raise ValueError(f"modo de tema invalido: {mode!r}")
        if mode != self._mode:
            self._mode = mode
            self.modeChanged.emit(mode)
        self.refresh()

    def refresh(self) -> None:
        """Rele o tema do sistema (se mode=system) e reaplica quando o efetivo mudou."""
        eff = self._resolve()
        if eff != self._effective:
            self._effective = eff
            self._install()
            self.changed.emit(eff)

    def stylesheet(self) -> str:
        from .kit.qss import build_qss
        css = build_qss(self.palette)
        if self._legacy:
            from .kit.legacy_qss import build_legacy_qss
            css += build_legacy_qss(self.palette)
        return css

    def apply(self, app: QApplication | None = None, *, legacy: bool = False) -> None:
        """Instala estilo Fusion, fonte, QPalette e stylesheet no app e passa a acompanhar o Windows."""
        target = app or QApplication.instance()
        if not isinstance(target, QApplication):
            raise RuntimeError("ThemeManager.apply precisa de um QApplication")
        if self._app is not target:
            self._app = target
            hints = target.styleHints()
            if hasattr(hints, "colorSchemeChanged"):
                hints.colorSchemeChanged.connect(lambda *_: self.refresh())
        self._legacy = self._legacy or legacy
        self._effective = self._resolve()
        self._install()
        self.changed.emit(self._effective)

    def _install(self) -> None:
        app = self._app
        if app is None:
            return
        app.setStyle("Fusion")
        app.setFont(make_font())
        app.setPalette(_qpalette(self.palette))
        app.setStyleSheet(self.stylesheet())


def manager() -> ThemeManager:
    return ThemeManager.instance()


def pal() -> Palette:
    """Paleta do tema efetivo agora."""
    return ThemeManager.instance().palette


def _qpalette(p: Palette) -> QPalette:
    qp = QPalette()
    roles = {QPalette.ColorRole.Window: p.bg, QPalette.ColorRole.WindowText: p.text,
             QPalette.ColorRole.Base: p.surface, QPalette.ColorRole.AlternateBase: p.raised,
             QPalette.ColorRole.Text: p.text, QPalette.ColorRole.Button: p.raised,
             QPalette.ColorRole.ButtonText: p.text, QPalette.ColorRole.Highlight: p.accent,
             QPalette.ColorRole.HighlightedText: p.on_accent, QPalette.ColorRole.PlaceholderText: p.text_muted,
             QPalette.ColorRole.ToolTipBase: p.raised, QPalette.ColorRole.ToolTipText: p.text,
             QPalette.ColorRole.Link: p.accent_ink, QPalette.ColorRole.BrightText: p.text}
    for role, color in roles.items():
        qp.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        qp.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.text_disabled))
    return qp


def repolish(widget: QWidget) -> None:
    """Reaplica o stylesheet depois de mudar uma propriedade dinamica (variant, state, invalid...)."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


# ---------------------------------------------------------------- compatibilidade DEPRECATED

SP1: Final = 8     # DEPRECATED: grade antiga de 8 px; use SPACE.*
SP2: Final = 16
SP3: Final = 24
SP4: Final = 32
SPACE_LEGACY: Final = 8
RADIUS_SM: Final = RADIUS.sm   # DEPRECATED
RADIUS_MD: Final = RADIUS.md
RADIUS_LG: Final = RADIUS.lg
FONT_FAMILY: Final = TYPE.families[-1]
FONT_SIZE_BASE, FONT_SIZE_SMALL, FONT_SIZE_TITLE = 10, 9, 14   # pt antigos (DEPRECATED)
FONT_SIZE_PHRASE, FONT_SIZE_COUNTDOWN = 22, 40
_LEGACY_COLORS: Final = {"BG": "bg", "SURFACE": "surface", "SURFACE_ALT": "raised", "BORDER": "border",
                         "TEXT": "text", "TEXT_MUTED": "text_muted", "ACCENT": "accent",
                         "ACCENT_HOVER": "accent_hover", "ACCENT_PRESSED": "accent_pressed",
                         "ON_ACCENT": "on_accent", "OK": "ok", "WARN": "warn", "ERROR": "error",
                         "DISABLED_TEXT": "text_disabled"}
_LEVEL_STATE: Final[dict[str, State]] = {"ok": "ok", "baixo": "warn", "saturado": "error", "silencio": "error"}


def __getattr__(name: str) -> Any:
    """Constantes de cor antigas (BG, TEXT...) resolvem para a paleta ATUAL."""
    if name in _LEGACY_COLORS:
        return getattr(pal(), _LEGACY_COLORS[name])
    if name == "STATE_COLORS":
        p = pal()
        return {"ok": p.ok, "warn": p.warn, "error": p.error}
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def level_state(level: str) -> State:
    """DEPRECATED. Mapeia o veredito de ``audio_analysis.assess`` para o estado de cor."""
    return _LEVEL_STATE.get(level, "warn")


def state_color(state: str) -> str:
    """DEPRECATED. Cor do estado no tema atual."""
    return pal().state(state)


def build_stylesheet() -> str:
    """DEPRECATED. Stylesheet base + papeis antigos (role/variant/state) do tema atual."""
    from .kit.legacy_qss import build_legacy_qss
    from .kit.qss import build_qss
    return build_qss(pal()) + build_legacy_qss(pal(), extras=False)


def build_settings_stylesheet() -> str:
    """DEPRECATED. Estilos extras das telas antigas (cartao, nav, tabelas, selos)."""
    from .kit.legacy_qss import build_legacy_qss
    return build_legacy_qss(pal(), extras=True, base=False)


def apply_theme(app: QApplication) -> None:
    """DEPRECATED. Aplica o novo sistema forcando tema ESCURO (as telas antigas foram feitas so para ele)."""
    mgr = ThemeManager.instance()
    mgr._mode = "dark"
    mgr._effective = "dark"
    mgr.apply(app, legacy=True)
