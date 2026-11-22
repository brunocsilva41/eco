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
import os
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
        self._key = secrets.token_urlsafe(32)          # só em memória/arquivo temporário privado; muda a cada execução
        self._key_file = _private_dir() / f"llama-key-{os.getpid()}.txt"
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._life = CancelToken()                     # cancela partidas em andamento quando o app encerra (N-16)
        self._monitor: threading.Thread | None = None
        self._restarts: list[float] = []
        self._force_cpu = False                        # a GPU falhou na partida e o modo é "auto": roda na CPU

    @property
    def api_key(self) -> str:
        return self._key

    # ------------------------------------------------------------- dispositivo
    def _ngl(self) -> int:
        c = self._cfg.llm
        return 0 if (c.device == "cpu" or self._force_cpu) else c.ngl

    @property
    def device_in_use(self) -> str:
        return "cpu" if self._ngl() == 0 else "gpu"

    # ------------------------------------------------------------- comando
    def build_command(self) -> list[str]:
        c = self._cfg.llm
        exe = self._cfg.paths.llama_bin / "llama-server.exe"
        problems = [f"não existe: {p}" for p in (exe, c.model) if not Path(p).is_file()]
        if c.mmproj is not None and not Path(c.mmproj).is_file():
            problems.append(f"não existe: {c.mmproj}")
        if problems:
            raise ServerError("; ".join(problems))
        cmd = [str(exe), "-m", str(c.model), "-ngl", str(self._ngl()), "-c", str(c.ctx),
               "--host", c.host, "--port", str(c.port), "--jinja", "--api-key-file", str(self._key_file),
               "-np", "1", "--no-webui", "-cram", "1024"]      # chave por ARQUIVO (a linha de comando é visível a outros processos)
        #                                                       1 slot; sem UI web; cache de prompt limitado (RAM é curta)
        if self._ngl() >= 99:
            cmd += ["-t", "2"]                          # tudo na GPU: 2 threads dão a mesma velocidade e metade do CPU (medido: 56% -> 32%)
        if not c.mmap:
            cmd += ["-lm", "none"]                      # sem mmap: com tudo na GPU a RAM do servidor cai ~2,3 GB (medido)
        if c.sleep_idle_s > 0:
            cmd += ["--sleep-idle-seconds", str(c.sleep_idle_s)]   # ocioso: descarrega modelo e KV (VRAM/RAM livres); acorda no 1º pedido
        if c.mmproj is not None:
            cmd += ["--mmproj", str(c.mmproj)]
            if c.mmproj_device == "cpu" or self._ngl() == 0:
                cmd += ["--no-mmproj-offload"]          # visão no processador (escolha do usuário ou GPU indisponível)
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
        self._life = CancelToken()                     # o stop() cancela este token e interrompe qualquer partida em curso
        try:
            self._spawn(cancel)
        except ServerError as exc:
            if c.device == "auto" and self._ngl() > 0 and not cancel.cancelled and "encerrou na partida" in str(exc):
                log.warning("o modelo não subiu na GPU (%s); tentando na CPU", str(exc).splitlines()[0][:120])
                self._force_cpu = True
                self._on_event("gpu_fallback", "A placa de vídeo falhou; o modelo de linguagem está rodando no processador (bem mais lento).")
                self._spawn(cancel)
            else:
                raise
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
            self._write_key_file()
            log_file = open(log_path, "ab")
            log.info("iniciando llama-server (porta %d, contexto %d)", self._cfg.llm.port, self._cfg.llm.ctx)
            proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW, cwd=str(self._cfg.paths.llama_bin))
            job = _make_kill_on_close_job()
            _assign_to_job(job, proc.pid)
            with self._lock:
                self._proc, self._job, self._log_file = proc, job, log_file
            if self._stopping.is_set():                # stop() chegou durante a partida: não deixa servidor para trás
                raise Cancelled("encerrando")
            self._wait_ready(proc, cancel)
            self._verify_identity()
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
        finally:
            self._remove_key_file()                    # o servidor já leu a chave; o arquivo não precisa ficar

    def _write_key_file(self) -> None:
        """Chave em arquivo temporário no perfil do usuário (privado por padrão no Windows), apagado depois da partida."""
        try:
            self._key_file.parent.mkdir(parents=True, exist_ok=True)
            self._key_file.write_text(self._key, encoding="ascii")
        except OSError as exc:
            raise ServerError(f"não consegui gravar o arquivo temporário da chave do servidor: {exc}") from exc

    def _remove_key_file(self) -> None:
        try:
            self._key_file.unlink(missing_ok=True)
        except OSError:
            log.warning("não consegui apagar o arquivo temporário da chave")

    def _verify_identity(self) -> None:
        """Garante que quem respondeu é O NOSSO servidor: uma chamada com chave errada TEM de ser recusada (401/403).
        Um impostor que tomou a porta (e não confere a chave) aceitaria e receberia a chave no primeiro pedido."""
        c = self._cfg.llm
        conn = http.client.HTTPConnection(c.host, c.port, timeout=5.0)
        try:
            body = json.dumps({"messages": [{"role": "user", "content": "."}], "max_tokens": 1})
            conn.request("POST", "/v1/chat/completions", body,
                         {"Content-Type": "application/json", "Authorization": "Bearer chave-errada-de-verificacao"})
            status = conn.getresponse().status
        except (OSError, http.client.HTTPException) as exc:
            raise ServerError(f"não consegui verificar a identidade do servidor: {exc}") from exc
        finally:
            conn.close()
        if status not in (401, 403):
            raise ServerError(f"o servidor na porta {c.port} aceitou uma chave inválida (resposta {status}); "
                              "não é o llama-server do Jarvis. Recuso usar.")

    def _wait_ready(self, proc: subprocess.Popen[bytes], cancel: CancelToken) -> None:
        c = self._cfg.llm
        deadline = time.monotonic() + c.startup_timeout_s
        while True:
            if cancel.cancelled or self._life.cancelled:
                raise Cancelled(cancel.reason or self._life.reason)
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
        """Supervisão: o servidor DEVE estar de pé até o stop(). Se cair, reinicia com recuo (2, 4, 8 s) e limite de
        tentativas por janela de tempo; reinício que falha também conta e é tentado de novo. Só desiste (e avisa) no teto."""
        while not self._stopping.wait(2.0):
            proc = self._proc
            if proc is not None and proc.poll() is None:
                continue                                           # saudável
            code = proc.returncode if proc is not None else None
            now = time.monotonic()
            self._restarts = [t for t in self._restarts if now - t < RESTART_WINDOW_S]
            if len(self._restarts) >= RESTART_LIMIT:
                log.error("llama-server fora do ar (código %s) e já houve %d tentativas; desisto", code, RESTART_LIMIT)
                self._on_event("llm_dead", "O modelo de linguagem caiu e não voltou. Reinicie o Jarvis.")
                return
            self._restarts.append(now)
            attempt = len(self._restarts)
            log.error("llama-server fora do ar (código %s); tentativa %d/%d", code, attempt, RESTART_LIMIT)
            self._on_event("llm_restarting", "O modelo de linguagem caiu; estou reiniciando.")
            if self._stopping.wait(2.0 * 2 ** (attempt - 1)):      # recuo exponencial, cancelável pelo stop()
                return
            try:
                self._release_dead()
                self._spawn(CancelToken())
                self._on_event("llm_restarted", "Modelo de linguagem de volta.")
            except Cancelled:
                return
            except Exception as exc:  # noqa: BLE001 - a falha conta como tentativa e o laço tenta de novo
                log.error("não consegui reiniciar o llama-server (tentativa %d): %s", attempt, exc)

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
        self._life.cancel("encerrando")                # interrompe partida/reinício em andamento
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


def _private_dir() -> Path:
    """Pasta temporária no perfil do usuário (o Windows a protege por padrão), nunca dentro de F:\\Jarvis\\logs."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Jarvis" / "run"


def _rotate(path: Path) -> None:
    """Rotação simples do log do servidor: passou de ~5 MB, vira .1 (o antigo .1 é descartado)."""
    try:
        if path.exists() and path.stat().st_size > LOG_ROTATE_BYTES:
            backup = path.with_suffix(".log.1")
            backup.unlink(missing_ok=True)
            path.rename(backup)
    except OSError:
        log.warning("não consegui rotacionar %s", path)
