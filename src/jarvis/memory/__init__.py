"""Memória local do Eco (SQLite): conversas em sessões, memória de longo prazo e busca.

Uso: `from jarvis.memory import Memory, MemoryError_`; `mem = Memory(db_path, cfg.memory)` e então
`mem.sessions` (SessionStore), `mem.longterm` (LongTermMemory) e `mem.search` (ConversationSearch).
Tudo é seguro entre threads (ver `store.py`). Nada de segredos é gravado e o banco NÃO é criptografado.
"""
from __future__ import annotations

from ._db import MemoryError_
from .longterm import LongTermMemory, MemoryItem
from .search import ConversationSearch, Hit
from .secrets import looks_secret
from .sessions import Message, Session, SessionStore, estimate_tokens
from .store import Memory

__all__ = ["Memory", "MemoryError_", "SessionStore", "LongTermMemory", "ConversationSearch",
           "Session", "Message", "MemoryItem", "Hit", "looks_secret", "estimate_tokens"]
