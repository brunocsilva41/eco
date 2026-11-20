"""Detecção de segredos (senhas, cartões, CPF, chaves de API, JWT, chaves privadas) antes de gravar qualquer texto.

`looks_secret` é uma função pura, sem estado: segura para chamar de qualquer thread. Ela prefere errar para o lado
seguro (recusar) em dúvida, mas usa limites de palavra para não recusar "pintar", "mapping", "tokenizar" etc.
NÃO é garantia: segredo escrito de forma incomum passa. O banco não é criptografado.
"""
from __future__ import annotations

import re

__all__ = ["looks_secret"]

from ..core.textutil import fold

# palavra-chave (já sem acento, minúscula) + qualificadores opcionais + separador opcional + valor
_KW = re.compile(
    r"\b(?P<kw>senhas?|password|passwd|pins?|tokens?|chaves?|segredos?|cvv|api[ _-]?keys?)\b"
    r"(?P<qual>(?:\s+(?:de|do|da|dos|das|pix|secreta|privada|api|acesso|bancaria|wifi|wi-fi|cartao))*)"
    r"\s*(?P<sep>[:=]|\b(?:e|eh|is|foi|sera|agora)\b)?\s*(?P<val>\S+)",
    re.I)
_EDGE = " \t.,;:!?\"'()[]{}"

_PREFIXED: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "chave de API"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "token do GitHub"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "token do GitHub"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "chave de acesso da AWS"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "chave de API do Google"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "token do Slack"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), "token JWT"),
    (re.compile(r"-----BEGIN\b"), "chave privada ou certificado"),
)

# 13-19 dígitos contíguos, ou grupos 4-4-4-(1..4) / 4-6-5 separados por espaço ou hífen
_CARD = re.compile(r"(?<!\d)(?:\d{13,19}|\d{4}(?:[ -]\d{4}){2}(?:[ -]\d{1,4})?|\d{4}[ -]\d{6}[ -]\d{4,5})(?!\d)")
_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _cpf_ok(digits: str) -> bool:
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    nums = [int(c) for c in digits]
    for n in (9, 10):
        s = sum(nums[i] * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != nums[n]:
            return False
    return True


def _keyword_secret(text: str) -> str | None:
    plain = fold(text)
    pos = 0
    while True:
        m = _KW.search(plain, pos)
        if m is None:
            return None
        pos = m.end("kw")                      # avança só além da palavra-chave: o valor pode conter outra palavra-chave
        value = m.group("val").strip(_EDGE)
        if not value:
            continue
        has_digit = any(c.isdigit() for c in value)
        if m.group("sep") and len(value) >= 2:
            return "senha, PIN ou chave"       # "senha: x", "a senha é x", "token = x"
        if has_digit and len(value) >= 3:
            return "senha, PIN ou chave"       # "senha 1234", "cvv 123"


def looks_secret(text: str) -> str | None:
    """Devolve o MOTIVO (texto curto em português) se `text` parece conter uma credencial; senão None."""
    if not isinstance(text, str) or not text:
        return None
    for pat, reason in _PREFIXED:
        if pat.search(text):
            return reason
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and len(set(digits)) > 1 and _luhn(digits):
            return "número de cartão"
    for m in _CPF.finditer(text):
        if _cpf_ok(re.sub(r"\D", "", m.group(0))):
            return "CPF"
    return _keyword_secret(text)
