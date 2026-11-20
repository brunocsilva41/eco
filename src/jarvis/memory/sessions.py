"""Sessões de conversa e suas mensagens completas (inclui chamadas e resultados de ferramentas).

Contrato de threads: todos os métodos são seguros entre threads (o lock e as transações ficam em `Database`).
Cada método que escreve é UMA transação. Invariante: no máximo uma sessão 'ativa' (índice único parcial).
Quem guarda o id da sessão corrente (o agente) deve reconsultar `active()` depois de `start`, `resume` ou
`ensure_active`, que podem trocar a sessão ativa.

Privacidade: mensagens de role user/assistant com cara de credencial são gravadas como
'[conteúdo omitido: parecia conter credenciais]'. Mensagens de ferramenta/sistema NÃO passam por esse filtro
(são dados do computador); `export` e `export_dict` o aplicam na saída.
"""
from __future__ import annotations

import builtins
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..core.textutil import fold, words
from ._db import Database, MemoryError_, atomic_write, like_escape
from .secrets import looks_secret

log = logging.getLogger(__name__)

__all__ = ["SessionStore", "Session", "Message", "DEFAULT_TITLE", "OMITTED", "MAX_CONTENT_CHARS", "estimate_tokens"]

DEFAULT_TITLE = "Nova conversa"
OMITTED = "[conteúdo omitido: parecia conter credenciais]"
MAX_CONTENT_CHARS = 20_000
MAX_TITLE_CHARS = 80
_MAX_TOOL_CALLS_JSON = 50_000
_ROLES = ("user", "assistant", "tool", "system")
_STATES = ("ativa", "encerrada", "lixeira")
_S_COLS = "id, title, auto_title, created, last_active, ended, state, token_count, summary, summary_upto_message_id, deleted_at"
_M_COLS = "id, session_id, ts, role, content, tool_calls_json, tool_call_id, name, untrusted, tokens"
_RESUME_STOP = frozenset("""continua continuar continue retoma retomar retome conversa conversas de da do das dos a o as os
sobre aquela aquele anterior ultima ultimo falamos que onde paramos abre abrir volta voltar nossa nosso minha meu""".split())

_DANGLING = frozenset("a o as os de da do das dos em no na para por com e ou que um uma".split())

SessionState = Literal["ativa", "encerrada", "lixeira"]


def estimate_tokens(text: str) -> int:
    """Estimativa conservadora (~3 caracteres por token em português) para quando o servidor não informa."""
    return max(1, (len(text) + 2) // 3)


@dataclass(frozen=True, slots=True)
class Session:
    id: int
    title: str
    auto_title: bool                  # True = título automático (ainda não renomeado pelo Bruno)
    created: float
    last_active: float
    ended: float | None
    state: str                        # 'ativa' | 'encerrada' | 'lixeira'
    token_count: int
    summary: str | None
    summary_upto_message_id: int | None
    deleted_at: float | None


@dataclass(frozen=True, slots=True)
class Message:
    id: int
    session_id: int
    ts: float
    role: str                         # 'user' | 'assistant' | 'tool' | 'system'
    content: str
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    name: str | None
    untrusted: bool
    tokens: int | None


def _session(r: Any) -> Session:
    return Session(id=r["id"], title=r["title"], auto_title=bool(r["auto_title"]), created=r["created"],
                   last_active=r["last_active"], ended=r["ended"], state=r["state"], token_count=r["token_count"],
                   summary=r["summary"], summary_upto_message_id=r["summary_upto_message_id"], deleted_at=r["deleted_at"])


def _message(r: Any) -> Message:
    calls: list[dict[str, Any]] | None = None
    if r["tool_calls_json"]:
        try:
            parsed = json.loads(r["tool_calls_json"])
            calls = parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            log.warning("tool_calls_json inválido na mensagem %s", r["id"])
    return Message(id=r["id"], session_id=r["session_id"], ts=r["ts"], role=r["role"], content=r["content"],
                   tool_calls=calls, tool_call_id=r["tool_call_id"], name=r["name"], untrusted=bool(r["untrusted"]),
                   tokens=r["tokens"])


def _clean_title(title: str) -> str:
    clean = " ".join(title.split())
    if len(clean) > MAX_TITLE_CHARS:
        clean = clean[:MAX_TITLE_CHARS - 1].rstrip() + "…"
    return clean


def _title_from(text: str) -> str:
    toks = text.split()[:6]
    while len(toks) > 2 and toks[-1].strip(".,;:!?").casefold() in _DANGLING:      # não terminar em "de", "para"...
        toks.pop()
    t = " ".join(" ".join(toks).strip(" \t.,;:!?-–—\"'").split())
    if len(t) > 60:
        t = t[:59].rstrip() + "…"
    return (t[0].upper() + t[1:]) if t else DEFAULT_TITLE


def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


class SessionStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------ ciclo de vida
    def _count_messages(self, c: Any, session_id: int) -> int:
        return int(c.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)).fetchone()[0])

    def _row(self, c: Any, session_id: int) -> Any:
        row = c.execute(f"SELECT {_S_COLS} FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise MemoryError_(f"não existe a conversa {session_id}")
        return row

    def _retire_active_tx(self, c: Any, now: float, exclude_id: int | None = None) -> None:
        """Encerra a(s) sessão(ões) ativa(s). Uma ativa vazia e nunca renomeada some (não deixa conversa vazia na lista)."""
        for r in c.execute("SELECT id, auto_title FROM sessions WHERE state='ativa'").fetchall():
            if r["id"] == exclude_id:
                continue
            if r["auto_title"] and self._count_messages(c, r["id"]) == 0:
                c.execute("DELETE FROM sessions WHERE id=?", (r["id"],))
            else:
                c.execute("UPDATE sessions SET state='encerrada', ended=? WHERE id=?", (now, r["id"]))

    def _start_tx(self, c: Any, title: str | None, now: float) -> int:
        act = c.execute("SELECT id, auto_title FROM sessions WHERE state='ativa'").fetchone()
        if act is not None and act["auto_title"] and self._count_messages(c, act["id"]) == 0:
            # a ativa está vazia e intocada: reaproveita (os ids que o app guardou continuam válidos)
            if title:
                c.execute("UPDATE sessions SET title=?, auto_title=0, created=?, last_active=? WHERE id=?",
                          (title, now, now, act["id"]))
            else:
                c.execute("UPDATE sessions SET created=?, last_active=? WHERE id=?", (now, now, act["id"]))
            return int(act["id"])
        self._retire_active_tx(c, now)
        cur = c.execute("INSERT INTO sessions(title, auto_title, created, last_active, state) VALUES (?, ?, ?, ?, 'ativa')",
                        (title or DEFAULT_TITLE, 0 if title else 1, now, now))
        return int(cur.lastrowid)

    def start(self, title: str | None = None) -> Session:
        """Abre uma conversa nova (encerrando a ativa anterior). Se a ativa ainda está vazia, ela é reaproveitada."""
        clean = _clean_title(title) if title else None
        now = time.time()
        with self._db.tx() as c:
            sid = self._start_tx(c, clean or None, now)
            row = self._row(c, sid)
        log.info("conversa %d ativa", sid)
        return _session(row)

    def active(self) -> Session | None:
        with self._db.read() as c:
            row = c.execute(f"SELECT {_S_COLS} FROM sessions WHERE state='ativa' ORDER BY id DESC LIMIT 1").fetchone()
        return _session(row) if row else None

    def ensure_active(self, idle_minutes: int) -> tuple[Session, bool]:
        """Devolve (sessão ativa, rolled). `rolled=True` quando a anterior passou de `idle_minutes` parada (e tinha
        conteúdo) e foi encerrada para abrir outra: o app deve avisar. `idle_minutes<=0` = nunca vira por inatividade."""
        now = time.time()
        with self._db.tx() as c:
            act = c.execute(f"SELECT {_S_COLS} FROM sessions WHERE state='ativa' ORDER BY id DESC LIMIT 1").fetchone()
            if act is None:
                return _session(self._row(c, self._start_tx(c, None, now))), False
            idle = idle_minutes > 0 and (now - act["last_active"]) > idle_minutes * 60
            if idle and self._count_messages(c, act["id"]) > 0:
                sid = self._start_tx(c, None, now)
                log.info("conversa %d encerrada por inatividade; aberta a %d", act["id"], sid)
                return _session(self._row(c, sid)), True
            if idle:                                              # vazia: só renova
                c.execute("UPDATE sessions SET last_active=? WHERE id=?", (now, act["id"]))
                return _session(self._row(c, act["id"])), False
            return _session(act), False

    def end(self, session_id: int) -> None:
        with self._db.tx() as c:
            row = self._row(c, session_id)
            if row["state"] == "ativa":
                c.execute("UPDATE sessions SET state='encerrada', ended=? WHERE id=?", (time.time(), session_id))

    def resume(self, session_id: int) -> Session:
        """Reativa uma conversa encerrada ('continua a conversa de ...'), encerrando a ativa atual."""
        now = time.time()
        with self._db.tx() as c:
            row = self._row(c, session_id)
            if row["state"] == "lixeira":
                raise MemoryError_("essa conversa está na lixeira; restaure antes de continuar")
            if row["state"] != "ativa":
                self._retire_active_tx(c, now, exclude_id=session_id)
                c.execute("UPDATE sessions SET state='ativa', ended=NULL, last_active=? WHERE id=?", (now, session_id))
            out = _session(self._row(c, session_id))
        return out

    def rename(self, session_id: int, title: str) -> None:
        clean = _clean_title(title or "")
        if not clean:
            raise MemoryError_("o título não pode ser vazio")
        with self._db.tx() as c:
            self._row(c, session_id)
            c.execute("UPDATE sessions SET title=?, auto_title=0 WHERE id=?", (clean, session_id))

    # ------------------------------------------------------------------ consulta
    def get(self, session_id: int) -> Session | None:
        with self._db.read() as c:
            row = c.execute(f"SELECT {_S_COLS} FROM sessions WHERE id=?", (session_id,)).fetchone()
        return _session(row) if row else None

    def list(self, limit: int = 20, offset: int = 0, state: str | None = None, query: str | None = None) -> builtins.list[Session]:
        """Mais recentes primeiro (por last_active). `state=None` = todas menos a lixeira. `query` filtra por título/resumo
        (todas as palavras, sem acento nem caixa)."""
        if state is not None and state not in _STATES:
            raise MemoryError_(f"estado inválido: {state!r}")
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        where = ["state != 'lixeira'"] if state is None else ["state = ?"]
        params: list[Any] = [] if state is None else [state]
        for w in words(query or ""):
            like = "%" + like_escape(w) + "%"
            where.append("(fold(title) LIKE ? ESCAPE '\\' OR fold(COALESCE(summary, '')) LIKE ? ESCAPE '\\')")
            params += [like, like]
        sql = f"SELECT {_S_COLS} FROM sessions WHERE {' AND '.join(where)} ORDER BY last_active DESC, id DESC LIMIT ? OFFSET ?"
        with self._db.read() as c:
            rows = c.execute(sql, (*params, limit, offset)).fetchall()
        return [_session(r) for r in rows]

    def resume_candidates(self, query: str, limit: int = 5) -> builtins.list[Session]:
        """Candidatas para 'continua a conversa de ...': por palavras no título (peso 2) e no resumo (peso 1).
        Sem palavras úteis, devolve as mais recentes. Nunca inclui a ativa nem a lixeira."""
        limit = max(1, min(int(limit), 20))
        terms = [w for w in words(query) if w not in _RESUME_STOP]
        with self._db.read() as c:
            rows = c.execute(f"SELECT {_S_COLS} FROM sessions WHERE state='encerrada' "
                             "ORDER BY last_active DESC, id DESC LIMIT 500").fetchall()
        if not terms:
            return [_session(r) for r in rows[:limit]]
        scored: list[tuple[int, float, Any]] = []
        for r in rows:
            title, summ = fold(r["title"]), fold(r["summary"] or "")
            score = sum((2 if t in title else 0) + (1 if t in summ else 0) for t in terms)
            if score:
                scored.append((score, r["last_active"], r))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [_session(r) for _, _, r in scored[:limit]]

    # ------------------------------------------------------------------ mensagens
    def append(self, session_id: int, role: str, content: str, *, tool_calls: builtins.list[dict[str, Any]] | None = None,
               tool_call_id: str | None = None, name: str | None = None, untrusted: bool = False,
               tokens: int | None = None) -> Message:
        """Grava uma mensagem, atualiza `last_active`/`token_count` e (na primeira fala) o título automático."""
        if role not in _ROLES:
            raise MemoryError_(f"papel inválido: {role!r}")
        if not isinstance(content, str):
            raise MemoryError_("o conteúdo da mensagem deve ser texto")
        if tokens is not None and (isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0):
            raise MemoryError_("tokens deve ser um inteiro >= 0")
        text = content
        if len(text) > MAX_CONTENT_CHARS:
            text = text[:MAX_CONTENT_CHARS - 1] + "…"
        if role in ("user", "assistant", "tool"):                # resultados de ferramentas também podem trazer segredos de tela/arquivos
            reason = looks_secret(text)
            if reason:
                log.warning("mensagem %s da conversa %s tinha cara de credencial (%s); conteúdo omitido", role, session_id, reason)
                text = OMITTED
        calls_json: str | None = None
        if tool_calls:
            try:
                calls_json = json.dumps(tool_calls, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                raise MemoryError_(f"tool_calls não serializável: {exc}") from exc
            if len(calls_json) > _MAX_TOOL_CALLS_JSON:
                log.warning("tool_calls grande demais (%d); guardando só os nomes", len(calls_json))
                names = [{"function": {"name": str((tc.get("function") or {}).get("name", "?"))}} for tc in tool_calls
                         if isinstance(tc, dict)]
                calls_json = json.dumps(names, ensure_ascii=False)
        n_tokens = tokens if tokens is not None else estimate_tokens(text)
        now = time.time()
        with self._db.tx() as c:
            row = self._row(c, session_id)
            if row["state"] == "lixeira":
                raise MemoryError_("essa conversa está na lixeira")
            cur = c.execute(
                "INSERT INTO messages(session_id, ts, role, content, tool_calls_json, tool_call_id, name, untrusted, tokens)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, now, role, text, calls_json, (tool_call_id or None) and tool_call_id[:200],
                 (name or None) and name[:200], 1 if untrusted else 0, n_tokens))
            c.execute("UPDATE sessions SET last_active=?, token_count=token_count+? WHERE id=?", (now, n_tokens, session_id))
            if role == "user" and row["auto_title"] and row["title"] == DEFAULT_TITLE:
                self._auto_title_tx(c, session_id)
            mid = int(cur.lastrowid)
        return Message(id=mid, session_id=session_id, ts=now, role=role, content=text, tool_calls=tool_calls or None,
                       tool_call_id=tool_call_id or None, name=name or None, untrusted=bool(untrusted), tokens=n_tokens)

    def messages(self, session_id: int, after_id: int | None = None, limit: int | None = None) -> builtins.list[Message]:
        """Mensagens em ordem cronológica, opcionalmente depois de `after_id` e limitadas."""
        sql = f"SELECT {_M_COLS} FROM messages WHERE session_id=? AND id>? ORDER BY id"
        params: list[Any] = [session_id, after_id if after_id is not None else 0]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(0, int(limit)))
        with self._db.read() as c:
            rows = c.execute(sql, params).fetchall()
        return [_message(r) for r in rows]

    def last_messages(self, session_id: int, n: int) -> builtins.list[Message]:
        """As últimas `n` mensagens (ordem cronológica). Pode começar no meio de um grupo chamada/resultado de ferramenta:
        quem monta o prompt deve cuidar disso."""
        n = max(0, min(int(n), 1000))
        if n == 0:
            return []
        with self._db.read() as c:
            rows = c.execute(f"SELECT {_M_COLS} FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                             (session_id, n)).fetchall()
        return [_message(r) for r in reversed(rows)]

    def count_messages(self, session_id: int) -> int:
        with self._db.read() as c:
            return self._count_messages(c, session_id)

    # ------------------------------------------------------------------ resumo e título
    def set_summary(self, session_id: int, text: str, upto_message_id: int) -> None:
        """Guarda o resumo (reindexado por trigger). As mensagens originais continuam no banco."""
        clean = (text or "").strip()
        if not clean:
            raise MemoryError_("resumo vazio")
        if len(clean) > 8000:
            clean = clean[:7999] + "…"
        reason = looks_secret(clean)
        if reason:
            raise MemoryError_(f"o resumo parece conter {reason}; não o guardei")
        with self._db.tx() as c:
            self._row(c, session_id)
            if c.execute("SELECT 1 FROM messages WHERE id=? AND session_id=?", (upto_message_id, session_id)).fetchone() is None:
                raise MemoryError_(f"a mensagem {upto_message_id} não pertence à conversa {session_id}")
            c.execute("UPDATE sessions SET summary=?, summary_upto_message_id=? WHERE id=?", (clean, upto_message_id, session_id))

    def get_summary(self, session_id: int) -> tuple[str, int | None] | None:
        """(texto, id da última mensagem resumida) ou None se não há resumo."""
        with self._db.read() as c:
            row = c.execute("SELECT summary, summary_upto_message_id FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None or not row["summary"]:
            return None
        return row["summary"], row["summary_upto_message_id"]

    def _auto_title_tx(self, c: Any, session_id: int) -> str:
        row = self._row(c, session_id)
        if not row["auto_title"]:
            return str(row["title"])
        first = c.execute("SELECT content FROM messages WHERE session_id=? AND role='user' AND content != ? ORDER BY id LIMIT 1",
                          (session_id, OMITTED)).fetchone()
        if first is None:
            return str(row["title"])
        title = _title_from(first["content"])
        if title != row["title"]:
            c.execute("UPDATE sessions SET title=? WHERE id=?", (title, session_id))
        return title

    def auto_title(self, session_id: int) -> str:
        """Título = primeiras ~6 palavras da primeira fala do Bruno. Não mexe em título renomeado. Devolve o título atual."""
        with self._db.tx() as c:
            return self._auto_title_tx(c, session_id)

    # ------------------------------------------------------------------ apagar / restaurar
    def delete(self, session_id: int, to_trash: bool = True) -> None:
        """Lixeira por padrão (recuperável por `trash_days`). `to_trash=False` apaga DEFINITIVAMENTE (irreversível)."""
        now = time.time()
        with self._db.tx() as c:
            row = self._row(c, session_id)
            if not to_trash:
                c.execute("DELETE FROM sessions WHERE id=?", (session_id,))      # mensagens saem por ON DELETE CASCADE
            elif row["state"] != "lixeira":
                c.execute("UPDATE sessions SET state='lixeira', deleted_at=?, ended=COALESCE(ended, ?) WHERE id=?",
                          (now, now, session_id))
        log.info("conversa %d %s", session_id, "apagada definitivamente" if not to_trash else "enviada para a lixeira")

    def restore(self, session_id: int) -> None:
        with self._db.tx() as c:
            row = self._row(c, session_id)
            if row["state"] != "lixeira":
                raise MemoryError_("essa conversa não está na lixeira")
            c.execute("UPDATE sessions SET state='encerrada', deleted_at=NULL WHERE id=?", (session_id,))

    def empty_trash(self, older_than_days: float | None = None) -> int:
        """Apaga definitivamente da lixeira (tudo, ou só o que está lá há mais de N dias). Devolve quantas conversas."""
        with self._db.tx() as c:
            if older_than_days is None:
                cur = c.execute("DELETE FROM sessions WHERE state='lixeira'")
            else:
                cur = c.execute("DELETE FROM sessions WHERE state='lixeira' AND deleted_at <= ?",
                                (time.time() - max(0.0, float(older_than_days)) * 86400,))
            n = cur.rowcount
        if n:
            log.info("lixeira de conversas: %d apagada(s) definitivamente", n)
        return n

    def expire_old(self, ttl_days: float) -> int:
        """Manda para a lixeira (recuperável) as conversas sem atividade há mais de `ttl_days`. Devolve quantas."""
        now = time.time()
        with self._db.tx() as c:
            cur = c.execute("UPDATE sessions SET state='lixeira', deleted_at=?, ended=COALESCE(ended, ?)"
                            " WHERE state != 'lixeira' AND last_active < ?", (now, now, now - float(ttl_days) * 86400))
            n = cur.rowcount
        if n:
            log.info("%d conversa(s) passaram de %s dias e foram para a lixeira", n, ttl_days)
        return n

    def purge_old_tool_results(self, older_than_days: float) -> int:
        """Apaga o CORPO de resultados de ferramentas antigos (podem trazer texto de tela/arquivos). Fica só um marcador:
        as falas e o resumo da conversa continuam. Devolve quantos foram limpos."""
        cutoff = time.time() - float(older_than_days) * 86400
        marker = "[resultado antigo removido]"
        with self._db.tx() as c:
            cur = c.execute("UPDATE messages SET content=?, tokens=? WHERE role='tool' AND ts < ? AND content != ?",
                            (marker, estimate_tokens(marker), cutoff, marker))
            n = cur.rowcount
        if n:
            log.info("%d resultado(s) de ferramenta com mais de %s dias tiveram o conteúdo removido", n, older_than_days)
        return n

    # ------------------------------------------------------------------ exportação
    def export_dict(self, session_id: int) -> dict[str, Any]:
        """Conversa como dicionário JSON-serializável, sem segredos (mensagens de qualquer papel passam pelo filtro)."""
        with self._db.read() as c:
            srow = self._row(c, session_id)
            mrows = c.execute(f"SELECT {_M_COLS} FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        s = _session(srow)
        out_msgs: list[dict[str, Any]] = []
        for r in mrows:
            m = _message(r)
            content = OMITTED if looks_secret(m.content) else m.content
            out_msgs.append({"id": m.id, "ts": m.ts, "role": m.role, "content": content, "tool_calls": m.tool_calls,
                             "tool_call_id": m.tool_call_id, "name": m.name, "untrusted": m.untrusted, "tokens": m.tokens})
        summary = s.summary if s.summary and not looks_secret(s.summary) else None
        return {"id": s.id, "title": s.title, "created": s.created, "last_active": s.last_active, "ended": s.ended,
                "state": s.state, "token_count": s.token_count, "summary": summary, "messages": out_msgs}

    def export(self, session_id: int, path: Path, fmt: str = "md") -> Path:
        """Exporta a conversa para `path` de forma ATÔMICA (arquivo temporário + os.replace). fmt: 'md' ou 'json'."""
        if fmt not in ("md", "json"):
            raise MemoryError_("formato de exportação deve ser 'md' ou 'json'")
        data = self.export_dict(session_id)
        if fmt == "json":
            payload = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            labels = {"user": "Você", "assistant": "Jarvis", "tool": "Ferramenta", "system": "Sistema"}
            lines = [f"# {data['title']}", "", f"- Criada: {_fmt_ts(data['created'])}",
                     f"- Última atividade: {_fmt_ts(data['last_active'])}", f"- Estado: {data['state']}", ""]
            if data["summary"]:
                lines += ["## Resumo", "", data["summary"], ""]
            lines += ["## Conversa", ""]
            for m in data["messages"]:
                lines += [f"**{labels.get(m['role'], m['role'])}** ({_fmt_ts(m['ts'])})", "", m["content"], ""]
            payload = "\n".join(lines)
        try:
            atomic_write(Path(path), payload)
        except OSError as exc:
            raise MemoryError_(f"não consegui gravar a exportação em {path}: {exc}") from exc
        return Path(path)
