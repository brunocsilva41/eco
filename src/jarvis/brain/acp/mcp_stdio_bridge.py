"""Ponte MCP stdio -> servidor loopback do Eco, para agentes sem suporte a MCP por HTTP.

O agente inicia este script (`python -I mcp_stdio_bridge.py`) com JARVIS_MCP_URL e JARVIS_MCP_TOKEN no ambiente; cada linha
JSON-RPC lida do stdin vira um POST em 127.0.0.1 e a resposta volta pelo stdout. Só aceita URL de loopback.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse


def main() -> int:
    url, token = os.environ.get("JARVIS_MCP_URL", ""), os.environ.get("JARVIS_MCP_TOKEN", "")
    if urlparse(url).hostname not in ("127.0.0.1", "localhost") or not token:
        sys.stderr.write("eco-mcp-bridge: URL de loopback e token são obrigatórios\n")
        return 2
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = urllib.request.Request(url, data=line.encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            try:
                rid = json.loads(line).get("id")
            except ValueError:
                rid = None
            body = json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": f"eco indisponível: {exc}"}})
        if body.strip():
            sys.stdout.write(body.replace("\n", " ") + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
