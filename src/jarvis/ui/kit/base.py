"""Infraestrutura comum do kit: observador de tema, animacao segura, anel de foco, rotulos."""
from __future__ import annotations

from typing import Callable, Literal

from PySide6.QtCore import QEasingCurve, QObject, QRectF, Qt, QVariantAnimation, Slot
from PySide6.QtGui import QFontMetrics, QPainter, QPaintEvent, QPen, QColor
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from .. import strings
from ..strings import Strings
from ..theme import SIZE, TYPE, duration, make_font, manager, pal, repolish

LabelKind = Literal["display", "title", "heading", "label", "body", "help", "caption", "counter"]


def strs() -> Strings:
    """Conjunto de strings ativo (le sempre do modulo, para respeitar ``set_strings``)."""
    return strings.S


class _ThemeWatcher(QObject):
    """Filho do widget: morre junto com ele, entao a conexao com o ThemeManager nao vaza."""

    def __init__(self, widget: QWidget, callback: Callable[[], None] | None) -> None:
        super().__init__(widget)
        self._w = widget
        self._cb = callback
        manager().changed.connect(self._on_changed)

    @Slot(str)
    def _on_changed(self, _name: str) -> None:
        if self._cb is not None:
            self._cb()
        self._w.update()


def watch_theme(widget: QWidget, callback: Callable[[], None] | None = None) -> None:
    """Repinta ``widget`` (e chama ``callback``, ex.: refazer icones) quando o tema muda."""
    _ThemeWatcher(widget, callback)


def animate(owner: QObject, start: float, end: float, ms: int, on_value: Callable[[float], None],
            on_done: Callable[[], None] | None = None) -> QVariantAnimation | None:
    """Anima um valor com ease-out. ``owner`` e o dono (sem vazamento); com 'reduzir animacoes' salta ao fim."""
    ms = duration(ms)
    if ms == 0:
        on_value(end)
        if on_done:
            on_done()
        return None
    anim = QVariantAnimation(owner)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    if on_done:
        anim.finished.connect(on_done)
    anim.finished.connect(anim.deleteLater)
    anim.start()
    return anim


def paint_focus_ring(painter: QPainter, rect: QRectF, radius: float, *, gap_color: str | None = None) -> None:
    """Anel de foco ambar de 2 px, desenhado DENTRO de ``rect``. ``gap_color`` pinta uma linha de
    separacao interna (para o anel nao se perder sobre o preenchimento ambar do botao primario)."""
    ring = float(SIZE.focus_ring)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(pal().focus_ring), ring))
    painter.drawRoundedRect(rect.adjusted(ring / 2, ring / 2, -ring / 2, -ring / 2), radius, radius)
    if gap_color:
        painter.setPen(QPen(QColor(gap_color), 1.0))
        inset = ring + 0.5
        painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), max(0.0, radius - ring), max(0.0, radius - ring))
    painter.restore()


def set_a11y(widget: QWidget, name: str, description: str = "") -> None:
    widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)


class Label(QLabel):
    """Texto tipado pela escala do tema. ``kind`` escolhe tamanho/peso/cor via stylesheet."""

    def __init__(self, text: str = "", kind: LabelKind = "body", *, wrap: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(wrap)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.set_kind(kind)

    def set_kind(self, kind: LabelKind) -> None:
        self.setProperty("kind", kind)
        if kind == "counter":
            self.setFont(make_font(TYPE.counter, TYPE.bold, tabular=True))
        repolish(self)

    def set_state(self, state: str) -> None:
        """Cor de estado (ok/warn/error) ou '' para a cor normal. Sempre acompanhe de texto/icone."""
        self.setProperty("state", state)
        repolish(self)


class ElidedLabel(QLabel):
    """Uma linha so: corta com reticencias e guarda o texto inteiro na dica (ajuda de campo)."""

    def __init__(self, text: str = "", kind: LabelKind = "help", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setProperty("kind", kind)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setMinimumWidth(0)
        self.updateGeometry()
        self.update()

    def full_text(self) -> str:
        return self._full

    def sizeHint(self):  # type: ignore[no-untyped-def]
        sh = super().sizeHint()
        sh.setWidth(QFontMetrics(self.font()).horizontalAdvance(self._full) + 2)
        return sh

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(QColor(pal().text_muted))
        elided = QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), elided)
