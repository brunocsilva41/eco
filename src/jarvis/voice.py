"""Canal de fala: fila de frases -> TTS (Piper) -> alto-falante, com interrupção imediata.

Contrato de threads: `say`/`say_and_wait`/`wait_done`/`interrupt` podem ser chamados de qualquer thread.
Uma única thread interna fala uma frase por vez, na ordem. `interrupt()` descarta a fila, para o som na hora
e invalida frases antigas (época), então nada fala depois de um "pare".
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

from .audio.playback import Speaker
from .audio.tts import Synthesizer
from .core.cancel import CancelToken
from .core.events import State
from .core.state import StateMachine

log = logging.getLogger(__name__)


@dataclass
class _Item:
    epoch: int
    text: str
    done: threading.Event


class Voice:
    def __init__(self, synth: Synthesizer, speaker: Speaker, state: StateMachine) -> None:
        self._synth = synth
        self._speaker = speaker
        self._state = state
        self._q: "queue.Queue[_Item | None]" = queue.Queue()
        self._lock = threading.Lock()
        self._epoch = 0
        self._token = CancelToken()
        self._busy = False
        self._idle = threading.Event()
        self._idle.set()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="voice", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------- API
    def say(self, text: str) -> threading.Event:
        """Enfileira uma frase. Devolve um evento que dispara quando a frase termina (ou é descartada)."""
        text = text.strip()
        done = threading.Event()
        if not text or self._closed:
            done.set()
            return done
        with self._lock:                  # clear + put atômicos: _maybe_idle nunca vê a fila vazia entre os dois
            self._idle.clear()
            self._q.put(_Item(self._epoch, text, done))
        return done

    def say_and_wait(self, text: str, cancel: CancelToken, timeout: float = 30.0) -> bool:
        """Fala e espera terminar. False se cancelado ou estourou o tempo."""
        done = self.say(text)
        waited = 0.0
        while not done.is_set():
            if cancel.cancelled or waited >= timeout:
                return False
            done.wait(0.05)
            waited += 0.05
        return True

    def wait_done(self, cancel: CancelToken, timeout: float = 120.0) -> bool:
        """Espera a fila esvaziar e a última frase terminar."""
        waited = 0.0
        while not self._idle.is_set():
            if cancel.cancelled or waited >= timeout:
                return False
            self._idle.wait(0.05)
            waited += 0.05
        return True

    @property
    def speaking(self) -> bool:
        return not self._idle.is_set()

    def interrupt(self) -> None:
        """Para a fala agora e descarta o que estava na fila."""
        with self._lock:
            self._epoch += 1
            old, self._token = self._token, CancelToken()
        old.cancel("fala interrompida")
        self._speaker.stop()
        self._drain()

    def close(self) -> None:
        self._closed = True
        self.interrupt()
        self._q.put(None)
        self._thread.join(3.0)

    # ------------------------------------------------------------- thread
    def _drain(self) -> None:
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                item.done.set()
        with self._lock:
            if not self._busy:
                self._idle.set()

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            with self._lock:
                stale = item.epoch != self._epoch
                token = self._token
                if not stale:
                    self._busy = True
            if stale:
                item.done.set()
                self._maybe_idle()
                continue
            try:
                self._state.go(State.SPEAKING)
                self._synth.speak(item.text, self._speaker, token)
            except Exception:  # noqa: BLE001 - falha de TTS nunca derruba o Jarvis
                log.exception("falha ao falar")
            finally:
                with self._lock:
                    self._busy = False
                item.done.set()
                self._maybe_idle()

    def _maybe_idle(self) -> None:
        with self._lock:
            if self._q.empty() and not self._busy:
                self._idle.set()
