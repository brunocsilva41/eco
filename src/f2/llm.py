"""Cliente do llama-server local (127.0.0.1). Streaming; entrega frases prontas para o TTS."""
import json, re, urllib.request

URL = "http://127.0.0.1:8089/v1/chat/completions"
SYSTEM = ("Você é o Jarvis, assistente de voz do Bruno, em português do Brasil. "
          "Responda curto (no máximo 2 frases), natural para ser falado, sem markdown nem emojis.")
_END = re.compile(r"(?<=[.!?…])\s+|\n+")

def stream_sentences(user_text, history=None, max_tokens=200):
    msgs = [{"role": "system", "content": SYSTEM}] + (history or []) + [{"role": "user", "content": user_text}]
    body = json.dumps({"messages": msgs, "stream": True, "max_tokens": max_tokens, "temperature": 0.4}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    buf = ""
    with urllib.request.urlopen(req, timeout=120) as r:
        for raw in r:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            delta = json.loads(line[5:])["choices"][0]["delta"].get("content") or ""
            buf += delta
            parts = _END.split(buf)
            for p in parts[:-1]:
                if p.strip():
                    yield p.strip()
            buf = parts[-1]
    if buf.strip():
        yield buf.strip()
