"""Infraestrutura interna do pacote de memória: conexão SQLite única, trava, transações e utilidades de FTS.

Contrato de threads: UMA conexão (`check_same_thread=False`) protegida por UM `RLock` (`Database.lock`).
Toda operação das camadas (`SessionStore`, `LongTermMemory`, `ConversationSearch`) entra por `tx()` (escrita,
transação explícita `BEGIN IMMEDIATE`) ou `read()` (leitura). As duas seguram o lock, então são seguras entre
threads; chamadas aninhadas na mesma thread entram na transação externa (sem savepoint: se algo falhar,
tudo volta). Quem captura `MemoryError_` DENTRO de um `tx()` e continua deve saber que o banco pode ter
efeitos parciais daquele bloco: prefira deixar a exceção subir.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Iterator

from ..core.textutil import fold, words

log = logging.getLogger(__name__)

__all__ = ["MemoryError_", "Database", "atomic_write", "fts_terms", "fts_match", "like_escape"]


class MemoryError_(RuntimeError):
    """Erro de memória com mensagem em português, segura para mostrar/falar ao Bruno."""


_STOP = frozenset("""a o as os um uma uns umas de da do das dos em no na nos nas por para pra com sem que e eh ou se
me te lhe eu tu ele ela nos voce voces meu minha meus minhas teu sua seu suas ao aos pelo pela pelos pelas isso isto
esse essa esses essas este esta estes estas aquele aquela qual quais como mais muito foi ser sao era""".split())


def fts_terms(query: str, max_terms: int = 12) -> list[str]:
    """Termos [a-z0-9] sem acento e sem repetição (sem stopwords, se sobrar algo): a única fonte de texto que vai para MATCH."""
    all_words: list[str] = []
    for w in words(query):
        w = w[:40]
        if w not in all_words:
            all_words.append(w)
    useful = [w for w in all_words if w not in _STOP]
    return (useful or all_words)[:max_terms]


def fts_match(terms: list[str]) -> str:
    """Expressão FTS5 segura: cada termo vira string entre aspas (prefixo para termos com 3+ letras), ligados por OR.
    Os termos só têm [a-z0-9], então não há aspas, operadores (AND/OR/NOT/NEAR), parênteses ou colunas a escapar."""
    return " OR ".join(f'"{t}"*' if len(t) >= 3 else f'"{t}"' for t in terms)


def like_escape(text: str) -> str:
    """Escapa %, _ e a barra para uso com `LIKE ? ESCAPE '\\'`."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def atomic_write(path: Path, data: str) -> None:
    """Grava `data` em `path` de forma atômica (arquivo temporário no mesmo diretório + fsync + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _sql_fold(value: object) -> str:
    return fold(value) if isinstance(value, str) else ""


def _probe_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__jarvis_fts_probe USING fts5(x, tokenize='unicode61 remove_diacritics 2')")
        conn.execute("DROP TABLE temp.__jarvis_fts_probe")
        return True
    except sqlite3.Error:
        return False


class Database:
    """Conexão SQLite + lock + transações. `path=None` abre um banco em memória (nada vai para o disco)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.lock = threading.RLock()
        self._depth = 0
        self._closed = False
        self.fts5 = False            # o SQLite tem FTS5 com o tokenizer pedido?
        self.fts_ready = False       # as tabelas FTS existem e os triggers as mantêm (definido por migrations.ensure_fts)
        target = ":memory:" if path is None else str(path)
        try:
            conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None, timeout=5.0)
        except sqlite3.Error as exc:
            raise MemoryError_(f"não consegui abrir o banco de memória: {exc}") from exc
        self.conn = conn
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise MemoryError_("este SQLite não aplicou foreign_keys=ON; recuso abrir para não corromper relações")
            if path is not None:
                mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if str(mode).lower() != "wal":
                    log.warning("journal_mode=WAL não disponível (%s); seguindo no modo padrão", mode)
                conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA secure_delete=ON")          # apagar de verdade o conteúdo removido
            conn.create_function("fold", 1, _sql_fold, deterministic=True)
            self.fts5 = _probe_fts5(conn)
        except (sqlite3.Error, MemoryError_) as exc:
            conn.close()
            if isinstance(exc, MemoryError_):
                raise
            raise MemoryError_(f"não consegui configurar o banco de memória: {exc}") from exc
        if not self.fts5:
            log.warning("SQLite sem FTS5: a busca usará LIKE (mais lenta e sem ranking)")

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed:
            raise MemoryError_("a memória já foi fechada")

    @contextlib.contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Leitura com o lock seguro. Erros do SQLite viram MemoryError_."""
        with self.lock:
            self._check_open()
            try:
                yield self.conn
            except sqlite3.Error as exc:
                log.exception("erro de leitura no banco de memória")
                raise MemoryError_(f"erro ao ler a memória: {exc}") from exc

    @contextlib.contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transação explícita (BEGIN IMMEDIATE ... COMMIT; ROLLBACK em qualquer exceção). Aninhável na mesma thread."""
        with self.lock:
            self._check_open()
            if self._depth > 0:
                self._depth += 1
                try:
                    yield self.conn
                finally:
                    self._depth -= 1
                return
            try:
                self.conn.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as exc:
                log.exception("não consegui iniciar transação")
                raise MemoryError_(f"o banco de memória está ocupado ou indisponível: {exc}") from exc
            self._depth = 1
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException as exc:
                self._rollback()
                if isinstance(exc, sqlite3.Error):
                    log.exception("erro de escrita no banco de memória (transação desfeita)")
                    raise MemoryError_(f"erro ao gravar na memória (nada foi alterado): {exc}") from exc
                raise
            finally:
                self._depth = 0

    def _rollback(self) -> None:
        try:
            self.conn.execute("ROLLBACK")
        except sqlite3.Error as exc:       # o SQLite pode já ter desfeito sozinho (ex.: disco cheio)
            log.debug("rollback: %s", exc)

    def has_table(self, name: str) -> bool:
        with self.read() as c:
            return c.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type IN ('table','view')", (name,)).fetchone() is not None

    def close(self) -> None:
        """Idempotente. Faz checkpoint do WAL antes de fechar."""
        with self.lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self.path is not None:
                    self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                log.warning("checkpoint do WAL falhou ao fechar", exc_info=True)
            try:
                self.conn.close()
            except sqlite3.Error:
                log.exception("erro ao fechar a memória")
