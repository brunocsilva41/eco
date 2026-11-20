"""Reprodução interrompível de uma gravação na saída do ``cfg.audio.output_device`` (não trava a UI).

O callback do ``OutputStream`` só copia amostras. Uma thread vigia fecha o stream SEMPRE (``finally``),
seja no fim natural, em ``stop()`` ou em falha do dispositivo.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ..audio.devices import AudioError, DeviceError, load_sounddevice, resolve_device, stream_extra_settings
from ..config import AudioCfg
from .wavio import SAMPLE_RATE

log = logging.getLogger(__name__)

JOIN_TIMEOUT_S = 3.0
WATCH_INTERVAL_S = 0.03
TAIL_S = 0.15                        # folga para o buffer do driver esvaziar antes de fechar


class PlaybackError(AudioError):
    """Não foi possível tocar (saída ausente, ocupada...). Mensagem pronta para o usuário."""


class Player:
    def __init__(self, audio_cfg: AudioCfg) -> None:
        self._cfg = audio_cfg
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_req = threading.Event()
        self._done = threading.Event()
        self._data: NDArray[np.float32] = np.zeros(0, dtype=np.float32)
        self._pos = 0

    @property
    def is_playing(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def play(self, samples: NDArray[np.floating], sample_rate: int = SAMPLE_RATE) -> None:
        """Começa a tocar (interrompe o que estiver tocando). Volta na hora. Levanta ``PlaybackError``."""
        data = np.nan_to_num(np.asarray(samples, dtype=np.float32).reshape(-1))
        if data.size == 0:
            raise PlaybackError("Não há áudio para tocar.")
        self.stop()
        with self._lock:
            self._data = np.ascontiguousarray(np.clip(data, -1.0, 1.0))
            self._pos = 0
            self._stop_req.clear()
            self._done.clear()
        stream: Any = None
        try:
            device = resolve_device(self._cfg.output_device, "output")
            sd = load_sounddevice()
            stream = sd.OutputStream(
                samplerate=sample_rate, channels=1, dtype="float32", device=device.index,
                callback=self._callback, finished_callback=self._done.set,
                extra_settings=stream_extra_settings(device))
            stream.start()
        except DeviceError as exc:
            self._close(stream)
            raise PlaybackError(f"Saída de áudio indisponível: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - PortAudioError e afins
            self._close(stream)
            log.warning("falha ao abrir a saída de áudio: %s", exc)
            raise PlaybackError(f"Não consegui tocar o áudio: {exc}. Confira a saída de som do Windows.") from exc
        thread = threading.Thread(target=self._watch, args=(stream, data.size / sample_rate),
                                  name="wav-player", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        """Interrompe a reprodução e garante o stream fechado ao voltar. Idempotente."""
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        self._stop_req.set()
        if thread is not threading.current_thread():
            thread.join(JOIN_TIMEOUT_S)

    def _callback(self, outdata: Any, frames: int, time_info: Any, status: Any) -> None:
        import sounddevice as sd  # já carregado; só para CallbackStop
        pos = self._pos
        chunk = self._data[pos:pos + frames]
        n = chunk.shape[0]
        outdata[:n, 0] = chunk
        if n < frames:
            outdata[n:, 0] = 0.0
            self._pos = self._data.shape[0]
            raise sd.CallbackStop
        self._pos = pos + n

    @staticmethod
    def _close(stream: Any) -> None:
        if stream is None:
            return
        for action in ("abort", "close"):
            try:
                getattr(stream, action)()
            except Exception as exc:  # noqa: BLE001
                log.debug("stream.%s falhou: %s", action, exc)

    def _watch(self, stream: Any, duration_s: float) -> None:
        try:
            limit = duration_s + 2.0                          # rede de segurança contra stream que nunca termina
            waited = 0.0
            while not self._done.wait(WATCH_INTERVAL_S):
                waited += WATCH_INTERVAL_S
                if self._stop_req.is_set() or waited > limit:
                    break
            else:
                self._stop_req.wait(TAIL_S)                   # deixa o resto do buffer sair
        except Exception:  # noqa: BLE001
            log.exception("erro na thread de reprodução")
        finally:
            self._close(stream)
