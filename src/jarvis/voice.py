"""Canal de fala: frases -> TTS (Piper) -> UM stream de saída por resposta, com interrupção imediata.

Pipeline (duas threads internas, ambas daemon):
* "voice-synth" (produtora): tira frases da fila de entrada NA ORDEM e as sintetiza, empurrando os
  trechos de áudio numa fila pequena (``_PIPE_DEPTH``). Assim a síntese da próxima frase acontece
  enquanto a atual toca (a fila cheia aplica contrapressão).
* "voice" (reprodutora): abre UM ``Speaker.play_stream`` e o alimenta continuamente com os trechos da
  fila, sem fechar/reabrir o stream (nem resolver o dispositivo) entre frases. Se não vier nada novo
  por ``_LINGER_S`` depois que tudo tocou, o stream é fechado; uma nova frase abre outro.

Contrato de threads: ``say``/``say_and_wait``/``wait_done``/``interrupt``/``speaking``/``idle_since``
podem ser chamados de qualquer thread. ``Event`` devolvido por ``say`` dispara quando a frase TERMINOU de
sair pelo alto-falante (ou foi descartada/falhou).

Interrupção: ``interrupt()`` incrementa a ÉPOCA, cancela o token da época anterior, para o Speaker na
hora e finaliza (``done``) todas as frases pendentes. Itens e trechos de épocas antigas que ainda estejam
em trânsito são descartados por quem os encontrar: nada antigo fala depois de um "pare".

Estado: ``StateMachine.set_speaking(True)`` quando a primeira frase de uma leva começa a sair e
``set_speaking(False)`` quando nada mais está pendente (ocioso) ou após ``interrupt()``.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from .audio.constants import SYNTH_JOIN_S
from .audio.playback import AudioChunk, Speaker
from .audio.tts import Synthesizer
from .core.cancel import CancelToken
from .core.state import StateMachine

log = logging.getLogger(__name__)

_POLL_S = 0.05
_PIPE_DEPTH = 3                     # trechos sintetizados à frente do que toca
_LINGER_S = 0.6                     # com tudo falado, o stream espera tanto por mais frases antes de fechar
_EMPTY = np.empty(0, dtype=np.int16)


@dataclass(eq=False)
class _Item:
    epoch: int
    text: str
    done: threading.Event = field(default_factory=threading.Event)
    finished: bool = False          # (sob _lock)
    started: bool = False           # só a thread reprodutora mexe


@dataclass(eq=False)
class _Piece:
    """Unidade da fila de áudio: um trecho, o fim de um item (``chunk is None``) ou o sinal de parada."""
    item: _Item | None
    chunk: AudioChunk | None = None
    stop: bool = False


class Voice:
    def __init__(self, synth: Synthesizer, speaker: Speaker, state: StateMachine) -> None:
        self._synth = synth
        self._speaker = speaker
        self._state = state
        self._q: "queue.Queue[_Item | None]" = queue.Queue()
        self._pipe: "queue.Queue[_Piece]" = queue.Queue(maxsize=_PIPE_DEPTH)
        self._lock = threading.Lock()
        self._epoch = 0
        self._token = CancelToken()
        self._live: set[_Item] = set()               # itens ainda não finalizados
        self._idle = threading.Event()
        self._idle.set()
        self._idle_at = time.monotonic()
        self._closed = False
        self._stash: _Piece | None = None            # peça de época mais nova achada por um stream velho (só thread "voice")
        self._synth_thread = threading.Thread(target=self._synth_loop, name="voice-synth", daemon=True)
        self._play_thread = threading.Thread(target=self._play_loop, name="voice", daemon=True)
        self._synth_thread.start()
        self._play_thread.start()

    # ------------------------------------------------------------- API
    def say(self, text: str) -> threading.Event:
        """Enfileira uma frase. Devolve um evento que dispara quando a frase termina (ou é descartada)."""
        text = text.strip()
        with self._lock:
            item = _Item(self._epoch, text)
            if not text or self._closed:
                item.finished = True
                item.done.set()
                return item.done
            self._live.add(item)                      # add + clear + put atômicos em relação a _finish
            self._idle.clear()
            self._q.put(item)
        return item.done

    def say_and_wait(self, text: str, cancel: CancelToken, timeout: float = 30.0) -> bool:
        """Fala e espera terminar. False se cancelado ou estourou o tempo."""
        done = self.say(text)
        deadline = time.monotonic() + timeout
        while not done.is_set():
            if cancel.cancelled or time.monotonic() >= deadline:
                return False
            done.wait(_POLL_S)
        return True

    def wait_done(self, cancel: CancelToken, timeout: float = 120.0) -> bool:
        """Espera a fila esvaziar e a última frase terminar."""
        deadline = time.monotonic() + timeout
        while not self._idle.is_set():
            if cancel.cancelled or time.monotonic() >= deadline:
                return False
            self._idle.wait(_POLL_S)
        return True

    @property
    def speaking(self) -> bool:
        return not self._idle.is_set()

    def idle_since(self) -> float | None:
        """None se há fala pendente; senão o ``time.monotonic()`` em que a última frase terminou de tocar.

        O app usa isto (somado a uma margem de eco) como ``not_before`` de ``Microphone.listen_utterance``.
        """
        with self._lock:
            return None if self._live else self._idle_at

    def interrupt(self) -> None:
        """Para a fala agora e descarta o que estava pendente."""
        self._speaker.stop()                          # fade imediato do que toca
        with self._lock:
            self._epoch += 1
            old, self._token = self._token, CancelToken()
            stale = list(self._live)
        old.cancel("fala interrompida")
        self._speaker.stop()                          # cobre um stream aberto entre o 1º stop e o cancel
        for item in stale:
            self._finish(item)
        with self._lock:
            idle = not self._live
        if idle:
            self._set_speaking(False)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self.interrupt()
        self._q.put(None)
        self._synth_thread.join(SYNTH_JOIN_S)
        self._play_thread.join(SYNTH_JOIN_S)
        for thread in (self._synth_thread, self._play_thread):
            if thread.is_alive():
                log.warning("thread %r não encerrou em %.0f s", thread.name, SYNTH_JOIN_S)

    # ------------------------------------------------------------- contabilidade
    def _finish(self, item: _Item) -> None:
        """Idempotente: marca o item como terminado, dispara ``done`` e, se nada resta, o estado ocioso."""
        became_idle = False
        with self._lock:
            if item.finished:
                return
            item.finished = True
            self._live.discard(item)
            if not self._live:
                self._idle_at = time.monotonic()
                self._idle.set()
                became_idle = True
        item.done.set()
        if became_idle:
            self._set_speaking(False)

    def _set_speaking(self, value: bool) -> None:
        try:
            self._state.set_speaking(value)
        except Exception:  # noqa: BLE001 - a interface nunca derruba a fala
            log.exception("falha ao atualizar o estado de fala")

    def _stale(self, item: _Item) -> bool:
        return item.epoch != self._epoch

    # ------------------------------------------------------------- thread produtora
    def _put_piece(self, piece: _Piece, epoch: int | None) -> bool:
        """Enfileira com contrapressão. False se a época do item ficou velha (ou o player morreu)."""
        while True:
            if epoch is not None and epoch != self._epoch:
                return False
            if not self._play_thread.is_alive():
                return False
            try:
                self._pipe.put(piece, timeout=_POLL_S)
                return True
            except queue.Full:
                continue

    def _synth_loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                self._put_piece(_Piece(None, stop=True), None)
                return
            with self._lock:
                stale = item.epoch != self._epoch
                token = self._token
            if stale:
                self._finish(item)                    # já finalizado pelo interrupt; idempotente
                continue
            produced = False
            try:
                for chunk in self._synth.synthesize(item.text, token):
                    if not self._put_piece(_Piece(item, chunk), item.epoch):
                        break
                    produced = True
                else:
                    if produced and not token.cancelled:
                        produced = self._put_piece(_Piece(item), item.epoch)   # marca de fim
                    else:
                        produced = False
            except Exception:  # noqa: BLE001 - falha de TTS nunca derruba o Eco
                log.exception("falha ao sintetizar a fala")
                produced = False
            if not produced:
                self._finish(item)                    # nada (mais) a tocar: não deixa o item pendente

    # ------------------------------------------------------------- thread reprodutora
    def _play_loop(self) -> None:
        while True:
            piece, self._stash = self._stash, None
            if piece is None:
                piece = self._pipe.get()
            if piece.stop:
                return
            item = piece.item
            assert item is not None
            with self._lock:
                epoch, token = self._epoch, self._token
            if item.epoch != epoch:
                continue                              # velha; o interrupt já a finalizou
            handed: list[_Item] = []
            try:
                self._speaker.play_stream(self._chunks(token, epoch, piece, handed), token)
            except Exception:  # noqa: BLE001 - falha de áudio nunca derruba o Eco
                log.exception("falha ao reproduzir a fala")
            finally:
                for it in handed:                     # nada que passou por este stream fica pendente
                    self._finish(it)

    def _next_piece(self, token: CancelToken) -> _Piece | None:
        """Próxima peça; None se o token foi cancelado ou se tudo foi falado e passou ``_LINGER_S`` em silêncio."""
        quiet_since: float | None = None
        while not token.cancelled:
            try:
                return self._pipe.get(timeout=_POLL_S)
            except queue.Empty:
                pass
            with self._lock:
                busy = bool(self._live)
            if busy:
                quiet_since = None
                continue
            now = time.monotonic()
            if quiet_since is None:
                quiet_since = now
            elif now - quiet_since >= _LINGER_S:
                return None
        return None

    def _chunks(self, token: CancelToken, epoch: int, first: _Piece, handed: list[_Item]) -> Iterator[AudioChunk]:
        """Alimenta o ``play_stream``: trechos da época ``epoch``; marca o fim de cada item com ``on_played``."""
        piece: _Piece | None = first
        last_rate: int | None = None
        while True:
            if piece is None:
                piece = self._next_piece(token)
                if piece is None:
                    return
            if piece.stop or (piece.item is not None and piece.item.epoch > epoch):
                self._stash = piece                   # pertence a outro stream/época: devolve para o laço
                return
            item = piece.item
            if item is None or item.epoch != epoch or token.cancelled:
                piece = None                          # velha: descarta
                if token.cancelled:
                    return
                continue
            if not item.started:
                item.started = True
                handed.append(item)
                self._set_speaking(True)
                if token.cancelled or self._stale(item):          # interrupt() correu entre a checagem e o True (N-21)
                    self._set_speaking(False)
                    return
            chunk = piece.chunk
            piece = None
            if chunk is not None:
                last_rate = chunk.sample_rate
                yield chunk
            elif last_rate is None:
                self._finish(item)                    # item sem áudio neste stream
            else:
                yield AudioChunk(_EMPTY, last_rate, on_played=lambda it=item: self._finish(it))
