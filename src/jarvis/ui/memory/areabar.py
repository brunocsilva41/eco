"""Faixa de áreas do painel (Memórias, Conversas, Armazenamento e privacidade).

Navegação própria, na horizontal, bem diferente da coluna lateral das Configurações: texto puro, sublinhado âmbar
só na área aberta (estado, não enfeite), foco visível e setas Esquerda/Direita do ``QTabBar``.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QTabBar, QWidget

from ..kit.base import paint_focus_ring, watch_theme
from ..theme import RADIUS, SIZE, SPACE, TYPE, make_font, pal

_UNDERLINE = SIZE.focus_ring


class AreaBar(QTabBar):
    """Abas em texto. ``currentChanged(int)`` vem do ``QTabBar``; ``set_areas`` recria as abas."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hover = -1
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(False)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        watch_theme(self)

    def set_areas(self, names: list[str]) -> None:
        while self.count():
            self.removeTab(0)
        for name in names:
            self.addTab(name)
            self.setTabToolTip(self.count() - 1, name)

    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802
        fm = QFontMetrics(make_font(TYPE.body, TYPE.semibold))
        return QSize(fm.horizontalAdvance(self.tabText(index)) + 2 * SPACE.lg, SIZE.target + SPACE.sm)

    def minimumTabSizeHint(self, index: int) -> QSize:  # noqa: N802
        return self.tabSizeHint(index)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        self._set_hover(self.tabAt(e.position().toPoint()))
        super().mouseMoveEvent(e)

    def leaveEvent(self, e: QEvent) -> None:  # noqa: N802
        self._set_hover(-1)
        super().leaveEvent(e)

    def _set_hover(self, index: int) -> None:
        if index != self._hover:
            self._hover = index
            self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:  # noqa: N802
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        g.setPen(QPen(QColor(p.border), 1.0))
        g.drawLine(QPoint(0, h - 1), QPoint(w, h - 1))
        for i in range(self.count()):
            r = QRectF(self.tabRect(i))
            body = r.adjusted(SPACE.xs, SPACE.xs, -SPACE.xs, -SPACE.xs - 1)
            selected = i == self.currentIndex()
            if i == self._hover and not selected:
                g.setPen(Qt.PenStyle.NoPen)
                g.setBrush(QColor(p.hover))
                g.drawRoundedRect(body, RADIUS.sm, RADIUS.sm)
            g.setFont(make_font(TYPE.body, TYPE.semibold if selected else TYPE.regular))
            g.setPen(QColor(p.text if selected else p.text_muted))
            g.drawText(body, int(Qt.AlignmentFlag.AlignCenter), self.tabText(i))
            if selected:
                g.setPen(Qt.PenStyle.NoPen)
                g.setBrush(QColor(p.accent_ink))
                g.drawRect(QRectF(r.left() + SPACE.md, h - _UNDERLINE, r.width() - 2 * SPACE.md, _UNDERLINE))
                if self.hasFocus():
                    paint_focus_ring(g, body.adjusted(0, 0, 0, -1), RADIUS.sm)
        g.end()
