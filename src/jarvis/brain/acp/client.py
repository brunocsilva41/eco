"""Cliente ACP (Agent Client Protocol) em Python puro: JSON-RPC 2.0, uma mensagem JSON por linha, sobre stdio de um processo filho.

Fluxo (protocolo v1): initialize -> [authenticate] -> session/new -> session/prompt (com session/update chegando em
streaming) -> resposta com stopReason. O AGENTE também faz pedidos ao cliente: session/request_permission (decidido por
`on_permission`), fs/* e terminal/* (este cliente NÃO anuncia essas capacidades e responde "método não suportado": o agente
nunca lê nem escreve arquivos, nem roda comandos, por nosso intermédio).

Garantias:
- tempo máximo por pedido e por turno (`AcpTimeout`), com `session/cancel` antes de desistir;
- cancelamento cooperativo (`CancelToken` do Eco) -> `session/cancel`, e se o agente não responder em poucos segundos o
  processo é encerrado (só o NOSSO filho e a árvore dele, por PID);
- processo morto/travado vira `AcpError` e pode ser reiniciado criando outro `AcpClient` (quem decide é o `CloudBrain`);
- nada de segredo em log: `env` e cabeçalhos de MCP nunca são impressos, e a saída de erro do agente só fica em memória.
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ...core.cancel import CancelToken

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
AUTH_REQUIRED = -32000                     # código usado pelos agentes para "faça login antes"
METHOD_NOT_FOUND = -32601
CANCEL_GRACE_S = 5.0                       # depois de session/cancel, quanto esperar o stopReason antes de matar o processo
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200


class AcpError(Exception):
    def __init__(self, message: str, code: int | None = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class AcpTimeout(AcpError):
    pass


class AcpCancelled(AcpError):
    pass


class AcpAuthRequired(AcpError):
    """O agente existe mas não tem login (assinatura/chave): o Eco não faz login por você."""


@dataclass
class PromptResult:
    text: str                                          # só a resposta final do agente (sem "pensamentos")
    stop_reason: str
    tool_calls: list[dict[str, str]] = field(default_factory=list)   # {"title","kind","status"} para auditoria (sem conteúdo)


PermissionHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _cap(text: str, n: int = 300) -> str:
    return text if len(text) <= n else text[:n] + "…"


class AcpClient:
    """Uma conexão com UM processo de agente. Não é reentrante para dois `prompt` simultâneos na mesma sessão."""

    def __init__(self, argv: list[str], cwd: Path, env: "dict[str, str | None] | None" = None, *,
                 on_permission: PermissionHandler | None = None, name: str = "acp") -> None:
        self.argv = list(argv)
        self.cwd = Path(cwd).resolve()
        self._env = env
        self._on_permission = on_permission
        self.name = name
        self._proc: subprocess.Popen[bytes] | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, tuple[threading.Event, dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._wlock = threading.Lock()
        self._closed = threading.Event()
        self._stderr_tail: deque[str] = deque(maxlen=30)
        self._collect: dict[str, dict[str, Any]] = {}     # sessionId -> {"chunks": [...], "tools": {...}}
        self.agent_info: dict[str, Any] = {}
        self.agent_caps: dict[str, Any] = {}
        self.auth_methods: list[dict[str, Any]] = []
        self.session_id: str | None = None
        self.session_info: dict[str, Any] = {}

    # ------------------------------------------------------------------ processo
    def start(self) -> None:
        if self._proc is not None:
            raise AcpError("o agente já foi iniciado")
        self.cwd.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        for k, v in (self._env or {}).items():                    # valor None = remover a variável herdada
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        flags = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            self._proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          cwd=str(self.cwd), env=env, creationflags=flags)
        except OSError as exc:
            raise AcpError(f"não consegui iniciar {self.name}: {exc}") from exc
        threading.Thread(target=self._read_loop, name=f"acp-{self.name}-out", daemon=True).start()
        threading.Thread(target=self._err_loop, name=f"acp-{self.name}-err", daemon=True).start()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and not self._closed.is_set()

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail)

    def close(self) -> None:
        """Encerra o agente e a árvore de processos dele (só o PID que NÓS iniciamos)."""
        self._closed.set()
        proc = self._proc
        self._fail_all("conexão encerrada")
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(2.0)
        except subprocess.TimeoutExpired:
            self._kill_tree(proc)
        for pipe in (proc.stdout, proc.stderr):                  # libera os descritores (a thread leitora termina no EOF)
            try:
                if pipe:
                    pipe.close()
            except OSError:
                pass

    @staticmethod
    def _kill_tree(proc: "subprocess.Popen[bytes]") -> None:
        if proc.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10,
                               creationflags=_CREATE_NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            proc.kill()
        except OSError:
            pass

    # ------------------------------------------------------------------ E/S
    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("[%s] linha não-JSON ignorada: %s", self.name, _cap(line, 120))
                    continue
                if isinstance(msg, dict):
                    self._dispatch(msg)
        except (OSError, ValueError):
            pass
        finally:
            self._closed.set()
            self._fail_all("o agente encerrou")

    def _err_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stderr is not None
        try:
            for raw in proc.stderr:
                self._stderr_tail.append(_cap(raw.decode("utf-8", "replace").rstrip(), 300))
        except (OSError, ValueError):
            pass

    def _send(self, obj: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or not self.alive:
            raise AcpError("o agente não está rodando")
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self._wlock:
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except (OSError, ValueError) as exc:
                raise AcpError(f"falha ao falar com o agente: {exc}") from exc

    def _fail_all(self, why: str) -> None:
        with self._lock:
            pend, self._pending = self._pending, {}
        for ev, box in pend.values():
            box.setdefault("error", {"code": -32099, "message": why})
            ev.set()

    # ------------------------------------------------------------------ despacho
    def _dispatch(self, msg: dict[str, Any]) -> None:
        if "method" in msg:
            if "id" in msg:                                        # pedido do agente ao cliente
                threading.Thread(target=self._serve_request, args=(msg,), name="acp-req", daemon=True).start()
            else:
                self._notification(msg["method"], msg.get("params") or {})
            return
        mid = msg.get("id")
        with self._lock:
            item = self._pending.pop(mid, None) if isinstance(mid, int) else None
        if item is None:
            return
        ev, box = item
        if "error" in msg:
            box["error"] = msg["error"] if isinstance(msg["error"], dict) else {"code": -32603, "message": str(msg["error"])}
        else:
            box["result"] = msg.get("result")
        ev.set()

    def _notification(self, method: str, params: dict[str, Any]) -> None:
        if method != "session/update":
            return
        sid = str(params.get("sessionId", ""))
        upd = params.get("update") or {}
        kind = upd.get("sessionUpdate")
        col = self._collect.get(sid)
        if col is None:
            return
        if kind == "agent_message_chunk":
            content = upd.get("content") or {}
            if content.get("type") == "text":
                col["chunks"].append(str(content.get("text", "")))
        elif kind in ("tool_call", "tool_call_update"):
            tid = str(upd.get("toolCallId", ""))
            rec = col["tools"].setdefault(tid, {"title": "", "kind": "", "status": ""})
            for k in ("title", "kind", "status"):
                if upd.get(k):
                    rec[k] = str(upd[k])

    def _serve_request(self, msg: dict[str, Any]) -> None:
        rid, method, params = msg["id"], msg["method"], msg.get("params") or {}
        try:
            if method == "session/request_permission":
                if self._on_permission is None:
                    result: dict[str, Any] = {"outcome": {"outcome": "cancelled"}}
                else:
                    result = self._on_permission(params)
                self._send({"jsonrpc": "2.0", "id": rid, "result": result})
                return
            # fs/* e terminal/*: NEGADOS por construção (capacidades não anunciadas)
            log.warning("[%s] pedido do agente recusado: %s", self.name, method)
            self._send({"jsonrpc": "2.0", "id": rid,
                        "error": {"code": METHOD_NOT_FOUND, "message": f"o cliente Eco não oferece {method}"}})
        except AcpError:
            pass
        except Exception:  # noqa: BLE001 - a fronteira do pedido nunca derruba o leitor
            log.exception("[%s] falha atendendo %s", self.name, method)
            try:
                self._send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": "erro interno do cliente"}})
            except AcpError:
                pass

    # ------------------------------------------------------------------ chamadas
    def request(self, method: str, params: dict[str, Any], timeout_s: float = 30.0,
                cancel: CancelToken | None = None) -> Any:
        rid = next(self._ids)
        ev = threading.Event()
        box: dict[str, Any] = {}
        with self._lock:
            self._pending[rid] = (ev, box)
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            deadline = time.monotonic() + timeout_s
            while not ev.wait(0.05):
                if cancel is not None and cancel.cancelled:
                    raise AcpCancelled(cancel.reason or "cancelado")
                if time.monotonic() >= deadline:
                    raise AcpTimeout(f"{method} passou de {timeout_s:.0f}s")
                if not self.alive and not ev.is_set():
                    raise AcpError("o agente encerrou")
        finally:
            with self._lock:
                self._pending.pop(rid, None)
        if "error" in box:
            err = box["error"]
            code = err.get("code")
            text = str(err.get("message", "erro"))
            if code == AUTH_REQUIRED or "auth" in text.lower() and "required" in text.lower():
                raise AcpAuthRequired(text, code, err.get("data"))
            raise AcpError(text, code, err.get("data"))
        return box.get("result")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def initialize(self, timeout_s: float = 30.0) -> dict[str, Any]:
        res = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
            "clientInfo": {"name": "eco-local", "title": "Eco local", "version": "1"},
        }, timeout_s) or {}
        self.agent_info = res.get("agentInfo") or {}
        self.agent_caps = res.get("agentCapabilities") or {}
        self.auth_methods = list(res.get("authMethods") or [])
        return res

    def authenticate(self, method_id: str, timeout_s: float = 60.0) -> None:
        self.request("authenticate", {"methodId": method_id}, timeout_s)

    def new_session(self, cwd: Path, mcp_servers: list[dict[str, Any]], timeout_s: float = 30.0) -> str:
        res = self.request("session/new", {"cwd": str(Path(cwd).resolve()), "mcpServers": mcp_servers}, timeout_s) or {}
        sid = res.get("sessionId")
        if not isinstance(sid, str) or not sid:
            raise AcpError("o agente não devolveu sessionId")
        self.session_id = sid
        self.session_info = res                                       # models / configOptions / modes que o agente anunciar
        return sid

    # ------------------------------------------------------------------ modelos anunciados pelo agente
    def available_models(self) -> tuple[str, list[tuple[str, str]]]:
        """(modelo atual, [(id, nome)]) a partir de `models` (ACP) ou `configOptions[id=model]`. Vazio se o agente não anuncia."""
        info = self.session_info or {}
        models = info.get("models") or {}
        out = [(str(m.get("modelId")), str(m.get("name") or m.get("modelId"))) for m in models.get("availableModels", []) if m.get("modelId")]
        cur = str(models.get("currentModelId") or "")
        if not out:
            for opt in info.get("configOptions") or []:
                if opt.get("id") == "model" or opt.get("category") == "model":
                    out = [(str(o.get("value")), str(o.get("name") or o.get("value"))) for o in opt.get("options", []) if o.get("value")]
                    cur = str(opt.get("currentValue") or cur)
        return cur, out

    def set_model(self, model_id: str, timeout_s: float = 10.0) -> None:
        """Troca o modelo da sessão: `session/set_config_option` (se o agente anuncia a opção) ou `session/set_model`."""
        sid = self.session_id
        if not sid:
            raise AcpError("sem sessão")
        has_opt = any(o.get("id") == "model" or o.get("category") == "model" for o in (self.session_info.get("configOptions") or []))
        errors: list[AcpError] = []
        if has_opt:
            try:
                self.request("session/set_config_option", {"sessionId": sid, "configId": "model", "value": model_id}, timeout_s)
                return
            except AcpError as exc:                                   # o formato do valor varia entre agentes (ex.: Codex: modelo[esforço])
                errors.append(exc)
        try:
            self.request("session/set_model", {"sessionId": sid, "modelId": model_id}, timeout_s)
        except AcpError as exc:
            raise (errors[0] if errors else exc) from exc

    def supports_http_mcp(self) -> bool:
        return bool((self.agent_caps.get("mcpCapabilities") or {}).get("http"))

    def prompt(self, text: str, cancel: CancelToken, timeout_s: float) -> PromptResult:
        """Um turno completo. Só texto vai ao agente. Cancelar/estourar o tempo manda `session/cancel` antes de desistir."""
        sid = self.session_id
        if not sid:
            raise AcpError("sem sessão")
        col: dict[str, Any] = {"chunks": [], "tools": {}}
        self._collect[sid] = col
        rid = next(self._ids)
        ev = threading.Event()
        box: dict[str, Any] = {}
        with self._lock:
            self._pending[rid] = (ev, box)
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": "session/prompt",
                        "params": {"sessionId": sid, "prompt": [{"type": "text", "text": text}]}})
            deadline = time.monotonic() + timeout_s
            sent_cancel_at: float | None = None
            reason = ""
            while not ev.wait(0.05):
                if not self.alive and not ev.is_set():
                    raise AcpError("o agente encerrou durante o pedido")
                if sent_cancel_at is None:
                    if cancel.cancelled:
                        reason = "cancel"
                    elif time.monotonic() >= deadline:
                        reason = "timeout"
                    if reason:
                        try:
                            self.notify("session/cancel", {"sessionId": sid})
                        except AcpError:
                            pass
                        sent_cancel_at = time.monotonic()
                elif time.monotonic() - sent_cancel_at > CANCEL_GRACE_S:
                    self.close()                                    # não respondeu ao cancelamento: encerra o processo
                    break
            if reason:
                raise (AcpCancelled(cancel.reason or "cancelado") if reason == "cancel"
                       else AcpTimeout(f"a nuvem passou de {timeout_s:.0f}s"))
        finally:
            with self._lock:
                self._pending.pop(rid, None)
            self._collect.pop(sid, None)
        if "error" in box:
            err = box["error"]
            code, msg = err.get("code"), str(err.get("message", "erro"))
            if code == AUTH_REQUIRED:
                raise AcpAuthRequired(msg, code, err.get("data"))
            raise AcpError(msg, code, err.get("data"))
        res = box.get("result") or {}
        return PromptResult("".join(col["chunks"]).strip(), str(res.get("stopReason", "")), list(col["tools"].values()))
