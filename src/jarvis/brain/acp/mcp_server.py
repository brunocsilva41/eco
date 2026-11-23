"""Servidor MCP local (somente loopback) que expõe as ferramentas do Eco ao agente da nuvem.

Transporte: "Streamable HTTP" no modo mais simples (POST /mcp com uma mensagem JSON-RPC, resposta JSON; sem SSE).
Defesas: escuta só em 127.0.0.1 (porta efêmera); exige `Authorization: Bearer <token aleatório da sessão>`; recusa `Host`
e `Origin` que não sejam loopback (DNS rebinding); sem token em log; fecha junto com o cérebro. NÃO executa nada por conta
própria: toda chamada vai ao `executor`, que usa o ToolRegistry (mesmas travas e confirmações) e só enxerga as ferramentas
que a política deixou visíveis para o agente.
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

log = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 256 * 1024


@dataclass(frozen=True)
class McpToolResult:
    ok: bool
    text: str
    image: bytes | None = None
    image_mime: str = "image/jpeg"


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    schema: dict[str, Any]


Lister = Callable[[], list[McpTool]]
Executor = Callable[[str, dict[str, Any]], McpToolResult]


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:     # conexão cortada pelo agente: sem traceback no console
        log.debug("conexão MCP encerrada pelo agente: %s", client_address)


class LoopbackMcpServer:
    def __init__(self, lister: Lister, executor: Executor) -> None:
        self._lister = lister
        self._executor = executor
        self.token = secrets.token_urlsafe(32)
        self._httpd: _QuietServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        assert self._httpd is not None
        return int(self._httpd.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def start(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "EcoMCP"

            def log_message(self, fmt: str, *args: Any) -> None:     # sem log de acesso (não vazar nada)
                return

            def _reply(self, code: int, body: bytes = b"", ctype: str = "application/json") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _guard(self) -> bool:
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
                origin = self.headers.get("Origin")
                if host not in ("127.0.0.1", "localhost", "[::1]") or (
                        origin and "127.0.0.1" not in origin and "localhost" not in origin):
                    self._reply(403, b'{"error":"forbidden"}')
                    return False
                auth = self.headers.get("Authorization", "")
                if not hmac.compare_digest(auth.encode(), f"Bearer {outer.token}".encode()):
                    self._reply(401, b'{"error":"unauthorized"}')
                    return False
                return True

            def do_GET(self) -> None:  # noqa: N802
                self._reply(405, b'{"error":"use POST"}')

            def do_DELETE(self) -> None:  # noqa: N802
                self._reply(200, b"{}")

            def do_POST(self) -> None:  # noqa: N802
                if not self._guard():
                    return
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if n <= 0 or n > MAX_BODY:
                        self._reply(413, b'{"error":"too large"}')
                        return
                    msg = json.loads(self.rfile.read(n).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._reply(400, b'{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}')
                    return
                reply = outer._handle(msg)
                if reply is None:
                    self._reply(202)
                else:
                    self._reply(200, json.dumps(reply, ensure_ascii=False).encode("utf-8"))

        self._httpd = _QuietServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="eco-mcp", daemon=True)
        self._thread.start()
        log.info("MCP do Eco em loopback na porta %d (token só em memória)", self.port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # ------------------------------------------------------------------ JSON-RPC
    def _handle(self, msg: Any) -> dict[str, Any] | None:
        if not isinstance(msg, dict) or "method" not in msg:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
        if "id" not in msg:                                         # notificação (initialized, cancelled...)
            return None

        def ok(result: Any) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        def err(code: int, text: str) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

        if method == "initialize":
            want = str(params.get("protocolVersion", ""))
            return ok({"protocolVersion": want if want in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "eco", "version": "1"}})
        if method == "ping":
            return ok({})
        if method == "tools/list":
            tools = [{"name": t.name, "description": t.description, "inputSchema": t.schema} for t in self._lister()]
            return ok({"tools": tools})
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(args, dict):
                return err(-32602, "invalid params")
            if name not in {t.name for t in self._lister()}:        # o que não foi liberado a este agente nem existe para ele
                return ok({"content": [{"type": "text", "text": f"A ferramenta '{name}' não está disponível."}], "isError": True})
            res = self._executor(name, args)
            content: list[dict[str, Any]] = [{"type": "text", "text": res.text}]
            if res.image:
                content.append({"type": "image", "data": base64.b64encode(res.image).decode("ascii"), "mimeType": res.image_mime})
            return ok({"content": content, "isError": not res.ok})
        return err(-32601, f"method not found: {method}")
