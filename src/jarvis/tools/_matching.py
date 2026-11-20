"""Comparação de nomes falados (sem acento, sem caixa) usada pelas ferramentas de apps, janelas e controles.

Módulo interno: concentra a regra de correspondência para que todas as ferramentas se comportem igual.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")

_SPACES = re.compile(r"\s+")


def fold(text: str) -> str:
    """Minúsculas, sem acentos e com espaços normalizados: 'Configurações ' -> 'configuracoes'."""
    decomposed = unicodedata.normalize("NFKD", text)
    base = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SPACES.sub(" ", base.casefold()).strip()


def clip(text: str, limit: int) -> str:
    """Corta em `limit` caracteres com reticências (para mensagens curtas)."""
    text = _SPACES.sub(" ", text).strip()
    return text if len(text) <= limit else text[: max(limit - 1, 1)].rstrip() + "…"


def best_matches(
    query: str,
    items: Iterable[T],
    key: Callable[[T], str],
    *,
    query_contains_item: bool = False,
    fuzzy_cutoff: float | None = None,
) -> list[T]:
    """Devolve os itens do melhor nível de correspondência (lista vazia = nada encontrado).

    Níveis, do mais ao menos forte: igualdade; o nome do item contém a consulta (e, se
    `query_contains_item`, a consulta contém o nome: "abre o paint" -> "paint");
    aproximada por difflib (só se `fuzzy_cutoff` for dado). Mais de um resultado = ambíguo.
    """
    q = fold(query)
    if not q:
        return []
    pool = [(item, fold(key(item))) for item in items]
    pool = [(item, name) for item, name in pool if name]

    exact = [item for item, name in pool if name == q]
    if exact:
        return exact
    partial = [item for item, name in pool if q in name or (query_contains_item and name in q)]
    if partial:
        return partial
    if fuzzy_cutoff is None:
        return []
    scored = [(difflib.SequenceMatcher(None, q, name).ratio(), item) for item, name in pool]
    scored = [(score, item) for score, item in scored if score >= fuzzy_cutoff]
    if not scored:
        return []
    top = max(score for score, _ in scored)
    return [item for score, item in scored if score >= top - 0.02]
