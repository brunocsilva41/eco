"""Captura de microfone: detecção de fala (VAD) e push-to-talk.

Fluxo: ``sounddevice.InputStream`` (16 kHz, mono, float32, blocos de 512 amostras = 1 janela do VAD)
-> callback leve que só copia o bloco para uma fila limitada -> thread de quem chama consome a fila.

Contrato de threads
-------------------
* O callback de áudio roda numa thread do PortAudio e faz apenas: carimbo de tempo, contadores,
  cópia do bloco e ``put_nowait`` (se a fila encher, descarta o bloco MAIS ANTIGO e conta). Nunca
  bloqueia, nunca loga, nunca publica eventos.
* ``listen_utterance`` e ``record_while`` rodam inteiros na thread que as chama (VAD, níveis e
  eventos incluídos); só uma captura por vez (a segunda levanta ``CaptureError``). Ambas devolvem
  ``None`` quando canceladas, quando ``close()`` é chamado de outra thread, ou sem fala.
* ``open``, ``close``, ``mute``, ``unmute`` e as propriedades são thread-safe e idempotentes.
* Esta classe não cria threads próprias.

Áudio recebido antes da chamada é descartado no início de cada captura (``flush_backlog``). Para ignorar
também o eco da fala/pergunta do próprio Eco, ``listen_utterance(not_before=t)`` descarta todo bloco
capturado antes de ``t`` (``time.monotonic()``): cada bloco é carimbado no callback com a hora de chegada
(erro ~ latência de entrada, dezenas de ms). O app deve esperar o fim da fala (``Voice.idle_since()`` /
``Speaker.idle_since()``) e passar esse instante, mais uma margem para o eco da sala.

O VAD é carregado em ``open()``/``preload()`` (erro claro e cedo se o modelo faltar), a partir de
``vad_path`` ou ``models_dir`` (use ``cfg.paths.models``: o mesmo caminho que o ``doctor`` valida).

Quando o dispositivo some (stream inativo ou sem callbacks por ``STALL_INPUT_S``), a captura tenta reabrir
com backoff exponencial (0,25 s .. 2 s) até ``max_open_attempts`` vezes e então levanta ``DeviceError``.
A reabertura NÃO segura ``_state_lock`` durante a abertura do dispositivo (que pode demorar): aberturas
são serializadas por ``_open_lock`` e o stream novo só é publicado sob ``_state_lock`` se ainda for
desejado; ``close()`` é sempre rápido e descarta um stream aberto concorrentemente.
"""
from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from ..config import AudioCfg
from ..core.cancel import CancelToken
from ..core.events import EventBus
from .constants import SAMPLE_RATE, STALL_INPUT_S
from .devices import (AudioDevice, AudioError, DeviceError, load_sounddevice, resolve_input_device,
                      stream_extra_settings)
from .levels import LevelMeter
from .vad import WINDOW_SAMPLES, SileroVAD, default_model_path

log = logging.getLogger(__name__)

FRAME_MS = WINDOW_SAMPLES * 1000.0 / SAMPLE_RATE       # 32 ms
_POLL_S = 0.1                                          # fatia máxima de espera por áudio (reatividade a cancel/close)
_TAIL_KEEP_FRAMES = 6                                  # silêncio final mantido (~190 ms) ao devolver a fala
_HYSTERESIS = 0.15                                     # limiar para CONTINUAR a fala = limiar de início - 0,15
_STATS_EVERY_S = 5.0
_EMPTY = np.empty(0, dtype=np.float32)


class CaptureError(AudioError):
    """Uso incorreto da captura (ex.: duas capturas simultâneas)."""


def _frames(ms: float) -> int:
    return max(1, math.ceil(ms / FRAME_MS))


class Microphone:
    def __init__(
        self,
        cfg: AudioCfg,
        bus: EventBus | None = None,
        *,
        vad_path: Path | str | None = None,
        models_dir: Path | str | None = None,
        queue_seconds: float = 20.0,
        max_open_attempts: int = 5,
    ) -> None:
        if cfg.sample_rate != SAMPLE_RATE:
            raise ValueError(f"audio.sample_rate deve ser {SAMPLE_RATE}")
        if queue_seconds <= 0 or max_open_attempts < 1:
            raise ValueError("queue_seconds > 0 e max_open_attempts >= 1")
        self._cfg = cfg
        # vad_path explícito vence; senão deriva de models_dir (passe cfg.paths.models); senão o padrão de PathsCfg
        self._vad_path: Path = Path(vad_path) if vad_path is not None else default_model_path(
            Path(models_dir) if models_dir is not None else None)
        self._vad: SileroVAD | None = None
        self._vad_lock = threading.Lock()
        self._meter = LevelMeter(bus, "mic")
        self._max_attempts = max_open_attempts

        self._min_speech_frames = _frames(cfg.min_speech_ms)
        self._end_silence_frames = _frames(cfg.end_silence_ms)
        self._max_frames = max(1, math.ceil(cfg.max_utterance_s * SAMPLE_RATE / WINDOW_SAMPLES))
        self._pre_roll_frames = max(0, math.ceil(cfg.pre_roll_ms / FRAME_MS))
        self._start_thr = float(cfg.vad_threshold)
        self._keep_thr = max(0.01, self._start_thr - _HYSTERESIS)

        self._queue: queue.Queue[tuple[float, np.ndarray]] = queue.Queue(
            maxsize=max(8, math.ceil(queue_seconds * SAMPLE_RATE / WINDOW_SAMPLES)))
        self._carry: np.ndarray = _EMPTY                   # sobra de amostras (só a thread consumidora mexe)
        self._state_lock = threading.Lock()                # protege _stream e _wanted (seções curtas, sem E/S)
        self._open_lock = threading.Lock()                 # serializa aberturas de stream (E/S fora do _state_lock)
        self._capture_lock = threading.Lock()              # uma captura por vez
        self._stream: Any | None = None
        self._wanted = False                               # True entre open() e close(); impede reabrir após close
        self._muted = threading.Event()

        self._last_cb = 0.0                                # escrito só pelo callback
        self._overflows = 0                                # idem
        self._dropped = 0                                  # idem
        self._rep_overflows = 0
        self._rep_dropped = 0
        self._rep_at = time.monotonic()

    # ------------------------------------------------------------------ ciclo de vida
    def __enter__(self) -> "Microphone":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    @property
    def muted(self) -> bool:
        return self._muted.is_set()

    @property
    def vad_path(self) -> Path:
        return self._vad_path

    def preload(self) -> None:
        """Carrega o VAD agora (idempotente). Levanta ``VadError`` se o modelo faltar ou for inválido."""
        self._get_vad()

    def open(self) -> None:
        """Carrega o VAD e abre o stream (idempotente). Levanta ``VadError``/``DeviceError`` (uma tentativa)."""
        self.preload()
        with self._state_lock:
            self._wanted = True
            has_stream = self._stream is not None
        if not has_stream:
            self._open_stream()

    def close(self) -> None:
        """Fecha o stream (idempotente) e interrompe qualquer captura em andamento em outra thread."""
        with self._state_lock:
            self._wanted = False
            stream, self._stream = self._stream, None
        self._close_raw(stream)
        self._drain_queue()

    def mute(self) -> None:
        """Descarta o áudio daqui em diante; capturas em andamento são abandonadas (voltam a esperar)."""
        if not self._muted.is_set():
            self._muted.set()
            self._drain_queue()
            log.info("microfone mudo")

    def unmute(self) -> None:
        if self._muted.is_set():
            self._drain_queue()
            self._muted.clear()
            log.info("microfone ativo")

    def _create_stream(self) -> tuple[Any, AudioDevice]:
        """Resolve o dispositivo e abre/inicia um stream (E/S lenta; chamar SEM ``_state_lock``)."""
        sd = load_sounddevice()
        device = resolve_input_device(self._cfg)
        stream: Any | None = None
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=WINDOW_SAMPLES,
                device=device.index, latency="low", callback=self._on_audio,
                extra_settings=stream_extra_settings(device))
            self._drain_queue()
            self._last_cb = time.monotonic()
            stream.start()
        except Exception as exc:  # PortAudioError, ValueError de parâmetros, OSError do driver
            self._close_raw(stream)
            raise DeviceError(f"não consegui abrir o microfone {device.label}: {exc}") from exc
        return stream, device

    def _open_stream(self) -> bool:
        """Garante um stream aberto sem segurar ``_state_lock`` durante a abertura.

        True se há stream aberto ao final; False se ``close()`` aconteceu no meio (o stream novo é descartado).
        """
        with self._open_lock:
            with self._state_lock:
                if self._stream is not None:
                    return True
                if not self._wanted:
                    return False
            stream, device = self._create_stream()
            with self._state_lock:
                installed = self._wanted and self._stream is None
                if installed:
                    self._stream = stream
        if not installed:
            self._close_raw(stream)
            self._drain_queue()
            log.debug("microfone fechado durante a abertura; stream novo descartado")
            return False
        log.info("microfone aberto: %s", device.label)
        return True

    @staticmethod
    def _close_raw(stream: Any | None) -> None:
        if stream is None:
            return
        for action in (stream.abort, stream.close):
            try:
                action()
            except Exception as exc:
                log.debug("erro ao fechar o stream de entrada: %s", exc)

    def _drain_queue(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def _recover(self, cancel: CancelToken) -> bool:
        """(Re)abre o stream com backoff. False se cancelado/fechado; ``DeviceError`` se esgotar as tentativas."""
        last: DeviceError | None = None
        for attempt in range(1, self._max_attempts + 1):
            with self._state_lock:
                if not self._wanted:
                    return False
                stale, self._stream = self._stream, None
            if stale is not None:                          # fecha o stream morto FORA do lock
                self._close_raw(stale)
                log.debug("microfone fechado para reabrir")
            self._drain_queue()
            try:
                opened = self._open_stream()
            except DeviceError as exc:
                last = exc
                log.warning("microfone indisponível (tentativa %d/%d): %s", attempt, self._max_attempts, exc)
            else:
                if not opened:
                    return False
                self._carry = _EMPTY
                return True
            if attempt < self._max_attempts and cancel.wait(min(0.25 * 2 ** (attempt - 1), 2.0)):
                return False
        raise DeviceError(f"microfone indisponível após {self._max_attempts} tentativas: {last}") from last

    # ------------------------------------------------------------------ callback (thread do PortAudio)
    def _on_audio(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        now = time.monotonic()
        self._last_cb = now
        if status.input_overflow:
            self._overflows += 1
        if self._muted.is_set():
            return
        block = indata[:, 0].copy()
        try:
            self._queue.put_nowait((now, block))
        except queue.Full:                                 # consumidor atrasado: mantém o áudio mais novo
            self._dropped += 1
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((now, block))
            except (queue.Empty, queue.Full):
                pass

    # ------------------------------------------------------------------ consumo
    def _log_stats(self) -> None:
        now = time.monotonic()
        if now - self._rep_at < _STATS_EVERY_S:
            return
        overflows, dropped = self._overflows, self._dropped
        if overflows != self._rep_overflows or dropped != self._rep_dropped:
            log.warning("captura: %d overflows e %d blocos descartados desde o último aviso",
                        overflows - self._rep_overflows, dropped - self._rep_dropped)
            self._rep_overflows, self._rep_dropped = overflows, dropped
        self._rep_at = now

    def _check_health(self, cancel: CancelToken) -> None:
        stream = self._stream
        try:
            dead = stream is None or not stream.active
        except Exception:
            dead = True
        if not dead and time.monotonic() - self._last_cb > STALL_INPUT_S:
            dead = True
        if dead:
            log.warning("stream de entrada parou ou ficou sem dados; tentando reabrir")
            self._recover(cancel)

    def _next_frame(self, cancel: CancelToken, deadline: float | None,
                    not_before: float | None = None) -> np.ndarray | None:
        """Próxima janela de 512 amostras. None se cancelado, fechado ou ``deadline`` (monotonic) vencido.

        Blocos carimbados antes de ``not_before`` (monotonic) são descartados.
        """
        while True:
            if len(self._carry) >= WINDOW_SAMPLES:
                frame = self._carry[:WINDOW_SAMPLES]
                self._carry = self._carry[WINDOW_SAMPLES:]
                return frame
            if cancel.cancelled or not self._wanted:
                return None
            timeout = _POLL_S
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                timeout = min(timeout, remaining)
            try:
                stamp, block = self._queue.get(timeout=timeout)
            except queue.Empty:
                self._check_health(cancel)
                continue
            if not_before is not None and stamp < not_before:
                continue                                   # eco / áudio anterior ao instante pedido
            self._carry = block if self._carry.size == 0 else np.concatenate((self._carry, block))
            self._log_stats()

    def _discard_pending(self) -> None:
        self._carry = _EMPTY
        self._drain_queue()

    @contextmanager
    def _capture_session(self, cancel: CancelToken, flush_backlog: bool) -> Iterator[bool]:
        """Reserva a captura, garante o stream aberto e limpa o backlog. Entrega False se abrir foi cancelado."""
        if not self._capture_lock.acquire(blocking=False):
            raise CaptureError("já existe uma captura de microfone em andamento")
        try:
            with self._state_lock:
                self._wanted = True
                needs_open = self._stream is None
            if needs_open and not self._recover(cancel):
                yield False
                return
            if flush_backlog:
                self._discard_pending()
            yield True
        finally:
            self._meter.finish()
            self._capture_lock.release()

    def _get_vad(self) -> SileroVAD:
        vad = self._vad
        if vad is not None:
            return vad
        with self._vad_lock:
            if self._vad is None:
                t0 = time.perf_counter()
                self._vad = SileroVAD(self._vad_path)
                log.info("VAD carregado em %.2f s (%s)", time.perf_counter() - t0, self._vad_path)
            return self._vad

    # ------------------------------------------------------------------ API pública de captura
    def listen_utterance(
        self,
        cancel: CancelToken,
        *,
        max_wait_s: float | None,
        flush_backlog: bool = True,
        not_before: float | None = None,
    ) -> np.ndarray | None:
        """Espera uma fala e a devolve (float32 mono 16 kHz, com pré-roll) ou None.

        ``max_wait_s`` limita a espera pelo INÍCIO da fala (None = sem limite); depois que a fala começa
        ela só termina por silêncio final (``end_silence_ms``) ou ``max_utterance_s`` (devolve o que
        gravou até ali). Ruído mais curto que ``min_speech_ms`` é descartado e a escuta continua.
        Retorna None se cancelado, se o microfone foi fechado, ou se estourou ``max_wait_s``.

        ``not_before`` (``time.monotonic()``): todo áudio capturado antes desse instante é descartado
        (eco da fala/pergunta do Eco e sobras do buffer). Pode estar no futuro (fim da fala + margem);
        nesse caso ``max_wait_s`` conta a partir dele. Com o microfone MUDO a chamada espera (sem
        busy-loop) até desmutar, cancelar ou vencer ``max_wait_s``; só então devolve None.
        """
        if max_wait_s is not None and max_wait_s <= 0:
            raise ValueError("max_wait_s deve ser > 0 ou None")
        if not_before is not None and not math.isfinite(not_before):
            raise ValueError("not_before deve ser um instante finito de time.monotonic()")
        with self._capture_session(cancel, flush_backlog) as ready:
            return self._listen_loop(cancel, max_wait_s, not_before) if ready else None

    def _listen_loop(self, cancel: CancelToken, max_wait_s: float | None,
                     not_before: float | None) -> np.ndarray | None:
        vad = self._get_vad()
        vad.reset()
        start = time.monotonic()
        if not_before is not None:
            start = max(start, not_before)
        deadline = None if max_wait_s is None else start + max_wait_s
        ring: deque[np.ndarray] = deque(maxlen=self._pre_roll_frames)
        utterance: list[np.ndarray] = []
        speaking = False
        voiced = 0
        silence_run = 0

        while True:
            if self._muted.is_set():                       # mudo: descarta tudo, não processa
                if speaking or ring:
                    speaking, voiced, silence_run = False, 0, 0
                    utterance = []
                    ring.clear()
                    vad.reset()
                self._discard_pending()
                wait_s = _POLL_S
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    wait_s = min(wait_s, remaining)
                if cancel.wait(wait_s) or not self._wanted:
                    return None
                continue

            frame = self._next_frame(cancel, None if speaking else deadline, not_before)
            if frame is None:
                if not cancel.cancelled and self._wanted:
                    log.debug("nenhuma fala dentro de %.1f s", max_wait_s or 0.0)
                return None
            self._meter.feed(frame)
            prob = vad.prob(frame)

            if not speaking:
                if prob >= self._start_thr:
                    speaking = True
                    utterance = [*ring, frame]
                    ring.clear()
                    voiced, silence_run = 1, 0
                else:
                    ring.append(frame)
                continue

            utterance.append(frame)
            if prob >= self._keep_thr:
                voiced += 1
                silence_run = 0
            else:
                silence_run += 1

            if silence_run >= self._end_silence_frames:
                if voiced >= self._min_speech_frames:
                    keep = len(utterance) - silence_run + _TAIL_KEEP_FRAMES
                    audio = np.concatenate(utterance[:keep])
                    log.debug("fala capturada: %.2f s (%d janelas de voz)", audio.size / SAMPLE_RATE, voiced)
                    return audio
                log.debug("ruído curto descartado (%d janelas de voz)", voiced)
                speaking, voiced, silence_run = False, 0, 0
                utterance = []
                vad.reset()
                continue

            if len(utterance) >= self._max_frames:
                log.warning("fala atingiu o limite de %.0f s; encerrando a gravação", self._cfg.max_utterance_s)
                return np.concatenate(utterance)

    def record_while(self, cancel: CancelToken, hold: Callable[[], bool]) -> np.ndarray | None:
        """Push-to-talk: grava enquanto ``hold()`` for True (checado a cada janela de 32 ms).

        Para em ``max_utterance_s``. Devolve None se cancelado, se o microfone está mudo, ou se a
        gravação tem menos que ``min_speech_ms``. Exceção em ``hold`` conta como "soltou".
        """
        frames: list[np.ndarray] = []
        with self._capture_session(cancel, True) as ready:
            if not ready:
                return None
            if self._muted.is_set():
                log.info("push-to-talk ignorado: microfone mudo")
                return None
            while True:
                if self._muted.is_set():
                    log.info("microfone ficou mudo durante a gravação; descartando")
                    return None
                frame = self._next_frame(cancel, None)
                if frame is None:
                    return None
                if not self._poll_hold(hold):
                    break
                self._meter.feed(frame)
                frames.append(frame)
                if len(frames) >= self._max_frames:
                    log.warning("gravação atingiu o limite de %.0f s", self._cfg.max_utterance_s)
                    break
        if len(frames) < self._min_speech_frames:
            log.debug("gravação curta demais (%d janelas); descartada", len(frames))
            return None
        return np.concatenate(frames)

    @staticmethod
    def _poll_hold(hold: Callable[[], bool]) -> bool:
        try:
            return bool(hold())
        except Exception:
            log.exception("hold() levantou exceção; encerrando a gravação")
            return False
