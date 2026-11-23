"""Cartoes de secao, recolher animado e cabecalho de pagina (visual v2 das Configuracoes).

``SectionCard``: cartao com titulo + descricao, linhas separadas por fio fino e, opcionalmente, recolher com
altura animada (``_Reveal`` mantem o conteudo na altura cheia e so recorta, entao nada quebra no meio da
animacao). ``PageHeader``: icone em ladrilho + titulo + frase de apoio.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..theme import MOTION, RADIUS, SIZE, SPACE, pal
from . import icons
from .base import Label, animate, paint_focus_ring, set_a11y, watch_theme
from .visibility import set_shown


class _Reveal(QWidget):
    """Janela de recorte com altura animavel (0 a 100 %). O conteudo fica sempre na altura cheia."""

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._content = content
        content.setParent(self)
        content.installEventFilter(self)                 # mudancas no corpo (linhas filtradas, ajuda que cresce) refazem o tamanho
        self._p = 1.0
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def progress(self) -> float:
        return self._p

    def set_progress(self, p: float) -> None:
        self._p = min(max(p, 0.0), 1.0)
        self.updateGeometry()
        self._place()

    def _full_h(self, width: int) -> int:
        lay = self._content.layout()
        if lay is not None:
            if lay.hasHeightForWidth():
                return max(lay.totalHeightForWidth(max(width, 1)), lay.minimumSize().height())
            return lay.sizeHint().height()
        return self._content.sizeHint().height()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return int(round(self._full_h(w) * self._p))

    def sizeHint(self) -> QSize:  # noqa: N802
        sh = self._content.sizeHint()
        return QSize(sh.width(), int(round(self._full_h(max(self.width(), sh.width())) * self._p)))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._content.minimumSizeHint().width(), int(round(self._full_h(max(self.width(), 1)) * self._p)))

    def eventFilter(self, obj, event) -> bool:  # type: ignore[no-untyped-def]  # noqa: N802
        if obj is self._content and event.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()
            self._place()
        return False

    def _place(self) -> None:
        self._content.setGeometry(0, 0, self.width(), self._full_h(self.width()))

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().resizeEvent(event)
        self._place()


class _CardHeader(QFrame):
    """Cabecalho do cartao. Recolhivel: clicavel (mouse, Enter, Espaco), com seta e anel de foco."""

    clicked = Signal()

    def __init__(self, title: str, description: str, collapsible: bool, badge: str) -> None:
        super().__init__()
        self._collapsible = collapsible
        self._open = True
        self._hover = False
        self.setProperty("kit", "plain")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if collapsible:
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setMinimumHeight(SIZE.target + SPACE.md)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE.lg, SPACE.md, SPACE.lg, SPACE.md if collapsible else SPACE.xs)
        lay.setSpacing(SPACE.md)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.xs)
        self._title = Label(title, "label" if collapsible else "heading")
        self._desc = Label(description, "help", wrap=True)
        set_shown(self._desc, bool(description))
        for w in (self._title, self._desc):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            col.addWidget(w)
        lay.addLayout(col, 1)
        self._badge = Label(badge, "caption")
        set_shown(self._badge, bool(badge))
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self._chev = QLabel()
        self._chev.setFixedSize(SIZE.icon, SIZE.icon)
        self._chev.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        set_shown(self._chev, collapsible)
        lay.addWidget(self._chev, 0, Qt.AlignmentFlag.AlignVCenter)
        watch_theme(self, self._refresh_icon)
        self._refresh_icon()

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_badge(self, text: str) -> None:
        self._badge.setText(text)
        set_shown(self._badge, bool(text))
    def set_expanded(self, value: bool) -> None:
        self._open = value
        self._refresh_icon()
        if self._collapsible:
            state = "expandido" if value else "recolhido"
            self.setAccessibleName(f"{self._title.text()}, {state}")
            self.setAccessibleDescription(self._desc.text())

    def _refresh_icon(self) -> None:
        pm = icons.pixmap("chevron_down", pal().text_muted, SIZE.icon, self)
        if not self._open:
            pm = pm.transformed(QTransform().rotate(-90), Qt.TransformationMode.SmoothTransformation)
        self._chev.setPixmap(pm)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._collapsible and event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.clicked.emit()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._collapsible and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    def event(self, e) -> bool:  # type: ignore[no-untyped-def]
        if e.type() == QEvent.Type.HoverEnter:
            self._hover = True
            self.update()
        elif e.type() == QEvent.Type.HoverLeave:
            self._hover = False
            self.update()
        return super().event(e)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().paintEvent(event)
        if not self._collapsible:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal().hover))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(SIZE.border, SIZE.border, -SIZE.border, -SIZE.border),
                              RADIUS.md, RADIUS.md)
        if self.hasFocus():
            paint_focus_ring(p, QRectF(self.rect()).adjusted(SPACE.xs, SPACE.xs, -SPACE.xs, -SPACE.xs), RADIUS.sm)
        p.end()


class SectionCard(QFrame):
    """Secao como cartao: cabecalho, linhas separadas por fio e (opcional) recolher com altura animada.

    ``collapsible=True``: o cabecalho vira botao; ``set_expanded(v, animated=True)``, ``expanded()``, sinal
    ``toggled(bool)``. O fio entre linhas e desenhado so entre as linhas VISIVEIS (acompanha a busca).
    """

    toggled = Signal(bool)

    def __init__(self, title: str, description: str = "", *, collapsible: bool = False, expanded: bool = True,
                 badge: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("kit", "card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._collapsible = collapsible
        self._expanded = expanded or not collapsible
        self._anim = None
        self._title_text = title
        self._rows: list[QWidget] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._head = _CardHeader(title, description, collapsible, badge)
        self._head.clicked.connect(self._on_head)
        root.addWidget(self._head)

        content = QWidget()
        self._body = QVBoxLayout(content)
        self._body.setContentsMargins(SPACE.lg, SPACE.xs, SPACE.lg, SPACE.md)
        self._body.setSpacing(2 * SPACE.sm)
        self._reveal = _Reveal(content)
        root.addWidget(self._reveal)
        self._reveal.set_progress(1.0 if self._expanded else 0.0)
        set_shown(self._reveal, self._expanded)
        self._head.set_expanded(self._expanded)
        set_a11y(self, title, description)

    # ---- API
    def add(self, widget: QWidget) -> QWidget:
        self._body.addWidget(widget)
        self._rows.append(widget)
        return widget

    def set_title(self, title: str) -> None:
        self._title_text = title
        self._head.set_title(title)
        self.setAccessibleName(title)

    def title(self) -> str:
        return self._title_text

    def is_collapsible(self) -> bool:
        return self._collapsible

    def expanded(self) -> bool:
        return self._expanded

    def set_badge(self, text: str) -> None:
        self._head.set_badge(text)

    def set_expanded(self, value: bool, *, animated: bool = True, emit: bool = True) -> None:
        if not self._collapsible:
            return
        value = bool(value)
        if value == self._expanded and self._anim is None:
            return
        self._expanded = value
        self._head.set_expanded(value)
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        start = self._reveal.progress()
        end = 1.0 if value else 0.0
        if value:
            set_shown(self._reveal, True)
        if not animated:
            self._reveal.set_progress(end)
            set_shown(self._reveal, value)
        else:
            def done() -> None:
                self._anim = None
                set_shown(self._reveal, self._expanded)
            self._anim = animate(self, start, end, MOTION.base, self._reveal.set_progress, done)
        if emit:
            self.toggled.emit(value)

    def _on_head(self) -> None:
        if self._collapsible:
            self.set_expanded(not self._expanded)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().paintEvent(event)
        if not self._reveal.isVisible():
            return
        p = QPainter(self)
        p.setPen(QColor(pal().border))
        shown = [w for w in self._rows if w.isVisibleTo(self)]
        limit = self._reveal.mapTo(self, QPoint(0, 0)).y() + self._reveal.height()
        for w in shown[1:]:
            y = w.mapTo(self, QPoint(0, 0)).y() - SPACE.sm
            if y < limit:
                p.drawLine(SPACE.lg, y, self.width() - SPACE.lg, y)
        p.end()


class PageHeader(QWidget):
    """Cabecalho de pagina: icone em ladrilho, titulo grande e frase de apoio."""

    def __init__(self, title: str, subtitle: str = "", icon_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, SPACE.xs)
        lay.setSpacing(SPACE.lg)
        self._side = SIZE.target + SPACE.md
        self._tile = QLabel()
        self._tile.setFixedSize(self._side, self._side)
        self._tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_shown(self._tile, bool(icon_name))
        lay.addWidget(self._tile, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.xs)
        self.title_label = Label(title, "title")
        self.subtitle_label = Label(subtitle, "help", wrap=True)
        set_shown(self.subtitle_label, bool(subtitle))
        col.addWidget(self.title_label)
        col.addWidget(self.subtitle_label)
        lay.addLayout(col, 1)
        watch_theme(self, self._refresh_icon)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        if not self._icon_name:
            return
        p, side = pal(), self._side
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(side * dpr), int(side * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        g = QPainter(pm)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        g.setPen(QColor(p.border))
        g.setBrush(QColor(p.raised))
        g.drawRoundedRect(QRectF(0.5, 0.5, side - 1, side - 1), RADIUS.md, RADIUS.md)
        g.drawPixmap(int((side - SIZE.icon_lg) / 2), int((side - SIZE.icon_lg) / 2),
                     icons.pixmap(self._icon_name, p.accent_ink, SIZE.icon_lg, self))
        g.end()
        self._tile.setPixmap(pm)
