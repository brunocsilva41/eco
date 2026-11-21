"""Acesso ao banco do painel (sem Qt). Tudo aqui roda numa thread (``ui.kit.tasks.run_async``), nunca na da interface.

``ConnectionHolder`` é dono da única conexão ``Memory`` do painel e a fecha uma só vez, mesmo se o painel for
destruído enquanto o banco ainda abre. As funções ``load_*`` e ``delete_*`` recebem um ``Memory`` e devolvem dados.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ...config import MemoryCfg
from ...memory import Hit, Memory, MemoryError_, MemoryItem, Message, Session

log = logging.getLogger(__name__)

DB_NAME: Final = "jarvis.db"
MAX_SESSIONS_LISTED: Final = 2000
MAX_MEMORIES_LISTED: Final = 5000
MAX_MESSAGES_SHOWN: Final = 300
SEARCH_LIMIT: Final = 50
PAGE: Final = 200


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


@dataclass(frozen=True, slots=True)
class ConversationData:
    session: Session
    messages: list[Message]            # no máximo MAX_MESSAGES_SHOWN (as primeiras)
    total_messages: int
    summary: str | None


class ConnectionHolder:
    """Guarda o ``Memory`` aberto e o fecha uma única vez. Independente de widgets (serve de alvo do ``destroyed``)."""

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


def open_database(holder: ConnectionHolder, path: Path, cfg: MemoryCfg) -> bool:
    """Abre ``Memory`` (migra e faz a manutenção) e entrega ao ``holder``. Devolve ``Memory.persistent``."""
    mem = Memory(path, cfg)
    holder.adopt(mem)
    return bool(mem.persistent)


def load_memories(mem: Memory, query: str, kind: str | None) -> MemoryList:
    """Sem busca: todas (inclusive expiradas, marcadas). Com busca: top-50 por relevância (as expiradas não entram)."""
    q = query.strip()
    if q:
        items = mem.longterm.search(q, k=SEARCH_LIMIT)
        if kind is not None:
            items = [i for i in items if i.kind == kind]
    else:
        items = mem.longterm.list(kind=kind, limit=MAX_MEMORIES_LISTED, include_expired=True)
    return MemoryList(items, mem.longterm.count(include_expired=True), len(mem.longterm.pinned()))


def all_sessions(mem: Memory, state: str | None, query: str | None = None) -> list[Session]:
    out: list[Session] = []
    offset = 0
    while len(out) < MAX_SESSIONS_LISTED:
        page = mem.sessions.list(limit=PAGE, offset=offset, state=state, query=query)
        out += page
        if len(page) < PAGE:
            break
        offset += PAGE
    return out


def load_session_rows(mem: Memory, state: str | None, query: str = "") -> list[SessionRow]:
    """``state``: None (ativa e encerradas), 'ativa', 'encerrada' ou 'lixeira'. ``query`` filtra por título e resumo."""
    return [SessionRow(s, mem.sessions.count_messages(s.id)) for s in all_sessions(mem, state, query.strip() or None)]


def search_conversations(mem: Memory, query: str) -> list[Hit]:
    return mem.search.search(query.strip(), limit=SEARCH_LIMIT)


def load_conversation(mem: Memory, session_id: int) -> ConversationData | None:
    """A conversa, as primeiras mensagens e o resumo. ``None`` se outro programa a apagou."""
    session = mem.sessions.get(session_id)
    if session is None:
        return None
    total = mem.sessions.count_messages(session_id)
    messages = mem.sessions.messages(session_id, limit=MAX_MESSAGES_SHOWN)
    summary = mem.sessions.get_summary(session_id)
    return ConversationData(session, messages, total, summary[0] if summary else None)


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
    live = all_sessions(mem, None)
    trashed = all_sessions(mem, "lixeira")
    messages = sum(mem.sessions.count_messages(s.id) for s in live + trashed)
    return Stats(mem.longterm.count(include_expired=True), len(mem.longterm.pinned()), len(live), len(trashed),
                 messages, file_size_bytes(path))


def delete_all_sessions(mem: Memory) -> int:
    """Apaga DEFINITIVAMENTE todas as conversas (inclusive a lixeira). Irreversível. Devolve quantas."""
    ids = [s.id for s in all_sessions(mem, None)] + [s.id for s in all_sessions(mem, "lixeira")]
    for sid in ids:
        mem.sessions.delete(sid, to_trash=False)
    log.info("todas as conversas foram apagadas pelo painel (%d)", len(ids))
    return len(ids)


def delete_memory_for_good(mem: Memory, memory_id: int) -> None:
    """Apaga a memória e esvazia a lixeira de memórias (memórias não são restauráveis: não deixa cópia escondida)."""
    mem.longterm.forget(memory_id)
    mem.longterm.empty_trash(None)
