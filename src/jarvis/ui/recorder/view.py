"""Vista do gravador: barra superior, coluna central (com estados vazio/carregando/erro) e lista lateral.

Nao ha regra de negocio aqui: o controlador chama os metodos ``show_*``/``set_*`` e escuta os sinais.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from ...audio.devices import DeviceSpec
from ..kit.base import Label, set_a11y
from ..kit.buttons import Button
from ..kit.feedback import InlineBanner
from ..kit.fields import ComboField
from ..kit.states import EmptyState, ErrorState, LoadingState
from ..theme import SIZE, SPACE
from .actions import ActionRow
from .sidebar import PhraseSidebar
from .stage import StageWidget
from .state import Controls, IndicatorKind, Notice, ResultView, RowView, StageView
from .texts import T

_READY, _LOADING, _ERROR, _EMPTY = range(4)


class _TopBar(QWidget):
    setChosen = Signal(str)
    refreshRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        w = T.window
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE.md)
        row.addWidget(Label(w.heading, "title"))
        row.addSpacing(SPACE.lg)
        self.sets = ComboField([(w.set_frases, "frases"), (w.set_jarvis, "jarvis")])
        self.mics = ComboField()
        self.mics.setMinimumContentsLength(SPACE.huge // 2)
        self.mics.setSizeAdjustPolicy(ComboField.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for combo, text in ((self.sets, w.set_label), (self.mics, w.mic_label)):
            label = Label(text, "label")
            label.setBuddy(combo)
            set_a11y(combo, text)
            row.addWidget(label)
            row.addWidget(combo, 1 if combo is self.mics else 0)
        self.refresh = Button(w.mic_refresh, icon_name="refresh", icon_only=True, variant="text")
        row.addWidget(self.refresh)
        self.sets.valueChanged.connect(lambda v: self.setChosen.emit(str(v)))
        self.refresh.clicked.connect(self.refreshRequested)


class RecorderView(QWidget):
    """Compoe as pecas e repassa os sinais. Um unico aviso por vez (``set_notice``)."""

    setChosen = Signal(str)
    refreshRequested = Signal()
    rowChosen = Signal(int)
    noticeAction = Signal()
    retryLoad = Signal()
    addRequested = Signal()
    editRequested = Signal()
    removeRequested = Signal()
    moveRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
        root.setSpacing(SPACE.lg)
        self._top = _TopBar()
        root.addWidget(self._top)
        body = QHBoxLayout()
        body.setSpacing(SPACE.xl)
        root.addLayout(body, 1)

        self._stack = QStackedWidget()
        self.stage = StageWidget()
        self.actions = ActionRow()
        self._notice_box = QVBoxLayout()
        self._notice_box.setContentsMargins(0, 0, 0, 0)
        self._notice: InlineBanner | None = None
        self._stack.addWidget(self._ready_page())
        for _ in range(_EMPTY):
            self._stack.addWidget(QWidget())
        body.addWidget(self._stack, 1)
        self.sidebar = PhraseSidebar()
        body.addWidget(self.sidebar)

        t, s = self._top, self.sidebar
        t.setChosen.connect(self.setChosen)
        t.refreshRequested.connect(self.refreshRequested)
        s.rowChosen.connect(self.rowChosen)
        s.addRequested.connect(self.addRequested)
        s.editRequested.connect(self.editRequested)
        s.removeRequested.connect(self.removeRequested)
        s.moveRequested.connect(self.moveRequested)
        self.setTabOrder(t.sets, t.mics)
        self.setTabOrder(t.mics, t.refresh)
        self.setTabOrder(t.refresh, self.actions.record)

    def _ready_page(self) -> QWidget:
        """Coluna de leitura centralizada: o miolo rola; aviso e acoes ficam fixos embaixo (nada some em janela baixa)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.stage)
        column = QWidget()
        column.setMaximumWidth(SIZE.reading_width)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.lg)
        col.addWidget(scroll, 1)
        col.addLayout(self._notice_box)
        col.addWidget(self.actions)
        col.addWidget(Label(T.window.close_hint, "caption", wrap=True))
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(column, 100)
        row.addStretch(1)
        return page

    # --- modos da coluna central (as paginas de estado sao refeitas: o texto delas e fixo na construcao)
    def show_loading(self, what: str) -> None:
        self._page(_LOADING, LoadingState(what), sidebar=False)

    def show_error(self, what: str, why: str, todo: str) -> None:
        page = ErrorState(what, why, todo)
        page.retryRequested.connect(self.retryLoad)
        self._page(_ERROR, page, sidebar=False)

    def show_empty(self, *, editable: bool) -> None:
        if editable:
            page = EmptyState(T.states.empty_title, T.states.empty_body, action_text=T.states.empty_action)
            page.actionTriggered.connect(self.addRequested)
        else:
            page = EmptyState(T.states.empty_title, T.states.empty_locked_body)
        self._page(_EMPTY, page, sidebar=True)

    def show_ready(self) -> None:
        self._stack.setCurrentIndex(_READY)
        self.sidebar.setVisible(True)

    def _page(self, index: int, page: QWidget, *, sidebar: bool) -> None:
        old = self._stack.widget(index)
        self._stack.removeWidget(old)
        old.deleteLater()
        self._stack.insertWidget(index, page)
        self._stack.setCurrentIndex(index)
        self.sidebar.setVisible(sidebar)

    # --- dados
    def set_sets(self, name: str) -> None:
        self._top.sets.blockSignals(True)
        self._top.sets.set_value(name)
        self._top.sets.blockSignals(False)

    def current_set(self) -> str:
        return str(self._top.sets.value())

    def set_mics(self, items: list[tuple[str, DeviceSpec]], selected: int) -> None:
        combo = self._top.mics
        combo.blockSignals(True)
        combo.clear()
        for label, spec in items:
            combo.addItem(label, spec)
        combo.setCurrentIndex(selected)
        combo.blockSignals(False)

    def mic_spec(self) -> DeviceSpec:
        data = self._top.mics.currentData()
        return data if isinstance(data, (str, int)) else None

    def set_stage(self, v: StageView) -> None:
        self.stage.apply(v)

    def set_result(self, r: ResultView) -> None:
        self.stage.set_result(r)

    def set_rows(self, title: str, rows: tuple[RowView, ...], current: int) -> None:
        self.sidebar.set_rows(title, rows, current)

    def set_controls(self, c: Controls) -> None:
        self.actions.apply(c)
        self.sidebar.apply(editable=not c.set_locked, items=c.has_items, enabled=not c.recording and not c.busy)
        for combo in (self._top.sets, self._top.mics, self._top.refresh):
            combo.setEnabled(not c.recording and not c.busy)

    def set_capture(self, kind: IndicatorKind, remaining_s: float) -> None:
        self.stage.set_capture(kind, remaining_s)

    def set_live(self, level_db: float, remaining_s: float) -> None:
        self.stage.set_live(level_db, remaining_s)

    def set_notice(self, notice: Notice | None) -> None:
        if self._notice is not None:
            self._notice_box.removeWidget(self._notice)
            self._notice.deleteLater()
            self._notice = None
        if notice is None:
            return
        banner = InlineBanner(notice.state, notice.what, notice.why, notice.todo, action_text=notice.action)
        if notice.detail:
            banner.setToolTip(notice.detail)
        banner.actionTriggered.connect(self.noticeAction)
        self._notice_box.addWidget(banner)
        self._notice = banner
