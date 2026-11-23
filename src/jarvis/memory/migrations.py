"""Migrações versionadas do banco de memória (versão em `meta(key='schema_version')`).

Versões:
  1  esquema ANTIGO (tabelas `notes` e `turns`, `meta.schema='1'`), só reconhecido, nunca criado aqui.
  2  esquema atual: sessions, messages, memories (+ índices). FTS é mantido por `ensure_fts` (idempotente).

Garantias: cada migração roda em UMA transação (`BEGIN IMMEDIATE`); qualquer falha desfaz tudo e levanta
`MemoryError_` com mensagem clara, deixando o banco como estava. Antes de migrar um banco que já tem dados,
é feita uma cópia (API de backup do SQLite) em `<banco>.bak-AAAAMMDD`. Um banco criado por uma versão mais nova
do Eco é recusado (nunca rebaixado).

Contrato de threads: chamado só na abertura, antes de a fachada ser entregue a outras threads.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Callable

from ..core.textutil import fold
from ._db import Database, MemoryError_
from .secrets import looks_secret

log = logging.getLogger(__name__)

__all__ = ["LATEST_VERSION", "migrate", "ensure_fts", "current_version", "LEGACY_CONVERSATION_TITLE"]

LATEST_VERSION = 2
LEGACY_CONVERSATION_TITLE = "Conversa antiga"
_MAX_CONTENT = 20_000

_V2_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        auto_title INTEGER NOT NULL DEFAULT 1 CHECK (auto_title IN (0, 1)),
        created REAL NOT NULL,
        last_active REAL NOT NULL,
        ended REAL,
        state TEXT NOT NULL DEFAULT 'ativa' CHECK (state IN ('ativa', 'encerrada', 'lixeira')),
        token_count INTEGER NOT NULL DEFAULT 0,
        summary TEXT,
        summary_upto_message_id INTEGER,
        deleted_at REAL)""",
    "CREATE UNIQUE INDEX sessions_one_active ON sessions(state) WHERE state = 'ativa'",
    "CREATE INDEX sessions_state_last ON sessions(state, last_active)",
    """CREATE TABLE messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        ts REAL NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
        content TEXT NOT NULL,
        tool_calls_json TEXT,
        tool_call_id TEXT,
        name TEXT,
        untrusted INTEGER NOT NULL DEFAULT 0 CHECK (untrusted IN (0, 1)),
        tokens INTEGER)""",
    "CREATE INDEX messages_session ON messages(session_id, id)",
    "CREATE INDEX messages_ts ON messages(ts)",
    """CREATE TABLE memories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        text_key TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('fato', 'preferencia', 'tarefa', 'nota')),
        pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
        origin TEXT NOT NULL CHECK (origin IN ('usuario', 'modelo', 'externo')),
        confidence REAL NOT NULL DEFAULT 1.0,
        created REAL NOT NULL,
        updated REAL NOT NULL,
        expires_at REAL,
        deleted_at REAL)""",
    "CREATE UNIQUE INDEX memories_live_key ON memories(text_key) WHERE deleted_at IS NULL",
    "CREATE INDEX memories_kind ON memories(kind, deleted_at)",
)

_FTS_DDL: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("memories_fts", (
        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, content='memories', content_rowid='id',"
        " tokenize='unicode61 remove_diacritics 2')",
        "CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN"
        " INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text); END",
        "CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN"
        " INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text); END",
        "CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF text ON memories BEGIN"
        " INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text);"
        " INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text); END",
    )),
    ("messages_fts", (
        "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, content='messages', content_rowid='id',"
        " tokenize='unicode61 remove_diacritics 2')",
        "CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages WHEN new.role IN ('user', 'assistant') BEGIN"
        " INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END",
        "CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages WHEN old.role IN ('user', 'assistant') BEGIN"
        " INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content); END",
        "CREATE TRIGGER IF NOT EXISTS messages_au_del AFTER UPDATE OF content, role ON messages"
        " WHEN old.role IN ('user', 'assistant') BEGIN"
        " INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content); END",
        "CREATE TRIGGER IF NOT EXISTS messages_au_ins AFTER UPDATE OF content, role ON messages"
        " WHEN new.role IN ('user', 'assistant') BEGIN"
        " INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END",
    )),
    ("sessions_fts", (
        "CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(title, summary, content='sessions', content_rowid='id',"
        " tokenize='unicode61 remove_diacritics 2')",
        "CREATE TRIGGER IF NOT EXISTS sessions_ai AFTER INSERT ON sessions BEGIN"
        " INSERT INTO sessions_fts(rowid, title, summary) VALUES (new.id, new.title, new.summary); END",
        "CREATE TRIGGER IF NOT EXISTS sessions_ad AFTER DELETE ON sessions BEGIN"
        " INSERT INTO sessions_fts(sessions_fts, rowid, title, summary) VALUES ('delete', old.id, old.title, old.summary); END",
        "CREATE TRIGGER IF NOT EXISTS sessions_au AFTER UPDATE OF title, summary ON sessions BEGIN"
        " INSERT INTO sessions_fts(sessions_fts, rowid, title, summary) VALUES ('delete', old.id, old.title, old.summary);"
        " INSERT INTO sessions_fts(rowid, title, summary) VALUES (new.id, new.title, new.summary); END",
    )),
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def current_version(conn: sqlite3.Connection) -> int:
    """0 = banco vazio; 1 = esquema antigo; N = `meta.schema_version`."""
    if _table_exists(conn, "meta"):
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is not None:
            try:
                return int(row[0])
            except (TypeError, ValueError) as exc:
                raise MemoryError_(f"schema_version ilegível no banco ({row[0]!r}); não vou mexer nele") from exc
        legacy = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if legacy is not None:
            return 1
    if _table_exists(conn, "notes") or _table_exists(conn, "turns"):
        return 1
    return 0


def _has_data(conn: sqlite3.Connection, version: int) -> bool:
    if version == 0:
        return False
    if version == 1:
        total = 0
        for table in ("notes", "turns"):
            if _table_exists(conn, table):
                total += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])   # nome fixo, não vem de fora
        return total > 0
    return True


def _backup_file(conn: sqlite3.Connection, db_path: Path) -> Path:
    """Cópia consistente (API de backup) em `<banco>.bak-AAAAMMDD` (com -HHMMSS se já existir)."""
    dest = db_path.with_name(f"{db_path.name}.bak-{time.strftime('%Y%m%d')}")
    if dest.exists():
        dest = db_path.with_name(f"{db_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".tmp")
    os.close(fd)
    try:
        target = sqlite3.connect(tmp)
        try:
            conn.backup(target)
        finally:
            target.close()
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return dest


# ------------------------------------------------------------------ migrações
def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 2) // 3)


def _m2_new_schema(conn: sqlite3.Connection) -> None:
    """Cria o esquema atual e, se houver o antigo, copia notes -> memories e turns -> sessão arquivada; só então apaga o antigo."""
    for ddl in _V2_DDL:
        conn.execute(ddl)
    suspicious = 0
    if _table_exists(conn, "notes"):
        rows = conn.execute("SELECT created, text FROM notes ORDER BY id").fetchall()
        for created, text in rows:
            clean = " ".join(str(text).split())
            if not clean:
                continue
            if looks_secret(clean):
                suspicious += 1
            conn.execute(
                "INSERT OR IGNORE INTO memories(text, text_key, kind, pinned, origin, confidence, created, updated)"
                " VALUES (?, ?, 'nota', 0, 'usuario', 1.0, ?, ?)", (clean, fold(clean), float(created), float(created)))
        conn.execute("DROP TABLE notes")
        log.info("migração: %d nota(s) antiga(s) viraram memórias de longo prazo", len(rows))
    if _table_exists(conn, "turns"):
        rows = conn.execute("SELECT created, role, content FROM turns WHERE role IN ('user', 'assistant') ORDER BY id").fetchall()
        if rows:
            first, last = float(rows[0][0]), max(float(r[0]) for r in rows)
            cur = conn.execute(
                "INSERT INTO sessions(title, auto_title, created, last_active, ended, state, token_count)"
                " VALUES (?, 0, ?, ?, ?, 'encerrada', 0)", (LEGACY_CONVERSATION_TITLE, first, last, last))
            sid = int(cur.lastrowid)
            tokens = 0
            redacted = 0
            for created, role, content in rows:
                text = str(content)[:_MAX_CONTENT]
                if looks_secret(text):
                    text = "[conteúdo omitido: parecia conter credenciais]"
                    redacted += 1
                n = _estimate_tokens(text)
                tokens += n
                conn.execute("INSERT INTO messages(session_id, ts, role, content, tokens) VALUES (?, ?, ?, ?, ?)",
                             (sid, float(created), role, text, n))
            copied = int(conn.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (sid,)).fetchone()[0])
            if copied != len(rows):
                raise MemoryError_(f"conferência falhou: copiei {copied} de {len(rows)} mensagens antigas")
            conn.execute("UPDATE sessions SET token_count=? WHERE id=?", (tokens, sid))
            log.info("migração: %d mensagem(ns) antiga(s) viraram a sessão %r (%d com credenciais omitidas)",
                     copied, LEGACY_CONVERSATION_TITLE, redacted)
        conn.execute("DROP TABLE turns")
    if suspicious:
        log.warning("migração: %d nota(s) antiga(s) parecem conter credenciais; foram mantidas (não perco dados do usuário), "
                    "revise e apague com 'esquecer'", suspicious)
    conn.execute("DELETE FROM meta WHERE key='schema'")


_MIGRATIONS: tuple[tuple[int, Callable[[sqlite3.Connection], None]], ...] = ((2, _m2_new_schema),)


def migrate(db: Database) -> int:
    """Leva o banco até `LATEST_VERSION`. Devolve a versão final. Levanta MemoryError_ (banco intacto) se falhar."""
    with db.read() as conn:
        version = current_version(conn)
        needs_backup = version < LATEST_VERSION and _has_data(conn, version)
    if version > LATEST_VERSION:
        raise MemoryError_(f"o banco de memória é da versão {version}, mais nova que esta ({LATEST_VERSION}); "
                           "atualize o Eco. Não alterei nada.")
    if version == LATEST_VERSION:
        return version
    backup: Path | None = None
    if needs_backup and db.path is not None:
        try:
            with db.lock:
                backup = _backup_file(db.conn, db.path)
            log.info("cópia de segurança do banco antes de migrar: %s", backup)
        except (sqlite3.Error, OSError) as exc:
            raise MemoryError_(f"não consegui fazer a cópia de segurança antes de migrar ({exc}); "
                               "não alterei o banco") from exc
    for target, fn in _MIGRATIONS:
        if target <= version:
            continue
        try:
            with db.tx() as conn:
                fn(conn)
                conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)"
                             " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(target),))
        except MemoryError_ as exc:
            raise MemoryError_(f"a migração do banco para a versão {target} falhou e foi desfeita "
                               f"(banco intacto{'; cópia em ' + str(backup) if backup else ''}): {exc}") from exc
        log.info("banco de memória migrado para a versão %d", target)
        version = target
    return version


def ensure_fts(db: Database) -> bool:
    """Cria (se faltar) as tabelas FTS5 e seus triggers, reindexando o que já existe. Idempotente.
    Devolve True e marca `db.fts_ready` se a busca FTS5 está disponível; senão a busca cai para LIKE."""
    db.fts_ready = False
    if not db.fts5:
        return False
    try:
        for name, statements in _FTS_DDL:
            if db.has_table(name):
                continue
            with db.tx() as conn:
                for stmt in statements:
                    conn.execute(stmt)
                if name == "messages_fts":
                    # só falas (user/assistant) entram no índice, igual aos triggers; 'rebuild' indexaria também as de ferramenta
                    conn.execute("INSERT INTO messages_fts(rowid, content) SELECT id, content FROM messages "
                                 "WHERE role IN ('user', 'assistant')")
                else:
                    conn.execute(f"INSERT INTO {name}({name}) VALUES ('rebuild')")  # nome fixo, não vem de fora
            log.info("índice de busca %s criado e preenchido", name)
    except MemoryError_:
        log.exception("não consegui preparar o índice FTS5; a busca usará LIKE")
        return False
    db.fts_ready = True
    return True
