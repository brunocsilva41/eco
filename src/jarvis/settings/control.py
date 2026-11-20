"""Canal de controle entre a tela de Configurações (outro processo) e o Jarvis em execução, SEM rede e SEM segredos.

Tudo é arquivo dentro de `data/control/`, gravado de forma atômica:
- `runtime.json`  (escrito pelo Jarvis): pid, hora de início, hash da configuração aplicada e chaves que aguardam reinício;
- `reload.req`    (escrito pela tela): "recarregue o config.toml agora";
- `restart.req`   (escrito pela tela): "reinicie o Jarvis".
O Jarvis consulta a pasta uma vez por segundo. Pedidos têm validade curta (60 s) para nunca disparar tarde.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .tomlio import atomic_write_text

log = logging.getLogger(__name__)

REQUEST_TTL_S = 60.0
RESTART_EXIT_CODE = 75                      # Jarvis.cmd reinicia o processo quando recebe este código


@dataclass(frozen=True)
class Runtime:
    pid: int
    started: float
    config_mtime: float
    pending_restart: tuple[str, ...] = field(default_factory=tuple)


def control_dir(data_dir: Path) -> Path:
    d = data_dir / "control"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_runtime(data_dir: Path, rt: Runtime) -> None:
    body = {"pid": rt.pid, "started": rt.started, "config_mtime": rt.config_mtime, "pending_restart": list(rt.pending_restart)}
    atomic_write_text(control_dir(data_dir) / "runtime.json", json.dumps(body))


def clear_runtime(data_dir: Path) -> None:
    try:
        (control_dir(data_dir) / "runtime.json").unlink(missing_ok=True)
    except OSError:
        log.warning("não consegui apagar runtime.json")


def _pid_alive(pid: int) -> bool:
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        return bool(ok) and code.value == 259         # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def read_runtime(data_dir: Path) -> Runtime | None:
    """Estado do Jarvis em execução, ou None se não estiver rodando (arquivo ausente, ilegível ou processo morto)."""
    path = control_dir(data_dir) / "runtime.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rt = Runtime(int(raw["pid"]), float(raw["started"]), float(raw["config_mtime"]),
                     tuple(str(x) for x in raw.get("pending_restart", [])))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rt if _pid_alive(rt.pid) else None


def request(data_dir: Path, kind: str) -> None:
    """Pede 'reload' ou 'restart' ao Jarvis em execução."""
    if kind not in ("reload", "restart"):
        raise ValueError(kind)
    atomic_write_text(control_dir(data_dir) / f"{kind}.req", str(time.time()))


def consume(data_dir: Path) -> set[str]:
    """Lê e apaga os pedidos pendentes e ainda válidos. Devolve {'reload', 'restart'} (subconjunto)."""
    found: set[str] = set()
    d = control_dir(data_dir)
    for kind in ("reload", "restart"):
        p = d / f"{kind}.req"
        try:
            stamp = float(p.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            stamp = 0.0
        try:
            p.unlink(missing_ok=True)
        except OSError:
            log.warning("não consegui apagar %s", p)
            continue
        if stamp and time.time() - stamp <= REQUEST_TTL_S:
            found.add(kind)
    return found


def config_mtime(path: Path) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0
