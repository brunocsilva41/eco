"""Logging: console + arquivo rotativo (`jarvis.log`) + trilha de auditoria (`audit.jsonl`, cada ação do PC).

A auditoria é um logger separado (`jarvis.audit`, propagate=False): vai SÓ para `audit.jsonl`, sem duplicar no
log comum nem no console. Tamanho e retenção vêm da config (`logs.max_mb`, `logs.keep_files`); o nível pode mudar
em tempo de execução (`set_level`).
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from ..config import LogsCfg

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


class _AuditFormatter(logging.Formatter):
    """Uma linha JSON por ação: {"ts": ..., "level": ..., "event": <objeto da ação>}. A mensagem já vem em JSON."""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
        msg = record.getMessage()
        event = msg if msg.startswith("{") else '"%s"' % msg.replace("\\", "/").replace('"', "'")
        return '{"ts":"%s","level":"%s","event":%s}' % (ts, record.levelname, event)


def setup(logs_dir: Path, cfg: LogsCfg) -> None:
    """Configura o logging uma única vez (idempotente). Falhas ao abrir arquivos não derrubam o app."""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(cfg.level.upper())

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_FMT))
    root.addHandler(console)

    audit = logging.getLogger("jarvis.audit")
    audit.setLevel(logging.INFO)
    audit.propagate = False                          # a auditoria não vai para o console nem para o log comum
    max_bytes = cfg.max_mb * 1_000_000
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(logs_dir / "jarvis.log", maxBytes=max_bytes,
                                                  backupCount=cfg.keep_files, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FMT))
        root.addHandler(fh)

        ah = logging.handlers.RotatingFileHandler(logs_dir / "audit.jsonl", maxBytes=max_bytes,
                                                  backupCount=max(cfg.keep_files, 10), encoding="utf-8")
        ah.setFormatter(_AuditFormatter())
        audit.addHandler(ah)
    except OSError:
        logging.getLogger(__name__).exception("não consegui abrir os arquivos de log em %s; seguindo só no console", logs_dir)
        audit.propagate = True                       # sem arquivo de auditoria, ao menos aparece no log comum

    for noisy in ("urllib3", "httpx", "numba", "comtypes", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def set_level(level: str) -> None:
    """Muda o nível de log em tempo de execução (configurações aplicadas sem reiniciar)."""
    logging.getLogger().setLevel(level.upper())
