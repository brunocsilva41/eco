"""Janela de Configuracoes: vista que junta navegacao lateral, busca, paginas, avisos e barra de acoes.

So apresentacao e fluxo: o estado mora no ``FormModel`` e as regras no ``SettingsController``. Lembra
posicao e tamanho (QSettings) e pede confirmacao antes de fechar com alteracoes pendentes.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from jarvis.config import Config
from jarvis.settings import schema
from jarvis.settings.store import SettingsStore

from ..kit.actionbar import ActionBar
from ..kit.base import Label, set_a11y
from ..kit.dialogs import ConfirmDialog
from ..kit.feedback import Toast
from ..kit.navlist import NavList
from ..kit.search import SearchField
from ..kit.states import EmptyState
from ..theme import SIZE, SPACE
from .banners import Banners
from .binder import FieldBinder
from .categories import BY_PAGE, CATEGORIES, category_of
from .controller import SettingsController
from .external_pages import KnowsPage, MyVoicePage
from .hotkeys import to_display
from .model import SaveOutcome
from .page_base import PageLike
from .pages import SettingsPage
from .prefs import UiPrefs
from .texts import T, plural

log = logging.getLogger(__name__)

MIN_WIDTH = SIZE.nav_width + max(SIZE.reading_width, 680)   # as páginas mais largas (nuvem, modelo) exigem ~650 px de conteúdo sem rolagem horizontal
MIN_HEIGHT = SIZE.target * 19
DEFAULT_WIDTH = MIN_WIDTH + SIZE.target * 5
DEFAULT_HEIGHT = SIZE.target * 24
_EMERGENCY_KEY = "safety.emergency_hotkey"


class _LazyPages(dict):
    """dict de páginas montadas na primeira vez que são pedidas. Iterar/`items()`/`values()` monta as que faltam."""

    def __init__(self, make, stack, keys) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._make, self._stack, self._keys = make, stack, list(keys)

    def _build_one(self, key: str):  # type: ignore[no-untyped-def]
        page = self._make(key)
        dict.__setitem__(self, key, page)
        self._stack.addWidget(page)
        return page

    def __missing__(self, key: str):  # type: ignore[no-untyped-def]
        if key in self._keys:
            return self._build_one(key)
        raise KeyError(key)

    def get(self, key, default=None):  # type: ignore[no-untyped-def]
        try:
            return self[key]
        except KeyError:
            return default

    def build_next(self) -> bool:
        """Monta UMA página pendente; True se ainda restam."""
        for k in self._keys:
            if not dict.__contains__(self, k):
                self._build_one(k)
                break
        return any(not dict.__contains__(self, k) for k in self._keys)

    def _all(self) -> None:
        while self.build_next():
            pass

    def items(self):  # type: ignore[no-untyped-def]
        self._all()
        return dict.items(self)

    def values(self):  # type: ignore[no-untyped-def]
        self._all()
        return dict.values(self)

    def keys(self):  # type: ignore[no-untyped-def]
        return list(self._keys)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


class SettingsWindow(QWidget):
    """Sinal ``saved(SaveOutcome)`` depois de gravar (ou restaurar o padrao) com sucesso."""

    saved = Signal(object)

    def __init__(self, cfg: Config | None = None, parent: QWidget | None = None, store: SettingsStore | None = None,
                 prefs: UiPrefs | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle(T.window.title)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.prefs = prefs or UiPrefs()
        self.controller = SettingsController(store, cfg, self)
        self.binder = FieldBinder(self.controller, self)
        self._keys: list[str] = [c.key for c in CATEGORIES]
        self.pages: dict[str, PageLike] = {}                 # trocado por _LazyPages em _build (páginas montadas sob demanda)
        self._search_empty: QWidget | None = None

        self._build()
        self._connect()
        if not self.prefs.restore_geometry(self):
            self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.nav.set_current(self._keys[0])
        self.controller.start()
        self._refresh_state()
        self._refresh_emergency()

    # ------------------------------------------------------------------ tela pequena / escala alta
    def _fit_to_screen(self) -> None:
        """Faz a janela caber na area util do monitor onde esta (tela pequena ou escala 150/200%): o tamanho minimo encolhe,
        a janela nunca passa da area e a barra Salvar/Descartar nunca fica fora da tela."""
        scr = self.screen()
        if scr is None:
            return
        avail = scr.availableGeometry()
        frame_w = max(0, self.frameGeometry().width() - self.width())
        frame_h = max(0, self.frameGeometry().height() - self.height())
        max_w, max_h = max(320, avail.width() - frame_w), max(240, avail.height() - frame_h)
        self.setMinimumSize(min(MIN_WIDTH, max_w), min(MIN_HEIGHT, max_h))
        w, h = min(self.width(), max_w), min(self.height(), max_h)
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
        fg = self.frameGeometry()
        x = min(max(fg.x(), avail.left()), max(avail.left(), avail.right() - fg.width() + 1))
        y = min(max(fg.y(), avail.top()), max(avail.top(), avail.bottom() - fg.height() + 1))
        if (x, y) != (fg.x(), fg.y()):
            self.move(x, y)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().showEvent(event)
        if not getattr(self, "_fitted", False):
            self._fitted = True
            self._fit_to_screen()
            QTimer.singleShot(0, self._fit_to_screen)          # de novo depois que o Windows aplicou a moldura final

    # ------------------------------------------------------------------ montagem
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_side())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.banners = Banners()
        self.stack = QStackedWidget()
        self.bar = ActionBar(show_when_clean=True)
        right.addWidget(self.banners)
        right.addWidget(self.stack, 1)
        right.addWidget(self.bar)
        root.addLayout(right, 1)
        self.pages = _LazyPages(self._make_page, self.stack, self._keys)    # só a página aberta é montada já; o resto em segundo plano
        self.nav.setFocus()
        QTimer.singleShot(150, self._build_rest)

    def _build_rest(self) -> None:
        """Monta as páginas que faltam, uma por volta do laço de eventos (a janela já está usável)."""
        try:
            if self.pages.build_next():
                QTimer.singleShot(0, self._build_rest)
        except RuntimeError:                                  # janela já destruída
            pass

    def _make_page(self, key: str) -> PageLike:
        if key == "my_voice":
            return MyVoicePage(self.controller)
        if key == "knows":
            return KnowsPage(self.controller)
        page = SettingsPage(BY_PAGE[key], self.controller, self.binder, self.prefs)
        page.resetRequested.connect(self._reset)
        return page

    def _build_side(self) -> QFrame:
        side = QFrame()
        side.setProperty("kit", "nav")
        side.setFixedWidth(SIZE.nav_width)
        col = QVBoxLayout(side)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.sm)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(SPACE.lg, SPACE.xl, SPACE.lg, SPACE.xs)
        tl.setSpacing(SPACE.md)
        tl.addWidget(Label(T.window.heading, "heading"))
        self.search = SearchField(placeholder=T.window.search_placeholder, accessible_name=T.window.search_name)
        self.search.bind_shortcut(self)
        tl.addWidget(self.search)
        self.summary = Label("", "caption", wrap=True)
        self.summary.hide()
        tl.addWidget(self.summary)
        col.addWidget(top)
        self.nav = NavList()
        set_a11y(self.nav, T.window.nav_name)
        for cat in CATEGORIES:
            self.nav.add_entry(cat.key, T.page(cat.key)[0], cat.icon)
        col.addWidget(self.nav, 1)
        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(SPACE.lg, SPACE.md, SPACE.lg, SPACE.lg)
        fl.setSpacing(SPACE.xs)
        fl.addWidget(Label(T.window.emergency_caption, "caption"))
        self._emergency = Label("", "label")
        fl.addWidget(self._emergency)
        fl.addWidget(Label(T.window.emergency_hint, "caption", wrap=True))
        col.addWidget(foot)
        return side

    def _connect(self) -> None:
        c = self.controller
        self.nav.currentKeyChanged.connect(self._show_page)
        self.search.searchChanged.connect(self._on_search)
        self.search.escaped.connect(self.nav.setFocus)
        self.bar.saveRequested.connect(c.save)
        self.bar.discardRequested.connect(self._discard)
        self.bar.resetRequested.connect(self._reset)
        c.stateChanged.connect(self._refresh_state)
        c.valuesReplaced.connect(self._refresh_emergency)
        c.busyChanged.connect(self.bar.set_busy)
        c.saved.connect(self._on_saved)
        c.saveBlocked.connect(self._on_blocked)
        c.writeFailed.connect(self.banners.show_write_error)
        c.loadFailed.connect(self.banners.show_load_error)
        c.reloadFailed.connect(self.banners.show_reload_error)
        c.diskChanged.connect(self.banners.show_disk)
        c.runtimeChanged.connect(self.banners.set_runtime)
        c.requestDone.connect(self._on_request)
        self.banners.applyRequested.connect(lambda: c.request("reload"))
        self.banners.restartRequested.connect(self._restart)
        self.banners.reloadRequested.connect(self._reload_disk)
        self.banners.keepRequested.connect(c.keep_mine)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)

    # ------------------------------------------------------------------ navegacao e busca
    def _show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)  # type: ignore[arg-type]
        page.ensure_loaded()

    def _on_search(self, query: str) -> None:
        query = query.strip()
        counts = {key: page.filter(query) for key, page in self.pages.items()}
        total = sum(counts.values())
        for i, key in enumerate(self._keys):
            item = self.nav.item(i)
            if item is not None:
                item.setHidden(bool(query) and counts[key] == 0)
            self.nav.set_hits(key, counts[key] if query else None)
        self._drop_empty()
        if not query:
            self.summary.hide()
            self.stack.setCurrentWidget(self.pages[self.nav.current_key()])  # type: ignore[arg-type]
            return
        s = T.search
        pages_hit = sum(1 for n in counts.values() if n)
        self.summary.setText(s.found.format(fields=plural(total, s.field_one, s.field_many),
                                            pages=plural(pages_hit, s.page_one, s.page_many)))
        self.summary.setVisible(total > 0)
        if total == 0:
            empty = EmptyState(s.empty_title.format(q=query), s.empty_body, action_text=s.clear, icon_name="search")
            empty.actionTriggered.connect(self.search.clear)
            self._search_empty = empty
            self.stack.addWidget(empty)
            self.stack.setCurrentWidget(empty)
            return
        current = self.nav.current_key()
        if counts.get(current, 0) == 0:
            self.nav.set_current(next(k for k in self._keys if counts[k]))
        else:
            self.stack.setCurrentWidget(self.pages[current])  # type: ignore[arg-type]

    def _drop_empty(self) -> None:
        if self._search_empty is not None:
            self.stack.removeWidget(self._search_empty)
            self._search_empty.deleteLater()
            self._search_empty = None

    def open_section(self, name: str | None) -> bool:
        """Abre a pagina que tem a secao ``name`` (ex.: "permissions"). Nome desconhecido e ignorado."""
        if not name:
            return False
        for cat in CATEGORIES:
            if any(sec.id == name for sec in cat.sections):
                if self.search.text():
                    self.search.clear()
                self.nav.set_current(cat.key)
                page = self.pages[cat.key]
                return bool(getattr(page, "focus_section", lambda _n: False)(name))
        return False

    def go_to_field(self, key: str) -> None:
        """Abre a pagina do campo e leva o foco ate ele (usado quando salvar e bloqueado por erro)."""
        spec = schema.BY_KEY.get(key)
        if spec is None:
            return
        page = category_of(spec)
        if self.search.text():
            self.search.clear()
        self.nav.set_current(page)
        self.pages[page].scroll_to(key)

    # ------------------------------------------------------------------ estado
    def _refresh_state(self) -> None:
        m = self.controller.model
        n = max(m.change_count(), 1 if m.force_dirty else 0)
        self.bar.set_changes(n, m.error_count())
        counts = self.controller.page_counts()
        for key in self._keys:
            errors, changes = counts.get(key, (0, 0))
            self.nav.set_counts(key, errors=errors, changes=changes)

    def _refresh_emergency(self) -> None:
        value = self.controller.model.original.get(_EMERGENCY_KEY) or ""
        self._emergency.setText(to_display(value) if value else T.window.emergency_none)

    # ------------------------------------------------------------------ fluxos
    def _on_saved(self, outcome: SaveOutcome) -> None:
        self.banners.show_saved(outcome)
        self.saved.emit(outcome)

    def _on_blocked(self) -> None:
        self.banners.show_blocked()
        first = self.binder.first_error_key()
        if first:
            self.go_to_field(first)

    def _on_request(self, kind: str, ok: bool, detail: str) -> None:
        if ok:
            self.banners.mark_requested(kind)
            Toast.show_message(self, "ok", T.banner.apply_sent if kind == "reload" else T.banner.restart_sent)
        else:
            self.banners.show_request_error(detail)

    def _changed_labels(self) -> str:
        return "\n".join(T.label_for(k) for k in self.controller.model.changed_keys())

    def _discard(self) -> None:
        d = T.dialogs
        if ConfirmDialog.ask(self, title=d.discard_title, message=d.discard_message, target=self._changed_labels(),
                             confirm_text=d.discard_confirm, destructive=True):
            self.controller.discard()

    def _reset(self) -> None:
        d = T.dialogs
        path = str(self.controller.store.path)
        if ConfirmDialog.ask(self, title=d.reset_title, message=d.reset_message, target=d.reset_target.format(path=path),
                             confirm_text=d.reset_confirm, destructive=True):
            self.controller.reset_defaults()

    def _restart(self) -> None:
        d = T.dialogs
        if ConfirmDialog.ask(self, title=d.restart_title, message=d.restart_message, confirm_text=d.restart_confirm,
                             destructive=True):
            self.controller.request("restart")

    def _reload_disk(self) -> None:
        d = T.dialogs
        if self.controller.model.has_pending() and not ConfirmDialog.ask(
                self, title=d.reload_title, message=d.reload_message, target=self._changed_labels(),
                confirm_text=d.reload_confirm, destructive=True):
            return
        self.controller.reload_from_disk()

    # ------------------------------------------------------------------ API publica
    def collect_values(self) -> dict[str, Any]:
        return self.controller.collect_values()

    def apply_values(self, values: dict[str, Any]) -> None:
        self.controller.apply_values(values)

    def change_count(self) -> int:
        return self.controller.model.change_count()

    def has_pending_changes(self) -> bool:
        return self.controller.model.has_pending()

    # ------------------------------------------------------------------ ciclo de vida
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        d = T.dialogs
        if self.controller.model.has_pending() and self.isVisible() and not ConfirmDialog.ask(
                self, title=d.close_title, message=d.close_message, target=self._changed_labels(),
                confirm_text=d.close_confirm, cancel_text=d.close_cancel, destructive=True):
            event.ignore()
            return
        self.prefs.save_geometry(self)
        self.controller.shutdown()
        for page in dict.values(self.pages):                  # só as já montadas (não monta páginas só para fechar)
            page.shutdown()
        super().closeEvent(event)

