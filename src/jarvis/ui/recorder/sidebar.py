"""Lista lateral dos itens com o estado de cada um, e os botoes do editor de frases."""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QListWidget, QListWidgetItem, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QWidget)

from ..kit import icons
from ..kit.base import Label, paint_focus_ring, set_a11y, watch_theme
from ..kit.buttons import Button
from ..kit.layout import Card
from ..kit.status import STATE_ICON, state_ink
from ..theme import RADIUS, SIZE, SPACE, TYPE, make_font, pal
from .state import RowView
from .texts import T

_NUMBER, _STATUS, _KIND = (Qt.ItemDataRole.UserRole + n for n in (1, 2, 3))
_ROW_H = SPACE.huge
_MARK_W = 3
_SMALL = SIZE.icon - 2
_NUM_W = SPACE.xl


class _RowDelegate(QStyledItemDelegate):
    """Duas linhas: numero + texto; embaixo icone + palavra do estado (o estado nunca e so cor)."""

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
            g.setBrush(QColor(p.pressed if selected else p.hover))
            g.drawRoundedRect(r, RADIUS.sm, RADIUS.sm)
        if selected:        # marcador: so o item atual (estado, nao enfeite)
            g.setBrush(QColor(p.accent_ink))
            g.drawRoundedRect(QRectF(r.left(), r.top() + SPACE.sm, _MARK_W, r.height() - 2 * SPACE.sm), 1.5, 1.5)
        x = r.left() + SPACE.md
        half = r.height() / 2
        g.setFont(make_font(TYPE.small, TYPE.semibold, tabular=True))
        g.setPen(QColor(p.text_muted))
        g.drawText(QRectF(x, r.top(), _NUM_W, half + SPACE.xs), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   f"{int(index.data(_NUMBER)):02d}")
        tx = x + _NUM_W + SPACE.xs
        g.setFont(make_font(TYPE.body, TYPE.semibold if selected else TYPE.regular))
        g.setPen(QColor(p.text))
        text = QFontMetrics(g.font()).elidedText(index.data(Qt.ItemDataRole.DisplayRole), Qt.TextElideMode.ElideRight,
                                                 int(r.right() - SPACE.sm - tx))
        g.drawText(QRectF(tx, r.top(), r.right() - tx, half + SPACE.xs), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        kind = str(index.data(_KIND))
        ink = state_ink(p, kind)
        row2 = QRectF(tx, r.top() + half + SPACE.xs, r.right() - tx, half - SPACE.sm)
        g.drawPixmap(int(row2.left()), int(row2.center().y() - _SMALL / 2), icons.pixmap(STATE_ICON[kind], ink, _SMALL, view))
        g.setFont(make_font(TYPE.caption))
        g.setPen(QColor(ink if kind != "neutral" else p.text_muted))
        g.drawText(row2.adjusted(_SMALL + SPACE.xs, 0, 0, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   str(index.data(_STATUS)))
        if view is not None and view.hasFocus() and bool(option.state & QStyle.StateFlag.State_HasFocus):
            paint_focus_ring(g, r, RADIUS.sm)
        g.restore()


class _UpButton(Button):
    """Seta para cima: o conjunto de icones so tem a seta para baixo, entao ela e girada 180 graus."""

    def _refresh_icon(self) -> None:
        p = pal()
        ic = QIcon()
        for mode, color in ((QIcon.Mode.Normal, p.text), (QIcon.Mode.Disabled, p.text_disabled)):
            ic.addPixmap(icons.pixmap("chevron_down", color, SIZE.icon, self).transformed(QTransform().rotate(180)), mode)
        self.setIcon(ic)


class PhraseSidebar(Card):
    """Cartao unico da tela (a lista e uma unidade independente). Sinais tipados, nenhuma regra de negocio."""

    rowChosen = Signal(int)
    addRequested = Signal()
    editRequested = Signal()
    removeRequested = Signal()
    moveRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        s = T.sidebar
        self.setFixedWidth(SIZE.target * 10)
        head = QHBoxLayout()
        head.setSpacing(SPACE.sm)
        self._title = Label(s.title_frases, "heading")
        self._count = Label("", "caption")
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._count)
        self.body.addLayout(head)
        self._list = QListWidget()
        self._list.setProperty("kit", "nav")
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setItemDelegate(_RowDelegate(self._list))
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setMouseTracking(True)
        self._list.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self._list.currentRowChanged.connect(self.rowChosen)
        set_a11y(self._list, s.list_name)
        self.body.addWidget(self._list, 1)
        self._editor = QWidget()
        self._editor.setProperty("kit", "plain")
        row = QHBoxLayout(self._editor)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE.xs)
        self._add = Button(s.add, icon_name="plus")
        self._edit = Button(s.edit, icon_name="edit", icon_only=True, variant="text")
        self._remove = Button(s.remove, icon_name="trash", icon_only=True, variant="text")
        self._up = _UpButton(s.up, icon_only=True, variant="text")
        self._down = Button(s.down, icon_name="chevron_down", icon_only=True, variant="text")
        for b in (self._add, self._edit, self._remove, self._up, self._down):
            row.addWidget(b)
        row.insertStretch(1, 1)
        self._add.clicked.connect(self.addRequested)
        self._edit.clicked.connect(self.editRequested)
        self._remove.clicked.connect(self.removeRequested)
        self._up.clicked.connect(lambda: self.moveRequested.emit(-1))
        self._down.clicked.connect(lambda: self.moveRequested.emit(1))
        self.body.addWidget(self._editor)
        watch_theme(self, self._list.viewport().update)

    def set_rows(self, title: str, rows: tuple[RowView, ...], current: int) -> None:
        self._title.setText(title)
        self._count.setText(T.sidebar.count(len(rows)))
        self._list.blockSignals(True)
        self._list.clear()
        for row in rows:
            item = QListWidgetItem(row.label)
            item.setData(_NUMBER, row.number)
            item.setData(_STATUS, row.status)
            item.setData(_KIND, row.kind)
            item.setToolTip(row.tooltip)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{row.number}, {row.label}, {row.status}")
            item.setSizeHint(QSize(0, _ROW_H))
            self._list.addItem(item)
        if rows and 0 <= current < len(rows):
            self._list.setCurrentRow(current)
        self._list.blockSignals(False)

    def set_current(self, row: int) -> None:
        if self._list.currentRow() != row and 0 <= row < self._list.count():
            self._list.blockSignals(True)
            self._list.setCurrentRow(row)
            self._list.blockSignals(False)

    def apply(self, *, editable: bool, items: bool, enabled: bool) -> None:
        """``editable``: conjunto com lista editavel; ``items``: ha algum item; ``enabled``: fora da gravacao."""
        self._editor.setVisible(editable)
        self._list.setEnabled(enabled)
        self._add.setEnabled(enabled)
        for b in (self._edit, self._remove, self._up, self._down):
            b.setEnabled(enabled and items)
