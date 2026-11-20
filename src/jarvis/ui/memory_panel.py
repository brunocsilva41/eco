"""Painel "O que o Jarvis sabe de mim": ver, editar e apagar tudo o que o Jarvis guarda (memórias, conversas, banco).

Uso::

    from jarvis.ui.memory_panel import MemoryPanel, open_memory, main_memory
    main_memory()                         # programa próprio (cria o QApplication)
    open_memory(cfg, parent=janela)       # janela solta dentro de um app Qt já em execução
    settings_window.set_memory_widget(MemoryPanel(cfg))   # embutido nas Configurações

Regras:
* Todo acesso ao banco roda em thread (``run_async``); a interface nunca trava. O banco é aberto no modo WAL (já
  ativo), então convive com o Jarvis em execução; "banco ocupado" vira mensagem clara com 'Tentar de novo'.
* A conexão é fechada quando o painel (ou a janela que o contém) é destruído ou fechado.
* Modo sem histórico (``cfg.memory.enabled`` falso ou ``Memory.persistent`` falso): nada é aberto nem editável.
* Erros viram texto em português (nunca traceback); o detalhe técnico vai para o log.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, TypeVar

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor, QShowEvent
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout, QFrame,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QPushButton,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..config import Config, ConfigError
from ..memory import Hit, Memory, MemoryError_, MemoryItem
from . import theme
from .memory_widgets import (ORIGIN_LABELS, ORIGIN_NOTES, KIND_LABELS, ROLE_LABELS, ConversationViewer, MemoryEditDialog,
                             MemoryList, SessionRow, Stats, StatusBanner, ask, confirm_typed, default_save_dir,
                             delete_all_sessions, delete_memory_for_good, file_size_bytes, fmt_mb, fmt_ts, friendly_error,
                             full_stylesheet, is_busy_error, load_memories, load_session_rows, load_stats, plural,
                             safe_file_stem, search_conversations, session_state_text, with_suffix_default)
from .settings_widgets import run_async

log = logging.getLogger(__name__)

T = TypeVar("T")

DB_NAME: Final = "jarvis.db"
SEARCH_DELAY_MS: Final = 300
TAB_MEMORIES, TAB_CONVERSATIONS, TAB_STORAGE = 0, 1, 2
_ROLE_ID: Final = Qt.ItemDataRole.UserRole
_STATE_FILTERS: Final[tuple[tuple[str, str | None], ...]] = (
    ("Todas (ativa e encerradas)", None), ("Só a ativa", "ativa"), ("Só encerradas", "encerrada"), ("Lixeira", "lixeira"))


# ============================================================================ dono da conexão
class _Holder:
    """Guarda o ``Memory`` aberto e o fecha uma única vez. Independente de widgets: serve de alvo do sinal ``destroyed``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.memory: Memory | None = None
        self.closed = False

    def adopt(self, mem: Memory) -> None:
        with self._lock:
            if self.closed:                                   # o painel foi destruído enquanto o banco abria
                mem.close()
                raise MemoryError_("o painel foi fechado antes de a memória abrir")
            self.memory = mem

    def close(self, *_args: object) -> None:
        with self._lock:
            self.closed = True
            mem, self.memory = self.memory, None
        if mem is not None:
            try:
                mem.close()
                log.info("conexão do painel de memória fechada")
            except Exception:  # noqa: BLE001 - fechar nunca pode derrubar a interface
                log.exception("erro ao fechar a memória do painel")


# ============================================================================ utilidades de tabela
def _make_table(columns: list[str], name: str) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setAccessibleName(name)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.setMinimumHeight(180)
    table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return table


def _cell(text: str, ident: int | None = None, tip: str = "", warn: bool = False, right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setToolTip(tip or text)
    if ident is not None:
        item.setData(_ROLE_ID, ident)
    if warn:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QColor(theme.WARN))
    if right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _selected_id(table: QTableWidget) -> int | None:
    row = table.currentRow()
    if row < 0 or not table.selectedItems():
        return None
    item = table.item(row, 0)
    value = item.data(_ROLE_ID) if item is not None else None
    return int(value) if value is not None else None


def _select_id(table: QTableWidget, ident: int | None) -> None:
    if ident is None:
        return
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is not None and item.data(_ROLE_ID) == ident:
            table.selectRow(row)
            return


def _muted(text: str = "", name: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", "muted")
    lab.setWordWrap(True)
    if name:
        lab.setAccessibleName(name)
    return lab


def _button(text: str, tip: str = "", variant: str = "") -> QPushButton:
    btn = QPushButton(text)
    if tip:
        btn.setToolTip(tip)
    if variant:
        btn.setProperty("variant", variant)
    return btn


# ============================================================================ aba Memórias
class _MemoriesTab(QWidget):
    def __init__(self, host: MemoryPanel) -> None:
        super().__init__()
        self.setObjectName("plain")
        self._host = host
        self._seq = 0
        self._items: dict[int, MemoryItem] = {}

        self._search = QLineEdit()
        self._search.setPlaceholderText("Palavras da memória...")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("Buscar nas memórias")
        search_label = QLabel("&Buscar:")
        search_label.setBuddy(self._search)
        self._kind = QComboBox()
        self._kind.addItem("Todos os tipos", None)
        for k, label in KIND_LABELS.items():
            self._kind.addItem(label, k)
        self._kind.setAccessibleName("Filtrar por tipo")
        kind_label = QLabel("&Tipo:")
        kind_label.setBuddy(self._kind)
        self._reload = _button("Atualizar", "Recarrega a lista do banco")
        top = QHBoxLayout()
        top.setSpacing(theme.SP1)
        for w in (search_label, self._search):
            top.addWidget(w, 1 if w is self._search else 0)
        top.addWidget(kind_label)
        top.addWidget(self._kind)
        top.addWidget(self._reload)

        self._table = _make_table(["Tipo", "Texto", "Origem", "Fixada", "Atualizada", "Expira"], "Tabela de memórias")
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._count = _muted("", "Contador de memórias")
        self._detail = QLabel("")
        self._detail.setWordWrap(True)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._detail.setAccessibleName("Detalhe da memória selecionada")
        self._detail.setMinimumHeight(theme.SP4 * 2)

        self._add = _button("Adicionar...", "Guardar uma nova memória (origem: você)", "primary")
        self._edit = _button("Editar...", "Alterar o texto da memória selecionada")
        self._pin = _button("Fixar", "Fixadas entram sempre na conversa")
        self._delete = _button("Apagar...", "Apaga a memória selecionada")
        self._export = _button("Exportar tudo (JSON)...", "Salva memórias e conversas em um arquivo JSON, sem senhas ou chaves")
        self._wipe = _button("Apagar TUDO...", "Apaga todas as memórias de longo prazo", "danger")
        row1 = QHBoxLayout()
        row1.setSpacing(theme.SP1)
        for b in (self._add, self._edit, self._pin, self._delete):
            row1.addWidget(b)
        row1.addStretch(1)
        row2 = QHBoxLayout()
        row2.setSpacing(theme.SP1)
        row2.addWidget(self._export)
        row2.addStretch(1)
        row2.addWidget(self._wipe)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP2, theme.SP2, theme.SP2, theme.SP2)
        lay.setSpacing(theme.SP1)
        lay.addLayout(top)
        lay.addWidget(self._table, 1)
        lay.addWidget(self._count)
        lay.addWidget(self._detail)
        lay.addLayout(row1)
        lay.addLayout(row2)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DELAY_MS)
        self._timer.timeout.connect(self.refresh)
        self._search.textChanged.connect(lambda _t: self._timer.start())
        self._kind.currentIndexChanged.connect(lambda _i: self.refresh())
        self._reload.clicked.connect(self.refresh)
        self._table.itemSelectionChanged.connect(self._on_select)
        self._table.itemDoubleClicked.connect(lambda _i: self._edit_selected())
        self._add.clicked.connect(self._add_memory)
        self._edit.clicked.connect(self._edit_selected)
        self._pin.clicked.connect(self._toggle_pin)
        self._delete.clicked.connect(self._delete_selected)
        self._export.clicked.connect(self._export_all)
        self._wipe.clicked.connect(self._wipe_all)
        order = [self._search, self._kind, self._reload, self._table, self._add, self._edit, self._pin, self._delete,
                 self._export, self._wipe]
        for a, b in zip(order, order[1:]):
            QWidget.setTabOrder(a, b)
        self.sync_enabled()

    # --- estado
    def sync_enabled(self) -> None:
        editable = self._host.editable
        sel = self._items.get(_selected_id(self._table) or -1)
        self._add.setEnabled(editable)
        self._edit.setEnabled(editable and sel is not None)
        self._pin.setEnabled(editable and sel is not None)
        self._delete.setEnabled(editable and sel is not None)
        self._export.setEnabled(editable)
        self._wipe.setEnabled(editable and bool(self._items))
        self._search.setEnabled(self._host.can_read)
        self._kind.setEnabled(self._host.can_read)
        self._reload.setEnabled(self._host.can_read)
        self._pin.setText("Desafixar" if sel is not None and sel.pinned else "Fixar")

    def _on_select(self) -> None:
        item = self._items.get(_selected_id(self._table) or -1)
        if item is None:
            self._detail.setText("Selecione uma memória para ver o texto completo e de onde ela veio.")
        else:
            exp = ""
            if item.expires_at is not None:
                exp = ("  Expirou em " if item.expires_at <= time.time() else "  Expira em ") + fmt_ts(item.expires_at) + "."
            self._detail.setText(f"{item.text}\n\n{ORIGIN_NOTES.get(item.origin, item.origin)}{exp}")
        self.sync_enabled()

    # --- carga
    def refresh(self) -> None:
        if not self._host.can_read:
            self._fill(MemoryList([], 0, 0))
            self._count.setText("Modo sem histórico: nada é guardado em disco, então não há memórias para mostrar."
                                if not self._host.persistent else "Abrindo a memória...")
            return
        self._seq += 1
        seq = self._seq
        query, kind = self._search.text(), self._kind.currentData()
        keep = _selected_id(self._table)
        self._count.setText("Carregando...")
        self._host.submit(lambda mem: load_memories(mem, query, kind),
                          lambda res: self._loaded(seq, res, keep), self.refresh)

    def _loaded(self, seq: int, data: MemoryList, keep: int | None) -> None:
        if seq != self._seq:
            return                                             # resposta velha: já pediram outra busca
        self._fill(data)
        _select_id(self._table, keep)
        searching = bool(self._search.text().strip()) or self._kind.currentData() is not None
        shown = len(data.items)
        text = (f"{plural(data.total, 'memória', 'memórias')} no total ({data.pinned} fixada(s))."
                + (f" Mostrando {shown} do filtro." if searching else ""))
        if not data.items:
            text += " Nada encontrado." if searching else " O Jarvis ainda não guardou nenhuma memória."
        self._count.setText(text)
        self._on_select()

    def _fill(self, data: MemoryList) -> None:
        self._items = {i.id: i for i in data.items}
        now = time.time()
        self._table.setUpdatesEnabled(False)
        self._table.setRowCount(0)
        for i in data.items:
            r = self._table.rowCount()
            self._table.insertRow(r)
            foreign = i.origin != "usuario"
            expired = i.expires_at is not None and i.expires_at <= now
            exp_text = "Nunca" if i.expires_at is None else (("Expirada em " if expired else "") + fmt_ts(i.expires_at))
            self._table.setItem(r, 0, _cell(KIND_LABELS.get(i.kind, i.kind), i.id))
            self._table.setItem(r, 1, _cell(i.text.replace("\n", " "), tip=i.text))
            self._table.setItem(r, 2, _cell(ORIGIN_LABELS.get(i.origin, i.origin), tip=ORIGIN_NOTES.get(i.origin, ""), warn=foreign))
            self._table.setItem(r, 3, _cell("Fixada" if i.pinned else "Não"))
            self._table.setItem(r, 4, _cell(fmt_ts(i.updated)))
            self._table.setItem(r, 5, _cell(exp_text))
        self._table.setUpdatesEnabled(True)
        self._table.clearSelection()
        self.sync_enabled()

    # --- ações
    def _add_memory(self) -> None:
        dlg = MemoryEditDialog(self, new=True)
        if dlg.exec() != MemoryEditDialog.DialogCode.Accepted or dlg.result_value() is None:
            return
        v = dlg.result_value()
        assert v is not None
        expires = time.time() + v.expires_days * 86400 if v.expires_days else None
        self._host.submit(lambda mem: mem.longterm.remember(v.text, v.kind, "usuario", expires_at=expires, pinned=v.pinned),
                          lambda _id: self._host.changed("Memória guardada."), None)

    def _edit_selected(self) -> None:
        item = self._items.get(_selected_id(self._table) or -1)
        if item is None or not self._host.editable:
            return
        dlg = MemoryEditDialog(self, new=False, text=item.text)
        if dlg.exec() != MemoryEditDialog.DialogCode.Accepted or dlg.result_value() is None:
            return
        v = dlg.result_value()
        assert v is not None
        self._host.submit(lambda mem: mem.longterm.edit(item.id, v.text), lambda _r: self._host.changed("Memória alterada."), None)

    def _toggle_pin(self) -> None:
        item = self._items.get(_selected_id(self._table) or -1)
        if item is None:
            return
        want = not item.pinned
        self._host.submit(lambda mem: mem.longterm.pin(item.id, want),
                          lambda _r: self._host.changed("Memória fixada." if want else "Memória desafixada."), None)

    def _delete_selected(self) -> None:
        item = self._items.get(_selected_id(self._table) or -1)
        if item is None:
            return
        shown = item.text if len(item.text) <= 300 else item.text[:299] + "…"
        if not ask(self, "Apagar memória", f"Apagar esta memória para sempre?\n\n\"{shown}\"\n\nNão há como desfazer.",
                   "Apagar memória", destructive=True):
            return
        self._host.submit(lambda mem: delete_memory_for_good(mem, item.id),
                          lambda _r: self._host.changed("Memória apagada."), None)

    def _export_all(self) -> None:
        picked = self._host.choose_save_path("Exportar memórias e conversas", f"jarvis-dados-{time.strftime('%Y%m%d')}.json",
                                             "JSON (*.json);;Todos os arquivos (*)", (".json",), ".json")
        if picked is None:
            return
        self._host.submit(lambda mem: mem.export_all_json(picked),
                          lambda p: self._host.notify(f"Exportado em {p}. Conversas (fora da lixeira) e memórias; "
                                                      "trechos com cara de senha ou chave foram omitidos.", "ok"), None)

    def _wipe_all(self) -> None:
        n = len(self._items)
        if not confirm_typed(self, "Apagar TODAS as memórias",
                             f"Isto apaga para sempre TODAS as memórias de longo prazo do Jarvis ({plural(n, 'item', 'itens')}), "
                             "inclusive as fixadas. As conversas não são afetadas. Não há como desfazer.",
                             "Apagar todas as memórias"):
            return
        self._host.submit(lambda mem: mem.longterm.purge_all(vacuum=True),
                          lambda cnt: self._host.changed(f"{plural(int(cnt), 'memória apagada', 'memórias apagadas')}."), None)


# ============================================================================ aba Conversas
class _ConversationsTab(QWidget):
    def __init__(self, host: MemoryPanel) -> None:
        super().__init__()
        self.setObjectName("plain")
        self._host = host
        self._seq = 0
        self._rows: dict[int, SessionRow] = {}
        self._hit_mode = False

        self._search = QLineEdit()
        self._search.setPlaceholderText("Palavras ditas na conversa e Enter...")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("Buscar nas conversas")
        search_label = QLabel("&Buscar:")
        search_label.setBuddy(self._search)
        self._go = _button("Buscar", "Procura nas mensagens, títulos e resumos")
        self._filter = QComboBox()
        for label, state in _STATE_FILTERS:
            self._filter.addItem(label, state)
        self._filter.setAccessibleName("Mostrar conversas")
        filter_label = QLabel("&Mostrar:")
        filter_label.setBuddy(self._filter)
        self._reload = _button("Atualizar", "Recarrega a lista do banco")
        top = QHBoxLayout()
        top.setSpacing(theme.SP1)
        top.addWidget(search_label)
        top.addWidget(self._search, 1)
        top.addWidget(self._go)
        top.addWidget(filter_label)
        top.addWidget(self._filter)
        top.addWidget(self._reload)

        self._table = _make_table(["Título", "Última atividade", "Mensagens", "Estado"], "Lista de conversas")
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._hits = _make_table(["Conversa", "Data", "Quem", "Trecho encontrado"], "Resultados da busca nas conversas")
        h2 = self._hits.horizontalHeader()
        h2.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h2.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._stack = QStackedWidget()
        self._stack.setObjectName("plain")
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._hits)
        self._count = _muted("", "Contador de conversas")
        self._trash_note = _muted("", "Aviso da lixeira")

        self._open = _button("Abrir (somente leitura)", "Mostra as mensagens sem poder alterá-las", "primary")
        self._rename = _button("Renomear...")
        self._export = _button("Exportar...", "Salva a conversa em Markdown ou JSON")
        self._delete = _button("Apagar...", "Envia a conversa para a lixeira")
        self._resume = _button("Retomar esta conversa", "Torna a conversa a ativa")
        self._restore = _button("Restaurar", "Tira a conversa da lixeira")
        self._empty = _button("Esvaziar lixeira...", "Apaga de vez tudo o que está na lixeira", "danger")
        row = QHBoxLayout()
        row.setSpacing(theme.SP1)
        for b in (self._open, self._rename, self._export, self._resume, self._delete, self._restore, self._empty):
            row.addWidget(b)
        row.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP2, theme.SP2, theme.SP2, theme.SP2)
        lay.setSpacing(theme.SP1)
        lay.addLayout(top)
        lay.addWidget(self._stack, 1)
        lay.addWidget(self._count)
        lay.addWidget(self._trash_note)
        lay.addLayout(row)

        self._search.returnPressed.connect(self.refresh)
        self._go.clicked.connect(self.refresh)
        self._search.textChanged.connect(self._on_text)
        self._filter.currentIndexChanged.connect(lambda _i: self.refresh())
        self._reload.clicked.connect(self.refresh)
        for t in (self._table, self._hits):
            t.itemSelectionChanged.connect(self.sync_enabled)
            t.itemDoubleClicked.connect(lambda _i: self._open_selected())
        self._open.clicked.connect(self._open_selected)
        self._rename.clicked.connect(self._rename_selected)
        self._export.clicked.connect(lambda: self._export_session(self._selected()))
        self._delete.clicked.connect(self._delete_selected)
        self._resume.clicked.connect(lambda: self._resume_session(self._selected()))
        self._restore.clicked.connect(self._restore_selected)
        self._empty.clicked.connect(self._empty_trash)
        order = [self._search, self._go, self._filter, self._reload, self._table, self._hits, self._open, self._rename,
                 self._export, self._resume, self._delete, self._restore, self._empty]
        for a, b in zip(order, order[1:]):
            QWidget.setTabOrder(a, b)
        self.sync_enabled()

    # --- estado
    def _in_trash(self) -> bool:
        return self._filter.currentData() == "lixeira"

    def _selected(self) -> int | None:
        return _selected_id(self._hits if self._hit_mode else self._table)

    def sync_enabled(self) -> None:
        editable = self._host.editable
        trash = self._in_trash()
        sid = self._selected()
        row = self._rows.get(sid or -1)
        has = sid is not None
        self._search.setEnabled(self._host.can_read)
        self._go.setEnabled(self._host.can_read)
        self._filter.setEnabled(self._host.can_read)
        self._reload.setEnabled(self._host.can_read)
        self._open.setEnabled(self._host.can_read and has)
        whole = editable and has and not self._hit_mode and row is not None
        for b in (self._rename, self._export, self._delete, self._resume):
            b.setVisible(not trash)
        for b in (self._restore, self._empty):
            b.setVisible(trash)
        self._rename.setEnabled(whole)
        self._export.setEnabled(editable and has)
        self._delete.setEnabled(whole)
        self._resume.setEnabled(whole and row is not None and row.session.state == "encerrada")
        self._restore.setEnabled(whole)
        self._empty.setEnabled(editable and trash and bool(self._rows))
        if not trash:
            tip = "" if not (row is not None and row.session.state == "ativa") else "Esta já é a conversa ativa."
            self._resume.setToolTip(tip or "Torna a conversa a ativa")
        days = self._host.trash_days
        self._trash_note.setVisible(trash)
        self._trash_note.setText(f"A lixeira guarda as conversas por {plural(days, 'dia', 'dias')}; depois elas são apagadas de vez. "
                                 "Restaurar devolve a conversa como encerrada.")

    def _on_text(self, text: str) -> None:
        if not text.strip() and self._hit_mode:
            self.refresh()                                     # apagou a busca: volta à lista

    # --- carga
    def refresh(self) -> None:
        if not self._host.can_read:
            self._rows = {}
            self._table.setRowCount(0)
            self._hits.setRowCount(0)
            self._stack.setCurrentIndex(0)
            self._hit_mode = False
            self._count.setText("Modo sem histórico: nada é guardado em disco, então não há conversas para mostrar."
                                if not self._host.persistent else "Abrindo a memória...")
            self.sync_enabled()
            return
        self._seq += 1
        seq = self._seq
        query = self._search.text().strip()
        state = self._filter.currentData()
        keep = self._selected()
        self._count.setText("Carregando...")
        if query and state != "lixeira":
            self._host.submit(lambda mem: search_conversations(mem, query), lambda res: self._hits_loaded(seq, query, res), self.refresh)
        else:
            self._host.submit(lambda mem: load_session_rows(mem, state, query),
                              lambda res: self._rows_loaded(seq, query, res, keep), self.refresh)

    def _rows_loaded(self, seq: int, query: str, rows: list[SessionRow], keep: int | None) -> None:
        if seq != self._seq:
            return
        self._hit_mode = False
        self._stack.setCurrentIndex(0)
        self._rows = {r.session.id: r for r in rows}
        days = self._host.trash_days
        now = time.time()
        self._table.setUpdatesEnabled(False)
        self._table.setRowCount(0)
        for r in rows:
            i = self._table.rowCount()
            self._table.insertRow(i)
            s = r.session
            self._table.setItem(i, 0, _cell(s.title, s.id))
            self._table.setItem(i, 1, _cell(fmt_ts(s.last_active)))
            self._table.setItem(i, 2, _cell(str(r.messages), right=True))
            self._table.setItem(i, 3, _cell(session_state_text(s, days, now)))
        self._table.setUpdatesEnabled(True)
        self._table.clearSelection()
        _select_id(self._table, keep)
        label = plural(len(rows), "conversa", "conversas")
        if not rows:
            label = "Nada na lixeira." if self._in_trash() else ("Nenhuma conversa encontrada." if query else "Nenhuma conversa guardada ainda.")
        self._count.setText(label)
        self.sync_enabled()

    def _hits_loaded(self, seq: int, query: str, hits: list[Hit]) -> None:
        if seq != self._seq:
            return
        self._hit_mode = True
        self._stack.setCurrentIndex(1)
        self._rows = {}
        self._hits.setUpdatesEnabled(False)
        self._hits.setRowCount(0)
        for h in hits:
            i = self._hits.rowCount()
            self._hits.insertRow(i)
            who = "Resumo" if h.role is None else ROLE_LABELS.get(h.role, h.role)
            self._hits.setItem(i, 0, _cell(h.title, h.session_id))
            self._hits.setItem(i, 1, _cell(fmt_ts(h.ts)))
            self._hits.setItem(i, 2, _cell(who))
            self._hits.setItem(i, 3, _cell(h.snippet))
        self._hits.setUpdatesEnabled(True)
        self._hits.clearSelection()
        self._count.setText(f"{plural(len(hits), 'trecho encontrado', 'trechos encontrados')} para \"{query}\". "
                            "Os termos achados aparecem entre « ». Dê duplo clique para abrir a conversa.")
        self.sync_enabled()

    # --- ações
    def _open_selected(self) -> None:
        sid = self._selected()
        if sid is None:
            return
        days = self._host.trash_days
        self._host.submit(lambda mem: (mem.sessions.get(sid), mem.sessions.messages(sid), mem.sessions.get_summary(sid)),
                          lambda res: self._show_viewer(res, days), None)

    def _show_viewer(self, res: Any, days: int) -> None:
        session, messages, summary = res
        if session is None:
            self._host.notify("Essa conversa não existe mais (outro programa pode tê-la apagado).", "warn")
            self.refresh()
            return
        dlg = ConversationViewer(self, session, messages, summary[0] if summary else None, days)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.resume_requested.connect(lambda sid: (dlg.accept(), self._resume_session(sid)))
        dlg.export_requested.connect(self._export_session)
        dlg.show()

    def _rename_selected(self) -> None:
        sid = self._selected()
        row = self._rows.get(sid or -1)
        if row is None:
            return
        title, ok = QInputDialog.getText(self, "Renomear conversa", "Novo título (até 80 caracteres):", QLineEdit.EchoMode.Normal, row.session.title)
        if not ok or not title.strip():
            return
        self._host.submit(lambda mem: mem.sessions.rename(row.session.id, title), lambda _r: self._host.changed("Conversa renomeada."), None)

    def _export_session(self, sid: int | None) -> None:
        if sid is None:
            return
        title = self._rows[sid].session.title if sid in self._rows else "conversa"
        picked = self._host.choose_save_path("Exportar conversa", f"{safe_file_stem(title)}.md",
                                             "Markdown (*.md);;JSON (*.json);;Todos os arquivos (*)", (".md", ".json"), ".md")
        if picked is None:
            return
        fmt = "json" if picked.suffix.lower() == ".json" else "md"
        self._host.submit(lambda mem: mem.sessions.export(sid, picked, fmt),
                          lambda p: self._host.notify(f"Conversa exportada em {p} (trechos com cara de senha ou chave foram omitidos).", "ok"), None)

    def _delete_selected(self) -> None:
        sid = self._selected()
        row = self._rows.get(sid or -1)
        if row is None:
            return
        extra = ""
        if row.session.state == "ativa":
            extra = ("\n\nEsta é a conversa ATIVA: se o Jarvis estiver em execução, o próximo pedido dele abre uma conversa nova.")
        days = self._host.trash_days
        if not ask(self, "Apagar conversa", f"Enviar a conversa \"{row.session.title}\" ({plural(row.messages, 'mensagem', 'mensagens')}) "
                   f"para a lixeira? Ela fica lá por {plural(days, 'dia', 'dias')} e pode ser restaurada.{extra}",
                   "Enviar para a lixeira", destructive=True):
            return
        self._host.submit(lambda mem: mem.sessions.delete(row.session.id, to_trash=True),
                          lambda _r: self._host.changed("Conversa enviada para a lixeira."), None)

    def _resume_session(self, sid: int | None) -> None:
        if sid is None:
            return
        if not ask(self, "Retomar conversa",
                   "A conversa escolhida passa a ser a ativa e a conversa ativa de agora é encerrada.\n\n"
                   "Atenção: o Jarvis em execução só verá essa mudança depois do próximo pedido que você fizer a ele.",
                   "Retomar esta conversa"):
            return
        self._host.submit(lambda mem: mem.sessions.resume(sid),
                          lambda s: self._host.changed(f"Conversa \"{s.title}\" retomada. O Jarvis em execução só a verá depois do próximo pedido."), None)

    def _restore_selected(self) -> None:
        sid = self._selected()
        if sid is None:
            return
        self._host.submit(lambda mem: mem.sessions.restore(sid), lambda _r: self._host.changed("Conversa restaurada (voltou como encerrada)."), None)

    def _empty_trash(self) -> None:
        n = len(self._rows)
        if not ask(self, "Esvaziar lixeira", f"Apagar para sempre {plural(n, 'conversa', 'conversas')} da lixeira? Não há como desfazer.",
                   "Esvaziar lixeira", destructive=True):
            return
        self._host.submit(lambda mem: mem.sessions.empty_trash(None),
                          lambda cnt: self._host.changed(f"Lixeira esvaziada ({plural(int(cnt), 'conversa apagada', 'conversas apagadas')})."), None)


# ============================================================================ aba Armazenamento e privacidade
class _StorageTab(QWidget):
    def __init__(self, host: MemoryPanel) -> None:
        super().__init__()
        self.setObjectName("plain")
        self._host = host
        self._seq = 0

        self._warning = StatusBanner("Aviso de privacidade")
        self._warning.show_message("O banco não é criptografado. Qualquer pessoa com acesso à sua conta do Windows pode ler esse "
                                   "arquivo, e as cópias de segurança e exportações têm o mesmo conteúdo.", "warn", dismissable=False)
        self._state = QLabel("")
        self._state.setWordWrap(True)
        self._path = QLabel("")
        self._path.setWordWrap(True)
        self._size = QLabel("")
        self._counts = QLabel("")
        self._counts.setWordWrap(True)
        self._retention = QLabel("")
        self._retention.setWordWrap(True)
        for lab, name in ((self._state, "Situação do histórico"), (self._path, "Caminho do banco"), (self._size, "Tamanho do banco"),
                          (self._counts, "Quantidades guardadas"), (self._retention, "Prazos de guarda")):
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setAccessibleName(name)
            lab.setTextFormat(Qt.TextFormat.PlainText)
        form = QFormLayout()
        form.setHorizontalSpacing(theme.SP2)
        form.setVerticalSpacing(theme.SP1)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for caption, widget in (("Situação:", self._state), ("Banco de dados:", self._path), ("Tamanho:", self._size),
                                ("Guardado:", self._counts), ("Prazos:", self._retention)):
            cap = QLabel(caption)
            cap.setProperty("role", "field")
            form.addRow(cap, widget)
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(theme.SP2, theme.SP2, theme.SP2, theme.SP2)
        cl.addLayout(form)

        self._refresh = _button("Atualizar números")
        self._backup = _button("Fazer cópia de segurança...", "Copia o banco inteiro para um arquivo à sua escolha", "primary")
        self._wipe = _button("Apagar TODAS as conversas...", "Apaga de vez todas as conversas e mensagens", "danger")
        self._result = StatusBanner("Resultado da operação de armazenamento")
        row = QHBoxLayout()
        row.setSpacing(theme.SP1)
        row.addWidget(self._backup)
        row.addWidget(self._refresh)
        row.addStretch(1)
        row.addWidget(self._wipe)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP2, theme.SP2, theme.SP2, theme.SP2)
        lay.setSpacing(theme.SP2)
        lay.addWidget(self._warning)
        lay.addWidget(card)
        lay.addLayout(row)
        lay.addWidget(self._result)
        lay.addStretch(1)
        self._refresh.clicked.connect(self.refresh)
        self._backup.clicked.connect(self._make_backup)
        self._wipe.clicked.connect(self._wipe_conversations)
        for a, b in ((self._backup, self._refresh), (self._refresh, self._wipe)):
            QWidget.setTabOrder(a, b)
        self.sync_enabled()

    def sync_enabled(self) -> None:
        editable = self._host.editable
        self._backup.setEnabled(editable)
        self._wipe.setEnabled(editable)
        self._refresh.setEnabled(self._host.can_read or not self._host.persistent)

    def show_result(self, text: str, state: str) -> None:
        self._result.show_message(text, state)

    def _static_info(self) -> None:
        cfg = self._host.cfg.memory
        self._path.setText(str(self._host.db_path))
        self._retention.setText(
            f"Conversas sem uso há {plural(cfg.conversation_ttl_days, 'dia', 'dias')} vão para a lixeira; a lixeira guarda por "
            f"{plural(cfg.trash_days, 'dia', 'dias')} e depois apaga de vez.")

    def refresh(self) -> None:
        self._static_info()
        if not self._host.persistent:
            self._state.setText("MODO SEM HISTÓRICO: nada é gravado em disco. Tudo o que o Jarvis ouve nesta sessão some quando ele fecha. "
                                "Para guardar conversas e memórias, ligue 'memória' nas Configurações e reinicie o Jarvis.")
            self._state.setProperty("state", "warn")
            theme.repolish(self._state)
            self._counts.setText("Não há nada guardado por este modo.")
            path = self._host.db_path
            self._size.setText("verificando...")
            self._host.submit_plain(lambda: file_size_bytes(path), lambda n: self._old_file(int(n)), None)
            self.sync_enabled()
            return
        self._state.setText("Histórico LIGADO: o Jarvis guarda conversas e memórias neste computador.")
        self._state.setProperty("state", "ok")
        theme.repolish(self._state)
        if not self._host.can_read:
            self._size.setText("abrindo...")
            self._counts.setText("abrindo...")
            self.sync_enabled()
            return
        self._seq += 1
        seq = self._seq
        path = self._host.db_path
        self._size.setText("calculando...")
        self._counts.setText("calculando...")
        self._host.submit(lambda mem: load_stats(mem, path), lambda st: self._stats(seq, st), self.refresh)
        self.sync_enabled()

    def _old_file(self, size: int) -> None:
        if size > 0:
            self._size.setText(f"{fmt_mb(size)} (arquivo antigo: não é lido nem alterado enquanto o histórico estiver desligado)")
        else:
            self._size.setText("Nenhum arquivo de banco encontrado.")

    def _stats(self, seq: int, st: Stats) -> None:
        if seq != self._seq:
            return
        self._size.setText(fmt_mb(st.size_bytes))
        self._counts.setText(f"{plural(st.memories, 'memória', 'memórias')} ({st.pinned} fixada(s))  |  "
                             f"{plural(st.sessions, 'conversa', 'conversas')} (+ {st.trashed} na lixeira)  |  "
                             f"{plural(st.messages, 'mensagem', 'mensagens')}")

    def _make_backup(self) -> None:
        picked = self._host.choose_save_path("Cópia de segurança do banco", f"jarvis-backup-{time.strftime('%Y%m%d-%H%M')}.db",
                                             "Banco SQLite (*.db);;Todos os arquivos (*)", (".db", ".sqlite", ".sqlite3"), ".db")
        if picked is None:
            return
        self._host.submit(lambda mem: mem.backup_to(picked),
                          lambda p: self._host.notify(f"Cópia de segurança gravada em {p}. Ela NÃO é criptografada: guarde-a com cuidado.", "ok"), None)

    def _wipe_conversations(self) -> None:
        if not confirm_typed(self, "Apagar TODAS as conversas",
                             "Isto apaga para sempre TODAS as conversas e mensagens (inclusive as da lixeira e a conversa ativa). "
                             "As memórias de longo prazo não são afetadas. Não há como desfazer.\n\n"
                             "Se o Jarvis estiver em execução, o próximo pedido dele abre uma conversa nova.",
                             "Apagar todas as conversas"):
            return
        self._host.submit(lambda mem: delete_all_sessions(mem),
                          lambda cnt: self._host.changed(f"{plural(int(cnt), 'conversa apagada', 'conversas apagadas')} para sempre."), None)


# ============================================================================ painel
class MemoryPanel(QWidget):
    """Painel completo (3 abas). Abre o banco sozinho, em segundo plano, e o fecha ao ser destruído/fechado."""

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.persistent: bool = bool(cfg.memory.enabled)
        self.db_path: Path = Path(cfg.paths.data) / DB_NAME
        self.trash_days: int = int(cfg.memory.trash_days)
        self._holder = _Holder()
        self.destroyed.connect(self._holder.close)
        self._opening = False
        self._pending = 0
        self._dirty: set[int] = {TAB_MEMORIES, TAB_CONVERSATIONS, TAB_STORAGE}

        self.setObjectName("plain")
        self.setStyleSheet(full_stylesheet())
        self.setMinimumHeight(560)
        self.setAccessibleName("O que o Jarvis sabe de mim")

        self._mode = StatusBanner("Situação do histórico")
        self._status = StatusBanner("Mensagens do painel de memória")
        self._busy = _muted("", "Atividade")
        self._busy.setVisible(False)
        self._tabs = QTabWidget()
        self._tabs.setAccessibleName("Seções do painel de memória")
        self._tabs.tabBar().setUsesScrollButtons(False)
        self._memories = _MemoriesTab(self)
        self._conversations = _ConversationsTab(self)
        self._storage = _StorageTab(self)
        self._tabs.addTab(self._memories, "Memórias")
        self._tabs.addTab(self._conversations, "Conversas")
        self._tabs.addTab(self._storage, "Armazenamento e privacidade")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP1)
        lay.addWidget(self._mode)
        lay.addWidget(self._status)
        lay.addWidget(self._busy)
        lay.addWidget(self._tabs, 1)
        self._tabs.currentChanged.connect(self._on_tab)
        QWidget.setTabOrder(self._tabs, self._memories)

        if not self.persistent:
            self._show_no_history()
        else:
            self._open_memory()
        self._refresh_current()

    # ------------------------------------------------------------------ estado
    @property
    def can_read(self) -> bool:
        return self.persistent and self._holder.memory is not None

    @property
    def editable(self) -> bool:
        return self.can_read

    def memory(self) -> Memory | None:
        """O ``Memory`` aberto (None enquanto abre, no modo sem histórico ou depois de fechar)."""
        return self._holder.memory

    def _show_no_history(self) -> None:
        self._mode.show_message("MODO SEM HISTÓRICO: o Jarvis não grava nada em disco, então não há o que ver, editar ou apagar aqui. "
                                "Para voltar a guardar conversas e memórias, ligue a memória nas Configurações e reinicie o Jarvis.",
                                "warn", dismissable=False)

    # ------------------------------------------------------------------ abrir / fechar o banco
    def _open_memory(self) -> None:
        if self._opening or self._holder.memory is not None:
            return
        self._opening = True
        holder, path, mcfg = self._holder, self.db_path, self.cfg.memory

        def job() -> bool:
            mem = Memory(path, mcfg)
            holder.adopt(mem)
            return bool(mem.persistent)

        def done(persistent: object) -> None:
            self._opening = False
            if not persistent:
                self.persistent = False
                self._show_no_history()
            self._status.clear()
            self._dirty = {TAB_MEMORIES, TAB_CONVERSATIONS, TAB_STORAGE}
            self._sync_all()
            self._refresh_current()

        def fail(message: str) -> None:
            self._opening = False
            self._show_error(message, self._open_memory, "Não consegui abrir a memória. ")

        run_async(job, self, done, fail)

    def close_memory(self) -> None:
        """Fecha a conexão (idempotente). Chamado ao fechar/destruir o painel."""
        self._holder.close()
        self._sync_all()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.close_memory()
        super().closeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if self.persistent and self._holder.closed and self._holder.memory is None:
            self._status.show_message("A memória foi fechada. Feche e abra esta seção de novo para recarregar.", "warn", dismissable=False)

    # ------------------------------------------------------------------ trabalho em segundo plano
    def _begin(self) -> None:
        self._pending += 1
        self._busy.setText("Trabalhando...")
        self._busy.setVisible(True)

    def _end(self) -> None:
        self._pending = max(0, self._pending - 1)
        if self._pending == 0:
            self._busy.setVisible(False)

    def submit(self, fn: Callable[[Memory], T], done: Callable[[T], None], retry: Callable[[], None] | None) -> None:
        """Roda ``fn(memory)`` numa thread. `done` roda na interface; erros viram faixa em pt-BR (com 'Tentar de novo' se `retry`
        ou se o banco estiver ocupado e a ação puder ser repetida)."""
        holder = self._holder

        def job() -> T:
            mem = holder.memory
            if mem is None:
                raise MemoryError_("a memória não está aberta")
            return fn(mem)

        self._submit_job(job, done, retry)

    def submit_plain(self, fn: Callable[[], T], done: Callable[[T], None], retry: Callable[[], None] | None) -> None:
        self._submit_job(fn, done, retry)

    def _submit_job(self, job: Callable[[], T], done: Callable[[T], None], retry: Callable[[], None] | None) -> None:
        self._begin()

        def ok(result: object) -> None:
            self._end()
            try:
                done(result)                                          # type: ignore[arg-type]
            except Exception:  # noqa: BLE001 - erro de apresentação não pode derrubar a tela
                log.exception("falha ao mostrar o resultado no painel de memória")
                self._show_error("", None, "Não consegui mostrar o resultado. ")

        def fail(message: str) -> None:
            self._end()
            again = retry if retry is not None else ((lambda: self._submit_job(job, done, None)) if is_busy_error(message) else None)
            self._show_error(message, again)

        run_async(job, self, ok, fail)

    def _show_error(self, message: str, retry: Callable[[], None] | None, prefix: str = "") -> None:
        text, _busy = friendly_error(message)
        log.warning("painel de memória: %s", message)
        self._status.show_message(f"Erro: {prefix}{text}", "error", retry=retry)

    def notify(self, text: str, state: str = "ok") -> None:
        self._status.show_message(text, state)

    def changed(self, text: str) -> None:
        """Depois de uma escrita: avisa, marca as abas como desatualizadas e recarrega a que está à vista."""
        self._status.show_message(text, "ok")
        self._dirty = {TAB_MEMORIES, TAB_CONVERSATIONS, TAB_STORAGE}
        self._refresh_current()

    # ------------------------------------------------------------------ abas
    def _sync_all(self) -> None:
        self._memories.sync_enabled()
        self._conversations.sync_enabled()
        self._storage.sync_enabled()

    def _on_tab(self, _index: int) -> None:
        self._refresh_current()

    def _refresh_current(self) -> None:
        index = self._tabs.currentIndex()
        if index not in self._dirty:
            return
        if self.persistent and not self.can_read and self._opening:
            return                                                    # o banco ainda abre; `done` recarrega
        self._dirty.discard(index)
        (self._memories, self._conversations, self._storage)[index].refresh()

    # ------------------------------------------------------------------ escolha de arquivo (isolada para ser trocável)
    def choose_save_path(self, title: str, default_name: str, filters: str, suffixes: tuple[str, ...], default_suffix: str) -> Path | None:
        start = str(default_save_dir() / default_name)
        chosen, _flt = QFileDialog.getSaveFileName(self, title, start, filters)
        if not chosen:
            return None
        return with_suffix_default(chosen, suffixes, default_suffix)


# ============================================================================ uso isolado
_window: MemoryPanel | None = None


def _load_cfg() -> Config:
    try:
        from ..config import load
        return load()
    except (ConfigError, OSError) as exc:
        log.warning("config.toml ilegível; o painel usa os padrões: %s", exc)
        return Config()


def open_memory(cfg: Config | None = None, parent: QWidget | None = None) -> MemoryPanel:
    """Abre (ou traz à frente) o painel como janela própria. Exige um ``QApplication`` ativo."""
    global _window
    if QApplication.instance() is None:
        raise RuntimeError("open_memory precisa de um QApplication; use main_memory() fora da interface")
    existing = _window
    if existing is not None:
        try:
            if existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return existing
        except RuntimeError:
            _window = None
    panel = MemoryPanel(cfg if cfg is not None else _load_cfg(), parent)
    panel.setWindowFlag(Qt.WindowType.Window, True)
    panel.setObjectName("page")                       # janela própria: fundo opaco (embutido, o fundo é transparente)
    panel.setWindowTitle("Jarvis - O que o Jarvis sabe de mim")
    panel.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    panel.resize(1000, 680)
    _window = panel
    panel.show()
    panel.raise_()
    panel.activateWindow()
    return panel


def main_memory() -> int:
    """Executa o painel como programa próprio. Devolve o código de saída."""
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    if owns_app:
        theme.apply_theme(app)           # type: ignore[arg-type]
    try:
        open_memory()
    except Exception:  # noqa: BLE001
        log.exception("não consegui abrir o painel de memória")
        return 1
    return int(app.exec()) if owns_app else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main_memory())
