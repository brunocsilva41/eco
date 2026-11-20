"""Peças do painel "O que o Jarvis sabe de mim": lógica pura (sem Qt), diálogos e o visualizador de conversas.

Separação: tudo o que fala com o banco (``load_*``, ``delete_all_sessions``...) são funções PURAS que recebem um
``Memory`` e devolvem dados; elas rodam numa thread (``run_async``), nunca na da interface. Os diálogos só coletam
uma decisão do usuário. Nada aqui grava segredo, usa ``print`` ou abre o banco por conta própria.
"""
from __future__ import annotations

import html
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QTextBrowser, QVBoxLayout, QWidget)

from ..memory import Hit, Memory, MemoryError_, MemoryItem, Message, Session, looks_secret
from ..memory.longterm import KINDS, MAX_CHARS, LongTermMemory
from ..memory.sessions import OMITTED
from . import theme

log = logging.getLogger(__name__)

CONFIRM_WORD: Final = "APAGAR"
MAX_SESSIONS_LISTED: Final = 2000
MAX_VIEW_CHARS: Final = 6000
SEARCH_LIMIT: Final = 50

KIND_LABELS: Final[dict[str, str]] = {"fato": "Fato", "preferencia": "Preferência", "tarefa": "Tarefa", "nota": "Nota"}
ORIGIN_LABELS: Final[dict[str, str]] = {"usuario": "Você", "modelo": "Veio do modelo", "externo": "Veio de conteúdo externo"}
ORIGIN_NOTES: Final[dict[str, str]] = {
    "usuario": "Você mesmo pediu para guardar isto.",
    "modelo": "Veio do modelo: o Jarvis propôs guardar isto. Ele só trata o texto como dado, nunca como ordem.",
    "externo": "Veio de conteúdo externo (página, arquivo, tela...). Confira antes de confiar: o Jarvis só o trata como dado, nunca como ordem.",
}
STATE_LABELS: Final[dict[str, str]] = {"ativa": "Ativa", "encerrada": "Encerrada", "lixeira": "Na lixeira"}
ROLE_LABELS: Final[dict[str, str]] = {"user": "Você", "assistant": "Jarvis", "tool": "Ferramenta", "system": "Sistema"}


# ============================================================================ formatação e erros (puro)
def fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "-"
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return "-"


def fmt_mb(size_bytes: int) -> str:
    """'12,34 MB' (vírgula decimal)."""
    return f"{size_bytes / (1024 * 1024):.2f}".replace(".", ",") + " MB"


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def trash_days_left(deleted_at: float | None, trash_days: float, now: float | None = None) -> int:
    """Dias inteiros (arredondados para cima) que faltam para a lixeira apagar a conversa; 0 = na próxima limpeza."""
    if deleted_at is None:
        return 0
    elapsed = ((now if now is not None else time.time()) - deleted_at) / 86400
    return max(0, math.ceil(trash_days - elapsed))


def session_state_text(s: Session, trash_days: float, now: float | None = None) -> str:
    if s.state == "lixeira":
        left = trash_days_left(s.deleted_at, trash_days, now)
        if left <= 0:
            return "Na lixeira (será apagada na próxima limpeza)"
        return f"Na lixeira (restam {plural(left, 'dia', 'dias')})"
    return STATE_LABELS.get(s.state, s.state)


_LOCK_WORDS: Final = ("locked", "ocupado", "busy", "indisponível")


def is_busy_error(message: str) -> bool:
    low = message.lower()
    return any(w in low for w in _LOCK_WORDS)


def friendly_error(message: str) -> tuple[str, bool]:
    """(mensagem em pt-BR para mostrar, vale 'tentar de novo'?). Nunca devolve traceback nem texto vazio."""
    text = " ".join((message or "").split())
    if is_busy_error(text):
        return ("O banco de memória está ocupado (o Jarvis pode estar gravando agora). Nada foi perdido. "
                "Espere um instante e use 'Tentar de novo'."), True
    if not text:
        return "Algo deu errado e não consegui concluir. Veja o log do Jarvis para detalhes.", False
    return text if len(text) <= 400 else text[:399] + "…", False


# ============================================================================ acesso ao banco (roda em thread)
@dataclass(frozen=True, slots=True)
class MemoryList:
    items: list[MemoryItem]
    total: int                         # memórias vivas no banco (sem filtro)
    pinned: int


@dataclass(frozen=True, slots=True)
class SessionRow:
    session: Session
    messages: int


@dataclass(frozen=True, slots=True)
class Stats:
    memories: int
    pinned: int
    sessions: int                      # fora da lixeira
    trashed: int
    messages: int
    size_bytes: int


def load_memories(mem: Memory, query: str, kind: str | None) -> MemoryList:
    """Sem busca: todas (inclusive expiradas, marcadas). Com busca: top-50 por relevância (as expiradas não entram)."""
    q = query.strip()
    if q:
        items = mem.longterm.search(q, k=SEARCH_LIMIT)
        if kind is not None:
            items = [i for i in items if i.kind == kind]
    else:
        items = mem.longterm.list(kind=kind, limit=5000, include_expired=True)
    return MemoryList(items, mem.longterm.count(include_expired=True), len(mem.longterm.pinned()))


def _all_sessions(mem: Memory, state: str | None, query: str | None = None) -> list[Session]:
    out: list[Session] = []
    offset = 0
    while len(out) < MAX_SESSIONS_LISTED:
        page = mem.sessions.list(limit=200, offset=offset, state=state, query=query)
        out += page
        if len(page) < 200:
            break
        offset += 200
    return out


def load_session_rows(mem: Memory, state: str | None, query: str = "") -> list[SessionRow]:
    """`state`: None (ativa+encerrada), 'ativa', 'encerrada' ou 'lixeira'. `query` filtra por título/resumo."""
    return [SessionRow(s, mem.sessions.count_messages(s.id)) for s in _all_sessions(mem, state, query.strip() or None)]


def search_conversations(mem: Memory, query: str) -> list[Hit]:
    return mem.search.search(query.strip(), limit=SEARCH_LIMIT)


def file_size_bytes(path: Path | None) -> int:
    """Tamanho do arquivo do banco somado ao do WAL (o que ainda não foi para o arquivo principal). 0 se não existir."""
    if path is None:
        return 0
    total = 0
    for p in (path, path.with_name(path.name + "-wal")):
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return total


def load_stats(mem: Memory, path: Path | None) -> Stats:
    live = _all_sessions(mem, None)
    trashed = _all_sessions(mem, "lixeira")
    messages = sum(mem.sessions.count_messages(s.id) for s in live + trashed)
    return Stats(mem.longterm.count(include_expired=True), len(mem.longterm.pinned()), len(live), len(trashed),
                 messages, file_size_bytes(path))


def delete_all_sessions(mem: Memory) -> int:
    """Apaga DEFINITIVAMENTE todas as conversas (inclusive a lixeira). Irreversível. Devolve quantas."""
    ids = [s.id for s in _all_sessions(mem, None)] + [s.id for s in _all_sessions(mem, "lixeira")]
    for sid in ids:
        mem.sessions.delete(sid, to_trash=False)
    log.info("todas as conversas foram apagadas pelo painel (%d)", len(ids))
    return len(ids)


def delete_memory_for_good(mem: Memory, memory_id: int) -> None:
    """Apaga a memória e esvazia a lixeira de memórias (não há como restaurar memórias, então não deixa cópia escondida)."""
    mem.longterm.forget(memory_id)
    mem.longterm.empty_trash(None)


# ============================================================================ estilo
def build_panel_stylesheet() -> str:
    """Estilos do painel que o tema geral não cobre (abas, visualizador). Sempre acrescentado ao tema."""
    return f"""
QTabWidget::pane {{ border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS_MD}px; top: -1px; background: {theme.BG}; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: {theme.SURFACE}; color: {theme.TEXT}; border: 1px solid {theme.BORDER}; border-bottom: none;
               padding: {theme.SP1}px {theme.SP2}px; margin-right: 2px;
               border-top-left-radius: {theme.RADIUS_SM}px; border-top-right-radius: {theme.RADIUS_SM}px; }}
QTabBar::tab:selected {{ background: {theme.SURFACE_ALT}; border-color: {theme.ACCENT}; font-weight: 600; }}
QTabBar::tab:hover {{ border-color: {theme.ACCENT_HOVER}; }}
QTabBar::tab:focus {{ border: 2px solid {theme.ACCENT_HOVER}; border-bottom: none; }}
QTextBrowser {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS_MD}px; padding: {theme.SP1}px; }}
QTextBrowser:focus {{ border: 2px solid {theme.ACCENT_HOVER}; }}
QPlainTextEdit {{ background: {theme.SURFACE_ALT}; }}
QDialog QFrame#card {{ background: {theme.SURFACE}; }}
"""


def full_stylesheet() -> str:
    return theme.build_stylesheet() + theme.build_settings_stylesheet() + build_panel_stylesheet()


# ============================================================================ faixa de estado
class StatusBanner(QFrame):
    """Faixa de aviso com texto (ok/warn/error) e botões opcionais. O estado aparece no TEXTO e na borda."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.setObjectName("banner")
        self.setAccessibleName(name)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setAccessibleName(name)
        self._retry = QPushButton("Tentar de novo")
        self._retry.setVisible(False)
        self._close = QPushButton("Fechar aviso")
        self._close.setProperty("variant", "ghost")
        self._retry_cb: Callable[[], None] | None = None
        self._dismissable = True
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SP2, theme.SP1, theme.SP2, theme.SP1)
        lay.setSpacing(theme.SP1)
        lay.addWidget(self._label, 1)
        lay.addWidget(self._retry)
        lay.addWidget(self._close)
        self._retry.clicked.connect(self._on_retry)
        self._close.clicked.connect(self.clear)
        self.setVisible(False)

    def show_message(self, text: str, state: str = "ok", retry: Callable[[], None] | None = None,
                     dismissable: bool = True) -> None:
        self._label.setText(text)
        self._retry_cb = retry
        self._retry.setVisible(retry is not None)
        self._close.setVisible(dismissable)
        self.setProperty("state", state)
        theme.repolish(self)
        self.setVisible(True)

    def clear(self) -> None:
        self._retry_cb = None
        self.setVisible(False)

    def text(self) -> str:
        return self._label.text()

    def _on_retry(self) -> None:
        cb = self._retry_cb
        self.clear()
        if cb is not None:
            cb()


# ============================================================================ diálogos simples
def ask(parent: QWidget, title: str, text: str, yes: str, no: str = "Cancelar", destructive: bool = False) -> bool:
    """Pergunta Sim/Não. O padrão (Enter) e o Esc são 'não'. O texto é SEMPRE puro (memória pode conter '<b>' etc.)."""
    box = QMessageBox(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question, title, text, parent=parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    yes_btn = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    no_btn = box.addButton(no, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(no_btn)
    box.setEscapeButton(no_btn)
    box.exec()
    return box.clickedButton() is yes_btn


def inform(parent: QWidget, title: str, text: str) -> None:
    box = QMessageBox(QMessageBox.Icon.Information, title, text, parent=parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.addButton("Entendi", QMessageBox.ButtonRole.AcceptRole)
    box.exec()


class TypedConfirmDialog(QDialog):
    """Confirmação forte: o botão só habilita depois de digitar a palavra (ex.: APAGAR). Cancelar é o padrão."""

    def __init__(self, parent: QWidget, title: str, message: str, action: str, word: str = CONFIRM_WORD) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._word = word
        self.setMinimumWidth(460)
        text = QLabel(message)
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.PlainText)
        prompt = QLabel(f"Para confirmar, digite {word} (em maiúsculas ou minúsculas):")
        prompt.setWordWrap(True)
        self._edit = QLineEdit()
        self._edit.setAccessibleName(f"Digite {word} para confirmar")
        self._edit.setPlaceholderText(word)
        prompt.setBuddy(self._edit)
        self._cancel = QPushButton("Cancelar")
        self._ok = QPushButton(action)
        self._ok.setProperty("variant", "danger")
        self._ok.setEnabled(False)
        self._cancel.setDefault(True)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._cancel)
        row.addWidget(self._ok)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP3, theme.SP3, theme.SP3, theme.SP2)
        lay.setSpacing(theme.SP2)
        lay.addWidget(text)
        lay.addWidget(prompt)
        lay.addWidget(self._edit)
        lay.addLayout(row)
        self._edit.textChanged.connect(self._on_text)
        self._ok.clicked.connect(self.accept)
        self._cancel.clicked.connect(self.reject)
        self.setTabOrder(self._edit, self._cancel)
        self.setTabOrder(self._cancel, self._ok)
        self._edit.setFocus()

    def _on_text(self, value: str) -> None:
        self._ok.setEnabled(value.strip().casefold() == self._word.casefold())


def confirm_typed(parent: QWidget, title: str, message: str, action: str, word: str = CONFIRM_WORD) -> bool:
    return TypedConfirmDialog(parent, title, message, action, word).exec() == QDialog.DialogCode.Accepted


# ============================================================================ adicionar / editar memória
@dataclass(frozen=True, slots=True)
class NewMemory:
    text: str
    kind: str
    pinned: bool
    expires_days: int | None


class MemoryEditDialog(QDialog):
    """Texto (3 a 1000 caracteres, sem segredos). No modo 'novo' também pede tipo, fixar e validade."""

    def __init__(self, parent: QWidget, *, new: bool, text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Adicionar memória" if new else "Editar memória")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._result: NewMemory | None = None
        label = QLabel("&Texto da memória:")
        self._text = QPlainTextEdit()
        self._text.setPlainText(text)
        self._text.setTabChangesFocus(True)
        self._text.setMinimumHeight(110)
        self._text.setAccessibleName("Texto da memória")
        label.setBuddy(self._text)
        self._count = QLabel("")
        self._count.setProperty("role", "muted")
        self._error = QLabel("")
        self._error.setProperty("state", "error")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        self._error.setAccessibleName("Erro da memória")
        self._kind = QComboBox()
        self._pin = QCheckBox("&Fixar (entra sempre na conversa)")
        self._expires = QCheckBox("E&xpira depois de")
        self._days = QSpinBox()
        self._days.setRange(1, 3650)
        self._days.setValue(30)
        self._days.setSuffix(" dias")
        self._days.setEnabled(False)
        self._days.setAccessibleName("Dias até expirar")
        form = QVBoxLayout()
        if new:
            kind_label = QLabel("T&ipo:")
            for k in KINDS:
                self._kind.addItem(KIND_LABELS[k], k)
            kind_label.setBuddy(self._kind)
            self._kind.setAccessibleName("Tipo da memória")
            krow = QHBoxLayout()
            krow.addWidget(kind_label)
            krow.addWidget(self._kind, 1)
            exp_row = QHBoxLayout()
            exp_row.addWidget(self._expires)
            exp_row.addWidget(self._days)
            exp_row.addStretch(1)
            form.addLayout(krow)
            form.addWidget(self._pin)
            form.addLayout(exp_row)
        else:
            for w in (self._kind, self._pin, self._expires, self._days):
                w.setVisible(False)
        self._cancel = QPushButton("Cancelar")
        self._ok = QPushButton("Guardar" if new else "Salvar")
        self._ok.setProperty("variant", "primary")
        self._ok.setDefault(True)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._cancel)
        row.addWidget(self._ok)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP3, theme.SP3, theme.SP3, theme.SP2)
        lay.setSpacing(theme.SP1)
        lay.addWidget(label)
        lay.addWidget(self._text)
        lay.addWidget(self._count)
        lay.addWidget(self._error)
        lay.addLayout(form)
        lay.addLayout(row)
        self._expires.toggled.connect(self._days.setEnabled)
        self._text.textChanged.connect(self._on_text)
        self._ok.clicked.connect(self._submit)
        self._cancel.clicked.connect(self.reject)
        self._new = new
        self._on_text()
        self._text.setFocus()

    def _on_text(self) -> None:
        n = len(" ".join(self._text.toPlainText().split()))
        self._count.setText(f"{n} de {MAX_CHARS} caracteres")
        self._error.setVisible(False)

    def _submit(self) -> None:
        raw = self._text.toPlainText()
        try:
            clean = LongTermMemory.validate_text(raw)
        except MemoryError_ as exc:
            self._error.setText(f"Erro: {exc}.")
            self._error.setVisible(True)
            self._text.setFocus()
            return
        days = int(self._days.value()) if (self._new and self._expires.isChecked()) else None
        self._result = NewMemory(clean, str(self._kind.currentData() or "nota"), self._pin.isChecked(), days)
        self.accept()

    def result_value(self) -> NewMemory | None:
        return self._result


# ============================================================================ visualizador de conversa (somente leitura)
def _message_label(m: Message) -> tuple[str, bool]:
    """(rótulo, é 'dado de fora'?). Ferramenta e conteúdo marcado como não confiável são sempre 'dado de fora'."""
    outside = m.role == "tool" or m.untrusted
    base = ROLE_LABELS.get(m.role, m.role)
    if m.role == "tool":
        return f"Dado de fora - ferramenta{(' ' + m.name) if m.name else ''}", True
    if outside:
        return f"Dado de fora - {base}", True
    return base, False


def _called_tools(m: Message) -> list[str]:
    names: list[str] = []
    for call in m.tool_calls or []:
        fn = call.get("function") if isinstance(call, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str) and name:
            names.append(name)
    return names


def render_conversation_html(session: Session, messages: list[Message], summary: str | None) -> str:
    """HTML (todo o texto do banco é escapado) para o QTextBrowser. Sem links, sem imagens, sem scripts."""
    e = html.escape
    parts: list[str] = [f'<body style="color:{theme.TEXT};">']
    if summary:
        parts.append(f'<table width="100%" cellpadding="8" cellspacing="0" bgcolor="{theme.SURFACE_ALT}"><tr><td>'
                     f'<b>Resumo desta conversa</b><br><span style="white-space:pre-wrap">{e(summary)}</span></td></tr></table><br>')
    if any(_message_label(m)[1] for m in messages):
        parts.append(f'<p style="color:{theme.WARN}"><b>Aviso:</b> trechos marcados como <b>Dado de fora</b> vieram de '
                     "ferramentas, páginas ou arquivos. O Jarvis os trata só como informação, nunca como ordem.</p>")
    if not messages:
        parts.append(f'<p style="color:{theme.TEXT_MUTED}">Esta conversa ainda não tem mensagens.</p>')
    for m in messages:
        label, outside = _message_label(m)
        content = m.content
        if (outside or m.role == "system") and looks_secret(content):
            content = OMITTED
        cut = len(content) > MAX_VIEW_CHARS
        if cut:
            content = content[:MAX_VIEW_CHARS]
        bg = theme.SURFACE_ALT if outside else theme.SURFACE
        head_color = theme.WARN if outside else theme.ACCENT_HOVER
        body = f'<span style="white-space:pre-wrap">{e(content)}</span>' if content else f'<i style="color:{theme.TEXT_MUTED}">(sem texto)</i>'
        if outside:
            body = f"<i>{body}</i>"
        extra = ""
        tools = _called_tools(m)
        if tools:
            extra += f'<br><span style="color:{theme.TEXT_MUTED}">Pediu para usar: {e(", ".join(tools))}</span>'
        if cut:
            extra += (f'<br><span style="color:{theme.TEXT_MUTED}">(texto cortado na tela; '
                      "a exportação traz a mensagem inteira)</span>")
        parts.append(f'<table width="100%" cellpadding="8" cellspacing="0" bgcolor="{bg}"><tr><td>'
                     f'<b style="color:{head_color}">{e(label)}</b> '
                     f'<span style="color:{theme.TEXT_MUTED}">- {e(fmt_ts(m.ts))}</span><br>{body}{extra}</td></tr></table>'
                     '<div style="font-size:4pt">&nbsp;</div>')
    parts.append("</body>")
    return "".join(parts)


class ConversationViewer(QDialog):
    """Visualizador SOMENTE LEITURA. Os botões apenas pedem ações ao painel (sinais); aqui nada é alterado."""

    resume_requested = Signal(int)
    export_requested = Signal(int)

    def __init__(self, parent: QWidget, session: Session, messages: list[Message], summary: str | None,
                 trash_days: float) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle(f"Conversa: {session.title}")
        self.setModal(True)
        self.resize(760, 600)
        title = QLabel(session.title)
        title.setProperty("role", "section")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setAccessibleName("Título da conversa")
        info = QLabel(f"Somente leitura  |  {session_state_text(session, trash_days)}  |  Última atividade: "
                      f"{fmt_ts(session.last_active)}  |  {plural(len(messages), 'mensagem', 'mensagens')}")
        info.setProperty("role", "muted")
        info.setWordWrap(True)
        self._view = QTextBrowser()
        self._view.setReadOnly(True)
        self._view.setOpenLinks(False)
        self._view.setOpenExternalLinks(False)
        self._view.setAccessibleName("Mensagens da conversa (somente leitura)")
        self._view.setHtml(render_conversation_html(session, messages, summary))
        self._resume = QPushButton("&Retomar esta conversa")
        self._resume.setProperty("variant", "primary")
        if session.state == "lixeira":
            self._resume.setEnabled(False)
            self._resume.setToolTip("Restaure a conversa da lixeira antes de retomar.")
        elif session.state == "ativa":
            self._resume.setEnabled(False)
            self._resume.setToolTip("Esta já é a conversa ativa.")
        self._export = QPushButton("&Exportar...")
        self._close = QPushButton("&Fechar")
        row = QHBoxLayout()
        row.addWidget(self._resume)
        row.addWidget(self._export)
        row.addStretch(1)
        row.addWidget(self._close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP3, theme.SP3, theme.SP3, theme.SP2)
        lay.setSpacing(theme.SP1)
        lay.addWidget(title)
        lay.addWidget(info)
        lay.addWidget(self._view, 1)
        lay.addLayout(row)
        self._resume.clicked.connect(lambda: self.resume_requested.emit(self.session.id))
        self._export.clicked.connect(lambda: self.export_requested.emit(self.session.id))
        self._close.clicked.connect(self.accept)
        self.setTabOrder(self._view, self._resume)
        self.setTabOrder(self._resume, self._export)
        self.setTabOrder(self._export, self._close)
        self._view.setFocus()


def default_save_dir() -> Path:
    docs = Path.home() / "Documents"
    try:
        return docs if docs.is_dir() else Path.home()
    except OSError:
        return Path.home()


def safe_file_stem(text: str, fallback: str = "conversa") -> str:
    """Nome de arquivo seguro (sem caracteres proibidos no Windows) a partir de um título."""
    keep = "".join(ch if (ch.isalnum() or ch in " -_") else " " for ch in text)
    stem = "-".join(keep.split())[:60].strip("-_.")
    return stem or fallback


def with_suffix_default(path: str | os.PathLike[str], allowed: tuple[str, ...], default: str) -> Path:
    """Acrescenta a extensão padrão se o usuário não digitou nenhuma das permitidas."""
    p = Path(path)
    return p if p.suffix.lower() in allowed else p.with_name(p.name + default)
