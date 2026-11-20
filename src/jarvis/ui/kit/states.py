"""Estados de tela escritos para humanos: EmptyState, LoadingState, ErrorState.

Alinhados a esquerda (nada de paragrafo centralizado). Vazio diz por que esta vazio e a unica
acao que preenche; carregando diz O QUE carrega; erro diz o que houve, por que importa e o que fazer.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..theme import SIZE, SPACE, motion_enabled, pal
from . import icons
from .base import Label, set_a11y, strs, watch_theme
from .buttons import Button
from .feedback import MessageBlock


class EmptyState(QWidget):
    """Nada para mostrar ainda. ``title`` diz por que, ``body`` explica, ``action_text`` e a acao que preenche."""

    actionTriggered = Signal()

    def __init__(self, title: str, body: str = "", *, action_text: str = "", icon_name: str = "info",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
        lay.setSpacing(SPACE.sm)
        self._icon = QLabel()
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(Label(title, "heading", wrap=True))
        if body:
            lay.addWidget(Label(body, "body", wrap=True))
        if action_text:
            lay.addSpacing(SPACE.sm)
            btn = Button(action_text)
            btn.clicked.connect(self.actionTriggered)
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        set_a11y(self, title, body)
        watch_theme(self, self._refresh_icon)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        self._icon.setPixmap(icons.pixmap(self._icon_name, pal().text_muted, SIZE.icon_lg, self))


class _Indeterminate(QWidget):
    """Barra fina que vai e volta. Anima so enquanto visivel e sem 'reduzir animacoes'; senao fica estatica."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(SIZE.target * 40)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on)
        self.setFixedHeight(SPACE.xs + 2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        watch_theme(self)

    def _on(self, v: float) -> None:
        self._t = float(v)
        self.update()

    def showEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(e)
        if motion_enabled():
            self._anim.start()

    def hideEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        self._anim.stop()
        super().hideEvent(e)

    def sizeHint(self) -> QSize:
        return QSize(SIZE.target * 6, SPACE.xs + 2)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(QColor(p.border))
        g.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        seg = r.width() * 0.3
        x = (r.width() - seg) * (self._t if motion_enabled() else 0.0)
        g.setBrush(QColor(p.text_muted))
        g.drawRoundedRect(QRectF(x, 0, seg, r.height()), r.height() / 2, r.height() / 2)
        g.end()


class LoadingState(QWidget):
    """Carregando. ``what`` diz o que (ex.: "as memorias"); a barra para quando escondida."""

    def __init__(self, what: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        text = f"{strs().states.loading_default} {what}..." if what else f"{strs().states.loading_default}..."
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
        lay.setSpacing(SPACE.md)
        lay.addWidget(Label(text, "body"))
        lay.addWidget(_Indeterminate())
        lay.addStretch(1)
        set_a11y(self, text)


class ErrorState(QWidget):
    """Falha ao carregar/executar. Tres linhas (o que, por que importa, o que fazer) e tentar de novo."""

    retryRequested = Signal()

    def __init__(self, what: str = "", why: str = "", todo: str = "", *, retry_text: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
        lay.setSpacing(SPACE.md)
        self._icon = QLabel()
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(SPACE.md)
        col.addWidget(MessageBlock(what or strs().states.error_title_default, why, todo))
        btn = Button(retry_text or strs().common.retry, icon_name="refresh")
        btn.clicked.connect(self.retryRequested)
        col.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        col.addStretch(1)
        lay.addLayout(col, 1)
        set_a11y(self, what or strs().states.error_title_default, " ".join(x for x in (why, todo) if x))
        watch_theme(self, self._refresh_icon)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        self._icon.setPixmap(icons.pixmap("error", pal().error, SIZE.icon_lg, self))
