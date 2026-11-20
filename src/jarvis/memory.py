"""Memória local em SQLite: notas do Bruno e histórico curto de conversa.

Thread-safe (um lock + uma conexão). Nada de segredos: o agente é instruído a não guardar senhas, e
`add_note` recusa textos que pareçam credenciais. Histórico tem teto de linhas (poda automática).
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turns(
    id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL);
"""
SCHEMA_VERSION = "1"
MAX_NOTE_CHARS = 1000
MAX_TURNS_KEPT = 200

_SECRETISH = re.compile(r"(senha|password|passwd|pin|token|api[_ -]?key|cvv|cart[aã]o)\s*(é|e|:|=)?\s*\S+", re.I)


class MemoryError_(RuntimeError):
    pass


@dataclass(frozen=True)
class Note:
    id: int
    created: float
    text: str


class Memory:
    def __init__(self, db_path: Path) -> None:
        self._lock = threading.Lock()
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)
            self._db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema', ?)", (SCHEMA_VERSION,))
            self._db.commit()
        except (sqlite3.Error, OSError) as exc:
            raise MemoryError_(f"não consegui abrir a memória em {db_path}: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            try:
                self._db.close()
            except sqlite3.Error:
                log.exception("erro ao fechar a memória")

    # --------------------------------------------------------------- notas
    def add_note(self, text: str) -> int:
        text = " ".join(text.split())
        if not text:
            raise MemoryError_("nota vazia")
        if len(text) > MAX_NOTE_CHARS:
            raise MemoryError_(f"nota longa demais (máximo {MAX_NOTE_CHARS} caracteres)")
        if _SECRETISH.search(text):
            raise MemoryError_("a nota parece conter senha, PIN ou chave; não guardo isso")
        with self._lock:
            cur = self._db.execute("INSERT INTO notes(created, text) VALUES(?, ?)", (time.time(), text))
            self._db.commit()
            return int(cur.lastrowid)

    def list_notes(self, limit: int = 10, contains: str | None = None) -> list[Note]:
        limit = max(1, min(limit, 50))
        with self._lock:
            if contains:
                like = "%" + contains.replace("%", r"\%").replace("_", r"\_") + "%"
                rows = self._db.execute(
                    "SELECT id, created, text FROM notes WHERE text LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT ?",
                    (like, limit)).fetchall()
            else:
                rows = self._db.execute("SELECT id, created, text FROM notes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [Note(*r) for r in rows]

    # ------------------------------------------------------------ conversa
    def add_turn(self, role: str, content: str) -> None:
        if role not in ("user", "assistant"):
            raise MemoryError_(f"papel inválido: {role}")
        with self._lock:
            self._db.execute("INSERT INTO turns(created, role, content) VALUES(?, ?, ?)", (time.time(), role, content[:4000]))
            self._db.execute("DELETE FROM turns WHERE id <= (SELECT MAX(id) FROM turns) - ?", (MAX_TURNS_KEPT,))
            self._db.commit()

    def recent_turns(self, n: int = 6, max_age_s: float = 1800.0) -> list[dict[str, str]]:
        """Últimas `n` mensagens recentes, em ordem cronológica, no formato do chat da API."""
        n = max(0, min(n, 40))
        if n == 0:
            return []
        since = time.time() - max_age_s
        with self._lock:
            rows = self._db.execute(
                "SELECT role, content FROM turns WHERE created >= ? ORDER BY id DESC LIMIT ?", (since, n)).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def clear_turns(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM turns")
            self._db.commit()
