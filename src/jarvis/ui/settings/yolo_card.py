"""Cartao do modo YOLO (Configuracoes > Ferramentas e seguranca > Permissoes). So visual e ligacao: o pedido vai por
``control.request_yolo`` (assinado, vale 60 s); nada e gravado em config. Ligar exige dialogo com Cancelar como
padrao; desligar nao pede nada. Sem Eco em execucao os dois botoes ficam desabilitados e a tela explica."""
from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jarvis.settings import control
from jarvis.settings.control import Runtime

from ..kit import icons
from ..kit.base import Label, set_a11y, watch_theme
from ..kit.buttons import Button
from ..kit.dialogs import ConfirmDialog
from ..kit.status import StatusChip
from ..theme import RADIUS, SIZE, SPACE, pal
from .controller import SettingsController
from .texts import T

log = logging.getLogger(__name__)
_DEFAULT_MINUTES = 15


class YoloCard(QFrame):
    def __init__(self, controller: SettingsController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        y = T.yolo
        self._ctl = controller
        self._running = False
        self._want_focus = False
        self._icon = QLabel()
        head = QHBoxLayout()
        head.setSpacing(SPACE.sm)
        head.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(Label(y.title, "heading"), 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(StatusChip("error", y.badge), 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self._intro = Label("", "body", wrap=True)
        facts = QVBoxLayout()
        facts.setSpacing(SPACE.xs)
        for text in y.facts:
            facts.addWidget(Label(text, "help", wrap=True))
        self.on_button = Button(y.on_button, variant="danger", icon_name="shield")
        self.off_button = Button(y.off_button)
        self.on_button.setToolTip(y.on_tip)
        self.off_button.setToolTip(y.off_tip)
        self._state = StatusChip("neutral", y.not_running)
        self._note = Label("", "help", wrap=True)
        row = QHBoxLayout()
        row.setSpacing(SPACE.sm)
        row.addWidget(self.on_button)
        row.addWidget(self.off_button)
        row.addSpacing(SPACE.sm)
        row.addWidget(self._state)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE.lg, SPACE.lg, SPACE.lg, SPACE.lg)
        lay.setSpacing(SPACE.md)
        lay.addLayout(head)
        lay.addWidget(self._intro)
        lay.addLayout(facts)
        lay.addLayout(row)
        lay.addWidget(self._note)
        self.on_button.clicked.connect(self._ask_on)
        self.off_button.clicked.connect(self._turn_off)
        controller.runtimeChanged.connect(self._on_runtime)
        controller.refresh_runtime()
        set_a11y(self, y.card_name, self._minutes_text(y.intro))
        self._on_runtime(None)
        watch_theme(self, self._refresh)
        self._refresh()

    # ---- estado
    def _minutes(self) -> int:
        try:
            return int(self._ctl.model.current.get("safety.yolo_minutes", _DEFAULT_MINUTES))
        except (TypeError, ValueError):
            return _DEFAULT_MINUTES

    def _minutes_text(self, template: str) -> str:
        return template.format(minutes=self._minutes())

    def _on_runtime(self, rt: object) -> None:
        y = T.yolo
        self._running = isinstance(rt, Runtime)
        self.on_button.setEnabled(self._running)
        self.off_button.setEnabled(self._running)
        self._state.set_state("ok" if self._running else "neutral", y.running if self._running else y.not_running)
        self._intro.setText(self._minutes_text(y.intro))
        if self._running and self._want_focus:
            self._want_focus = False
            self.on_button.setFocus(Qt.FocusReason.TabFocusReason)
        if not self._running:
            self._note.setText(y.not_running_why)
        elif self._note.text() == y.not_running_why:
            self._note.setText("")

    # ---- acoes
    def _ask_on(self) -> None:
        y = T.yolo
        ok = ConfirmDialog.ask(self.window(), title=y.dialog_title, message=self._minutes_text(y.dialog_message),
                               target=self._minutes_text(y.dialog_target), confirm_text=y.dialog_confirm,
                               destructive=False)
        if ok:
            self._send(True)

    def _turn_off(self) -> None:
        self._send(False)

    def _send(self, on: bool) -> None:
        y = T.yolo
        try:
            control.request_yolo(self._ctl.cfg.paths.data, on)
        except OSError:
            log.exception("nao consegui gravar o pedido de YOLO")
            self._note.setText(y.failed)
            return
        self._note.setText(y.sent_on if on else y.sent_off)

    def focus_primary(self) -> None:
        """Leva o foco do teclado ao botao de ativar (sem aciona-lo)."""
        if self.on_button.isEnabled():
            self.on_button.setFocus(Qt.FocusReason.TabFocusReason)
        else:
            self._want_focus = True                       # foca quando o estado do Eco chegar

    # ---- pintura
    def _refresh(self) -> None:
        self._icon.setPixmap(icons.pixmap("error", pal().error, SIZE.icon_lg, self))
        self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:  # noqa: N802
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g.setBrush(QColor(p.error_bg))
        g.setPen(QPen(QColor(p.error), 1.0))
        g.drawRoundedRect(r, RADIUS.md, RADIUS.md)
        g.end()
