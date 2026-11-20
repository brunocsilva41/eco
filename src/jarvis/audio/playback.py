"""Reprodução de PCM int16 mono em taxa arbitrária, cancelável e sem estalo.

Arquitetura: cada reprodução (``play`` / ``play_stream``) abre UM ``sounddevice.OutputStream`` na taxa
do primeiro trecho e o alimenta por uma fila limitada de blocos de 20 ms. O callback só consome
a fila (sem bloquear), aplica o volume (``cfg.tts.volume``) e mede o nível do que REALMENTE sai.
Se a fila secar (síntese atrasada) o callback emite silêncio e segue; trechos consecutivos na mesma
taxa saem sem lacuna. Se a taxa mudar no meio, o stream é fechado (esvaziando) e reaberto.

Parada: ``stop()`` ou ``cancel`` aplicam um fade-out linear de ~12 ms dentro do próprio callback e
encerram o stream (sem estalo, latência de poucos blocos). O restante da fila é descartado.

Contrato de threads
-------------------
* ``play`` / ``play_stream`` bloqueiam a thread que chamou até acabar, cancelar ou falhar; só uma por
  vez (a segunda espera até 1 s e então levanta ``PlaybackError``).
* ``stop()``, ``close()`` e ``speaking`` são thread-safe e podem ser chamados de qualquer thread.
* Callback do PortAudio: só lê a fila, escreve no buffer de saída e atualiza contadores.
* Cada reprodução cria uma thread daemon ("jarvis-speaker-monitor", ~40 Hz) que observa o
  ``CancelToken``/``stop()`` (para reagir mesmo se a thread chamadora estiver presa esperando o
  próximo trecho do iterador) e publica o evento ``level`` {source:'tts'}. Ela é sempre encerrada e
  juntada no ``finally`` que fecha o stream.
* O iterador passado a ``play_stream`` é consumido na thread chamadora; ele deve respeitar o mesmo
  ``CancelToken`` (ou devolver rápido), pois uma parada não consegue interromper um ``next()`` bloqueado.

Marcas de fim (``AudioChunk.on_played``): o callback é chamado quando TODO o áudio entregue até aquele
trecho (inclusive) saiu pelo dispositivo (aprox.; contado em amostras consumidas pelo callback do
PortAudio), na thread do monitor ou na do chamador. Um trecho vazio com ``on_played`` serve de marca
"fim do que veio antes". Se a reprodução for parada, as marcas pendentes NÃO disparam (quem as criou
deve limpar por conta própria). Os callbacks devem ser curtos e não podem levantar.

Dispositivo: a resolução (``resolve_output_device``) é feita UMA vez e guardada em cache; só é refeita
se abrir o stream falhar (aparelho trocado/removido).

Ociosidade: ``speaking`` vale True enquanto ``play_stream`` está em andamento (inclusive esperando o
próximo trecho). ``idle_since()`` devolve None enquanto fala, ou o ``time.monotonic()`` do fim da última
reprodução (inicializado na criação), para o app descartar eco com ``Microphone.listen_utterance(not_before=...)``.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import AudioCfg, TtsCfg
from ..core.cancel import CancelToken
from ..core.events import EventBus
from .constants import JOIN_S, STALL_OUTPUT_S
from .devices import AudioDevice, AudioError, load_sounddevice, resolve_output_device, stream_extra_settings
from .levels import LevelMeter

log = logging.getLogger(__name__)

_BLOCK_S = 0.020                    # duração de cada bloco da fila
_QUEUE_BLOCKS = 25                  # 0,5 s de áudio de folga (contrapressão para quem alimenta)
_FADE_S = 0.012                     # fade-out de parada
_MONITOR_S = 0.025
_MIN_RATE, _MAX_RATE = 8000, 192000


class PlaybackError(AudioError):
    """Falha ao abrir/usar a saída de áudio, ou uso concorrente do ``Speaker``."""


@dataclass(frozen=True)
class AudioChunk:
    """Trecho de áudio pronto para tocar: PCM int16 mono e sua taxa. Não altere ``pcm_int16`` depois de entregar.

    ``on_played`` (opcional): chamado quando este trecho terminou de sair pelo alto-falante (ver o docstring
    do módulo). Pode acompanhar um trecho vazio, como marca de fim.
    """
    pcm_int16: np.ndarray
    sample_rate: int
    on_played: Callable[[], None] | None = field(default=None, compare=False, repr=False)

    @property
    def duration_s(self) -> float:
        return float(self.pcm_int16.size) / self.sample_rate if self.sample_rate > 0 else 0.0


def _call_mark(callback: Callable[[], None]) -> None:
    try:
        callback()
    except Exception:  # noqa: BLE001 - marca com defeito nunca derruba a reprodução
        log.exception("callback on_played levantou exceção")


def _validate_chunk(chunk: AudioChunk) -> np.ndarray:
    pcm = chunk.pcm_int16
    if not isinstance(pcm, np.ndarray) or pcm.dtype != np.int16:
        raise PlaybackError("áudio deve ser np.ndarray int16 (mono)")
    if pcm.ndim != 1:
        raise PlaybackError(f"áudio deve ser mono (1-D); recebido shape {pcm.shape}")
    if not _MIN_RATE <= chunk.sample_rate <= _MAX_RATE:
        raise PlaybackError(f"taxa de amostragem inválida: {chunk.sample_rate}")
    return np.ascontiguousarray(pcm)


class _OutputSession:
    """Um stream de saída numa taxa fixa. Uso interno do Speaker; fecha tudo em ``close()``."""

    def __init__(self, device: AudioDevice, rate: int, gain: float, cancel: CancelToken,
                 stop_evt: threading.Event, meter: LevelMeter) -> None:
        self._sd = load_sounddevice()
        self._device = device
        self.rate = rate
        self._gain = gain
        self._cancel = cancel
        self._stop_evt = stop_evt
        self._meter = meter
        self._blocksize = max(64, int(rate * _BLOCK_S))
        self._fade_n = max(1, min(self._blocksize, int(rate * _FADE_S)))
        self._ramp = np.linspace(1.0, 0.0, self._fade_n, dtype=np.float32)
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=_QUEUE_BLOCKS)
        self._cur: np.ndarray | None = None              # (callback) bloco em consumo
        self._pos = 0                                    # (callback)
        self._fade_req = threading.Event()
        self._finished = threading.Event()               # PortAudio terminou o stream
        self._ended_cleanly = False                      # callback chegou ao fim planejado (fim da fila ou fade)
        self._last_cb = 0.0
        self._last_rms = 0.0
        self._fed = 0                                    # amostras enfileiradas (thread chamadora)
        self._played = 0                                 # amostras consumidas do stream (callback)
        self._marks: deque[tuple[int, Callable[[], None]]] = deque()
        self._marks_lock = threading.Lock()
        self._underflows = 0
        self._stream: Any | None = None
        self._mon_stop = threading.Event()
        self._monitor: threading.Thread | None = None

    # ---------------------------------------------------------------- ciclo de vida
    def start(self) -> None:
        stream: Any | None = None
        try:
            stream = self._sd.OutputStream(
                samplerate=self.rate, channels=1, dtype="int16", blocksize=self._blocksize,
                device=self._device.index, latency="low", callback=self._callback,
                finished_callback=self._finished.set, extra_settings=stream_extra_settings(self._device))
            self._last_cb = time.monotonic()
            stream.start()
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise PlaybackError(f"não consegui abrir a saída de áudio {self._device.label} a {self.rate} Hz: {exc}") from exc
        self._stream = stream
        self._monitor = threading.Thread(target=self._monitor_loop, name="jarvis-speaker-monitor", daemon=True)
        self._monitor.start()

    def close(self) -> None:
        self._mon_stop.set()
        monitor, self._monitor = self._monitor, None
        if monitor is not None and monitor is not threading.current_thread():
            monitor.join(JOIN_S)
            if monitor.is_alive():
                log.warning("thread de monitoramento da reprodução não encerrou em %.1f s", JOIN_S)
        stream, self._stream = self._stream, None
        if stream is not None:
            for action in (stream.abort, stream.close):
                try:
                    action()
                except Exception as exc:
                    log.debug("erro ao fechar o stream de saída: %s", exc)
        self._meter.finish()
        if self._underflows:
            log.warning("reprodução teve %d underflows de saída", self._underflows)

    def request_fade(self) -> None:
        self._fade_req.set()

    @property
    def stopping(self) -> bool:
        return self._fade_req.is_set()

    # ---------------------------------------------------------------- alimentação (thread chamadora)
    def _check_alive(self) -> None:
        if self._finished.is_set() and not self._ended_cleanly:
            raise PlaybackError("a saída de áudio foi interrompida (dispositivo removido ou driver falhou)")

    def _put(self, item: np.ndarray | None) -> bool:
        """Enfileira com contrapressão. False se parou (fade pedido/encerrado) antes de caber."""
        while True:
            if self._fade_req.is_set() or self._finished.is_set():
                self._check_alive()
                return False
            try:
                self._queue.put(item, timeout=_MONITOR_S * 2)
                return True
            except queue.Full:
                continue

    def feed(self, pcm: np.ndarray, on_played: Callable[[], None] | None = None) -> bool:
        """Enfileira ``pcm`` em blocos. False se a reprodução foi parada (a marca então não é registrada)."""
        for i in range(0, pcm.size, self._blocksize):
            if not self._put(pcm[i:i + self._blocksize]):
                return False
        self._fed += pcm.size
        if on_played is not None:
            self.add_mark(on_played)
        return True

    def add_mark(self, callback: Callable[[], None]) -> None:
        """Registra ``callback`` para quando tudo o que já foi enfileirado tiver tocado."""
        with self._marks_lock:
            self._marks.append((self._fed, callback))

    def _fire_marks(self, final: bool = False) -> None:
        while True:
            with self._marks_lock:
                if not self._marks or (not final and self._marks[0][0] > self._played):
                    return
                _, callback = self._marks.popleft()
            _call_mark(callback)

    def drain(self) -> bool:
        """Sinaliza fim da entrada e espera tocar tudo. True se terminou naturalmente; False se foi parada."""
        if not self._put(None):
            return False
        while not self._finished.wait(_MONITOR_S * 2):
            if time.monotonic() - self._last_cb > STALL_OUTPUT_S:
                raise PlaybackError(f"a saída de áudio travou (sem callbacks há {STALL_OUTPUT_S:.0f} s)")
        self._check_alive()
        completed = not self._fade_req.is_set()
        if completed:
            self._fire_marks(final=True)
        return completed

    # ---------------------------------------------------------------- monitor (thread daemon)
    def _monitor_loop(self) -> None:
        while not self._mon_stop.wait(_MONITOR_S):
            if self._cancel.cancelled or self._stop_evt.is_set():
                self._fade_req.set()
            self._meter.feed_rms(self._last_rms)
            self._fire_marks()

    # ---------------------------------------------------------------- callback (thread do PortAudio)
    def _callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        self._last_cb = time.monotonic()
        if status.output_underflow:
            self._underflows += 1
        out = outdata[:, 0]
        fading = self._fade_req.is_set()
        eof = False
        filled = 0
        if not fading:
            while filled < frames:
                cur = self._cur
                if cur is None or self._pos >= cur.size:
                    try:
                        nxt = self._queue.get_nowait()
                    except queue.Empty:
                        break                              # underrun: completa com silêncio
                    if nxt is None:
                        eof = True
                        self._cur = None
                        break
                    self._cur, self._pos = nxt, 0
                    continue
                take = min(frames - filled, cur.size - self._pos)
                out[filled:filled + take] = cur[self._pos:self._pos + take]
                filled += take
                self._pos += take
        else:                                              # fade: usa o que há no bloco em curso e zera o resto
            cur = self._cur
            if cur is not None and self._pos < cur.size:
                take = min(frames, cur.size - self._pos)
                out[:take] = cur[self._pos:self._pos + take]
                filled = take
        self._played += filled
        if filled < frames:
            out[filled:] = 0

        buf = out.astype(np.float32)
        if self._gain != 1.0:
            buf *= self._gain
        if fading:
            n = min(frames, self._fade_n)
            buf[:n] *= self._ramp[:n]
            buf[n:] = 0.0
        np.clip(buf, -32768.0, 32767.0, out=buf)
        out[:] = buf
        self._last_rms = float(np.sqrt(np.dot(buf, buf) / frames)) / 32768.0 if frames else 0.0

        if fading or eof:
            self._ended_cleanly = True
            raise self._sd.CallbackStop


class Speaker:
    def __init__(self, audio: AudioCfg, tts: TtsCfg, bus: EventBus | None = None) -> None:
        self._audio = audio
        self._gain = min(2.0, max(0.0, float(tts.volume)))
        self._meter_bus = bus
        self._play_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop_evt: threading.Event | None = None
        self._session: _OutputSession | None = None
        self._device: AudioDevice | None = None            # cache da resolução do dispositivo de saída
        self._idle_at = time.monotonic()

    @property
    def speaking(self) -> bool:
        """True enquanto ``play_stream`` está em andamento (também quando espera o próximo trecho)."""
        return self._stop_evt is not None

    def idle_since(self) -> float | None:
        """None se está tocando; senão o ``time.monotonic()`` em que a última reprodução terminou."""
        with self._state_lock:
            return None if self._stop_evt is not None else self._idle_at

    def _output_device(self, refresh: bool = False) -> AudioDevice:
        with self._state_lock:
            device = None if refresh else self._device
        if device is None:
            device = resolve_output_device(self._audio)    # DeviceError claro se não houver saída
            with self._state_lock:
                self._device = device
        return device

    def _start_session(self, rate: int, cancel: CancelToken, stop_evt: threading.Event) -> _OutputSession:
        """Abre um stream de saída; se falhar com o dispositivo em cache, resolve de novo e tenta uma vez."""
        device = self._output_device()
        for attempt in (1, 2):
            session = _OutputSession(device, rate, self._gain, cancel, stop_evt, LevelMeter(self._meter_bus, "tts"))
            try:
                session.start()
            except PlaybackError:
                if attempt == 2:
                    raise
                log.warning("falha ao abrir %s; resolvendo o dispositivo de saída de novo", device.label)
                device = self._output_device(refresh=True)
                continue
            log.debug("reprodução iniciada em %s a %d Hz", device.label, rate)
            return session
        raise PlaybackError("não consegui abrir a saída de áudio")  # inalcançável

    def play(self, pcm: np.ndarray, rate: int, cancel: CancelToken | None = None) -> bool:
        """Toca ``pcm`` (int16 mono) a ``rate`` Hz. True se tocou até o fim; False se cancelado/parado."""
        return self.play_stream([AudioChunk(pcm, rate)], cancel)

    def play_stream(self, chunks: Iterable[AudioChunk], cancel: CancelToken | None = None) -> bool:
        """Toca trechos em sequência, sem lacuna entre trechos de mesma taxa. True se tocou tudo."""
        cancel = cancel or CancelToken()
        if not self._play_lock.acquire(timeout=1.0):
            raise PlaybackError("o alto-falante já está tocando outro áudio")
        stop_evt = threading.Event()
        session: _OutputSession | None = None
        iterator = iter(chunks)
        try:
            with self._state_lock:
                self._stop_evt = stop_evt
            for chunk in iterator:
                if cancel.cancelled or stop_evt.is_set():
                    return False
                pcm = _validate_chunk(chunk)
                if pcm.size == 0:
                    if chunk.on_played is not None:        # marca de fim sem áudio
                        if session is None:
                            _call_mark(chunk.on_played)
                        else:
                            session.add_mark(chunk.on_played)
                    continue
                if session is not None and session.rate != chunk.sample_rate:
                    completed = session.drain()
                    self._release(session)
                    session = None
                    if not completed:
                        return False
                if session is None:
                    session = self._start_session(chunk.sample_rate, cancel, stop_evt)
                    with self._state_lock:
                        self._session = session
                if not session.feed(pcm, chunk.on_played):
                    return False
            if session is None:
                return not (cancel.cancelled or stop_evt.is_set())
            return session.drain()
        finally:
            closer = getattr(iterator, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    log.debug("erro ao fechar o iterador de áudio", exc_info=True)
            if session is not None:
                self._release(session)
            with self._state_lock:
                self._stop_evt = None
                self._session = None
                self._idle_at = time.monotonic()
            self._play_lock.release()

    def _release(self, session: _OutputSession) -> None:
        session.close()
        with self._state_lock:
            if self._session is session:
                self._session = None

    def stop(self) -> None:
        """Interrompe a reprodução atual na hora (fade de ~12 ms). Sem efeito se nada toca. Thread-safe."""
        with self._state_lock:
            stop_evt, session = self._stop_evt, self._session
        if stop_evt is not None:
            stop_evt.set()
        if session is not None:
            session.request_fade()

    def close(self) -> None:
        """Alias de ``stop()``: o Speaker não mantém recursos entre reproduções (mantido para o ``shutdown`` do app)."""
        self.stop()
