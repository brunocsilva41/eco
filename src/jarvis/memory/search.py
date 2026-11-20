"""Busca nas conversas anteriores: FTS5 sobre mensagens (só user/assistant) e sobre títulos/resumos de sessões.

Contrato de threads: seguro entre threads (somente leitura, via `Database.read`). O índice é mantido por triggers
(`migrations.ensure_fts`); sem FTS5 cai para LIKE (mais lento, sem ranking). Conversas na lixeira nunca aparecem.
O texto devolvido é conteúdo gravado de conversas passadas: quem o entrega ao modelo deve marcá-lo como NÃO CONFIÁVEL.
"""
from __future__ import annotations

import builtins
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Literal

from ._db import Database, MemoryError_, fts_match, fts_terms, like_escape
from .sessions import OMITTED

log = logging.getLogger(__name__)

__all__ = ["ConversationSearch", "Hit"]

SNIPPET_CHARS = 160
_MAX_PER_SESSION = 2


@dataclass(frozen=True, slots=True)
class Hit:
    session_id: int
    title: str
    ts: float                         # data da mensagem (ou última atividade da conversa, nos resumos)
    role: str | None                  # 'user' | 'assistant' (None nos resumos)
    snippet: str                      # ~160 caracteres; termos achados entre «»
    kind: Literal["mensagem", "resumo"]


def _clip(text: str, n: int = SNIPPET_CHARS) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[:n - 1].rstrip() + "…"


def _plain_snippet(text: str, terms: builtins.list[str]) -> str:
    """Trecho sem FTS5: começa um pouco antes do primeiro termo (comparação sem acento quando as posições coincidem)."""
    one = " ".join(text.split())
    low = one.casefold()
    pos = min((p for p in (low.find(t) for t in terms) if p >= 0), default=-1)
    if pos < 0:
        return _clip(one)
    start = max(0, pos - 40)
    return ("…" if start else "") + _clip(one[start:], SNIPPET_CHARS - (1 if start else 0))


class ConversationSearch:
    def __init__(self, db: Database) -> None:
        self._db = db

    def search(self, query: str, since: float | None = None, until: float | None = None,
               limit: int = 10) -> builtins.list[Hit]:
        """Acha trechos de mensagens e resumos, mais relevantes primeiro, no máx. 2 por conversa. `since`/`until` são
        timestamps (epoch, float; `until` inclusive). Consulta sem termos úteis devolve lista vazia."""
        terms = fts_terms(query)
        if not terms:
            return []
        if since is not None and until is not None and since > until:
            raise MemoryError_("a data inicial é depois da final")
        limit = max(1, min(int(limit), 50))
        with self._db.read() as c:
            if self._db.fts_ready:
                try:
                    raw = self._fts(c, terms, since, until, limit * 3)
                except sqlite3.OperationalError:
                    log.warning("MATCH falhou nas conversas; usando LIKE", exc_info=True)
                    raw = self._like(c, terms, since, until, limit * 3)
            else:
                raw = self._like(c, terms, since, until, limit * 3)
        per: dict[int, int] = {}
        hits: builtins.list[Hit] = []
        for _rank, hit in sorted(raw, key=lambda x: x[0]):
            if per.get(hit.session_id, 0) >= _MAX_PER_SESSION:
                continue
            per[hit.session_id] = per.get(hit.session_id, 0) + 1
            hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    @staticmethod
    def _range(col: str, since: float | None, until: float | None) -> tuple[str, builtins.list[Any]]:
        sql, params = "", []
        if since is not None:
            sql += f" AND {col} >= ?"
            params.append(float(since))
        if until is not None:
            sql += f" AND {col} <= ?"
            params.append(float(until))
        return sql, params

    def _fts(self, c: Any, terms: builtins.list[str], since: float | None, until: float | None,
             n: int) -> builtins.list[tuple[float, Hit]]:
        match = fts_match(terms)
        out: builtins.list[tuple[float, Hit]] = []
        rng, rp = self._range("m.ts", since, until)
        rows = c.execute(
            "SELECT m.session_id, s.title, m.ts, m.role, snippet(messages_fts, 0, '«', '»', '…', 24) AS snip,"
            " bm25(messages_fts) AS rank FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid"
            " JOIN sessions s ON s.id = m.session_id WHERE messages_fts MATCH ? AND s.state != 'lixeira'" + rng +
            " AND m.content != ? ORDER BY rank LIMIT ?", (match, *rp, OMITTED, n)).fetchall()
        for r in rows:
            out.append((r["rank"], Hit(r["session_id"], r["title"], r["ts"], r["role"], _clip(r["snip"] or ""), "mensagem")))
        rng, rp = self._range("s.last_active", since, until)
        rows = c.execute(
            "SELECT s.id AS sid, s.title, s.last_active, s.summary, snippet(sessions_fts, 1, '«', '»', '…', 24) AS snip,"
            " bm25(sessions_fts) AS rank FROM sessions_fts JOIN sessions s ON s.id = sessions_fts.rowid"
            " WHERE sessions_fts MATCH ? AND s.state != 'lixeira'" + rng + " ORDER BY rank LIMIT ?",
            (match, *rp, n)).fetchall()
        for r in rows:
            snip = r["snip"] if r["summary"] else r["title"]
            out.append((r["rank"], Hit(r["sid"], r["title"], r["last_active"], None, _clip(snip or r["title"]), "resumo")))
        return out

    def _like(self, c: Any, terms: builtins.list[str], since: float | None, until: float | None,
              n: int) -> builtins.list[tuple[float, Hit]]:
        likes = ["%" + like_escape(t) + "%" for t in terms]
        out: builtins.list[tuple[float, Hit]] = []
        cond = " OR ".join("fold(m.content) LIKE ? ESCAPE '\\'" for _ in terms)
        rng, rp = self._range("m.ts", since, until)
        rows = c.execute(
            "SELECT m.session_id, s.title, m.ts, m.role, m.content FROM messages m JOIN sessions s ON s.id = m.session_id"
            f" WHERE m.role IN ('user', 'assistant') AND s.state != 'lixeira' AND m.content != ? AND ({cond}){rng}"
            " ORDER BY m.ts DESC LIMIT ?", (OMITTED, *likes, *rp, n)).fetchall()
        for i, r in enumerate(rows):
            out.append((float(i), Hit(r["session_id"], r["title"], r["ts"], r["role"], _plain_snippet(r["content"], terms), "mensagem")))
        cond = " OR ".join("fold(s.title) LIKE ? ESCAPE '\\' OR fold(COALESCE(s.summary, '')) LIKE ? ESCAPE '\\'" for _ in terms)
        params = [x for lk in likes for x in (lk, lk)]
        rng, rp = self._range("s.last_active", since, until)
        rows = c.execute(
            f"SELECT s.id AS sid, s.title, s.last_active, s.summary FROM sessions s WHERE s.state != 'lixeira' AND ({cond}){rng}"
            " ORDER BY s.last_active DESC LIMIT ?", (*params, *rp, n)).fetchall()
        for i, r in enumerate(rows):
            out.append((float(i) + 0.5, Hit(r["sid"], r["title"], r["last_active"], None,
                                            _plain_snippet(r["summary"] or r["title"], terms), "resumo")))
        return out

    def session_digest(self, session_id: int, max_chars: int = 1500) -> str:
        """Resumo da conversa (se houver) ou as primeiras e últimas falas, SEMPRE limitado a `max_chars` (nunca o texto
        inteiro). Levanta MemoryError_ se a conversa não existe ou está na lixeira."""
        max_chars = max(200, min(int(max_chars), 8000))
        with self._db.read() as c:
            s = c.execute("SELECT title, state, last_active, summary, summary_upto_message_id FROM sessions WHERE id=?",
                          (session_id,)).fetchone()
            if s is None or s["state"] == "lixeira":
                raise MemoryError_(f"não encontrei a conversa {session_id}")
            header = f"Conversa \"{s['title']}\" ({time.strftime('%Y-%m-%d', time.localtime(s['last_active']))})."
            if s["summary"]:
                body = "Resumo: " + s["summary"]
            else:
                rows = c.execute("SELECT role, content FROM messages WHERE session_id=? AND role IN ('user', 'assistant')"
                                 " ORDER BY id", (session_id,)).fetchall()
                if not rows:
                    return header + " Está vazia."
                per = max(60, (max_chars - len(header)) // 7)
                labels = {"user": "Bruno", "assistant": "Jarvis"}

                def fmt(r: Any) -> str:
                    return f"{labels[r['role']]}: {_clip(r['content'], per)}"

                if len(rows) <= 6:
                    parts = [fmt(r) for r in rows]
                else:
                    parts = [fmt(r) for r in rows[:3]] + [f"[... {len(rows) - 6} mensagens ...]"] + [fmt(r) for r in rows[-3:]]
                body = "\n".join(parts)
        text = header + "\n" + body
        return text if len(text) <= max_chars else text[:max_chars - 1].rstrip() + "…"
