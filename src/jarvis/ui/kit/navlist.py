"""NavList: navegacao lateral com marcador ambar no item selecionado e contadores de erro/alteracao."""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QWidget)

from ..theme import RADIUS, SIZE, SPACE, TYPE, make_font, pal
from . import icons
from .base import paint_focus_ring, strs, watch_theme

_KEY, _ERR, _CHG, _ICON = Qt.ItemDataRole.UserRole, Qt.ItemDataRole.UserRole + 1, Qt.ItemDataRole.UserRole + 2, Qt.ItemDataRole.UserRole + 3
_HIT = Qt.ItemDataRole.UserRole + 4              # resultados da busca nesta pagina (None = sem busca)
_ROW_H = SIZE.target + SPACE.sm
_MARK_W = 3
_SMALL = SIZE.icon - 2


class _NavDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), _ROW_H)

    def paint(self, g: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        p = pal()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        view = option.widget
        r = QRectF(option.rect).adjusted(SPACE.xs, 1, -SPACE.xs, -1)
        g.save()
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        g.setPen(Qt.PenStyle.NoPen)
        if selected or hover:
            g.setBrush(QColor(p.raised if selected else p.hover))
            g.drawRoundedRect(r, RADIUS.sm, RADIUS.sm)
        if selected:   # marcador: so o item atual (informacao de estado, nao enfeite)
            g.setBrush(QColor(p.accent_ink))
            g.drawRoundedRect(QRectF(r.left(), r.top() + SPACE.sm, _MARK_W, r.height() - 2 * SPACE.sm), 1.5, 1.5)
        x = r.left() + SPACE.md
        mid = r.center().y()
        g.drawPixmap(int(x), int(mid - SIZE.icon / 2), icons.pixmap(index.data(_ICON), p.text if selected else p.text_muted, SIZE.icon, view))
        right = r.right() - SPACE.sm
        g.setFont(make_font(TYPE.small))
        fm = QFontMetrics(g.font())
        hits = index.data(_HIT)
        if hits is not None:                       # contador da busca: pilula com o numero de campos que casaram
            txt = str(int(hits))
            w = fm.horizontalAdvance(txt) + SPACE.md
            pill = QRectF(right - w, mid - (fm.height() + 2) / 2, w, fm.height() + 2)
            g.setBrush(QColor(p.accent if int(hits) else p.pressed))
            g.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            g.setPen(QColor(p.on_accent if int(hits) else p.text_muted))
            g.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), txt)
            g.setPen(Qt.PenStyle.NoPen)
            right -= w + SPACE.sm
        for role, icon_name, color in ((_ERR, "error", p.error), (_CHG, "edit", p.text_muted)):
            n = int(index.data(role) or 0)
            if n:
                txt = str(n)
                w = fm.horizontalAdvance(txt)
                g.setPen(QColor(color))
                g.drawText(QRectF(right - w, r.top(), w, r.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), txt)
                right -= w + SPACE.xs
                g.drawPixmap(int(right - _SMALL), int(mid - _SMALL / 2), icons.pixmap(icon_name, color, _SMALL, view))
                right -= _SMALL + SPACE.sm
        g.setFont(make_font(TYPE.body, TYPE.semibold if selected else TYPE.regular))
        g.setPen(QColor(p.text))
        tx = x + SIZE.icon + SPACE.md
        text = QFontMetrics(g.font()).elidedText(index.data(Qt.ItemDataRole.DisplayRole), Qt.TextElideMode.ElideRight, int(right - tx))
        g.drawText(QRectF(tx, r.top(), right - tx, r.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        if view is not None and view.hasFocus() and bool(option.state & QStyle.StateFlag.State_HasFocus):
            paint_focus_ring(g, r, RADIUS.sm)
        g.restore()


class NavList(QListWidget):
    """Lista de navegacao de uma coluna. Setas/Home/End movem; um unico Tab entra e sai da lista.

    Sinal: ``currentKeyChanged(str)`` com a chave do item. Contadores por item: ``set_counts(key,
    errors=, changes=)`` mostram icone + numero (e o numero entra no texto acessivel).
    """

    currentKeyChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("kit", "nav")
        self.setItemDelegate(_NavDelegate(self))
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedWidth(SIZE.nav_width)
        self.currentItemChanged.connect(self._on_current)
        watch_theme(self)

    def add_entry(self, key: str, text: str, icon_name: str) -> None:
        item = QListWidgetItem(text)
        item.setData(_KEY, key)
        item.setData(_ICON, icon_name)
        item.setData(_ERR, 0)
        item.setData(_CHG, 0)
        item.setSizeHint(QSize(SIZE.nav_width, _ROW_H))
        item.setToolTip(text)
        self.addItem(item)
        self._describe(item)

    def set_current(self, key: str) -> None:
        item = self._item(key)
        if item is not None:
            self.setCurrentItem(item)

    def current_key(self) -> str:
        item = self.currentItem()
        return str(item.data(_KEY)) if item is not None else ""

    def set_counts(self, key: str, *, errors: int = 0, changes: int = 0) -> None:
        item = self._item(key)
        if item is not None:
            item.setData(_ERR, errors)
            item.setData(_CHG, changes)
            self._describe(item)
            self.viewport().update()

    def set_hits(self, key: str, hits: int | None) -> None:
        """Mostra (ou, com None, esconde) o contador de resultados da busca no item."""
        item = self._item(key)
        if item is not None:
            item.setData(_HIT, hits)
            self.viewport().update()

    def _item(self, key: str) -> QListWidgetItem | None:
        for i in range(self.count()):
            it = self.item(i)
            if it is not None and it.data(_KEY) == key:
                return it
        return None

    def _describe(self, item: QListWidgetItem) -> None:
        item.setData(Qt.ItemDataRole.AccessibleTextRole,
                     strs().nav.describe(item.text(), int(item.data(_ERR) or 0), int(item.data(_CHG) or 0)))

    def _on_current(self, cur: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if cur is not None:
            self.currentKeyChanged.emit(str(cur.data(_KEY)))
