"""Button: primario (ambar), secundario, perigo e texto, com icone opcional e foco visivel."""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QKeySequence, QPainter, QPaintEvent
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from ..theme import RADIUS, SIZE, Palette, pal, repolish
from . import icons
from .base import paint_focus_ring, set_a11y, watch_theme

ButtonVariant = Literal["primary", "secondary", "danger", "text"]


class Button(QPushButton):
    """Botao do kit. Estados: normal, hover, foco (anel ambar 2 px), pressionado, desabilitado.

    * ``variant``: "primary" (uma por tela, a acao principal), "secondary", "danger", "text".
    * ``icon_name``: nome em ``kit.icons.NAMES``; a cor acompanha variante, estado e tema.
    * ``icon_only=True``: 32x32; ``text`` vira nome acessivel e dica (obrigatorio descrever a acao).
    * ``shortcut``: ex. "Space", "Ctrl+S"; aparece na dica e na descricao acessivel.
    Sinais: os do QPushButton (``clicked``, ``toggled``).
    """

    def __init__(self, text: str = "", *, variant: ButtonVariant = "secondary", icon_name: str | None = None,
                 icon_only: bool = False, shortcut: str = "", parent: QWidget | None = None) -> None:
        super().__init__("" if icon_only else text, parent)
        self._variant: ButtonVariant = variant
        self._icon_name = icon_name
        self._label = text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setIconSize(QSize(SIZE.icon, SIZE.icon))
        self.setProperty("variant", variant)
        self.setProperty("iconOnly", icon_only)
        self.setMinimumHeight(SIZE.target)
        if icon_only:
            self.setFixedSize(SIZE.target, SIZE.target)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.set_shortcut_hint(shortcut)
        watch_theme(self, self._refresh_icon)
        self._refresh_icon()

    # --- API
    def variant(self) -> ButtonVariant:
        return self._variant

    def set_variant(self, variant: ButtonVariant) -> None:
        self._variant = variant
        self.setProperty("variant", variant)
        repolish(self)
        self._refresh_icon()

    def set_icon_name(self, name: str | None) -> None:
        self._icon_name = name
        self._refresh_icon()

    def set_shortcut_hint(self, shortcut: str) -> None:
        self.setShortcut(QKeySequence(shortcut) if shortcut else QKeySequence())
        tip = f"{self._label} ({shortcut})" if shortcut else self._label
        self.setToolTip(tip)
        set_a11y(self, self._label, f"Atalho: {shortcut}" if shortcut else "")

    # --- interno
    def _icon_color(self, p: Palette, disabled: bool = False) -> str:
        if disabled:
            return p.text_disabled
        return {"primary": p.on_accent, "danger": p.on_error}.get(self._variant, p.text)

    def _refresh_icon(self) -> None:
        if not self._icon_name:
            self.setIcon(QIcon())
            return
        p = pal()
        self.setIcon(icons.icon(self._icon_name, self._icon_color(p), SIZE.icon,
                                disabled_color=self._icon_color(p, True), widget=self))

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.hasFocus():
            painter = QPainter(self)
            gap = pal().bg if self._variant in ("primary", "danger") else None
            paint_focus_ring(painter, QRectF(self.rect()), RADIUS.sm, gap_color=gap)
            painter.end()
