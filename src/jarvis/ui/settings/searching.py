"""Busca nas Configuracoes: comparacao sem acento e sem diferenca de maiuscula. Funcoes puras."""
from __future__ import annotations

import unicodedata


def fold(text: str) -> str:
    """Minusculo e sem acento: 'Memória' e 'memoria' ficam iguais."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def matches(query: str, haystack: str) -> bool:
    """Todas as palavras da busca precisam aparecer no texto (em qualquer ordem)."""
    words = fold(query).split()
    if not words:
        return True
    target = fold(haystack)
    return all(w in target for w in words)
