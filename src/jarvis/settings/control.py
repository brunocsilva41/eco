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


def _pid_alive(pid: int, started: float) -> bool:
    """O processo existe E é o mesmo que gravou o runtime (hora de criação perto de `started`): PID reaproveitado não engana."""
    import ctypes
    import ctypes.wintypes as wt
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:      # 259 = STILL_ACTIVE
            return False
        created, exited, kernel, user = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
        if not k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            return True                               # não deu para conferir a hora: confia no PID vivo
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        created_epoch = (ticks - 116444736000000000) / 1e7
        return abs(created_epoch - started) < 600.0
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
    return rt if _pid_alive(rt.pid, rt.started) else None


def request(data_dir: Path, kind: str) -> None:
    """Pede 'reload' ou 'restart' ao Jarvis em execução."""
    if kind not in ("reload", "restart"):
        raise ValueError(kind)
    atomic_write_text(control_dir(data_dir) / f"{kind}.req", str(time.time()))


def _yolo_key(data_dir: Path) -> bytes:
    import secrets
    p = control_dir(data_dir) / "yolo.key"
    try:
        return bytes.fromhex(p.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        key = secrets.token_bytes(32)
        atomic_write_text(p, key.hex())
        return key


def _yolo_mac(data_dir: Path, kind: str, stamp: str) -> str:
    import hashlib
    import hmac
    return hmac.new(_yolo_key(data_dir), f"{kind}|{stamp}".encode("ascii"), hashlib.sha256).hexdigest()


def request_yolo(data_dir: Path, on: bool) -> None:
    """Chamado SOMENTE pelo botão da tela de Configurações (clique do Bruno, com diálogo de confirmação).
    O pedido é assinado (HMAC) e vale 60 s; o Jarvis ignora pedido sem assinatura válida."""
    kind = "yolo_on" if on else "yolo_off"
    stamp = str(time.time())
    atomic_write_text(control_dir(data_dir) / f"{kind}.req", f"{stamp}|{_yolo_mac(data_dir, kind, stamp)}")


def consume(data_dir: Path) -> set[str]:
    """Lê e apaga os pedidos pendentes e ainda válidos. Devolve {'reload', 'restart'} (subconjunto)."""
    found: set[str] = set()
    d = control_dir(data_dir)
    for kind in ("reload", "restart", "yolo_on", "yolo_off"):
        p = d / f"{kind}.req"
        taken = d / f"{kind}.taken"
        try:
            os.replace(p, taken)                       # atômico: um pedido novo cai num arquivo novo, nunca se perde
        except FileNotFoundError:
            continue
        except OSError:
            log.warning("não consegui pegar o pedido %s", p)
            continue
        try:
            raw = taken.read_text(encoding="utf-8").strip()
            stamp_txt, _, mac = raw.partition("|")
            stamp = float(stamp_txt)
        except (OSError, ValueError):
            stamp, stamp_txt, mac = 0.0, "", ""
        if kind.startswith("yolo_"):
            import hmac
            if not mac or not hmac.compare_digest(mac, _yolo_mac(data_dir, kind, stamp_txt)):
                log.warning("pedido %s sem assinatura válida: ignorado", kind)
                stamp = 0.0
        try:
            taken.unlink(missing_ok=True)
        except OSError:
            log.warning("não consegui apagar %s", taken)
        if stamp and time.time() - stamp <= REQUEST_TTL_S:
            found.add(kind)
    return found


def config_mtime(path: Path) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0
