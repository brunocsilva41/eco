"""Segurança do Jarvis: parada de emergência, confirmação Sim/Não, tratamento de conteúdo não confiável.

- `EmergencyStop`: tecla global que cancela TUDO (agente, ferramentas, fala), solta mouse/teclado
  e fica registrada no log. Depois o Jarvis volta ao repouso.
- `ConfirmationBroker`: pede Sim/Não ao Bruno por voz OU tecla. Sem resposta = NÃO.
- `wrap_untrusted`: marca texto da tela/web como DADO; instruções dentro dele nunca são obedecidas.
"""
from __future__ import annotations

import logging
import re
import threading
import unicodedata
import uuid
from typing import Callable

from .core.cancel import CancelToken
from .core.events import EventBus
from .tools.registry import Risk

log = logging.getLogger(__name__)


# ----------------------------------------------------------------- conteúdo não confiável
_FENCE = "«DADO-NAO-CONFIAVEL»"


def wrap_untrusted(source: str, text: str, limit: int = 1500) -> str:
    """Envolve conteúdo externo. O modelo é instruído (prompt do sistema) a nunca seguir ordens dentro disso."""
    clean = text.replace(_FENCE, "")[:limit]
    return f"{_FENCE} fonte={source}\n{clean}\n{_FENCE}"


# ----------------------------------------------------------------- Sim / Não por voz
def _norm(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z ]+", " ", t).strip()


# palavras já sem acento; "para" (preposição) fica de fora de propósito
_YES = frozenset({"sim", "pode", "confirmo", "confirmado", "claro", "positivo", "autorizo", "ok", "isso"})
_NO = frozenset({"nao", "negativo", "cancela", "cancelar", "pare", "deixa", "esquece", "nunca", "jamais"})


def parse_yes_no(text: str) -> bool | None:
    """True=sim, False=não, None=ambíguo/irreconhecível. Nunca assume sim em caso de dúvida.

    Se houver as duas famílias ("não, pode esquecer"), vale a que aparece primeiro apenas quando for a negativa;
    "sim ... não" é ambíguo e o Jarvis pergunta de novo (ou o timeout vira NÃO).
    """
    words = _norm(text).split()
    hits = [("no" if w in _NO else "yes") for w in words if w in _NO or w in _YES]
    if not hits:
        return None
    if all(h == "yes" for h in hits):
        return True
    if all(h == "no" for h in hits):
        return False
    return False if hits[0] == "no" else None


class ConfirmationBroker:
    """Implementa o protocolo `Confirmer` do registro.

    Fluxo: `ask()` publica `confirm_request` (a Ilha mostra Sim/Não), fala a pergunta (se houver `speak`) e espera
    uma resposta de `answer()` (clique/tecla/voz). Timeout ou cancelamento = False. Seguro entre threads.
    """

    def __init__(self, bus: EventBus, timeout_s: float, speak: Callable[[str], None] | None = None) -> None:
        self._bus = bus
        self._timeout = timeout_s
        self._speak = speak
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[threading.Event, list[bool]]] = {}
        self._listen: Callable[[CancelToken, float], str | None] | None = None

    def set_speaker(self, speak: Callable[[str], object]) -> None:
        """`speak(texto)` fala a pergunta e só retorna quando termina (para a escuta não pegar a própria voz)."""
        self._speak = speak  # type: ignore[assignment]

    def set_voice_listener(self, listen: Callable[[CancelToken, float], str | None]) -> None:
        """`listen(cancel, timeout_s)` grava e transcreve uma resposta curta; devolve o texto ou None."""
        self._listen = listen

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def answer(self, yes: bool, request_id: str | None = None) -> bool:
        """Responde a uma confirmação pendente (a mais recente se `request_id` for None). False se não havia nenhuma."""
        with self._lock:
            if not self._pending:
                return False
            rid = request_id or next(reversed(self._pending))
            item = self._pending.get(rid)
            if item is None:
                return False
            event, box = item
            if not box:
                box.append(yes)
                event.set()
            return True

    def ask(self, text: str, risk: Risk, cancel: CancelToken) -> bool:
        rid = uuid.uuid4().hex[:8]
        event, box = threading.Event(), []
        with self._lock:
            self._pending[rid] = (event, box)
        try:
            self._bus.publish("confirm_request", id=rid, text=text, risk=int(risk), timeout_s=self._timeout)
            if self._speak:
                try:
                    self._speak(f"{text}. Posso fazer? Diga sim ou não.")
                except Exception:  # noqa: BLE001
                    log.exception("falha ao falar a confirmação")
            result = self._wait(rid, event, box, cancel)
            log.info("confirmação %s (%s): %s", rid, text, {True: "SIM", False: "NÃO", None: "SEM RESPOSTA = NÃO"}[result])
            return bool(result)
        finally:
            with self._lock:
                self._pending.pop(rid, None)
            self._bus.publish("confirm_done", id=rid)

    def _wait(self, rid: str, event: threading.Event, box: list[bool], cancel: CancelToken) -> bool | None:
        import time
        deadline = time.monotonic() + self._timeout
        # a escuta por voz roda em uma thread à parte; tecla/clique chegam via answer()
        voice_cancel = cancel.child()
        if self._listen is not None:
            def voice() -> None:
                while not event.is_set() and not voice_cancel.cancelled and time.monotonic() < deadline:
                    try:
                        heard = self._listen(voice_cancel, max(1.0, deadline - time.monotonic()))  # type: ignore[misc]
                    except Exception:  # noqa: BLE001
                        log.exception("escuta da confirmação falhou")
                        return
                    verdict = parse_yes_no(heard) if heard else None
                    if verdict is not None:
                        self.answer(verdict, rid)
                        return
            threading.Thread(target=voice, name="confirm-voice", daemon=True).start()
        try:
            while time.monotonic() < deadline:
                if event.wait(0.1):
                    return box[0] if box else None
                if cancel.cancelled:
                    return None
            return None
        finally:
            voice_cancel.cancel("confirmação encerrada")
            voice_cancel.release()


class EmergencyStop:
    """Tecla de emergência. Cancela o token raiz da sessão e solta teclas/botões presos."""

    def __init__(self, on_stop: Callable[[str], None], release_inputs: Callable[[], None] | None = None) -> None:
        self._on_stop = on_stop
        self._release = release_inputs

    def trigger(self, source: str = "tecla de emergência") -> None:
        log.warning("PARADA DE EMERGÊNCIA acionada (%s)", source)
        if self._release:
            try:
                self._release()
            except Exception:  # noqa: BLE001
                log.exception("falha ao soltar teclas/mouse")
        try:
            self._on_stop(source)
        except Exception:  # noqa: BLE001
            log.exception("falha ao parar tudo")
