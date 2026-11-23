"""Terminal integrado: executa comandos, com sessão (pasta e histórico), saída em streaming, tempo limite e cancelamento.

- Cada comando é um processo filho NOSSO (PowerShell, cmd ou Git Bash), dentro de um Job Object do Windows: encerrar = derrubar
  só a árvore que o Eco iniciou (nunca processo alheio, nunca por nome). Terminou normal, o Job é solto sem matar o que o
  comando deixou de propósito em segundo plano (ex.: `Start-Process notepad`); timeout, cancelamento, emergência e fechamento matam tudo.
- A sessão guarda a pasta atual entre comandos (um marcador no fim do script devolve o `cd` feito) e o histórico.
- A saída é redigida (segredos) linha a linha, guardada com limite (começo + fim) e espelhada em `data/terminal/` para o painel.
- O painel (outro processo) conversa por arquivos ASSINADOS em `data/terminal/req/` (HMAC, validade 30 s), no mesmo estilo do YOLO.
"""
from __future__ import annotations

import base64
import codecs
import ctypes
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..core.cancel import CancelToken
from . import policy

log = logging.getLogger(__name__)
audit = logging.getLogger("jarvis.audit")

HISTORY_KEEP = 60
REQUEST_TTL_S = 30.0
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_SUSPENDED = 0x00000004
SHELLS = ("powershell", "cmd", "bash")
SHELL_LABEL = {"powershell": "PowerShell", "cmd": "Prompt de Comando", "bash": "Git Bash"}


class TerminalError(Exception):
    """Falha previsível ao iniciar (shell ausente, comando já rodando...). A mensagem é falável."""


# --------------------------------------------------------------------------- Job Object (só filhos NOSSOS)
class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ro", "wo", "oo", "rb", "wb", "ob")]


class _Basic(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _Extended(ctypes.Structure):
    _fields_ = [("Basic", _Basic), ("Io", _IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll")
_k32.CreateJobObjectW.restype = wintypes.HANDLE
_k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
_k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
_k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
_k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_k32.CloseHandle.argtypes = (wintypes.HANDLE,)
_ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
_KILL_ON_CLOSE = 0x2000


class _Job:
    """Job Object com KILL_ON_JOB_CLOSE: se o Eco morrer, a árvore dele morre junto."""

    def __init__(self) -> None:
        self.h = _k32.CreateJobObjectW(None, None)
        if not self.h:
            raise OSError("CreateJobObject falhou")
        self._flags(_KILL_ON_CLOSE)

    def _flags(self, flags: int) -> None:
        info = _Extended()
        info.Basic.LimitFlags = flags
        if not _k32.SetInformationJobObject(self.h, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("SetInformationJobObject falhou")

    def adopt(self, pid: int) -> None:
        ph = _k32.OpenProcess(0x0001 | 0x0100 | 0x0800, False, pid)          # TERMINATE | SET_QUOTA | SUSPEND_RESUME
        if not ph:
            raise OSError("OpenProcess falhou")
        try:
            if not _k32.AssignProcessToJobObject(self.h, ph):
                raise OSError("AssignProcessToJobObject falhou")
            _ntdll.NtResumeProcess(ph)                                         # nasceu suspenso: só roda já dentro do Job
        finally:
            _k32.CloseHandle(ph)

    def kill(self) -> None:
        if self.h:
            _k32.TerminateJobObject(self.h, 1)

    def release(self, kill: bool) -> None:
        """Fecha o Job. kill=False solta o que sobrou (processo deixado de propósito em segundo plano)."""
        if not self.h:
            return
        try:
            if kill:
                self.kill()
            else:
                self._flags(0)
        except OSError:
            pass
        _k32.CloseHandle(self.h)
        self.h = None


# --------------------------------------------------------------------------- shells
def find_shell(shell: str) -> str | None:
    """Caminho do executável do shell, ou None."""
    from ..core import toolpaths                      # caminhos PERSONALIZADOS (Configurações > Caminhos dos programas) valem primeiro
    if shell == "powershell":
        return toolpaths.exe("powershell") or shutil.which("pwsh") or shutil.which("powershell")
    if shell == "cmd":
        return os.environ.get("ComSpec") or shutil.which("cmd")
    if shell == "bash":
        custom = toolpaths.exe("git_bash")
        if custom:
            return custom
        cands = [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"]
        git = shutil.which("git")
        if git:
            cands.insert(0, str(Path(git).resolve().parent.parent / "bin" / "bash.exe"))
        return next((c for c in cands if Path(c).is_file()), None)      # nunca o bash.exe do WSL (System32)
    return None


def available_shells() -> dict[str, str | None]:
    return {s: find_shell(s) for s in SHELLS}


def _build(shell: str, exe: str, command: str, marker: str, tmp_dir: Path, run_id: str) -> tuple[list[str], Path | None]:
    if shell == "powershell":
        script = ("$ErrorActionPreference='Continue'; $ProgressPreference='SilentlyContinue'\n"
                  "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $OutputEncoding=[Text.Encoding]::UTF8\n"
                  f"{command}\n"
                  "$__ok=$?; $__c=$LASTEXITCODE\n"
                  f"Write-Output (\"{marker}\" + (Get-Location).ProviderPath)\n"
                  "if ($null -ne $__c -and $__c -ne 0) { exit $__c } elseif (-not $__ok) { exit 1 } else { exit 0 }\n")
        enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], None
    if shell == "cmd":
        tmp_dir.mkdir(parents=True, exist_ok=True)
        path = tmp_dir / f"{run_id}.cmd"
        body = f"@echo off\r\nchcp 65001 >nul\r\n{command}\r\nset \"__rc=%errorlevel%\"\r\necho {marker}%CD%\r\nexit /b %__rc%\r\n"
        path.write_bytes(body.encode("utf-8"))
        return [exe, "/d", "/q", "/c", str(path)], path
    script = f"{command}\n__rc=$?\necho \"{marker}$(pwd -W 2>/dev/null || pwd)\"\nexit $__rc\n"
    return [exe, "-c", script], None


# --------------------------------------------------------------------------- saída
class OutputBuffer:
    """Guarda a saída REDIGIDA com limite (começo + fim). Linhas completas são redigidas antes de entrar."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(4096, max_bytes)
        self._head_cap = self.max_bytes * 35 // 100
        self._tail_cap = self.max_bytes - self._head_cap
        self._head: list[str] = []
        self._head_bytes = 0
        self._tail: deque[str] = deque()
        self._tail_bytes = 0
        self.omitted = 0
        self.total = 0
        self._partial = ""
        self._lock = threading.Lock()
        self.on_line: Callable[[str], None] | None = None

    def feed(self, chunk: str) -> None:
        with self._lock:
            data = self._partial + chunk
            lines = data.split("\n")
            self._partial = lines.pop()
            if len(self._partial) > 4000:                    # linha sem fim (barra de progresso): fecha à força
                lines.append(self._partial)
                self._partial = ""
            for ln in lines:
                self._add(policy.redact(ln.rstrip("\r")))

    def finish(self) -> None:
        with self._lock:
            if self._partial:
                self._add(policy.redact(self._partial.rstrip("\r")))
                self._partial = ""

    def _add(self, line: str) -> None:
        n = len(line.encode("utf-8", "replace")) + 1
        self.total += n
        if self.on_line is not None:
            try:
                self.on_line(line)
            except Exception:  # noqa: BLE001
                log.debug("on_line falhou", exc_info=True)
        if self._head_bytes + n <= self._head_cap and not self._tail and not self.omitted:
            self._head.append(line)
            self._head_bytes += n
            return
        self._tail.append(line)
        self._tail_bytes += n
        while self._tail_bytes > self._tail_cap and self._tail:
            old = self._tail.popleft()
            self._tail_bytes -= len(old.encode("utf-8", "replace")) + 1
            self.omitted += 1

    @property
    def truncated(self) -> bool:
        return self.omitted > 0

    def text(self) -> str:
        with self._lock:
            parts = list(self._head)
            if self.omitted:
                parts.append(f"[... {self.omitted} linhas do meio omitidas ...]")
            parts.extend(self._tail)
            if self._partial:
                parts.append(policy.redact(self._partial))
            return "\n".join(parts)


def clip(text: str, limit: int) -> tuple[str, bool]:
    """Corta para `limit` caracteres mantendo começo (40%) e fim (60%); (texto, foi_cortado)."""
    if len(text) <= limit:
        return text, False
    head, tail = int(limit * 0.4), int(limit * 0.6)
    return f"{text[:head]}\n[... {len(text) - head - tail} caracteres omitidos ...]\n{text[-tail:]}", True


# --------------------------------------------------------------------------- execução
@dataclass
class Run:
    id: str
    command: str                       # já redigido (guarda-se só a versão sem segredos)
    shell: str
    cwd: str
    origin: str                        # "agent" | "cloud:<id>" | "manual"
    started: float
    timeout_s: float
    buffer: OutputBuffer
    marker: str = ""
    ended: float = 0.0
    exit_code: int | None = None
    status: str = "running"            # running | ok | error | timeout | killed | blocked
    reason: str = ""
    cwd_end: str = ""
    pid: int = 0
    kill_reason: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    log_name: str = ""

    @property
    def duration(self) -> float:
        return (self.ended or time.time()) - self.started

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "command": self.command, "shell": self.shell, "cwd": self.cwd, "cwd_end": self.cwd_end,
                "origin": self.origin, "started": self.started, "ended": self.ended, "exit": self.exit_code,
                "status": self.status, "reason": self.reason, "bytes": self.buffer.total, "truncated": self.buffer.truncated,
                "log": self.log_name}


def _mac_key(data_dir: Path) -> bytes:
    from ..settings import control                   # mesma chave do YOLO (data/control/yolo.key): só quem acessa a pasta de dados assina
    return control._yolo_key(data_dir)               # noqa: SLF001


def _mac(data_dir: Path, stamp: str, action: str, body: str) -> str:
    msg = f"terminal|{stamp}|{action}|{hashlib.sha256(body.encode('utf-8')).hexdigest()}"
    return hmac.new(_mac_key(data_dir), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def terminal_dir(data_dir: Path) -> Path:
    d = Path(data_dir) / "terminal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def send_request(data_dir: Path, action: str, args: dict[str, Any] | None = None) -> Path:
    """Chamado pelo PAINEL (outro processo): pede 'run' | 'stop' | 'clear' | 'arm_free' | 'disarm_free' ao Eco em execução."""
    from ..settings.tomlio import atomic_write_text
    body = json.dumps(args or {}, ensure_ascii=False, sort_keys=True)
    stamp = str(time.time())
    req = terminal_dir(data_dir) / "req"
    req.mkdir(exist_ok=True)
    path = req / f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.json"
    atomic_write_text(path, json.dumps({"action": action, "args": body, "stamp": stamp, "mac": _mac(Path(data_dir), stamp, action, body)}))
    return path


def read_state(data_dir: Path) -> dict[str, Any] | None:
    try:
        return json.loads((terminal_dir(data_dir) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class TerminalManager:
    """Uma sessão (pasta atual + histórico), um comando por vez. Seguro entre threads."""

    def __init__(self, data_dir: Path, cfg: Config, bus: Any = None) -> None:
        self.data_dir = Path(data_dir)
        self.cfg = cfg
        self.bus = bus
        from .. import config as cfgmod
        self.cfg_loader: Callable[[], Config] = cfgmod.load              # pedidos manuais do painel valem o config.toml de AGORA
        self._lock = threading.RLock()
        self.cwd: str = ""
        self.shell: str = cfg.terminal.shell
        self.history: deque[Run] = deque(maxlen=HISTORY_KEEP)
        self._current: Run | None = None
        self._jobs: dict[str, _Job] = {}
        self._free_until = 0.0
        self._stop = threading.Event()
        self._poller: threading.Thread | None = None
        self._last_state = 0.0
        self._dir = terminal_dir(self.data_dir)
        (self._dir / "runs").mkdir(exist_ok=True)

    # ------------------------------------------------------------- configuração e modo livre
    def update_cfg(self, cfg: Config) -> None:
        self.cfg = cfg

    def free_active(self) -> bool:
        with self._lock:
            return time.time() < self._free_until and self.cfg.terminal.mode == "free"

    def arm_free(self, minutes: int | None = None) -> None:
        """SÓ o painel (pedido assinado de um clique do usuário) chama isto. Nada na ferramenta/voz/nuvem alcança."""
        m = max(1, min(120, int(minutes or self.cfg.terminal.free_minutes)))
        with self._lock:
            self._free_until = time.time() + m * 60
        log.warning("TERMINAL EM MODO LIVRE por %d min (liberado à mão no painel)", m)
        self._write_state(force=True)

    def disarm_free(self, why: str = "desligado") -> None:
        with self._lock:
            was = self._free_until > 0
            self._free_until = 0.0
        if was:
            log.warning("terminal: modo livre desligado (%s)", why)
        self._write_state(force=True)

    def free_remaining_s(self) -> float:
        with self._lock:
            return max(0.0, self._free_until - time.time())

    # ------------------------------------------------------------- iniciar
    def current(self) -> Run | None:
        with self._lock:
            return self._current if self._current and not self._current.done.is_set() else None

    def start(self, command: str, *, shell: str | None, cwd: str | None, origin: str, timeout_s: float | None = None) -> Run:
        cfg = self.cfg
        t = cfg.terminal
        shell = shell or t.shell
        exe = find_shell(shell)
        if exe is None:
            raise TerminalError(f"{SHELL_LABEL.get(shell, shell)} não está instalado neste computador.")
        with self._lock:
            busy = self.current()
            if busy is not None:
                raise TerminalError(f"Já há um comando rodando ({busy.command[:50]}). Cancele ou espere terminar.")
            real, err = policy.resolve_cwd(cwd, self.cwd or None, cfg)
            if real is None:
                raise TerminalError(err[0].upper() + err[1:] + ".")
            run_id = uuid.uuid4().hex[:10]
            marker = f"__JARVIS_CWD_{secrets.token_hex(6)}__"
            buf = OutputBuffer(t.max_output_kb * 1024)
            run = Run(id=run_id, command=policy.redact(command), shell=shell, cwd=str(real), origin=origin, started=time.time(),
                      timeout_s=float(timeout_s or t.timeout_s), buffer=buf, marker=marker, log_name=f"{run_id}.log")
            argv, tmp = _build(shell, exe, command, marker, self._dir / "tmp", run_id)
            try:
                job = _Job()
                proc = subprocess.Popen(argv, cwd=str(real), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env=policy.clean_env(), creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED)
            except OSError as exc:
                if tmp:
                    tmp.unlink(missing_ok=True)
                raise TerminalError(f"Não consegui iniciar o {SHELL_LABEL.get(shell, shell)}: {exc.strerror or exc}") from exc
            try:
                job.adopt(proc.pid)
            except OSError:
                proc.kill()
                job.release(kill=True)
                if tmp:
                    tmp.unlink(missing_ok=True)
                raise TerminalError("Não consegui isolar o comando em um Job do Windows; não executei.") from None
            run.pid = proc.pid
            self._jobs[run.id] = job
            self._current = run
            self.history.append(run)
            self.cwd = self.cwd or str(real)
        self._log_audit("start", run)
        self._publish("start", run)
        self._write_state(force=True)
        threading.Thread(target=self._pump, args=(run, proc, job, tmp), name=f"terminal-{run.id}", daemon=True).start()
        return run

    # ------------------------------------------------------------- bomba de saída
    def _pump(self, run: Run, proc: subprocess.Popen[bytes], job: _Job, tmp: Path | None) -> None:
        log_path = self._dir / "runs" / run.log_name
        cap = self.cfg.terminal.max_output_kb * 1024
        written = [0]
        logf = open(log_path, "w", encoding="utf-8", newline="\n")          # noqa: SIM115

        def on_line(line: str) -> None:
            if written[0] < cap:
                logf.write(line + "\n")
                logf.flush()
                written[0] += len(line) + 1
            self._write_state()

        run.buffer.on_line = on_line
        marker_re = re.compile(re.escape(run.marker) + r"(.*)$")
        dec = codecs.getincrementaldecoder("utf-8")(errors="replace")

        def reader() -> None:
            carry = ""
            assert proc.stdout is not None
            try:
                while True:
                    chunk = proc.stdout.read1(8192)                         # type: ignore[attr-defined]
                    if not chunk:
                        break
                    carry += dec.decode(chunk)
                    *lines, carry = carry.split("\n")
                    for ln in lines:
                        self._feed_line(run, ln, marker_re)
                carry += dec.decode(b"", final=True)
                if carry:
                    self._feed_line(run, carry, marker_re, final=True)
            except (OSError, ValueError):
                pass

        rt = threading.Thread(target=reader, name=f"terminal-read-{run.id}", daemon=True)
        rt.start()
        deadline = time.time() + run.timeout_s
        killed = False
        while proc.poll() is None:
            if run.kill_reason and not killed:
                killed = True
                self._kill(run, job, proc)
            elif time.time() >= deadline and not killed:
                killed = True
                run.kill_reason = "timeout"
                self._kill(run, job, proc)
            time.sleep(0.05)
        rt.join(2.5)                                                       # netos detidos podem segurar o cano: não esperamos
        if rt.is_alive():
            try:
                proc.stdout.close()                                        # type: ignore[union-attr]
            except OSError:
                pass
        run.buffer.finish()
        code = proc.returncode
        with self._lock:
            run.ended = time.time()
            run.exit_code = code
            if run.kill_reason == "timeout":
                run.status, run.reason = "timeout", f"passou de {run.timeout_s:.0f} s e foi encerrado"
            elif run.kill_reason:
                run.status, run.reason = "killed", f"encerrado: {run.kill_reason}"
            else:
                run.status = "ok" if code == 0 else "error"
            if run.status in ("ok", "error") and run.cwd_end:
                self.cwd = run.cwd_end
            if self._current is run:
                self._current = None
        job.release(kill=bool(run.kill_reason))
        self._jobs.pop(run.id, None)
        if tmp:
            tmp.unlink(missing_ok=True)
        try:
            logf.write(f"\n[fim: {run.status}, código {run.exit_code}]\n")
            logf.close()
        except OSError:
            pass
        run.done.set()
        self._log_audit("end", run)
        self._publish("end", run)
        self._write_state(force=True)
        self._trim_logs()

    def _feed_line(self, run: Run, line: str, marker_re: re.Pattern[str], final: bool = False) -> None:
        m = marker_re.search(line)
        if m:
            path = m.group(1).strip()
            before = line[:m.start()]
            if before.strip():
                run.buffer.feed(before + "\n")
            roots = policy._norm_roots(self.cfg.terminal.roots)         # noqa: SLF001
            try:
                real = str(Path(path).resolve())
            except OSError:
                real = path
            if path and policy._within(real, roots):                    # noqa: SLF001
                run.cwd_end = real
            elif path:
                run.reason = f"o comando terminou em {path[:60]}, fora das pastas permitidas; a sessão voltou para {run.cwd}"
                run.cwd_end = run.cwd
            return
        run.buffer.feed(line + ("" if final else "\n"))

    @staticmethod
    def _kill(run: Run, job: _Job, proc: subprocess.Popen[bytes]) -> None:
        job.kill()
        try:
            proc.kill()
        except OSError:
            pass
        if proc.poll() is None:                                          # plano B: SÓ o pid que nós iniciamos, com a árvore
            subprocess.run(["taskkill", "/PID", str(run.pid), "/T", "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW, check=False)

    # ------------------------------------------------------------- esperar, cancelar, consultar
    def wait(self, run: Run, seconds: float, cancel: CancelToken | None = None) -> bool:
        """Espera até `seconds`. Se `cancel` disparar, derruba o comando. True = terminou."""
        end = time.time() + seconds
        while not run.done.is_set():
            if cancel is not None and cancel.cancelled:
                self.cancel_run(run.id, "cancelado pelo usuário")
                run.done.wait(3.0)
                return run.done.is_set()
            if time.time() >= end:
                return False
            run.done.wait(0.05)
        return True

    def cancel_run(self, run_id: str | None = None, reason: str = "cancelado") -> bool:
        with self._lock:
            run = self._current if (run_id is None or (self._current and self._current.id == run_id)) else None
        if run is None or run.done.is_set():
            return False
        run.kill_reason = reason
        return True

    def kill_all(self, reason: str) -> int:
        """Emergência/encerramento: derruba o que o terminal iniciou (e só isso)."""
        n = 0
        with self._lock:
            run = self._current
        if run is not None and not run.done.is_set():
            run.kill_reason = reason
            n = 1
        self.disarm_free(reason)
        return n

    def get(self, run_id: str | None = None) -> Run | None:
        with self._lock:
            if run_id is None:
                return self.history[-1] if self.history else None
            return next((r for r in self.history if r.id == run_id), None)

    def runs(self, n: int = 10) -> list[Run]:
        with self._lock:
            return list(self.history)[-max(1, n):]

    def clear_history(self) -> None:
        with self._lock:
            keep = [r for r in self.history if not r.done.is_set()]
            self.history.clear()
            self.history.extend(keep)
        for f in (self._dir / "runs").glob("*.log"):
            if not any(f.name == r.log_name for r in keep):
                f.unlink(missing_ok=True)
        self._write_state(force=True)

    # ------------------------------------------------------------- estado para o painel e auditoria
    def _publish(self, phase: str, run: Run) -> None:
        if self.bus is not None:
            try:
                self.bus.publish("terminal", phase=phase, run=run.id, command=run.command[:120], status=run.status,
                                 exit=run.exit_code, origin=run.origin)
            except Exception:  # noqa: BLE001
                log.debug("não consegui publicar o evento do terminal", exc_info=True)

    @staticmethod
    def _log_audit(phase: str, run: Run) -> None:
        audit.info(json.dumps({"event": f"terminal_{phase}", "run": run.id, "origin": run.origin, "shell": run.shell, "cwd": run.cwd,
                               "command": run.command[:400], "exit": run.exit_code, "status": run.status,
                               "duration_s": round((run.ended or time.time()) - run.started, 2) if phase == "end" else None,
                               "bytes": run.buffer.total if phase == "end" else None}, ensure_ascii=False))

    def state(self) -> dict[str, Any]:
        with self._lock:
            cur = self.current()
            return {"updated": time.time(), "pid": os.getpid(), "mode": self.cfg.terminal.mode, "free_until": self._free_until,
                    "shell": self.shell, "cwd": self.cwd, "running": cur.id if cur else None,
                    "roots": list(self.cfg.terminal.roots), "shells": {k: bool(v) for k, v in available_shells().items()},
                    "runs": [r.summary() for r in list(self.history)[-HISTORY_KEEP:]]}

    def _write_state(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_state < 0.4:
            return
        self._last_state = now
        try:
            from ..settings.tomlio import atomic_write_text
            atomic_write_text(self._dir / "state.json", json.dumps(self.state(), ensure_ascii=False))
        except OSError:
            log.debug("não consegui gravar o estado do terminal", exc_info=True)

    def _trim_logs(self) -> None:
        keep = {r.log_name for r in self.history}
        for f in (self._dir / "runs").glob("*.log"):
            if f.name not in keep:
                f.unlink(missing_ok=True)

    # ------------------------------------------------------------- pedidos assinados do painel
    def start_poller(self) -> None:
        if self._poller is not None:
            return
        self._poller = threading.Thread(target=self._poll, name="terminal-poll", daemon=True)
        self._poller.start()

    def _poll(self) -> None:
        req_dir = self._dir / "req"
        req_dir.mkdir(exist_ok=True)
        beat = 0.0
        while not self._stop.wait(0.35):
            try:
                for f in sorted(req_dir.glob("*.json")):
                    self._handle_request(f)
                if time.time() - beat > 2.0:
                    beat = time.time()
                    if self._free_until and time.time() >= self._free_until:
                        self.disarm_free("tempo esgotado")
                    self._write_state(force=True)
            except Exception:  # noqa: BLE001 - o vigia nunca morre
                log.exception("vigia do terminal falhou")

    def _handle_request(self, f: Path) -> None:
        taken = f.with_suffix(".taken")
        try:
            os.replace(f, taken)
            raw = json.loads(taken.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        finally:
            taken.unlink(missing_ok=True)
        action, body, stamp, mac = str(raw.get("action", "")), str(raw.get("args", "{}")), str(raw.get("stamp", "")), str(raw.get("mac", ""))
        try:
            fresh = time.time() - float(stamp) <= REQUEST_TTL_S
            valid = fresh and hmac.compare_digest(mac, _mac(self.data_dir, stamp, action, body))
        except (ValueError, OSError):
            valid = False
        if not valid:
            log.warning("pedido do terminal ignorado (assinatura inválida ou vencido): %s", action)
            return
        args = json.loads(body)
        if action == "stop":
            self.cancel_run(args.get("run"), "parado no painel")
        elif action == "clear":
            self.clear_history()
        elif action == "arm_free":
            self.arm_free(int(args.get("minutes") or 0) or None)
        elif action == "disarm_free":
            self.disarm_free("painel")
        elif action == "run":
            self._manual_run(str(args.get("command", "")), args.get("shell"), args.get("cwd"))

    def _manual_run(self, command: str, shell: str | None, cwd: str | None) -> None:
        """Comando digitado pelo usuário no painel: vale o modo (desligado recusa), o bloqueio fixo e as pastas; sem confirmação."""
        try:
            self.cfg = self.cfg_loader()
        except Exception:  # noqa: BLE001 - config inválida: segue com a última boa
            pass
        t = self.cfg.terminal
        why = ""
        verdict = policy.analyze(command, self.cfg, cwd or self.cwd or None)
        if t.mode == "off":
            why = "o terminal está desligado (Configurações > Terminal)"
        elif verdict.blocked:
            why = f"bloqueado: {verdict.blocked}"
        if not why:
            try:
                self.start(command, shell=shell if shell in SHELLS else None, cwd=cwd, origin="manual")
                return
            except TerminalError as exc:
                why = str(exc)
        run = Run(id=uuid.uuid4().hex[:10], command=policy.redact(command), shell=shell or t.shell, cwd=cwd or self.cwd or "",
                  origin="manual", started=time.time(), timeout_s=0, buffer=OutputBuffer(4096), status="blocked", reason=why)
        run.ended = run.started
        run.done.set()
        with self._lock:
            self.history.append(run)
        self._log_audit("end", run)
        self._write_state(force=True)

    def close(self) -> None:
        self._stop.set()
        self.kill_all("encerramento do Eco")


_MANAGER: TerminalManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager(cfg: Config, bus: Any = None, *, start_poller: bool = True) -> TerminalManager:
    """Gerenciador único do processo (o registro de ferramentas e o app compartilham o mesmo)."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None or _MANAGER.data_dir != Path(cfg.paths.data):
            if _MANAGER is not None:
                _MANAGER.close()
            _MANAGER = TerminalManager(Path(cfg.paths.data), cfg, bus)
            if start_poller:
                _MANAGER.start_poller()
        else:
            _MANAGER.update_cfg(cfg)
            if bus is not None and _MANAGER.bus is None:
                _MANAGER.bus = bus
        return _MANAGER
