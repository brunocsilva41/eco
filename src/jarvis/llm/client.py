"""Cliente HTTP do llama-server (API compatível com OpenAI), com streaming, tool calling e cancelamento.

Só fala com loopback e SEM proxy do sistema (http.client direto). Usa a chave de API da execução (header Bearer).
Cancelamento: um observador fecha o socket quando o token dispara, o que destrava a leitura bloqueada na hora.
Um stream que acaba sem `[DONE]`/`finish_reason` é erro (resposta cortada nunca é tratada como sucesso).
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

from ..config import Config, assert_loopback
from ..core.cancel import CancelToken, Cancelled

log = logging.getLogger(__name__)


class LlmError(RuntimeError):
    pass


class ContextOverflow(LlmError):
    """O pedido não cabe no contexto do modelo; quem chama deve compactar/encurtar."""


class TruncatedReply(LlmError):
    """A resposta foi cortada pelo limite de tokens com uma chamada de ferramenta no meio (argumentos incompletos)."""


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

    @property
    def truncated(self) -> bool:
        """True se o texto foi cortado pelo limite de tokens (finish_reason == length)."""
        return self.finish_reason == "length"

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

    def __init__(self, cfg: Config, api_key: Callable[[], str | None] | None = None) -> None:
        assert_loopback(cfg.llm.host)
        self._cfg = cfg
        self._api_key = api_key or (lambda: None)
        self._n_ctx: int | None = None

    def reconfigure(self, cfg: Config) -> None:
        """Aplica temperatura, max_tokens e timeouts novos sem reiniciar (host/porta só valem após reiniciar)."""
        self._cfg = cfg

    # ------------------------------------------------------------- utilidades HTTP
    def _conn(self, timeout: float) -> http.client.HTTPConnection:
        host = self._cfg.llm.host
        return http.client.HTTPConnection(host, self._cfg.llm.port, timeout=timeout)

    def _headers(self, json_body: bool = True) -> dict[str, str]:
        h = {"Content-Type": "application/json; charset=utf-8"} if json_body else {}
        key = self._api_key()
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def _json(self, method: str, path: str, body: Any = None, timeout: float = 10.0) -> Any:
        conn = self._conn(timeout)
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, payload, self._headers(payload is not None))
            resp = conn.getresponse()
            raw = resp.read(2_000_000)
            if resp.status != 200:
                raise LlmError(f"llama-server respondeu {resp.status} em {path}")
            return json.loads(raw.decode("utf-8", "replace"))
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise LlmError(f"falha em {path}: {exc}") from exc
        finally:
            conn.close()

    def n_ctx(self) -> int:
        """Contexto REAL do servidor (n_ctx por slot), com cache; cai para a config se o servidor não informar."""
        if self._n_ctx:
            return self._n_ctx
        try:
            props = self._json("GET", "/props")
            n = int(props.get("default_generation_settings", {}).get("n_ctx") or 0)
            if n > 0:
                self._n_ctx = n
                return n
        except (LlmError, ValueError, TypeError):
            log.warning("não consegui ler n_ctx do servidor; usando llm.ctx da config")
        return self._cfg.llm.ctx

    def count_tokens(self, text: str) -> int:
        """Tokens de um texto segundo o tokenizador do modelo. Se o servidor falhar, estima (~3 caracteres por token)."""
        if not text:
            return 0
        try:
            data = self._json("POST", "/tokenize", {"content": text}, timeout=5.0)
            toks = data.get("tokens")
            if isinstance(toks, list):
                return len(toks)
        except LlmError:
            pass
        return max(1, len(text) // 3)

    # ------------------------------------------------------------- chat
    def chat(self, messages: list[dict[str, Any]], cancel: CancelToken, tools: list[dict[str, Any]] | None = None,
             on_text: Callable[[str], None] | None = None, max_tokens: int | None = None,
             temperature: float | None = None) -> Reply:
        """Pede uma resposta em streaming. `on_text` recebe cada pedaço de texto assim que chega."""
        c = self._cfg.llm
        body: dict[str, Any] = {"messages": messages, "stream": True,
                                "temperature": c.temperature if temperature is None else temperature,
                                "max_tokens": max_tokens or c.max_tokens}
        if tools:
            body["tools"] = tools
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

        conn = self._conn(c.request_timeout_s)
        done = threading.Event()

        def watcher() -> None:
            # insiste até a chamada acabar: se o cancelamento chegar antes de existir o socket, mata assim que ele aparecer
            while not done.is_set():
                if cancel.cancelled and _kill_socket(conn):
                    return
                done.wait(0.05)

        threading.Thread(target=watcher, name="llm-cancel", daemon=True).start()
        try:
            cancel.raise_if_cancelled()
            try:
                conn.request("POST", "/v1/chat/completions", payload, {**self._headers(), "Accept": "text/event-stream"})
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
        finished = False
        try:
            for raw in resp:
                if cancel.cancelled:
                    raise Cancelled(cancel.reason)
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    finished = True
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
                        try:
                            on_text(text)
                        except Exception:  # noqa: BLE001 - falha da voz/UI não é falha da rede: segue sem o callback
                            log.exception("o callback de texto falhou; continuo recebendo a resposta sem ele")
                            on_text = None
                for tc in delta.get("tool_calls") or []:
                    try:
                        idx = int(tc.get("index", 0))
                    except (TypeError, ValueError):
                        idx = 0
                    slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
                if ch.get("finish_reason"):
                    reply.finish_reason = ch["finish_reason"]
                    finished = True
        except (OSError, http.client.HTTPException) as exc:
            if cancel.cancelled:
                raise Cancelled(cancel.reason) from exc
            if isinstance(exc, (socket.timeout, TimeoutError)):
                raise LlmError("o llama-server parou de responder (timeout)") from exc
            raise LlmError(f"conexão com o llama-server caiu: {exc}") from exc
        if cancel.cancelled:
            raise Cancelled(cancel.reason)
        if not finished:
            raise LlmError("a resposta do llama-server foi interrompida no meio (sem fim de stream)")
        for i in sorted(calls):
            s = calls[i]
            if s["name"]:
                reply.tool_calls.append(ToolCall(s["id"] or f"call_{i}", s["name"], s["arguments"] or "{}"))
        if reply.tool_calls and reply.finish_reason == "length":
            raise TruncatedReply("a chamada de ferramenta foi cortada pelo limite de tokens")
        return reply


def _kill_socket(conn: http.client.HTTPConnection) -> bool:
    """Fecha o socket da conexão. True se havia socket para fechar."""
    sock = conn.sock
    if sock is None:
        return False
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass
    return True
