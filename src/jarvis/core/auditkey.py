"""Resumo (HMAC) de textos sensíveis para a auditoria, em vez de hash puro.

Um SHA-256 simples de um texto curto (PIN, senha numérica) é recuperável por força bruta a partir do log. Aqui o
resumo usa HMAC-SHA256 com uma chave aleatória guardada FORA da pasta de logs (no perfil do usuário, que o Windows
protege por padrão): quem lê só o `audit.jsonl` não consegue testar palpites. A chave nunca é impressa nem logada.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_lock = threading.Lock()
_key: bytes | None = None


def _key_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Jarvis" / "audit.key"


def _load_key() -> bytes:
    global _key
    with _lock:
        if _key is not None:
            return _key
        path = _key_path()
        try:
            data = path.read_bytes()
            if len(data) >= 32:
                _key = data
                return _key
        except OSError:
            pass
        fresh = secrets.token_bytes(32)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(fresh)
            os.replace(tmp, path)
        except OSError:
            log.warning("não consegui gravar a chave de auditoria; usando chave só desta execução")
        _key = fresh
        return _key


def digest(text: str, length: int = 16) -> str:
    """HMAC-SHA256(texto) em hexadecimal, truncado. Estável entre execuções (mesma chave), não reversível por palpite."""
    mac = hmac.new(_load_key(), text.encode("utf-8", "replace"), hashlib.sha256).hexdigest()
    return mac[:length]
