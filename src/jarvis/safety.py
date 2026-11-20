"""Segurança do Jarvis: parada de emergência, confirmação Sim/Não, tratamento de conteúdo não confiável.

- `EmergencyStop`: tecla global que cancela TUDO (agente, ferramentas, fala), solta mouse/teclado
  e fica registrada no log. Depois o Jarvis volta ao repouso.
- `ConfirmationBroker`: pede Sim/Não ao Bruno por voz, tecla OU texto. Sem resposta = NÃO.
  Por voz a resposta é ESTRITA: "sim" / "confirmo" / "autorizo" / "não" (até 3 palavras); em ações RISKY só vale
  "confirmo" ou "autorizo" (um "sim" solto, falado por qualquer um, não basta). Fala durante a própria pergunta é ignorada.
- `wrap_untrusted`: marca texto da tela/web como DADO; instruções dentro dele nunca são obedecidas.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .core.cancel import CancelToken
from .core.events import EventBus
from .core.risk import Risk
from .core.textutil import words
from .tools.registry import Decision

log = logging.getLogger(__name__)


# ----------------------------------------------------------------- conteúdo não confiável
_FENCE = "«DADO-NAO-CONFIAVEL»"


def wrap_untrusted(source: str, text: str, limit: int = 1500) -> str:
    """Envolve conteúdo externo. O modelo é instruído (prompt do sistema) a nunca seguir ordens dentro disso.

    Remove qualquer tentativa de forjar a cerca dentro do texto e sanitiza `source`.
    """
    clean = text.replace("«", "<").replace("»", ">")[:limit]
    src = "".join(c for c in source if c.isalnum() or c in "_-.")[:40] or "origem"
    return f"{_FENCE} fonte={src}\n{clean}\n{_FENCE}"


# ----------------------------------------------------------------- Sim / Não por voz (estrito)
_YES_PLAIN = frozenset({"sim", "confirmo", "autorizo"})
_YES_STRONG = frozenset({"confirmo", "autorizo"})           # exigidas em ações RISKY
_NO = frozenset({"nao", "negativo", "cancela", "cancelar", "pare"})
MAX_ANSWER_WORDS = 3


def parse_yes_no(text: str, strong: bool = False) -> bool | None:
    """True=sim, False=não, None=ambíguo/irreconhecível (continua ouvindo). Nunca assume sim em dúvida.

    Só respostas curtas (até 3 palavras). Frase longa é conversa alheia, não resposta. Com `strong=True`,
    "sim" sozinho NÃO aprova (precisa de "confirmo"/"autorizo"), mas "não" sempre vale.
    """
    ws = words(text)
    if not ws or len(ws) > MAX_ANSWER_WORDS:
        return None
    no = any(w in _NO for w in ws)
    yes_words = _YES_STRONG if strong else _YES_PLAIN
    yes = any(w in yes_words for w in ws)
    if no and yes:
        return None                                          # "sim ... não": ambíguo, pergunta de novo
    if no:
        return False
    if yes:
        return True
    return None


@dataclass
class _Pending:
    event: threading.Event
    decision: Decision | None = None
    strong: bool = False


class ConfirmationBroker:
    """Implementa o protocolo `Confirmer` do registro.

    Fluxo: `ask()` publica `confirm_request` (a Ilha mostra Sim/Não), fala a pergunta (se houver `speak`) e espera
    uma resposta de `answer()` (tecla/clique/texto) ou da escuta por voz. Timeout ou cancelamento = NÃO.
    Contrato de threads: seguro entre threads; `ask` bloqueia a thread do pedido.
    """

    def __init__(self, bus: EventBus, timeout_s: float, speak: Callable[[str, CancelToken], object] | None = None) -> None:
        self._bus = bus
        self._timeout = timeout_s
        self._speak = speak
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._listen: Callable[[CancelToken, float, float], str | None] | None = None
        self._voice_ok: Callable[[], bool] = lambda: True

    # ------------------------------------------------------------- configuração
    def set_speaker(self, speak: Callable[[str, CancelToken], object]) -> None:
        """`speak(texto, cancel)` fala a pergunta (com o token DO PEDIDO) e só retorna quando termina (a escuta não pode pegar a própria voz)."""
        self._speak = speak

    def set_voice_listener(self, listen: Callable[[CancelToken, float, float], str | None],
                           available: Callable[[], bool] | None = None) -> None:
        """`listen(cancel, timeout_s, not_before)` grava/transcreve uma resposta curta e devolve o texto ou None.
        `not_before` (time.monotonic) é o instante a partir do qual vale o áudio. `available()` diz se há microfone útil."""
        self._listen = listen
        if available is not None:
            self._voice_ok = available

    def set_timeout(self, timeout_s: float) -> None:
        self._timeout = timeout_s

    # ------------------------------------------------------------- respostas
    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def answer(self, yes: bool, request_id: str | None = None, via: str = "key", heard: str | None = None) -> bool:
        """Responde a uma confirmação pendente (a mais recente se `request_id` for None). False se não havia nenhuma."""
        with self._lock:
            if not self._pending:
                return False
            rid = request_id or next(reversed(self._pending))
            item = self._pending.get(rid)
            if item is None or item.decision is not None:
                return False
            item.decision = Decision(yes, via, heard)
            item.event.set()
            return True

    def answer_text(self, text: str, via: str = "text") -> bool:
        """Resposta digitada (modo --text). Teclado físico é prova forte: aceita 'sim' simples mesmo em RISKY."""
        verdict = parse_yes_no(text, strong=False)
        return verdict is not None and self.answer(verdict, via=via, heard=text)

    # ------------------------------------------------------------- pergunta
    def ask(self, text: str, risk: Risk, cancel: CancelToken) -> Decision:
        rid = uuid.uuid4().hex[:8]
        strong = risk >= Risk.RISKY
        pend = _Pending(threading.Event(), strong=strong)
        with self._lock:
            self._pending[rid] = pend
        try:
            self._bus.publish("confirm_request", id=rid, text=text, risk=int(risk), timeout_s=self._timeout,
                              voice=self._listen is not None and self._voice_ok())
            if self._speak:
                how = "Diga confirmo para autorizar, ou não." if strong else "Diga sim ou não."
                try:
                    self._speak(f"{text}. {how}", cancel)
                except Exception:  # noqa: BLE001
                    log.exception("falha ao falar a confirmação")
            heard_after = time.monotonic()           # só vale áudio que começa DEPOIS da pergunta terminar
            decision = self._wait(rid, pend, cancel, heard_after)
            log.info("confirmação %s: %s via %s", rid, "SIM" if decision.allowed else "NÃO", decision.via)
            return decision
        finally:
            with self._lock:
                self._pending.pop(rid, None)
            self._bus.publish("confirm_done", id=rid)

    def _wait(self, rid: str, pend: _Pending, cancel: CancelToken, not_before: float) -> Decision:
        deadline = time.monotonic() + self._timeout
        voice_cancel = cancel.child()
        voice_thread: threading.Thread | None = None
        if self._listen is not None and self._voice_ok():
            voice_thread = threading.Thread(target=self._voice_loop, args=(rid, pend, voice_cancel, deadline, not_before),
                                            name="confirm-voice", daemon=True)
            voice_thread.start()
        else:
            log.info("confirmação %s: sem escuta por voz (microfone mudo/indisponível); vale tecla ou texto", rid)
        try:
            while time.monotonic() < deadline:
                if pend.event.wait(0.1) and pend.decision is not None:
                    return pend.decision
                if cancel.cancelled:
                    return Decision(False, "cancel")
            return Decision(False, "timeout")
        finally:
            voice_cancel.cancel("confirmação encerrada")
            voice_cancel.release()
            if voice_thread is not None:
                voice_thread.join(2.0)

    def _voice_loop(self, rid: str, pend: _Pending, cancel: CancelToken, deadline: float, not_before: float) -> None:
        assert self._listen is not None
        while not pend.event.is_set() and not cancel.cancelled and time.monotonic() < deadline:
            started = time.monotonic()
            try:
                heard = self._listen(cancel, max(1.0, deadline - started), not_before)
            except Exception:  # noqa: BLE001
                log.exception("escuta da confirmação falhou")
                return
            verdict = parse_yes_no(heard, strong=pend.strong) if heard else None
            if verdict is not None:
                self.answer(verdict, rid, via="voice", heard=heard)
                return
            if heard:
                log.info("resposta ignorada (não é um sim/não válido para esta ação)")
            if time.monotonic() - started < 0.2:     # retorno imediato (mudo, erro): sem busy-loop
                cancel.wait(0.25)


class EmergencyStop:
    """Tecla de emergência. Cancela o token da sessão PRIMEIRO e depois solta teclas/botões presos."""

    def __init__(self, on_stop: Callable[[str], None], release_inputs: Callable[[], None] | None = None) -> None:
        self._on_stop = on_stop
        self._release = release_inputs

    def trigger(self, source: str = "tecla de emergência") -> None:
        log.warning("PARADA DE EMERGÊNCIA acionada (%s)", source)
        try:
            self._on_stop(source)                    # cancelar vem antes de tudo (nada novo pode começar)
        except Exception:  # noqa: BLE001
            log.exception("falha ao parar tudo")
        if self._release:
            try:
                self._release()
            except Exception:  # noqa: BLE001
                log.exception("falha ao soltar teclas/mouse")
