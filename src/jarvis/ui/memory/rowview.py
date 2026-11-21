"""Lista de linhas do painel: modelo, delegate (pintura) e a ``RowList``. Só apresentação, nada de regra de negócio.

Uma linha mostra texto (até 2 linhas, cortado com reticências), uma linha de apoio e marcas com ÍCONE + TEXTO
(Fixada, Do modelo, Conteúdo externo, Na lixeira...). O item atual leva o marcador âmbar (estado, não enfeite).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import (QAbstractItemView, QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget)

from ..kit import icons
from ..kit.base import paint_focus_ring, watch_theme
from ..theme import RADIUS, SIZE, SPACE, TYPE, make_font, pal
from .rows import HEADER_KEY, ListRow, RowTag

NO_KEY = -2                              # nada selecionado (HEADER_KEY = -1 é só dos cabeçalhos)
ROW_ROLE = Qt.ItemDataRole.UserRole
_INSET = SPACE.xs
_PAD_X = SPACE.md
_PAD_Y = SPACE.md
_MARK_W = 3
_ICON = SIZE.icon - 2
_TAG_GAP = SPACE.md
_MIN_META = SIZE.target * 3


def _body(bold: bool) -> QFont:
    return make_font(TYPE.body, TYPE.semibold if bold else TYPE.regular)


def _small() -> QFont:
    return make_font(TYPE.small)


def _tag_font() -> QFont:
    return make_font(TYPE.small, TYPE.semibold)


def wrap_lines(text: str, font: QFont, width: int, max_lines: int) -> list[str]:
    """Quebra por palavras em até ``max_lines`` linhas; a última recebe reticências se o texto não coube."""
    fm = QFontMetrics(font)
    if max_lines <= 1 or width <= 0:
        return [fm.elidedText(text, Qt.TextElideMode.ElideRight, max(width, 0))]
    layout = QTextLayout(text, font)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WordWrap)
    layout.setTextOption(opt)
    lines: list[str] = []
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        start = line.textStart()
        if len(lines) == max_lines - 1:
            lines.append(fm.elidedText(text[start:], Qt.TextElideMode.ElideRight, width))
            break
        lines.append(text[start:start + line.textLength()].rstrip())
    layout.endLayout()
    return lines or [""]


def tags_width(tags: tuple[RowTag, ...]) -> int:
    fm = QFontMetrics(_tag_font())
    return sum(_ICON + SPACE.xs + fm.horizontalAdvance(t.text) for t in tags) + _TAG_GAP * max(0, len(tags) - 1)


@dataclass(frozen=True, slots=True)
class _Geometry:
    primary: tuple[str, ...]
    secondary: tuple[str, ...]
    tags_inline: bool                    # marcas na linha de apoio (à direita) ou numa linha própria
    height: int


@lru_cache(maxsize=8192)
def _geometry(row: ListRow, width: int) -> _Geometry:
    """Texto já quebrado e altura da linha para a largura de texto ``width`` (cache: a lista pode ter milhares)."""
    body, small = QFontMetrics(_body(row.bold)), QFontMetrics(_small())
    if row.kind == "header":
        return _Geometry((), (), False, SPACE.lg + small.lineSpacing() + SPACE.xs)
    primary = wrap_lines(row.primary, _body(row.bold), width, row.primary_lines)
    height = 2 * _PAD_Y + len(primary) * body.lineSpacing()
    secondary: tuple[str, ...] = ()
    inline = False
    if row.secondary or row.tags:
        tag_w = tags_width(row.tags)
        inline = bool(row.tags) and row.secondary_lines == 1 and width - tag_w - _TAG_GAP >= _MIN_META
        room = width - (tag_w + _TAG_GAP if inline else 0)
        secondary = tuple(wrap_lines(row.secondary, _small(), room, row.secondary_lines)) if row.secondary else ()
        lines = max(len(secondary), 1 if inline else 0) + (0 if inline or not row.tags else 1)
        height += SPACE.xs + lines * small.lineSpacing()
    return _Geometry(tuple(primary), secondary, inline, height)


class RowModel(QAbstractListModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[ListRow] = []

    def set_rows(self, rows: list[ListRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def row_at(self, i: int) -> ListRow | None:
        return self._rows[i] if 0 <= i < len(self._rows) else None

    def index_of_key(self, key: int) -> QModelIndex:
        for i, r in enumerate(self._rows):
            if r.kind == "row" and r.key == key:
                return self.index(i, 0)
        return QModelIndex()

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        row = self.row_at(index.row())
        if row is None or row.kind == "header":
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        row = self.row_at(index.row())
        if row is None:
            return None
        if role == ROW_ROLE:
            return row
        if role == Qt.ItemDataRole.DisplayRole:
            return row.primary
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return row.a11y or row.primary
        if role == Qt.ItemDataRole.ToolTipRole and row.kind == "row":
            return row.primary if len(row.primary) <= 600 else row.primary[:599] + "…"
        return None


class RowDelegate(QStyledItemDelegate):
    def _text_width(self, viewport_width: int) -> int:
        return max(SIZE.target * 3, viewport_width - 2 * _INSET - _PAD_X - _PAD_X - _MARK_W)

    def _width(self) -> int:
        view = self.parent()
        return self._text_width(view.viewport().width() if isinstance(view, QListView) else SIZE.target * 10)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:  # noqa: N802
        row = index.data(ROW_ROLE)
        if not isinstance(row, ListRow):
            return QSize(0, SIZE.target)
        return QSize(option.rect.width(), _geometry(row, self._width()).height)

    def paint(self, g: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        row = index.data(ROW_ROLE)
        if not isinstance(row, ListRow):
            return
        p = pal()
        geo = _geometry(row, self._width())
        r = QRectF(option.rect)
        g.save()
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if row.kind == "header":
            g.setFont(make_font(TYPE.small, TYPE.semibold))
            g.setPen(QColor(p.text_muted))
            g.drawText(QRectF(r.left() + _INSET + _PAD_X + _MARK_W, r.top(), r.width(), r.height() - SPACE.xs),
                       int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft), row.primary)
            g.restore()
            return
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        inner = r.adjusted(_INSET, 1, -_INSET, -1)
        g.setPen(Qt.PenStyle.NoPen)
        if selected or hover:
            g.setBrush(QColor(p.raised if selected else p.hover))
            g.drawRoundedRect(inner, RADIUS.sm, RADIUS.sm)
        if selected:
            g.setBrush(QColor(p.accent_ink))
            g.drawRoundedRect(QRectF(inner.left(), inner.top() + SPACE.sm, _MARK_W, inner.height() - 2 * SPACE.sm), 1.5, 1.5)
        x = inner.left() + _PAD_X + _MARK_W
        w = inner.width() - 2 * _PAD_X - _MARK_W
        y = inner.top() + _PAD_Y - 1
        body = QFontMetrics(_body(row.bold))
        g.setFont(_body(row.bold))
        g.setPen(QColor(p.text_muted if row.muted else p.text))
        for line in geo.primary:
            g.drawText(QRectF(x, y, w, body.lineSpacing()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), line)
            y += body.lineSpacing()
        small = QFontMetrics(_small())
        y += SPACE.xs
        y_meta = y
        g.setFont(_small())
        g.setPen(QColor(p.text_muted))
        for line in geo.secondary:
            g.drawText(QRectF(x, y, w, small.lineSpacing()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), line)
            y += small.lineSpacing()
        if row.tags:
            if geo.tags_inline:
                self._draw_tags(g, row.tags, x + w - tags_width(row.tags), y_meta, small.lineSpacing(), option.widget)
            else:
                self._draw_tags(g, row.tags, x, y, small.lineSpacing(), option.widget)
        if not (selected or hover):
            g.setPen(QPen(QColor(p.border), 1.0))
            g.drawLine(int(x), int(r.bottom()), int(r.right() - _INSET - _PAD_X), int(r.bottom()))
        view = option.widget
        if view is not None and view.hasFocus() and bool(option.state & QStyle.StateFlag.State_HasFocus):
            paint_focus_ring(g, inner, RADIUS.sm)
        g.restore()

    @staticmethod
    def _draw_tags(g: QPainter, tags: tuple[RowTag, ...], x: float, y: float, line_h: int, widget: QWidget | None) -> None:
        p = pal()
        fm = QFontMetrics(_tag_font())
        g.setFont(_tag_font())
        for tag in tags:
            color = p.state(tag.state) if tag.state else p.text_muted
            g.drawPixmap(int(x), int(y + (line_h - _ICON) / 2), icons.pixmap(tag.icon, color, _ICON, widget))
            x += _ICON + SPACE.xs
            tw = fm.horizontalAdvance(tag.text)
            g.setPen(QColor(color))
            g.drawText(QRectF(x, y, tw + 2, line_h), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), tag.text)
            x += tw + _TAG_GAP


class RowList(QListView):
    """Lista de uma coluna. ``currentKeyChanged(int)`` (``NO_KEY`` sem seleção), ``itemActivated`` (Enter ou duplo clique)
    e ``deleteRequested`` (tecla Del). Setas movem; um único Tab entra e sai da lista."""

    currentKeyChanged = Signal(int)
    itemActivated = Signal(int)
    deleteRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = RowModel(self)
        self._quiet = False
        self.setModel(self._model)
        self.setItemDelegate(RowDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(False)
        self.setMouseTracking(True)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.selectionModel().currentChanged.connect(self._on_current)
        self.doubleClicked.connect(lambda _i: self._activate())
        watch_theme(self)

    def current_key(self) -> int:
        row = self._model.row_at(self.currentIndex().row()) if self.currentIndex().isValid() else None
        return row.key if row is not None and row.kind == "row" else NO_KEY

    def set_rows(self, rows: list[ListRow], keep_key: int | None = None) -> None:
        """Troca as linhas. Mantém a seleção em ``keep_key`` se ele ainda existir; emite ``currentKeyChanged`` uma vez."""
        self._quiet = True
        _geometry.cache_clear()
        self._model.set_rows(rows)
        idx = self._model.index_of_key(keep_key) if keep_key is not None else QModelIndex()
        self.setCurrentIndex(idx) if idx.isValid() else self.clearSelection()
        self._quiet = False
        self.currentKeyChanged.emit(self.current_key())

    def row_count(self) -> int:
        return sum(1 for i in range(self._model.rowCount()) if (r := self._model.row_at(i)) is not None and r.kind == "row")

    def _on_current(self, *_a: object) -> None:
        if not self._quiet:
            self.currentKeyChanged.emit(self.current_key())

    def _activate(self) -> None:
        key = self.current_key()
        if key != NO_KEY:
            self.itemActivated.emit(key)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        key = self.current_key()
        if e.key() == Qt.Key.Key_Delete and key != NO_KEY:
            self.deleteRequested.emit(key)
            e.accept()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and key != NO_KEY:
            self.itemActivated.emit(key)
            e.accept()
            return
        super().keyPressEvent(e)


__all__ = ["HEADER_KEY", "NO_KEY", "RowList", "RowModel", "wrap_lines"]
