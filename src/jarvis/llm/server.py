"""Gerenciador do `llama-server` (llama.cpp Vulkan): sobe, supervisiona, reinicia e derruba.

Segurança: só escuta em loopback (validado) e exige uma CHAVE DE API aleatória por execução (`--api-key`), guardada só
na memória deste processo; outro programa local ou página web não consegue usar o modelo. Um servidor desconhecido na
porta NÃO é adotado: o Jarvis só fala com o servidor que ele mesmo iniciou.
Limpeza: o processo filho entra num Job Object do Windows com KILL_ON_JOB_CLOSE; se o Jarvis morrer (até por falha), o
Windows encerra o servidor e a VRAM é liberada. Se o Job Object não puder ser criado, a partida FALHA (não há órfão).
Supervisão: uma thread verifica o processo; se morrer, reinicia (no máximo 3 vezes em 10 minutos) e avisa por evento.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import http.client
import json
import logging
import secrets
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from ..config import Config, assert_loopback
from ..core.cancel import CancelToken, Cancelled

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
RESTART_LIMIT = 3
RESTART_WINDOW_S = 600.0
LOG_ROTATE_BYTES = 5_000_000


class ServerError(RuntimeError):
    pass


# ----------------------------------------------------------------- Job Object (kill-on-close)
class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BASIC_LIMIT(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]


class _EXT_LIMIT(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


_JOB_KILL_ON_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateJobObjectW.restype = wt.HANDLE
_k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
_k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
_k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
_k32.OpenProcess.restype = wt.HANDLE
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.CloseHandle.argtypes = [wt.HANDLE]


def _make_kill_on_close_job() -> int:
    job = _k32.CreateJobObjectW(None, None)
    if not job:
        raise ServerError(f"não consegui criar o Job Object (erro {ctypes.get_last_error()})")
    info = _EXT_LIMIT()
    info.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE
    if not _k32.SetInformationJobObject(job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
        err = ctypes.get_last_error()
        _k32.CloseHandle(job)
        raise ServerError(f"SetInformationJobObject falhou (erro {err})")
    return int(job)


def _assign_to_job(job: int, pid: int) -> None:
    """Prende o processo (por PID, com handle próprio: sem usar API privada do Popen) ao Job Object."""
    h = _k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
    if not h:
        raise ServerError(f"OpenProcess falhou (erro {ctypes.get_last_error()})")
    try:
        if not _k32.AssignProcessToJobObject(job, h):
            raise ServerError(f"AssignProcessToJobObject falhou (erro {ctypes.get_last_error()})")
    finally:
        _k32.CloseHandle(h)


def health_ok(host: str, port: int, timeout: float = 1.5) -> bool:
    """True se algo responde /health com status ok (sem proxy do sistema, IPv6 correto)."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", "/health")
        resp = conn.getresponse()
        return resp.status == 200 and json.loads(resp.read(10_000).decode("utf-8", "ignore")).get("status") == "ok"
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        conn.close()


class LlamaServer:
    """Contrato de threads: start()/stop() da thread do app; `api_key` e `is_running()` são seguros de qualquer thread."""

    def __init__(self, cfg: Config, on_event: Callable[[str, str], None] | None = None) -> None:
        assert_loopback(cfg.llm.host)
        self._cfg = cfg
        self._on_event = on_event or (lambda kind, text: None)
        self._proc: subprocess.Popen[bytes] | None = None
        self._job: int | None = None
        self._log_file = None
        self._key = secrets.token_urlsafe(32)          # só em memória; muda a cada execução
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._monitor: threading.Thread | None = None
        self._restarts: list[float] = []

    @property
    def api_key(self) -> str:
        return self._key

    # ------------------------------------------------------------- comando
    def build_command(self) -> list[str]:
        c = self._cfg.llm
        exe = self._cfg.paths.llama_bin / "llama-server.exe"
        problems = [f"não existe: {p}" for p in (exe, c.model) if not Path(p).is_file()]
        if c.mmproj is not None and not Path(c.mmproj).is_file():
            problems.append(f"não existe: {c.mmproj}")
        if problems:
            raise ServerError("; ".join(problems))
        cmd = [str(exe), "-m", str(c.model), "-ngl", str(c.ngl), "-c", str(c.ctx),
               "--host", c.host, "--port", str(c.port), "--jinja", "--api-key", self._key,
               "-np", "1", "--no-webui", "-cram", "1024"]      # 1 slot; sem UI web; cache de prompt limitado (RAM é curta)
        if c.mmproj is not None:
            cmd += ["--mmproj", str(c.mmproj)]
        if c.reasoning_off:
            cmd += ["--reasoning", "off"]
        return cmd

    # ------------------------------------------------------------- ciclo de vida
    def is_running(self) -> bool:
        p = self._proc
        return p is not None and p.poll() is None

    def start(self, cancel: CancelToken) -> None:
        """Sobe o servidor e só retorna quando ele estiver pronto. Recusa porta ocupada por servidor desconhecido."""
        c = self._cfg.llm
        if self.is_running():
            return
        if health_ok(c.host, c.port):
            raise ServerError(f"a porta {c.port} já tem outro servidor de modelo rodando que o Jarvis não iniciou. "
                              "Feche-o ou mude llm.port; o Jarvis não usa servidores desconhecidos.")
        self._stopping.clear()
        self._spawn(cancel)
        if self._monitor is None or not self._monitor.is_alive():
            self._monitor = threading.Thread(target=self._watch, name="llama-watch", daemon=True)
            self._monitor.start()

    def _spawn(self, cancel: CancelToken) -> None:
        cmd = self.build_command()
        log_path = self._cfg.paths.logs / "llama-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _rotate(log_path)
        proc: subprocess.Popen[bytes] | None = None
        job: int | None = None
        log_file = None
        try:
            log_file = open(log_path, "ab")
            log.info("iniciando llama-server (porta %d, contexto %d)", self._cfg.llm.port, self._cfg.llm.ctx)
            proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW, cwd=str(self._cfg.paths.llama_bin))
            job = _make_kill_on_close_job()
            _assign_to_job(job, proc.pid)
            with self._lock:
                self._proc, self._job, self._log_file = proc, job, log_file
            self._wait_ready(proc, cancel)
        except BaseException:
            # qualquer falha na partida limpa TUDO (nada de servidor órfão ocupando VRAM)
            if proc is not None and proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    log.error("llama-server não respondeu ao kill")
            if job is not None:
                _k32.CloseHandle(job)
            if log_file is not None:
                try:
                    log_file.close()
                except OSError:
                    pass
            with self._lock:
                self._proc, self._job, self._log_file = None, None, None
            raise

    def _wait_ready(self, proc: subprocess.Popen[bytes], cancel: CancelToken) -> None:
        c = self._cfg.llm
        deadline = time.monotonic() + c.startup_timeout_s
        while True:
            if cancel.cancelled:
                raise Cancelled(cancel.reason)
            code = proc.poll()
            if code is not None:
                raise ServerError(f"o llama-server encerrou na partida (código {code}). Últimas linhas:\n{self._tail_log()}")
            if health_ok(c.host, c.port):
                log.info("llama-server pronto")
                return
            if time.monotonic() > deadline:
                raise ServerError(f"o llama-server não ficou pronto em {c.startup_timeout_s:.0f}s")
            cancel.wait(0.5)

    def _watch(self) -> None:
        """Supervisão: se o processo morrer sem pedido de parada, reinicia (com limite) e avisa."""
        while not self._stopping.wait(2.0):
            proc = self._proc
            if proc is None or proc.poll() is None:
                continue
            code = proc.returncode
            now = time.monotonic()
            self._restarts = [t for t in self._restarts if now - t < RESTART_WINDOW_S]
            if len(self._restarts) >= RESTART_LIMIT:
                log.error("llama-server caiu (código %s) e já foi reiniciado %d vezes; desisto", code, RESTART_LIMIT)
                self._on_event("llm_dead", "O modelo de linguagem caiu repetidas vezes. Reinicie o Jarvis.")
                return
            self._restarts.append(now)
            log.error("llama-server caiu (código %s); reiniciando (%d/%d)", code, len(self._restarts), RESTART_LIMIT)
            self._on_event("llm_restarting", "O modelo de linguagem caiu; estou reiniciando.")
            try:
                self._release_dead()
                self._spawn(CancelToken())
                self._on_event("llm_restarted", "Modelo de linguagem de volta.")
            except Exception as exc:  # noqa: BLE001
                log.error("não consegui reiniciar o llama-server: %s", exc)

    def _release_dead(self) -> None:
        with self._lock:
            job, lf = self._job, self._log_file
            self._proc, self._job, self._log_file = None, None, None
        if job is not None:
            _k32.CloseHandle(job)
        if lf is not None:
            try:
                lf.close()
            except OSError:
                pass

    def stop(self) -> None:
        self._stopping.set()
        mon = self._monitor
        if mon is not None and mon.is_alive() and mon is not threading.current_thread():
            mon.join(3.0)
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            log.info("encerrando llama-server")
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    log.error("llama-server não respondeu ao kill")
        self._release_dead()                 # fechar o Job derruba qualquer filho remanescente

    # ------------------------------------------------------------- util
    def _tail_log(self, n: int = 8) -> str:
        try:
            lines = (self._cfg.paths.logs / "llama-server.log").read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except OSError:
            return "(sem log)"


def _rotate(path: Path) -> None:
    """Rotação simples do log do servidor: passou de ~5 MB, vira .1 (o antigo .1 é descartado)."""
    try:
        if path.exists() and path.stat().st_size > LOG_ROTATE_BYTES:
            backup = path.with_suffix(".log.1")
            backup.unlink(missing_ok=True)
            path.rename(backup)
    except OSError:
        log.warning("não consegui rotacionar %s", path)
