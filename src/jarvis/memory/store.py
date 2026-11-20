"""Fachada `Memory`: abre o banco, migra, faz a manutenção e expõe `.sessions`, `.longterm` e `.search`.

Contrato de threads: `Memory` e as três camadas são seguras entre threads (um RLock e uma conexão em `Database`;
cada escrita é uma transação). `close()` é idempotente; depois dele qualquer operação levanta `MemoryError_`.

Modo sem histórico (`cfg.enabled=False`): o banco é ':memory:' e `persistent` é False; NADA é gravado em disco
(nem o arquivo do banco é aberto ou migrado), tudo some ao fechar. `backup_to` e `export_all_json` recusam nesse
modo. O banco em disco NÃO é criptografado.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config import MemoryCfg
from . import migrations
from ._db import Database, MemoryError_, atomic_write
from .longterm import LongTermMemory
from .search import ConversationSearch
from .secrets import looks_secret
from .sessions import OMITTED, SessionStore

log = logging.getLogger(__name__)

__all__ = ["Memory"]

TOOL_RESULT_RETENTION_DAYS = 7        # resultados de ferramentas (texto de tela/arquivos) não ficam um ano no banco


class Memory:
    def __init__(self, db_path: Path, cfg: MemoryCfg) -> None:
        self.cfg = cfg
        self.persistent: bool = bool(cfg.enabled)
        self.path: Path | None = Path(db_path) if self.persistent else None
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise MemoryError_(f"não consegui criar a pasta da memória {self.path.parent}: {exc}") from exc
        else:
            log.info("modo sem histórico: a memória fica só na RAM e nada é gravado em disco")
        self._db = Database(self.path)
        try:
            migrations.migrate(self._db)
            migrations.ensure_fts(self._db)
        except BaseException:
            self._db.close()
            raise
        self.sessions = SessionStore(self._db)
        self.longterm = LongTermMemory(self._db)
        self.search = ConversationSearch(self._db)
        self._maintenance()

    def reconfigure(self, cfg: MemoryCfg) -> None:
        """Aplica parâmetros novos na hora (recall, inatividade, prazos). Ligar/desligar a persistência exige reiniciar."""
        self.cfg = cfg

    def _maintenance(self) -> None:
        """Conversas expiradas -> lixeira; lixeiras e memórias expiradas vencidas -> apagadas. Falha aqui não impede abrir."""
        steps = (
            ("expirar conversas", lambda: self.sessions.expire_old(self.cfg.conversation_ttl_days)),
            ("limpar resultados antigos de ferramentas", lambda: self.sessions.purge_old_tool_results(TOOL_RESULT_RETENTION_DAYS)),
            ("esvaziar lixeira de conversas", lambda: self.sessions.empty_trash(self.cfg.trash_days)),
            ("esvaziar lixeira de memórias", lambda: self.longterm.empty_trash(self.cfg.trash_days)),
            ("limpar memórias expiradas", lambda: self.longterm.purge_expired(self.cfg.trash_days)),
        )
        for label, fn in steps:
            try:
                fn()
            except MemoryError_:
                log.exception("manutenção da memória falhou ao %s", label)

    @property
    def fts_available(self) -> bool:
        return self._db.fts_ready

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ backup e exportação
    def _require_persistent(self, what: str) -> None:
        if not self.persistent:
            raise MemoryError_(f"estou no modo sem histórico: não há o que {what}")

    def backup_to(self, path: Path) -> Path:
        """Cópia consistente e ATÔMICA do banco inteiro (API de backup do SQLite; arquivo temporário + os.replace).
        Atenção: a cópia contém TUDO (e não é criptografada); trate-a como dado pessoal."""
        self._require_persistent("copiar")
        dest = Path(path)
        try:
            if self.path is not None and dest.resolve() == self.path.resolve():
                raise MemoryError_("o destino do backup é o próprio banco")
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".tmp")
            os.close(fd)
        except OSError as exc:
            raise MemoryError_(f"não consegui preparar o backup em {dest}: {exc}") from exc
        try:
            with self._db.lock:
                if self._db.closed:
                    raise MemoryError_("a memória já foi fechada")
                target = sqlite3.connect(tmp)
                try:
                    self._db.conn.backup(target)
                finally:
                    target.close()
            os.replace(tmp, dest)
        except (sqlite3.Error, OSError) as exc:
            log.exception("backup da memória falhou")
            raise MemoryError_(f"o backup falhou: {exc}") from exc
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        log.info("backup da memória gravado em %s", dest)
        return dest

    def export_all_json(self, path: Path) -> Path:
        """Exporta conversas (fora da lixeira) e memórias vivas em JSON, SEM segredos (trechos suspeitos são omitidos).
        Gravação atômica."""
        self._require_persistent("exportar")
        with self._db.lock:                      # instantâneo consistente: lê tudo sob o mesmo lock
            ids = [s.id for s in self.sessions.list(limit=200, state=None)]
            offset = 200
            while len(ids) == offset:
                more = [s.id for s in self.sessions.list(limit=200, offset=offset, state=None)]
                ids += more
                offset += 200
            sessions = [self.sessions.export_dict(i) for i in ids]
            memories: list[dict[str, Any]] = []
            for m in self.longterm.list(limit=10_000, include_expired=True):
                memories.append({"id": m.id, "text": OMITTED if looks_secret(m.text) else m.text, "kind": m.kind,
                                 "pinned": m.pinned, "origin": m.origin, "confidence": m.confidence,
                                 "created": m.created, "updated": m.updated, "expires_at": m.expires_at})
        payload = {"versao": 1, "exportado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "conversas": sessions, "memorias": memories}
        try:
            atomic_write(Path(path), json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError as exc:
            raise MemoryError_(f"não consegui gravar a exportação em {path}: {exc}") from exc
        return Path(path)
