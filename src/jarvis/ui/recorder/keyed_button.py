"""Botao do kit com a tecla de atalho desenhada ao lado do texto (o atalho fica visivel, nao so na dica)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from ..kit.base import set_a11y
from ..kit.buttons import Button, ButtonVariant
from ..theme import RADIUS, SIZE, SPACE, TYPE, make_font, pal

_KEY_H = SPACE.lg + SPACE.xs


class KeyedButton(Button):
    """``Button`` + tecla em uma plaquinha a direita. O atalho real e ligado por quem usa (``shortcut`` ou
    por roteador de teclas da janela); ``key`` e so o texto mostrado. Alcancavel por Tab, nao por clique."""

    def __init__(self, label: str, key: str, *, variant: ButtonVariant = "secondary", icon_name: str | None = None,
                 shortcut: str = "", large: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(label, variant=variant, icon_name=icon_name, shortcut=shortcut, parent=parent)
        self._key = key
        self._plain = label
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)      # o clique do mouse nao rouba o foco do teclado
        if large:
            self.setMinimumHeight(SIZE.target + SPACE.md)
        self._reserve()
        self._describe()

    def set_action(self, label: str, key: str) -> None:
        """Troca texto e tecla (ex.: Gravar vira Parar)."""
        self._plain, self._key = label, key
        self.setText(label)
        self._reserve()
        self._describe()

    def _key_width(self) -> int:
        return max(SPACE.xl, QFontMetrics(make_font(TYPE.caption, TYPE.semibold)).horizontalAdvance(self._key) + 2 * SPACE.sm)

    def _reserve(self) -> None:
        self.setStyleSheet(f"QPushButton {{ padding-right: {SPACE.lg + self._key_width() + SPACE.sm}px; }}")
        self.updateGeometry()

    def _describe(self) -> None:
        self.setToolTip(f"{self._plain} ({self._key})")
        set_a11y(self, self._plain, f"Atalho: {self._key}")

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        p = pal()
        if not self.isEnabled():
            ink = p.text_disabled
        else:
            ink = {"primary": p.on_accent, "danger": p.on_error}.get(self.variant(), p.text_muted)
        w = float(self._key_width())
        box = QRectF(self.width() - SPACE.lg - w + SPACE.xs, (self.height() - _KEY_H) / 2, w, _KEY_H)
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(QPen(QColor(ink), SIZE.border))
        g.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS.sm, RADIUS.sm)
        g.setFont(make_font(TYPE.caption, TYPE.semibold))
        g.drawText(box, int(Qt.AlignmentFlag.AlignCenter), self._key)
        g.end()
