"""Linhas das listas (sem Qt): dados prontos para o delegate pintar e o leitor de tela ler.

Memórias, conversas e trechos de busca viram o mesmo ``ListRow``; quem decide texto, ícone e cor é este módulo
(``presenters``), então a vista não conhece regra de negócio.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from ...memory import Hit, MemoryItem
from .logic import fmt_date, fmt_ts, session_state_text
from .service import SessionRow
from .texts import tr

RowKind = Literal["row", "header"]
TagState = Literal["", "ok", "warn", "error"]


@dataclass(frozen=True, slots=True)
class RowTag:
    """Marca à direita da linha. Sempre ícone + texto: o estado nunca fica só na cor."""
    icon: str
    text: str
    state: TagState = ""


@dataclass(frozen=True, slots=True)
class ListRow:
    key: int
    primary: str
    secondary: str = ""
    kind: RowKind = "row"
    primary_lines: int = 2
    secondary_lines: int = 1
    bold: bool = False
    tags: tuple[RowTag, ...] = ()
    a11y: str = ""
    muted: bool = False
    extra: dict[str, str] = field(default_factory=dict, compare=False)


HEADER_KEY = -1


def header_row(text: str) -> ListRow:
    return ListRow(HEADER_KEY, text, kind="header", primary_lines=1, a11y=text)


def _origin_tag(origin: str) -> RowTag | None:
    m = tr().memories
    if origin == "modelo":
        return RowTag("brain", m.origin_short["modelo"])
    if origin == "externo":
        return RowTag("alert", m.origin_short["externo"], "warn")
    return None


def memory_row(item: MemoryItem, now: float) -> ListRow:
    m = tr().memories
    expired = item.expires_at is not None and item.expires_at <= now
    tags: list[RowTag] = []
    origin = _origin_tag(item.origin)
    if origin is not None:
        tags.append(origin)
    if expired:
        tags.append(RowTag("alert", m.expired_chip, "warn"))
    if item.pinned:
        tags.append(RowTag("pin", m.pinned_chip))
    kind = m.kinds.get(item.kind, item.kind)
    text = " ".join(item.text.split())
    meta = f"{kind} · {fmt_date(item.updated)}"
    spoken = ", ".join([kind, text, *(t.text for t in tags)])
    return ListRow(item.id, text, meta, tags=tuple(tags), a11y=spoken, muted=expired)


def memory_rows(items: list[MemoryItem], now: float | None = None) -> list[ListRow]:
    """Fixadas no topo sob um cabeçalho; sem nenhuma fixada, a lista fica sem cabeçalhos."""
    t = time.time() if now is None else now
    pinned = [i for i in items if i.pinned]
    if not pinned:
        return [memory_row(i, t) for i in items]
    m = tr().memories
    rest = [i for i in items if not i.pinned]
    out = [header_row(m.header_pinned), *(memory_row(i, t) for i in pinned)]
    if rest:
        out += [header_row(m.header_others), *(memory_row(i, t) for i in rest)]
    return out


def session_row(row: SessionRow, trash_days: float, now: float) -> ListRow:
    c = tr().conversations
    s = row.session
    tags: list[RowTag] = []
    if s.state == "ativa":
        tags.append(RowTag("record", c.state_active, "ok"))
    elif s.state == "lixeira":
        tags.append(RowTag("trash", session_state_text(s, trash_days, now), "warn"))
    meta = f"{c.meta_messages(row.messages)} · {fmt_ts(s.last_active)}"
    spoken = ", ".join([s.title, meta, *(t.text for t in tags)])
    return ListRow(s.id, s.title, meta, primary_lines=1, bold=True, tags=tuple(tags), a11y=spoken)


def session_rows(rows: list[SessionRow], trash_days: float, now: float | None = None) -> list[ListRow]:
    t = time.time() if now is None else now
    return [session_row(r, trash_days, t) for r in rows]


def hit_rows(hits: list[Hit]) -> list[ListRow]:
    """Um trecho por linha: o texto achado (termos entre « ») e, embaixo, conversa, quem falou e quando."""
    c = tr().conversations
    out: list[ListRow] = []
    for h in hits:
        who = c.role_summary if h.role is None else c.roles.get(h.role, h.role)
        meta = f"{h.title} · {who} · {fmt_ts(h.ts)}"
        out.append(ListRow(h.session_id, h.snippet, meta, a11y=f"{h.snippet}. {meta}"))
    return out
