"""Cliente HTTP do llama-server (API compatível com OpenAI), com streaming, tool calling e cancelamento.

Só fala com loopback. Cancelamento: um observador fecha o socket quando o token dispara, o que
destrava a leitura bloqueada na hora (nenhuma espera de timeout).
"""
from __future__ import annotations

import base64
import http.client
import json
import logging
import socket
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import Config
from ..core.cancel import CancelToken, Cancelled

log = logging.getLogger(__name__)


class LlmError(RuntimeError):
    pass


class ContextOverflow(LlmError):
    """O pedido não cabe no contexto do modelo; quem chama deve encurtar o histórico."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str          # JSON em texto, exatamente como o modelo emitiu (validado pelo registro)


@dataclass
class Reply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""

    def as_message(self) -> dict[str, Any]:
        """Mensagem do assistente para devolver ao histórico da conversa."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [{"id": t.id, "type": "function",
                                  "function": {"name": t.name, "arguments": t.arguments}} for t in self.tool_calls]
        return msg


def image_content(text: str, image: bytes, mime: str = "image/jpeg") -> list[dict[str, Any]]:
    """Conteúdo multimodal (texto + imagem em data URL) para o Qwen3-VL."""
    b64 = base64.b64encode(image).decode("ascii")
    return [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]


class LlmClient:
    """Contrato de threads: `chat` é reentrante (uma conexão por chamada), mas o servidor tem 1 slot: chame uma por vez."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._host = cfg.llm.host
        self._port = cfg.llm.port

    def chat(self, messages: list[dict[str, Any]], cancel: CancelToken, tools: list[dict[str, Any]] | None = None,
             on_text: Callable[[str], None] | None = None, max_tokens: int | None = None) -> Reply:
        """Pede uma resposta em streaming. `on_text` recebe cada pedaço de texto assim que chega."""
        c = self._cfg.llm
        body: dict[str, Any] = {"messages": messages, "stream": True, "temperature": c.temperature,
                                "max_tokens": max_tokens or c.max_tokens}
        if tools:
            body["tools"] = tools
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

        conn = http.client.HTTPConnection(self._host, self._port, timeout=c.request_timeout_s)
        done = threading.Event()

        def watcher() -> None:
            while not done.is_set():
                if cancel.wait(0.2):
                    if not done.is_set():
                        _kill_socket(conn)
                    return

        threading.Thread(target=watcher, name="llm-cancel", daemon=True).start()
        try:
            cancel.raise_if_cancelled()
            try:
                conn.request("POST", "/v1/chat/completions", payload,
                             {"Content-Type": "application/json; charset=utf-8", "Accept": "text/event-stream"})
                resp = conn.getresponse()
            except (OSError, http.client.HTTPException) as exc:
                if cancel.cancelled:
                    raise Cancelled(cancel.reason) from exc
                raise LlmError(f"não consegui falar com o llama-server ({type(exc).__name__}): {exc}") from exc
            if resp.status != 200:
                detail = resp.read(2000).decode("utf-8", "replace")
                if resp.status == 400 and "context" in detail.lower():
                    raise ContextOverflow(detail[:200])
                raise LlmError(f"llama-server respondeu {resp.status}: {detail[:200]}")
            return self._consume(resp, cancel, on_text)
        finally:
            done.set()
            conn.close()

    # ------------------------------------------------------------- leitura do stream SSE
    @staticmethod
    def _consume(resp: http.client.HTTPResponse, cancel: CancelToken, on_text: Callable[[str], None] | None) -> Reply:
        reply = Reply()
        calls: dict[int, dict[str, str]] = {}
        try:
            for raw in resp:
                if cancel.cancelled:
                    raise Cancelled(cancel.reason)
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    log.warning("pedaço SSE ilegível ignorado: %.80s", data)
                    continue
                if "error" in chunk:
                    raise LlmError(str(chunk["error"])[:200])
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                ch = choices[0]
                delta = ch.get("delta") or {}
                text = delta.get("content")
                if text:
                    reply.content += text
                    if on_text:
                        on_text(text)
                for tc in delta.get("tool_calls") or []:
                    slot = calls.setdefault(int(tc.get("index", 0)), {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
                if ch.get("finish_reason"):
                    reply.finish_reason = ch["finish_reason"]
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if cancel.cancelled:
                raise Cancelled(cancel.reason) from exc
            if isinstance(exc, (socket.timeout, TimeoutError)):
                raise LlmError("o llama-server parou de responder (timeout)") from exc
            raise LlmError(f"conexão com o llama-server caiu: {exc}") from exc
        for i in sorted(calls):
            s = calls[i]
            if s["name"]:
                reply.tool_calls.append(ToolCall(s["id"] or f"call_{i}", s["name"], s["arguments"] or "{}"))
        return reply


def _kill_socket(conn: http.client.HTTPConnection) -> None:
    sock = conn.sock
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass
