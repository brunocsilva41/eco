"""Painel de ferramentas: liga/desliga cada uma e "sempre confirmar". Ferramentas ARRISCADAS sempre confirmam
(o interruptor fica ligado e travado, e a tela diz isso). Mexe nas duas chaves ``tools.disabled`` e
``tools.confirm``: guarda as listas, desenha a grade quando o catalogo chega (em segundo plano) e emite
``keyChanged(chave, lista)``. A lista de nomes e a fonte da verdade; os interruptores sao so a vista."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from jarvis.tools.catalog import ToolInfo

from ..kit.base import ElidedLabel, Label, set_a11y
from ..kit.states import EmptyState, ErrorState, LoadingState
from ..kit.status import StatusChip
from ..kit.tasks import run_async
from ..kit.toggle import ToggleSwitch
from ..theme import SPACE
from .texts import T

log = logging.getLogger(__name__)

KEY_DISABLED, KEY_CONFIRM = "tools.disabled", "tools.confirm"
_RISKY = 2
_COL_NAME, _COL_ON, _COL_CONFIRM = 0, 1, 2


class ToolsPanel(QWidget):
    keyChanged = Signal(str, list)

    def __init__(self, load: Callable[[], list[ToolInfo]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._load = load
        self._disabled: list[str] = []
        self._confirm: list[str] = []
        self._tools: list[ToolInfo] = []
        self._state = "idle"
        self._syncing = False
        self._on: dict[str, ToggleSwitch] = {}
        self._conf: dict[str, ToggleSwitch] = {}
        self._intro = Label(T.tools.intro, "help", wrap=True)
        self._count = Label("", "label")
        self._status = QVBoxLayout()
        self._status.setContentsMargins(0, 0, 0, 0)
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(SPACE.xl)
        self._grid.setVerticalSpacing(SPACE.md)
        self._grid.setColumnStretch(_COL_NAME, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.md)
        lay.addWidget(self._intro)
        lay.addWidget(self._count)
        lay.addLayout(self._status)
        lay.addWidget(self._grid_host)
        self._count.hide()
        self._grid_host.hide()
        set_a11y(self, T.label_for(KEY_DISABLED), T.tools.intro)

    # ---- valores por chave
    def value_for(self, key: str) -> list[str]:
        return list(self._disabled if key == KEY_DISABLED else self._confirm)

    def set_value_for(self, key: str, names: list[str]) -> None:
        if key == KEY_DISABLED:
            self._disabled = [str(n) for n in names]
        else:
            self._confirm = [str(n) for n in names]
        self._sync()

    # ---- carga sob demanda
    def ensure_loaded(self) -> None:
        if self._state != "idle":
            return
        self._state = "loading"
        self._show_status(LoadingState(T.tools.loading))
        run_async(self._load, self, self._on_tools, self._on_fail)

    def _show_status(self, widget: QWidget | None) -> None:
        while self._status.count():
            item = self._status.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if widget is not None:
            self._status.addWidget(widget)

    def _on_fail(self, message: str) -> None:
        log.warning("nao consegui listar as ferramentas: %s", message)
        self._state = "idle"
        err = ErrorState(T.tools.fail_what, T.tools.fail_why.format(detail=message), T.tools.fail_todo)
        err.retryRequested.connect(self.ensure_loaded)
        self._show_status(err)

    def _on_tools(self, tools: object) -> None:
        self._tools = list(tools)  # type: ignore[call-overload]
        self._state = "ready"
        if not self._tools:
            self._show_status(EmptyState(T.tools.empty_title, T.tools.empty_body))
            return
        self._show_status(None)
        self._build()

    # ---- grade
    def _build(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._on.clear()
        self._conf.clear()
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self._grid.addWidget(Label(T.tools.col_on, "caption"), 0, _COL_ON, right)
        self._grid.addWidget(Label(T.tools.col_confirm, "caption"), 0, _COL_CONFIRM, right)
        for row, tool in enumerate(self._tools, start=1):
            self._add_tool(row, tool, right)
        self._grid_host.show()
        self._count.show()
        self._sync()

    def _add_tool(self, row: int, tool: ToolInfo, right: Qt.AlignmentFlag) -> None:
        risky = int(tool.risk) >= _RISKY
        risk_text = {0: T.tools.risk_read, 1: T.tools.risk_control}.get(int(tool.risk), T.tools.risk_risky)
        text = QWidget()
        col = QVBoxLayout(text)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.xs)
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(SPACE.sm)
        hl.addWidget(Label(tool.name, "label"))
        if risky:
            hl.addWidget(StatusChip("warn", T.tools.risky_always))
        hl.addStretch(1)
        col.addWidget(head)
        col.addWidget(ElidedLabel(f"{risk_text}. {tool.description}".strip()))
        on = ToggleSwitch(True, show_text=False, accessible_name=T.tools.on_name.format(name=tool.name))
        conf = ToggleSwitch(risky, show_text=False, accessible_name=T.tools.confirm_name.format(name=tool.name))
        on.valueChanged.connect(lambda v, n=tool.name: self._toggle(KEY_DISABLED, n, not v))
        conf.valueChanged.connect(lambda v, n=tool.name: self._toggle(KEY_CONFIRM, n, v))
        if risky:
            conf.setEnabled(False)
            conf.setToolTip(T.tools.risky_always)
        self._on[tool.name], self._conf[tool.name] = on, conf
        self._grid.addWidget(text, row, _COL_NAME)
        self._grid.addWidget(on, row, _COL_ON, right)
        self._grid.addWidget(conf, row, _COL_CONFIRM, right)

    def _toggle(self, key: str, name: str, listed: bool) -> None:
        if self._syncing:
            return
        names = self._disabled if key == KEY_DISABLED else self._confirm
        if listed and name not in names:
            names.append(name)
        elif not listed and name in names:
            names.remove(name)
        self._sync()
        self.keyChanged.emit(key, list(names))

    def _sync(self) -> None:
        """Poe os interruptores no estado das listas, sem disparar sinais."""
        total = len(self._on)
        self._syncing = True
        for tool in self._tools:
            on, conf = self._on.get(tool.name), self._conf.get(tool.name)
            if on is None or conf is None:
                continue
            risky = int(tool.risk) >= _RISKY
            for sw, value in ((on, tool.name not in self._disabled), (conf, risky or tool.name in self._confirm)):
                sw.setChecked(value)
            conf.setEnabled(not risky and on.isChecked())
        self._syncing = False
        enabled = sum(1 for n in self._on if n not in self._disabled)
        self._count.setText(T.tools.counts.format(on=enabled, total=total))
