"""Agente ACP de exemplo (só para testes): fala JSON-RPC por stdio como um agente real. Comportamento por FAKE_MODE:
ok | model_switch | quota | perm | perm_jarvis | fs | hang | hang_ignore | die | auth | tool | tool_screen | err_text
"""
import json
import os
import queue
import sys
import threading
import urllib.request

MODE = os.environ.get("FAKE_MODE", "ok")
HTTP_MCP = os.environ.get("FAKE_HTTP", "1") == "1"
inbox: "queue.Queue[dict]" = queue.Queue()
resp_q: "queue.Queue[dict]" = queue.Queue()
cancelled = threading.Event()
mcp_servers: list = []
_next = [1000]


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def reader():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("method") == "session/cancel":
            cancelled.set()
        elif "method" not in msg:
            resp_q.put(msg)
        else:
            inbox.put(msg)
    inbox.put({"_eof": True})


def call_client(method, params):
    _next[0] += 1
    rid = _next[0]
    send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    while True:
        msg = resp_q.get()
        if msg.get("id") == rid:
            return msg


def chunk(sid, text):
    send({"jsonrpc": "2.0", "method": "session/update",
          "params": {"sessionId": sid, "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}}})


def mcp_call(srv, method, params):
    req = urllib.request.Request(srv["url"], data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                 headers={"Content-Type": "application/json", **{h["name"]: h["value"] for h in srv["headers"]}})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


CUR_MODEL = ["bad"]


def prompt(rid, p):
    sid = p["sessionId"]
    if MODE == "model_switch":
        chunk(sid, "Resposta boa." if CUR_MODEL[0] == "opencode/big-pickle" else "Error: Model \"bad\" is not available.")
    elif MODE == "quota":
        chunk(sid, "Info: indexing. Error: You have exceeded your monthly quota (Request ID x)")
    elif MODE == "ok":
        chunk(sid, "Olá, ")
        chunk(sid, "mundo.")
    elif MODE == "err_text":
        chunk(sid, "Error: Model not available")
    elif MODE in ("perm", "perm_jarvis"):
        title = "Run bash ls" if MODE == "perm" else "Run mcp_eco_hora_atual"
        r = call_client("session/request_permission", {"sessionId": sid, "toolCall": {"toolCallId": "c1", "title": title},
                        "options": [{"optionId": "a", "name": "Allow", "kind": "allow_once"},
                                    {"optionId": "aa", "name": "Always", "kind": "allow_always"},
                                    {"optionId": "r", "name": "Reject", "kind": "reject_once"}]})
        chunk(sid, "decisão=" + json.dumps(r["result"]["outcome"]))
    elif MODE == "fs":
        r = call_client("fs/read_text_file", {"sessionId": sid, "path": "C:\\Windows\\win.ini"})
        chunk(sid, "fs=" + ("erro" if "error" in r else "ok"))
    elif MODE in ("hang", "hang_ignore"):
        if MODE == "hang":
            cancelled.wait(60)
            send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "cancelled"}})
            return
        threading.Event().wait(120)
    elif MODE == "die":
        os._exit(3)
    elif MODE == "term":                                    # pede um comando ao terminal integrado (FAKE_CMD) pelo MCP
        srv = mcp_servers[0] if mcp_servers else None
        names = [t["name"] for t in mcp_call(srv, "tools/list", {})["result"]["tools"]] if srv and "url" in srv else []
        has = "executar_comando" in names
        if has:
            res = mcp_call(srv, "tools/call", {"name": "executar_comando", "arguments": {"comando": os.environ.get("FAKE_CMD", "echo oi")}})["result"]
            chunk(sid, f"has={has} ok={not res.get('isError')} res={res['content'][0]['text'][:400]}")
        else:
            chunk(sid, f"has={has}")
    elif MODE in ("tool", "tool_screen"):
        srv = mcp_servers[0] if mcp_servers else None
        if srv is None or "url" not in srv:
            chunk(sid, "sem mcp http: " + json.dumps(srv)[:80])
        else:
            names = [t["name"] for t in mcp_call(srv, "tools/list", {})["result"]["tools"]]
            if MODE == "tool":
                res = mcp_call(srv, "tools/call", {"name": "hora_atual", "arguments": {}})["result"]
                chunk(sid, f"tools={len(names)} hora={res['content'][0]['text']}")
            else:
                chunk(sid, "ver_tela=" + str("ver_tela" in names) + " ler_arquivo=" + str("ler_arquivo" in names))
    send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})


def main():
    threading.Thread(target=reader, daemon=True).start()
    while True:
        msg = inbox.get()
        if msg.get("_eof"):
            return
        m, rid = msg.get("method"), msg.get("id")
        if m == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": 1, "agentInfo": {"name": "fake", "version": "0"},
                  "agentCapabilities": {"mcpCapabilities": {"http": HTTP_MCP}}, "authMethods": []}})
        elif m == "session/new":
            if MODE == "auth":
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "Authentication required"}})
            else:
                mcp_servers[:] = msg["params"].get("mcpServers", [])
                send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "s1", "models": {
                    "currentModelId": "bad", "availableModels": [{"modelId": "bad", "name": "bad"}, {"modelId": "opencode/big-pickle", "name": "free"}]}}})
        elif m == "session/set_model" and MODE == "model_switch":
            CUR_MODEL[0] = msg["params"]["modelId"]
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif m == "session/set_model":
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "set_model não suportado"}})
        elif m == "session/prompt":
            cancelled.clear()
            threading.Thread(target=prompt, args=(rid, msg["params"]), daemon=True).start()
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "método desconhecido"}})


main()
