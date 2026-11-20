"""Logging: console + arquivo rotativo (`jarvis.log`) + trilha de auditoria (`audit.jsonl`, cada ação do PC)."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


class _AuditFormatter(logging.Formatter):
    """Uma linha JSON por ação: {"ts": ..., "level": ..., <campos da ação>}. A mensagem já vem em JSON."""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
        msg = record.getMessage()
        return '{"ts":"%s","level":"%s","event":%s}' % (ts, record.levelname, msg if msg.startswith("{") else '"%s"' % msg.replace('"', "'"))


def setup(logs_dir: Path, level: str = "INFO") -> None:
    """Configura o logging uma única vez (idempotente). Falhas ao abrir arquivos não derrubam o app."""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(level.upper())

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_FMT))
    root.addHandler(console)

    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(logs_dir / "jarvis.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FMT))
        root.addHandler(fh)

        ah = logging.handlers.RotatingFileHandler(logs_dir / "audit.jsonl", maxBytes=2_000_000, backupCount=10, encoding="utf-8")
        ah.setFormatter(_AuditFormatter())
        audit = logging.getLogger("jarvis.audit")
        audit.setLevel(logging.INFO)
        audit.addHandler(ah)
    except OSError:
        logging.getLogger(__name__).exception("não consegui abrir os arquivos de log em %s; seguindo só no console", logs_dir)

    # bibliotecas barulhentas
    for noisy in ("urllib3", "httpx", "numba", "comtypes", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True
