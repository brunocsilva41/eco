"""IconSet: conjunto unico de icones proprios, tracos de 1,5 px em grade de 24, desenhados aqui.

Voz do conjunto (para nao parecer biblioteca generica): pontas retas e juntas em esquadro,
cantos chanfrados a 45 graus nas formas fechadas (microfone, escudo, cerebro, pasta), como
mostrador de cabine. Curvas so onde o objeto e curvo (ouvido, circulos, setas de atualizar).
Nada de faiscas, estrelas, robos ou orbes. O icone de cada nome e relevante ao seu conteudo:
``settings`` e um painel de ajustes (tres controles deslizantes), ``memory`` e uma caixa de
arquivo, ``brain`` representa o modelo de linguagem.

Cada icone e uma string SVG; ``currentColor`` e trocado pela cor pedida, entao o icone
sempre usa a cor do tema. Renderizado em pixels FISICOS (devicePixelRatio) e cacheado.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from ..theme import SIZE, dpr

_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
         'stroke-width="1.5" stroke-linecap="square" stroke-linejoin="miter">')


def _p(*d: str) -> str:
    return "".join(f'<path d="{x}"/>' for x in d)


_FILLED = 'fill="currentColor"'
_BODIES: dict[str, str] = {
    "settings": _p("M4 6H12M18 6H20", "M4 12H6M12 12H20", "M4 18H10M16 18H20")
    + '<rect x="12" y="4" width="6" height="4"/><rect x="6" y="10" width="6" height="4"/><rect x="10" y="16" width="6" height="4"/>',
    "mic": _p("M9 5L10 4H14L15 5V11L14 12H10L9 11Z", "M6 11V12L9 16H15L18 12V11", "M12 16V20", "M9 20H15"),
    "ear": _p("M7.5 10A4.5 4.5 0 0 1 16.5 10C16.5 12.2 15 13 14.3 14.3C13.6 15.6 13.5 18 11.5 18C9.9 18 9.2 16.7 9.2 15.4",
              "M10.5 10A1.5 1.5 0 0 1 13.5 10C13.5 11 12.5 11.4 12 12.2"),
    "brain": _p("M12 5V19", "M12 5H9.5L7 7.5V9L5.5 10.5V13.5L7 15V16.5L9.5 19H12",
                "M12 5H14.5L17 7.5V9L18.5 10.5V13.5L17 15V16.5L14.5 19H12", "M7 9H9.5V12", "M17 9H14.5V12", "M7 15H10", "M17 15H14"),
    "shield": _p("M12 3.5L19 6V12L16.5 17L12 20.5L7.5 17L5 12V6Z"),
    "folder": _p("M3.5 6.5V18.5H20.5V8.5H11L9.5 6.5Z"),
    "memory": _p("M4 5H20V9H4Z", "M5.5 9V19H18.5V9", "M10 13H14"),
    "log": _p("M6 3.5H14.5L18 7V20.5H6Z", "M14 3.5V7.5H18", "M9 12H15", "M9 15H15", "M9 18H12"),
    "lock": _p("M6 11H18V20H6Z", "M8.5 11V8L10 5.5H14L15.5 8V11", "M12 14.5V16.5"),
    "alert": _p("M12 4L21 19.5H3Z", "M12 10V14", "M12 16.5V17.5"),
    "ok": '<circle cx="12" cy="12" r="8.5"/>' + _p("M8 12.5L11 15.5L16.5 9.5"),
    "error": _p("M8.5 3.5H15.5L20.5 8.5V15.5L15.5 20.5H8.5L3.5 15.5V8.5Z", "M9 9L15 15", "M15 9L9 15"),
    "info": '<circle cx="12" cy="12" r="8.5"/>' + _p("M12 11V16", "M12 8V9"),
    "search": '<circle cx="10.5" cy="10.5" r="6"/>' + _p("M15 15L20 20"),
    "record": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5" ' + _FILLED + "/>",
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" ' + _FILLED + "/>",
    "listen": _p("M4 9.5H8L13 5.5V18.5L8 14.5H4Z", "M16 9C17.3 10.3 17.3 13.7 16 15", "M18.5 6.5C21 9 21 15 18.5 17.5"),
    "skip": _p("M4.5 6L11.5 12L4.5 18Z", "M12.5 6L19.5 12L12.5 18Z"),
    "next": _p("M7 6L15 12L7 18Z", "M18 6V18"),
    "prev": _p("M17 6L9 12L17 18Z", "M6 6V18"),
    "trash": _p("M4 7H20", "M9.5 7V4.5H14.5V7", "M6 7L7 20H17L18 7", "M10 11V16", "M14 11V16"),
    "edit": _p("M4 20V16L15 5L19 9L8 20Z", "M13 7L17 11"),
    "pin": _p("M9 4H15V8L17.5 12H6.5L9 8Z", "M12 12V20"),
    "refresh": _p("M18.5 12A6.5 6.5 0 1 1 16.6 7.4", "M17 3.5V7.5H13"),
    "close": _p("M6 6L18 18", "M18 6L6 18"),
    "plus": _p("M12 5V19", "M5 12H19"),
    "minus": _p("M5 12H19"),
    "check": _p("M5 12.5L10 17.5L19 7"),
    "chevron_down": _p("M6 9.5L12 15.5L18 9.5"),
    "keyboard": _p("M3.5 6.5H20.5V17.5H3.5Z", "M7 10H7.5", "M10.5 10H11", "M14 10H14.5", "M17 10H17.5", "M8 14H16"),
}
NAMES: tuple[str, ...] = tuple(_BODIES)


@lru_cache(maxsize=512)
def _render(name: str, color: str, size_phys: int) -> QPixmap:
    svg = f"{_HEAD}{_BODIES[name]}</svg>".replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size_phys, size_phys)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(p, QRectF(0, 0, size_phys, size_phys))
    p.end()
    return pm


def pixmap(name: str, color: str, size: int = SIZE.icon, widget: QWidget | None = None) -> QPixmap:
    """Pixmap nitido: ``size`` em pixels logicos, desenhado em pixels fisicos e marcado com o DPR."""
    if name not in _BODIES:
        raise KeyError(f"icone desconhecido: {name!r} (disponiveis: {', '.join(NAMES)})")
    ratio = dpr(widget)
    pm = _render(name, color, max(1, round(size * ratio))).copy()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str, size: int = SIZE.icon, *, disabled_color: str | None = None,
         widget: QWidget | None = None) -> QIcon:
    """QIcon com estado normal e (opcional) desabilitado; refaca quando o tema mudar."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size, widget), QIcon.Mode.Normal)
    if disabled_color:
        ic.addPixmap(pixmap(name, disabled_color, size, widget), QIcon.Mode.Disabled)
    return ic


class IconSet:
    """Atalho em forma de classe: ``IconSet.icon("mic", color)``, ``IconSet.NAMES``."""

    NAMES = NAMES
    pixmap = staticmethod(pixmap)
    icon = staticmethod(icon)
