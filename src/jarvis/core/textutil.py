"""Utilidades de texto compartilhadas (uma só normalização de acentos/caixa no projeto inteiro)."""
from __future__ import annotations

import re
import unicodedata


def fold(text: str) -> str:
    """Minúsculas, sem acentos e com espaços normalizados: base de toda comparação de nomes e comandos de voz."""
    nfd = unicodedata.normalize("NFD", text.casefold())
    plain = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", plain).strip()


def words(text: str) -> list[str]:
    """Palavras de `fold(text)` só com letras e dígitos."""
    return re.sub(r"[^a-z0-9 ]+", " ", fold(text)).split()
