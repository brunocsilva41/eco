"""Retorno ao usuario: InlineBanner, Toast e MessageBlock (o que houve, por que importa, o que fazer)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..theme import MOTION, SIZE, SPACE, pal
from . import icons
from .base import Label, animate, set_a11y, strs, watch_theme
from .visibility import set_shown
from .buttons import Button
from .status import STATE_ICON, state_ink


def _live_toast(parent: QWidget):  # type: ignore[no-untyped-def]
    """O toast atual da janela, ou None se nao ha ou se o objeto Qt ja foi apagado (acessar um toast apagado derrubava o app)."""
    old = parent.property("_jarvis_toast")
    if old is None or not isinstance(old, Toast):
        return None
    try:
        from shiboken6 import isValid
        return old if isValid(old) else None
    except Exception:  # noqa: BLE001
        return None


class MessageBlock(QWidget):
    """Tres linhas para humanos: O QUE houve (peso 600), POR QUE importa (secundario), O QUE fazer."""

    def __init__(self, what: str, why: str = "", todo: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.xs)
        self._what = Label(what, "label", wrap=True)
        self._why = Label(why, "help", wrap=True)
        self._todo = Label(todo, "body", wrap=True)
        for lbl, text in ((self._what, what), (self._why, why), (self._todo, todo)):
            set_shown(lbl, bool(text))
            lay.addWidget(lbl)
        set_a11y(self, what, " ".join(x for x in (why, todo) if x))


class InlineBanner(QFrame):
    """Aviso dentro da tela (nao some sozinho). Erro: diga o que houve, por que importa e o que fazer.

    ``state``: "ok" | "warn" | "error". Sinais: ``actionTriggered()`` (botao de acao opcional) e
    ``dismissed()`` (botao de dispensar, quando ``dismissible``). Usa icone + texto, nunca so cor.
    """

    actionTriggered = Signal()
    dismissed = Signal()

    def __init__(self, state: str, what: str, why: str = "", todo: str = "", *, action_text: str = "",
                 dismissible: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setProperty("kit", "banner")
        self.setProperty("state", state)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE.lg, SPACE.md, SPACE.md, SPACE.md)
        lay.setSpacing(SPACE.md)
        self._icon = QLabel()
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(MessageBlock(what, why, todo), 1)
        if action_text:
            act = Button(action_text)
            act.clicked.connect(self.actionTriggered)
            lay.addWidget(act, 0, Qt.AlignmentFlag.AlignTop)
        if dismissible:
            x = Button(strs().banner.dismiss, icon_name="close", icon_only=True, variant="text")
            x.clicked.connect(self._dismiss)
            lay.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)
        set_a11y(self, what, " ".join(t for t in (why, todo) if t))
        watch_theme(self, self._refresh_icon)
        self._refresh_icon()

    @classmethod
    def error(cls, what: str, why: str, todo: str, **kw) -> "InlineBanner":  # type: ignore[no-untyped-def]
        return cls("error", what, why, todo, **kw)

    def _refresh_icon(self) -> None:
        self._icon.setPixmap(icons.pixmap(STATE_ICON[self._state], state_ink(pal(), self._state), SIZE.icon_lg, self))

    def _dismiss(self) -> None:
        self.hide()
        self.dismissed.emit()


class Toast(QFrame):
    """Mensagem curta e temporaria no canto inferior direito da janela (some em ~5 s, ou no x).

    Use para confirmar uma acao ("Configuracoes salvas"). Erros que exigem acao vao em
    ``InlineBanner``. Um toast por janela: o novo substitui o anterior. Timer e animacao pertencem
    ao toast e param ao esconder, entao nada vaza.
    """

    def __init__(self, parent: QWidget, state: str, title: str, detail: str = "",
                 timeout_ms: int = MOTION.toast) -> None:
        super().__init__(parent)
        self._state = state
        self.setProperty("kit", "toast")
        self.setProperty("state", state)
        self._margin = SPACE.xl
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE.md, SPACE.sm, SPACE.sm, SPACE.sm)
        lay.setSpacing(SPACE.md)
        self._icon = QLabel()
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(MessageBlock(title, detail), 1)
        x = Button(strs().common.close, icon_name="close", icon_only=True, variant="text")
        x.clicked.connect(self.dismiss)
        lay.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)
        self.setFixedWidth(min(SIZE.target * 12, max(SIZE.target * 8, parent.width() - 2 * self._margin)))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self.dismiss)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        set_a11y(self, title, detail)
        watch_theme(self, self._refresh_icon)
        self._refresh_icon()
        parent.installEventFilter(self)

    @classmethod
    def show_message(cls, parent: QWidget, state: str, title: str, detail: str = "",
                     timeout_ms: int = MOTION.toast) -> "Toast":
        old = _live_toast(parent)
        if old is not None:
            old.dismiss()
        toast = cls(parent, state, title, detail, timeout_ms)
        parent.setProperty("_jarvis_toast", toast)
        toast.present()
        return toast

    def present(self) -> None:
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        animate(self, 0.0, 1.0, MOTION.base, self._fx.setOpacity)
        self._timer.start()

    def dismiss(self) -> None:
        self._timer.stop()
        if not self.isVisible():
            return
        self._timer.stop()
        animate(self, 1.0, 0.0, MOTION.fast, self._fx.setOpacity, self._finish)

    def _finish(self) -> None:
        par = self.parentWidget()
        if par is not None and par.property("_jarvis_toast") is self:
            par.setProperty("_jarvis_toast", None)           # nunca deixa um ponteiro para um toast que vai ser apagado
        self.hide()
        self.deleteLater()

    def hideEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        self._timer.stop()
        super().hideEvent(e)

    def _place(self) -> None:
        par = self.parentWidget()
        if par is not None:
            self.move(par.width() - self.width() - self._margin, par.height() - self.height() - self._margin)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return super().eventFilter(obj, event)

    def _refresh_icon(self) -> None:
        self._icon.setPixmap(icons.pixmap(STATE_ICON[self._state], state_ink(pal(), self._state), SIZE.icon_lg, self))
