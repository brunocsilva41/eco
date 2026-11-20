"""Tokens de design do Jarvis (fonte unica) e gerenciador de tema em tempo de execucao.

Tudo que e cor, tamanho, raio, espacamento, fonte ou duracao mora aqui; o resto da UI so le estes
tokens. Uso::

    from jarvis.ui.theme import ThemeManager, pal, SPACE, RADIUS, TYPE, SIZE, MOTION
    mgr = ThemeManager.instance()
    mgr.set_mode("system")             # "dark" | "light" | "system" (segue o Windows)
    mgr.apply(app)                     # Fusion, fonte, QPalette e stylesheet gerada dos tokens
    mgr.changed.connect(slot)          # sinal(str "dark"|"light") a cada troca, sem reiniciar
    color = pal().accent_ink           # paleta do tema efetivo agora

Unidades: layout/QSS em pixels LOGICOS (o Qt 6 ja aplica a escala do monitor); texto em pontos
(px*72/96), entao acompanha DPI e escala de 100% a 200%. ``dp(n)`` = px logicos inteiros;
``px(n, widget)`` = px FISICOS (n*devicePixelRatio) para pixmaps nitidos; ``crisp(v, widget)`` alinha
a grade fisica. DEPRECATED (telas antigas): apply_theme, build_stylesheet, build_settings_stylesheet,
level_state, state_color, repolish, constantes BG/SURFACE/.../SP1..SP4/RADIUS_*.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from .kit.color import contrast, contrast_pairs, ensure_contrast, luminance, mix  # noqa: F401 (re-export)
from .kit.platform import motion_enabled, set_motion_override, system_prefers_dark  # noqa: F401 (re-export)


Mode = Literal["dark", "light", "system"]
Effective = Literal["dark", "light"]
State = Literal["ok", "warn", "error"]

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

    @property
    def focus_ring(self) -> str:
        """Cor do anel de foco (ambar com >= 3:1 contra todas as superficies)."""
        return self.accent_ink

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


def dpr(widget: QWidget | None) -> float:
    if widget is not None:
        return widget.devicePixelRatioF()
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


def px(n: float, widget: QWidget | None = None) -> int:
    """Pixels FISICOS (n * devicePixelRatio): tamanho de pixmap/QImage para ficar nitido."""
    return max(1, int(round(n * dpr(widget))))


def crisp(v: float, widget: QWidget | None = None) -> float:
    """Alinha ``v`` (logico) a grade de pixels fisicos, para tracos de 1 px sem borrao."""
    d = dpr(widget)
    return round(v * d) / d



def duration(ms: int) -> int:
    """``ms`` se animar, senao 0 ('reduzir animacoes' do Windows)."""
    return ms if motion_enabled() else 0


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
        from .kit.qss import build_qpalette
        app.setStyle("Fusion")
        app.setFont(make_font())
        app.setPalette(build_qpalette(self.palette))
        app.setStyleSheet(self.stylesheet())


def manager() -> ThemeManager:
    return ThemeManager.instance()


def pal() -> Palette:
    """Paleta do tema efetivo agora."""
    return ThemeManager.instance().palette


def repolish(widget: QWidget) -> None:
    """Reaplica o stylesheet depois de mudar uma propriedade dinamica (variant, state, invalid...)."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


# ---------------------------------------------------------------- compatibilidade DEPRECATED

SP1, SP2, SP3, SP4 = 8, 16, 24, 32   # DEPRECATED: grade antiga de 8 px; use SPACE.*
RADIUS_SM, RADIUS_MD, RADIUS_LG = RADIUS.sm, RADIUS.md, RADIUS.lg   # DEPRECATED
FONT_FAMILY: Final = TYPE.families[-1]
FONT_SIZE_BASE, FONT_SIZE_SMALL, FONT_SIZE_TITLE, FONT_SIZE_PHRASE, FONT_SIZE_COUNTDOWN = 10, 9, 14, 22, 40  # pt antigos


def __getattr__(name: str) -> Any:
    """Constantes de cor antigas (BG, TEXT, OK...) resolvem para a paleta ATUAL."""
    if not name.isupper():       # o import system consulta __path__/__spec__: nao delegue
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .kit.legacy_qss import LEGACY_COLORS
    if name in LEGACY_COLORS:
        return getattr(pal(), LEGACY_COLORS[name])
    if name == "STATE_COLORS":
        return {k: pal().state(k) for k in ("ok", "warn", "error")}
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def level_state(level: str) -> State:
    """DEPRECATED. Mapeia o veredito de ``audio_analysis.assess`` para o estado de cor."""
    from .kit.legacy_qss import LEVEL_STATE
    return LEVEL_STATE.get(level, "warn")  # type: ignore[return-value]


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
