"""Memória de longo prazo (fatos, preferências, tarefas, notas) com busca FTS5/BM25 (ou LIKE se não houver FTS5).

Contrato de threads: todos os métodos são seguros entre threads; cada escrita é uma transação.
Higiene: segredos são recusados, o texto é deduplicado por forma normalizada (`fold`), tamanho 3..1000.
Apagar é "soft delete" (`deleted_at`); a lixeira é esvaziada por `empty_trash`. O texto vindo do modelo/tela é DADO,
nunca instrução: quem injeta no prompt deve rotulá-lo assim.
"""
from __future__ import annotations

import builtins
import logging
import math
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from ..core.textutil import fold
from ._db import Database, MemoryError_, fts_match, fts_terms, like_escape
from .secrets import looks_secret

log = logging.getLogger(__name__)

__all__ = ["LongTermMemory", "MemoryItem", "KINDS", "ORIGINS", "MIN_CHARS", "MAX_CHARS", "MAX_PINNED", "MAX_MEMORIES"]

KINDS = ("fato", "preferencia", "tarefa", "nota")
ORIGINS = ("usuario", "modelo", "externo")
MIN_CHARS = 3
MAX_CHARS = 1000
MAX_PINNED = 20            # fixadas entram sempre no prompt: o teto protege o contexto
MAX_MEMORIES = 5000        # teto de memórias vivas (disco e busca)
_ORIGIN_RANK = {"externo": 0, "modelo": 1, "usuario": 2}
_COLS = "id, text, kind, pinned, origin, confidence, created, updated, expires_at, deleted_at"


@dataclass(frozen=True, slots=True)
class MemoryItem:
    id: int
    text: str
    kind: str                         # fato | preferencia | tarefa | nota
    pinned: bool
    origin: str                       # usuario | modelo | externo
    confidence: float
    created: float
    updated: float
    expires_at: float | None
    deleted_at: float | None


def _item(r: Any) -> MemoryItem:
    return MemoryItem(id=r["id"], text=r["text"], kind=r["kind"], pinned=bool(r["pinned"]), origin=r["origin"],
                      confidence=r["confidence"], created=r["created"], updated=r["updated"],
                      expires_at=r["expires_at"], deleted_at=r["deleted_at"])


def validate_text(text: str) -> str:
    """Normaliza espaços e valida tamanho 3..1000 e ausência de segredos. Devolve o texto limpo ou levanta MemoryError_."""
    if not isinstance(text, str):
        raise MemoryError_("o texto da memória deve ser texto")
    clean = " ".join("".join(ch for ch in text if ch >= " " or ch in "\t\n").split())
    if len(clean) < MIN_CHARS:
        raise MemoryError_(f"memória curta demais (mínimo {MIN_CHARS} caracteres)")
    if len(clean) > MAX_CHARS:
        raise MemoryError_(f"memória longa demais (máximo {MAX_CHARS} caracteres)")
    reason = looks_secret(clean)
    if reason:
        raise MemoryError_(f"o texto parece conter {reason}; não guardo isso")
    return clean


class LongTermMemory:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def validate_text(text: str) -> str:
        return validate_text(text)

    def _live_where(self, include_expired: bool) -> tuple[str, builtins.list[Any]]:
        if include_expired:
            return "deleted_at IS NULL", []
        return "deleted_at IS NULL AND (expires_at IS NULL OR expires_at > ?)", [time.time()]

    # ------------------------------------------------------------------ escrita
    def remember(self, text: str, kind: str, origin: str, confidence: float = 1.0, expires_at: float | None = None,
                 pinned: bool = False) -> int:
        """Guarda uma memória e devolve o id. Texto igual (após normalizar) a uma existente NÃO duplica: devolve o id
        existente, atualiza `updated` (e sobe a origem/fixação/expiração se a nova for mais forte)."""
        if kind not in KINDS:
            raise MemoryError_(f"tipo inválido: {kind!r} (use {', '.join(KINDS)})")
        if origin not in ORIGINS:
            raise MemoryError_(f"origem inválida: {origin!r}")
        clean = validate_text(text)
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or math.isnan(confidence):
            raise MemoryError_("confiança deve ser um número entre 0 e 1")
        confidence = min(1.0, max(0.0, float(confidence)))
        now = time.time()
        if expires_at is not None:
            if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)) or not math.isfinite(expires_at):
                raise MemoryError_("expiração inválida")
            if expires_at <= now:
                raise MemoryError_("a data de expiração já passou")
            expires_at = float(expires_at)
        key = fold(clean)
        with self._db.tx() as c:
            row = c.execute(f"SELECT {_COLS} FROM memories WHERE text_key=? AND deleted_at IS NULL", (key,)).fetchone()
            if row is not None:
                was_expired = row["expires_at"] is not None and row["expires_at"] <= now
                new_origin = origin if _ORIGIN_RANK[origin] > _ORIGIN_RANK[row["origin"]] else row["origin"]
                new_pinned = 1 if (pinned or row["pinned"]) else 0
                if new_pinned and not row["pinned"] and self._pinned_count(c) >= MAX_PINNED:
                    raise MemoryError_(f"já há {MAX_PINNED} memórias fixadas; desafixe uma antes")
                new_exp = expires_at if (expires_at is not None or was_expired) else row["expires_at"]
                c.execute("UPDATE memories SET updated=?, origin=?, pinned=?, expires_at=?, confidence=MAX(confidence, ?)"
                          " WHERE id=?", (now, new_origin, new_pinned, new_exp, confidence, row["id"]))
                return int(row["id"])
            live = int(c.execute("SELECT COUNT(*) FROM memories WHERE deleted_at IS NULL").fetchone()[0])
            if live >= MAX_MEMORIES:
                raise MemoryError_(f"a memória está cheia ({MAX_MEMORIES}); apague algumas antes de guardar mais")
            if pinned and self._pinned_count(c) >= MAX_PINNED:
                raise MemoryError_(f"já há {MAX_PINNED} memórias fixadas; desafixe uma antes")
            cur = c.execute(
                "INSERT INTO memories(text, text_key, kind, pinned, origin, confidence, created, updated, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (clean, key, kind, 1 if pinned else 0, origin, confidence, now, now, expires_at))
            return int(cur.lastrowid)

    def _pinned_count(self, c: Any) -> int:
        return int(c.execute("SELECT COUNT(*) FROM memories WHERE pinned=1 AND deleted_at IS NULL").fetchone()[0])

    def forget(self, memory_id: int) -> None:
        """Soft delete (some das buscas e listas; a lixeira é esvaziada por `empty_trash`)."""
        with self._db.tx() as c:
            cur = c.execute("UPDATE memories SET deleted_at=?, pinned=0 WHERE id=? AND deleted_at IS NULL", (time.time(), memory_id))
            if cur.rowcount == 0:
                raise MemoryError_(f"não existe a memória {memory_id}")

    def edit(self, memory_id: int, text: str) -> MemoryItem:
        clean = validate_text(text)
        key = fold(clean)
        with self._db.tx() as c:
            row = c.execute(f"SELECT {_COLS} FROM memories WHERE id=? AND deleted_at IS NULL", (memory_id,)).fetchone()
            if row is None:
                raise MemoryError_(f"não existe a memória {memory_id}")
            dup = c.execute("SELECT id FROM memories WHERE text_key=? AND deleted_at IS NULL AND id != ?", (key, memory_id)).fetchone()
            if dup is not None:
                raise MemoryError_(f"já existe uma memória igual (número {dup['id']})")
            c.execute("UPDATE memories SET text=?, text_key=?, updated=? WHERE id=?", (clean, key, time.time(), memory_id))
            out = c.execute(f"SELECT {_COLS} FROM memories WHERE id=?", (memory_id,)).fetchone()
        return _item(out)

    def pin(self, memory_id: int, pinned: bool = True) -> None:
        with self._db.tx() as c:
            row = c.execute("SELECT pinned FROM memories WHERE id=? AND deleted_at IS NULL", (memory_id,)).fetchone()
            if row is None:
                raise MemoryError_(f"não existe a memória {memory_id}")
            if pinned and not row["pinned"] and self._pinned_count(c) >= MAX_PINNED:
                raise MemoryError_(f"já há {MAX_PINNED} memórias fixadas; desafixe uma antes")
            c.execute("UPDATE memories SET pinned=?, updated=? WHERE id=?", (1 if pinned else 0, time.time(), memory_id))

    # ------------------------------------------------------------------ leitura
    def get(self, memory_id: int, include_deleted: bool = False) -> MemoryItem | None:
        sql = f"SELECT {_COLS} FROM memories WHERE id=?" + ("" if include_deleted else " AND deleted_at IS NULL")
        with self._db.read() as c:
            row = c.execute(sql, (memory_id,)).fetchone()
        return _item(row) if row else None

    def list(self, kind: str | None = None, limit: int = 50, include_expired: bool = False) -> builtins.list[MemoryItem]:
        """Fixadas primeiro, depois as mais recentemente atualizadas."""
        if kind is not None and kind not in KINDS:
            raise MemoryError_(f"tipo inválido: {kind!r}")
        where, params = self._live_where(include_expired)
        if kind is not None:
            where += " AND kind=?"
            params.append(kind)
        limit = max(1, min(int(limit), MAX_MEMORIES))
        with self._db.read() as c:
            rows = c.execute(f"SELECT {_COLS} FROM memories WHERE {where} ORDER BY pinned DESC, updated DESC, id DESC LIMIT ?",
                             (*params, limit)).fetchall()
        return [_item(r) for r in rows]

    def pinned(self) -> builtins.list[MemoryItem]:
        where, params = self._live_where(False)
        with self._db.read() as c:
            rows = c.execute(f"SELECT {_COLS} FROM memories WHERE {where} AND pinned=1 ORDER BY updated DESC, id DESC",
                             params).fetchall()
        return [_item(r) for r in rows]

    def count(self, include_expired: bool = False) -> int:
        where, params = self._live_where(include_expired)
        with self._db.read() as c:
            return int(c.execute(f"SELECT COUNT(*) FROM memories WHERE {where}", params).fetchone()[0])

    def search(self, query: str, k: int = 5) -> builtins.list[MemoryItem]:
        """Top-k por relevância (BM25). Ignora apagadas e expiradas. A consulta é reduzida a termos [a-z0-9] entre aspas,
        então sintaxe FTS inválida/maliciosa não chega ao MATCH. Sem FTS5 (ou se o MATCH falhar) usa LIKE."""
        terms = fts_terms(query)
        if not terms:
            return []
        k = max(1, min(int(k), 50))
        now = time.time()
        with self._db.read() as c:
            if self._db.fts_ready:
                try:
                    rows = c.execute(
                        "SELECT m.id, m.text, m.kind, m.pinned, m.origin, m.confidence, m.created, m.updated, m.expires_at,"
                        " m.deleted_at FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid"
                        " WHERE memories_fts MATCH ? AND m.deleted_at IS NULL AND (m.expires_at IS NULL OR m.expires_at > ?)"
                        " ORDER BY bm25(memories_fts), m.id DESC LIMIT ?", (fts_match(terms), now, k)).fetchall()
                    return [_item(r) for r in rows]
                except sqlite3.OperationalError:
                    log.warning("MATCH falhou na memória; usando LIKE", exc_info=True)
            score = " + ".join("(CASE WHEN text_key LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END)" for _ in terms)
            likes = ["%" + like_escape(t) + "%" for t in terms]
            rows = c.execute(
                f"SELECT {_COLS}, ({score}) AS score FROM memories WHERE deleted_at IS NULL"
                " AND (expires_at IS NULL OR expires_at > ?) AND score > 0 ORDER BY score DESC, updated DESC LIMIT ?",
                (*likes, now, k)).fetchall()
        return [_item(r) for r in rows]

    # ------------------------------------------------------------------ manutenção
    def empty_trash(self, older_than_days: float | None = None) -> int:
        """Apaga definitivamente as memórias apagadas (todas, ou há mais de N dias). Devolve quantas."""
        with self._db.tx() as c:
            if older_than_days is None:
                cur = c.execute("DELETE FROM memories WHERE deleted_at IS NOT NULL")
            else:
                cur = c.execute("DELETE FROM memories WHERE deleted_at IS NOT NULL AND deleted_at <= ?",
                                (time.time() - max(0.0, float(older_than_days)) * 86400,))
            return int(cur.rowcount)

    def purge_expired(self, grace_days: float) -> int:
        """Apaga definitivamente as memórias que expiraram há mais de `grace_days` dias."""
        with self._db.tx() as c:
            cur = c.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
                            (time.time() - max(0.0, float(grace_days)) * 86400,))
            return int(cur.rowcount)

    def purge_all(self, vacuum: bool = False) -> int:
        """Apaga TUDO (inclusive a lixeira), de forma irreversível. `vacuum=True` compacta o arquivo depois. Devolve quantas."""
        with self._db.tx() as c:
            n = int(c.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            c.execute("DELETE FROM memories")
        if vacuum:
            with self._db.lock:
                try:
                    self._db.conn.execute("VACUUM")
                except sqlite3.Error:
                    log.warning("VACUUM falhou após purge_all", exc_info=True)
        log.info("memória de longo prazo apagada: %d item(ns)", n)
        return n
