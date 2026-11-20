"""Gerenciador do `llama-server` (llama.cpp Vulkan): sobe, espera ficar saudável, adota um já em execução, derruba.

Segurança: só escuta em loopback (validado na config). Sem chave de API, porque nada sai da máquina.
Limpeza: o processo filho entra num Job Object do Windows com KILL_ON_JOB_CLOSE; se o Jarvis morrer
(até por falha), o Windows encerra o servidor e a VRAM é liberada.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import Config
from ..core.cancel import CancelToken, Cancelled

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000


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
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateJobObjectW.restype = wt.HANDLE
_k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
_k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
_k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
_k32.CloseHandle.argtypes = [wt.HANDLE]


def _make_kill_on_close_job() -> int | None:
    job = _k32.CreateJobObjectW(None, None)
    if not job:
        log.warning("não consegui criar o Job Object (%s)", ctypes.get_last_error())
        return None
    info = _EXT_LIMIT()
    info.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE
    if not _k32.SetInformationJobObject(job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
        log.warning("SetInformationJobObject falhou (%s)", ctypes.get_last_error())
        _k32.CloseHandle(job)
        return None
    return int(job)


def health_ok(host: str, port: int, timeout: float = 1.5) -> bool:
    """True se o llama-server responde /health com status ok."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore")).get("status") == "ok"
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError):
        return False


class LlamaServer:
    """Contrato de threads: start()/stop() devem ser chamados da mesma thread (a do app); is_running() é seguro de qualquer uma."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._proc: subprocess.Popen[bytes] | None = None
        self._job: int | None = None
        self._log_file = None
        self._adopted = False

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
               "--host", c.host, "--port", str(c.port), "--jinja",
               "-np", "1", "--no-webui", "-cram", "1024"]      # 1 slot; sem UI web; cache de prompt limitado (RAM é curta)
        if c.mmproj is not None:
            cmd += ["--mmproj", str(c.mmproj)]
        if c.reasoning_off:
            cmd += ["--reasoning", "off"]
        return cmd

    # ------------------------------------------------------------- ciclo de vida
    def is_running(self) -> bool:
        if self._adopted:
            return health_ok(self._cfg.llm.host, self._cfg.llm.port)
        return self._proc is not None and self._proc.poll() is None

    def start(self, cancel: CancelToken) -> None:
        """Sobe o servidor (ou adota um já saudável na porta) e só retorna quando ele estiver pronto."""
        c = self._cfg.llm
        if self.is_running():
            return
        if health_ok(c.host, c.port):
            log.info("llama-server já está rodando em %s:%d; vou usá-lo (não será encerrado por mim)", c.host, c.port)
            self._adopted = True
            return
        cmd = self.build_command()
        log_path = self._cfg.paths.logs / "llama-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(log_path, "ab")
        log.info("iniciando llama-server: %s", " ".join(cmd))
        try:
            self._proc = subprocess.Popen(cmd, stdout=self._log_file, stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
                                          cwd=str(self._cfg.paths.llama_bin))
        except OSError as exc:
            self._close_log()
            raise ServerError(f"não consegui iniciar o llama-server: {exc}") from exc
        self._job = _make_kill_on_close_job()
        if self._job is not None and not _k32.AssignProcessToJobObject(self._job, int(self._proc._handle)):  # type: ignore[attr-defined]
            log.warning("não consegui prender o servidor ao Job Object (%s)", ctypes.get_last_error())
        try:
            self._wait_ready(cancel)
        except BaseException:
            self.stop()
            raise

    def _wait_ready(self, cancel: CancelToken) -> None:
        c = self._cfg.llm
        deadline = time.monotonic() + c.startup_timeout_s
        assert self._proc is not None
        while True:
            if cancel.cancelled:
                raise Cancelled(cancel.reason)
            code = self._proc.poll()
            if code is not None:
                raise ServerError(f"o llama-server encerrou na partida (código {code}). Últimas linhas:\n{self._tail_log()}")
            if health_ok(c.host, c.port):
                log.info("llama-server pronto")
                return
            if time.monotonic() > deadline:
                raise ServerError(f"o llama-server não ficou pronto em {c.startup_timeout_s:.0f}s")
            cancel.wait(0.5)

    def stop(self) -> None:
        proc, self._proc = self._proc, None
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
        if self._job is not None:
            _k32.CloseHandle(self._job)      # KILL_ON_JOB_CLOSE garante que nada fica órfão
            self._job = None
        self._adopted = False
        self._close_log()

    # ------------------------------------------------------------- util
    def _tail_log(self, n: int = 8) -> str:
        try:
            lines = (self._cfg.paths.logs / "llama-server.log").read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except OSError:
            return "(sem log)"

    def _close_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None
