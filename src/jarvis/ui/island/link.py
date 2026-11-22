"""Lado do NÚCLEO da ligação com a Ilha (sem Qt: este módulo roda dentro do processo do Jarvis).

A Ilha é um PROCESSO FILHO (`python -I -X utf8 -c ... island --child`). A conversa é JSON por linha nos pipes
stdin/stdout do filho (sem rede, sem soquete):

    núcleo -> Ilha:  {"k": "state"|"transcript"|"reply_text"|"action_step"|"confirm_request"|"confirm_done"|
                           "context_usage"|"yolo"|"mute"|"emergency"|"error"|"mode"|"level"|"quit", "d": {...}}
    Ilha -> núcleo:  {"c": "confirm"|"mute"|"stop"|"settings"|"ready", ...}

Garantias: o núcleo NUNCA espera a Ilha (fila limitada: descarta níveis antigos primeiro; o gravador de pipe é
uma thread própria); se o filho morrer, reinicia com espera crescente e número limitado de tentativas (o Jarvis
segue normalmente sem a Ilha); se o Jarvis morrer, o pipe fecha e o filho encerra sozinho. Textos são truncados e
mascarados antes de sair do núcleo (nada de senha, digitação, conteúdo de arquivo ou de memória).
"""
from __future__ import annotations

import collections
import json
import logging
import math
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

QUEUE_MAX = 200
LEVEL_HZ = 30.0
MAX_RESTARTS = 5
BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 15.0)
HEALTHY_AFTER_S = 60.0                       # o filho que viveu isso zera a conta de reinícios
STALE_MIC_S = 0.3
_CREATE_NO_WINDOW = 0x08000000

# ferramentas cujo texto/resultado pode conter dado sensível: a Ilha só vê o nome
_REDACT_TOOLS = frozenset({"digitar_texto", "lembrar", "editar_memoria", "buscar_memoria", "buscar_conversas", "ler_arquivo",
                           "resumir_conversa", "abrir_conversa", "listar_memorias", "ver_tela"})
_SECRET = re.compile(r"(?i)\b(senha|password|passwd|token|pin|segredo|api[ _-]?key|chave)\b(\s*(?:é|e|:|=|is)?\s*)\S+")


def clean_text(text: Any, limit: int) -> str:
    """Trunca, tira quebras de linha e mascara o que vem depois de 'senha', 'token', 'pin'..."""
    s = " ".join(str(text or "").split())
    s = _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[oculto]", s)
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def sanitize(kind: str, d: dict[str, Any]) -> dict[str, Any] | None:
    """Evento do EventBus -> payload mínimo e seguro para a Ilha (None = não enviar)."""
    if kind == "state":
        return {"state": str(d.get("state", "idle"))}
    if kind == "transcript":
        return {"text": clean_text(d.get("text"), 300)}
    if kind == "reply_text":
        return {"text": clean_text(d.get("text"), 400)}
    if kind == "action_step":
        tool = clean_text(d.get("tool"), 40)
        hide = tool in _REDACT_TOOLS
        return {"tool": tool, "status": str(d.get("status", ""))[:10],
                "text": "" if hide else clean_text(d.get("text"), 90),
                "result": "" if hide else clean_text(d.get("result"), 120)}
    if kind == "confirm_request":
        return {"id": str(d.get("id", ""))[:16], "text": clean_text(d.get("text"), 160),
                "timeout_s": int(d.get("timeout_s") or 15), "risk": int(d.get("risk") or 0)}
    if kind == "confirm_done":
        return {"id": str(d.get("id", ""))[:16]}
    if kind == "context_usage":
        return {"pct": float(d.get("pct", 0))}
    if kind == "mute":
        return {"muted": bool(d.get("muted"))}
    if kind == "emergency":
        return {}
    if kind == "error":
        return {"text": clean_text(d.get("text"), 120)}
    return None                                           # notice, config_applied, session_started...: a Ilha não precisa


def level_of(rms: float) -> float:
    """RMS linear (0..1) -> 0..1 visual (-60..-10 dBFS), a mesma escala do LevelMeter."""
    db = 20.0 * math.log10(max(float(rms), 1e-9))
    return min(1.0, max(0.0, (db + 60.0) / 50.0))


class IslandLink:
    def __init__(self, bus: Any, *, root: Path, log_dir: Path,
                 on_command: Callable[[str, dict[str, Any]], None],
                 tts_rms: Callable[[], float], speaking: Callable[[], bool],
                 yolo_remaining: Callable[[], float], permission_mode: Callable[[], str]) -> None:
        self._bus = bus
        self._root = Path(root)
        self._log_dir = Path(log_dir)
        self._on_command = on_command
        self._tts_rms = tts_rms
        self._speaking = speaking
        self._yolo_remaining = yolo_remaining
        self._permission_mode = permission_mode
        self._stop = threading.Event()
        self._cv = threading.Condition()
        self._q: collections.deque[bytes] = collections.deque()
        self._proc: subprocess.Popen[bytes] | None = None
        self._unsub: Callable[[], None] | None = None
        self._threads: list[threading.Thread] = []
        self._snap: dict[str, Any] = {"state": "idle", "muted": False, "yolo": False, "pct": None}
        self._snap_lock = threading.Lock()
        self._mic = 0.0
        self._mic_at = 0.0
        self._tts_smooth = 0.0
        self._last_level_nonzero = False
        self.restarts = 0
        self.gave_up = False

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        self._unsub = self._bus.subscribe(self._on_bus)
        for name, fn in (("island-super", self._supervise), ("island-writer", self._writer), ("island-levels", self._levels)):
            t = threading.Thread(target=fn, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._enqueue({"k": "quit", "d": {}})
        with self._cv:
            self._cv.notify_all()
        proc = self._proc
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(1.5)
        if proc is not None:
            self._kill(proc)

    @property
    def pid(self) -> int | None:
        p = self._proc
        return p.pid if p is not None and p.poll() is None else None

    # ------------------------------------------------------------------ núcleo -> Ilha
    def _on_bus(self, ev: Any) -> None:                    # thread de despacho do EventBus (própria deste assinante)
        kind, d = ev.kind, ev.data
        if kind == "user_text":                            # texto digitado (run --text) aparece como fala reconhecida
            kind = "transcript"
        if kind == "level":
            if d.get("source") == "mic":
                self._mic, self._mic_at = float(d.get("rms", 0.0)), time.monotonic()
            return                                         # os níveis saem pela thread de 30 Hz
        if kind == "config_applied":                       # o modo de permissão pode ter mudado
            self._enqueue({"k": "mode", "d": {"mode": self._permission_mode()}})
            return
        if kind == "yolo":
            on = bool(d.get("on"))
            with self._snap_lock:
                self._snap["yolo"] = on
            self._enqueue({"k": "yolo", "d": {"on": on, "remaining_s": self._yolo_remaining() if on else 0.0}})
            return
        payload = sanitize(kind, d)
        if payload is None:
            return
        with self._snap_lock:
            if kind == "state":
                self._snap["state"] = payload["state"]
            elif kind == "mute":
                self._snap["muted"] = payload["muted"]
            elif kind == "context_usage":
                self._snap["pct"] = payload["pct"]
        self._enqueue({"k": kind, "d": payload})

    def _snapshot_messages(self) -> list[dict[str, Any]]:
        with self._snap_lock:
            s = dict(self._snap)
        msgs: list[dict[str, Any]] = [{"k": "mode", "d": {"mode": self._permission_mode()}},
                                      {"k": "mute", "d": {"muted": s["muted"]}}]
        if s["yolo"] and self._yolo_remaining() > 0:
            msgs.append({"k": "yolo", "d": {"on": True, "remaining_s": self._yolo_remaining()}})
        if s["pct"] is not None:
            msgs.append({"k": "context_usage", "d": {"pct": s["pct"]}})
        msgs.append({"k": "state", "d": {"state": s["state"]}})
        return msgs

    def _enqueue(self, msg: dict[str, Any]) -> None:
        line = (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        is_level = msg["k"] == "level"
        with self._cv:
            if is_level and self._q and self._q[-1].startswith(b'{"k":"level"'):
                self._q[-1] = line                          # só o último nível interessa
            else:
                if len(self._q) >= QUEUE_MAX:
                    for i, old in enumerate(self._q):       # descarta níveis antigos primeiro, depois o mais antigo
                        if old.startswith(b'{"k":"level"'):
                            del self._q[i]
                            break
                    else:
                        self._q.popleft()
                self._q.append(line)
            self._cv.notify()

    def _writer(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                while not self._q and not self._stop.is_set():
                    self._cv.wait(0.5)
                if self._stop.is_set() and not self._q:
                    return
                line = self._q.popleft() if self._q else None
            proc = self._proc
            if line is None or proc is None or proc.stdin is None or proc.poll() is not None:
                continue                                    # sem filho vivo: descarta (o snapshot cobre o reinício)
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except (OSError, ValueError):
                pass                                        # filho caiu; o supervisor cuida

    def _levels(self) -> None:
        period = 1.0 / LEVEL_HZ
        while not self._stop.wait(period):
            with self._snap_lock:
                st = self._snap["state"]
            now = time.monotonic()
            mic = self._mic if (now - self._mic_at) < STALE_MIC_S else 0.0
            tts = 0.0
            if self._speaking():
                try:
                    tts = level_of(self._tts_rms())        # RMS REAL do que está saindo no alto-falante
                except Exception:  # noqa: BLE001
                    tts = 0.0
            nonzero = mic > 0.001 or tts > 0.001
            if nonzero or self._last_level_nonzero:
                self._enqueue({"k": "level", "d": {"mic": round(mic, 3), "tts": round(tts, 3)}})
            self._last_level_nonzero = nonzero
            if not nonzero and st not in ("listening", "speaking"):
                self._stop.wait(0.15)                       # repouso: acorda menos

    # ------------------------------------------------------------------ processo filho
    def _spawn(self) -> subprocess.Popen[bytes]:
        code = ("import sys; sys.path.insert(0, r'%s'); from jarvis.__main__ import main; "
                "raise SystemExit(main(sys.argv[1:]))" % str(self._root / "src"))
        self._log_dir.mkdir(parents=True, exist_ok=True)
        err_path = self._log_dir / "island-child.log"
        try:
            if err_path.exists() and err_path.stat().st_size > 512_000:
                err_path.write_bytes(b"")
            err = open(err_path, "ab")
        except OSError:
            err = subprocess.DEVNULL                        # type: ignore[assignment]
        try:
            return subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-c", code, "island", "--child"],
                                    cwd=str(self._root), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                    creationflags=_CREATE_NO_WINDOW, close_fds=True)
        finally:
            if err is not subprocess.DEVNULL:
                err.close()

    def _supervise(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                proc = self._spawn()
            except OSError:
                log.exception("não consegui iniciar a Ilha")
                proc = None
            if proc is not None:
                with self._cv:
                    self._q.clear()
                self._proc = proc
                for m in self._snapshot_messages():
                    self._enqueue(m)
                reader = threading.Thread(target=self._read_commands, args=(proc,), name="island-reader", daemon=True)
                reader.start()
                log.info("Ilha iniciada (pid %d)", proc.pid)
                while not self._stop.is_set() and proc.poll() is None:
                    self._stop.wait(0.5)
                if self._stop.is_set():
                    return
                log.warning("a Ilha encerrou (código %s)", proc.returncode)
                if proc.returncode == 0:
                    return                                  # saída normal pedida pela própria Ilha: não insiste
            if time.monotonic() - started > HEALTHY_AFTER_S:
                self.restarts = 0
            self.restarts += 1
            if self.restarts > MAX_RESTARTS:
                self.gave_up = True
                log.error("a Ilha caiu %d vezes; desisti de reiniciar (o Jarvis segue sem ela)", MAX_RESTARTS)
                return
            self._stop.wait(BACKOFF_S[min(self.restarts - 1, len(BACKOFF_S) - 1)])

    def _read_commands(self, proc: subprocess.Popen[bytes]) -> None:
        out = proc.stdout
        if out is None:
            return
        try:
            for raw in out:
                if self._stop.is_set():
                    return
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                    if not isinstance(msg, dict):
                        continue
                    self._on_command(str(msg.get("c", "")), msg)
                except ValueError:
                    continue                                # linha que não é JSON (lixo): ignora
                except Exception:  # noqa: BLE001 - comando com defeito nunca derruba o núcleo
                    log.exception("falha ao tratar comando da Ilha")
        except (OSError, ValueError):
            pass

    @staticmethod
    def _kill(proc: subprocess.Popen[bytes]) -> None:
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(1.0)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(1.5)
            except subprocess.TimeoutExpired:
                proc.kill()
