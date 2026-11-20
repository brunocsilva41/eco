"""Gravação de microfone com duração EXATA, sem travar quem chama.

Modelo de threads
-----------------
* ``start()`` (thread da UI) resolve o dispositivo, abre o ``InputStream`` e volta na hora.
* O callback do PortAudio só COPIA o bloco para um buffer pré-alocado (nada de cálculo, log ou lock).
* Uma thread vigia (daemon) acompanha: buffer cheio, pedido de parada, relógio ``time.monotonic`` (prazo =
  duração + folga, vale mesmo se o callback falhar), travamento do fluxo (sem blocos por ``STALL_TIMEOUT_S``)
  e stream que parou sozinho (dispositivo removido). Ela SEMPRE fecha o stream (``finally``) e só então
  publica o resultado.
* ``level()``, ``state``, ``remaining_s`` etc. podem ser lidos de qualquer thread (o medidor calcula pico/RMS
  sobre a janela mais recente do buffer, sem lock).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from ..audio.devices import (AudioError, AudioDevice, DeviceError, DeviceSpec, list_devices, load_sounddevice,
                             resolve_device, stream_extra_settings)
from .wavio import SAMPLE_RATE

log = logging.getLogger(__name__)

BLOCK_SIZE = 512                    # 32 ms a 16 kHz
LEVEL_WINDOW_S = 0.05
DEADLINE_GRACE_S = 0.75             # folga além da duração antes de o relógio encerrar
STALL_TIMEOUT_S = 2.5               # sem blocos por tanto tempo = dispositivo morto
WATCH_INTERVAL_S = 0.02
JOIN_TIMEOUT_S = 3.0
SHORTFALL_TOLERANCE = 0.9           # no prazo, aceita >=90 % das amostras (completa com silêncio); menos = erro
MIN_DURATION_S = 0.1
MAX_DURATION_S = 600.0
_EXCLUDED_RANK = 99                 # igual a devices._EXCLUDED_RANK (WDM-KS fica de fora da lista)

ErrorKind = Literal["missing", "busy", "permission", "format", "stalled", "other"]


class RecorderState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    FINISHED = "finished"
    ERROR = "error"


class RecorderError(AudioError):
    """Falha de gravação com mensagem pronta para o usuário (pt-BR). ``kind`` ajuda a interface a orientar."""

    def __init__(self, message: str, kind: ErrorKind = "other") -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind


@dataclass(frozen=True)
class LevelReading:
    peak: float                     # 0..1, janela mais recente
    rms: float


_SILENT = LevelReading(0.0, 0.0)


@dataclass(frozen=True)
class InputChoice:
    spec: int | None                # None = padrão do Windows; senão índice do PortAudio
    label: str
    is_default: bool = False


def translate_error(exc: BaseException, device: AudioDevice | None = None) -> RecorderError:
    """Converte falhas do PortAudio em mensagem clara. Heurística sobre o texto do erro (varia por driver)."""
    raw = str(exc)
    low = raw.lower()
    name = f" \"{device.name}\"" if device else ""
    if any(t in low for t in ("denied", "access", "permission", "privacy", "0x80070005", "-2147024891")):
        return RecorderError(
            f"O Windows bloqueou o acesso ao microfone{name}. Abra Configurações > Privacidade e segurança > "
            "Microfone e permita que aplicativos de área de trabalho usem o microfone. "
            f"(detalhe técnico: {raw})", "permission")
    if any(t in low for t in ("in use", "allocated", "exclusive", "mme error 4", "0x8889000a", "busy")):
        return RecorderError(
            f"O microfone{name} está ocupado por outro programa. Feche apps que o estejam usando "
            f"(chamadas, gravadores) e tente de novo. (detalhe técnico: {raw})", "busy")
    if any(t in low for t in ("invalid device", "no driver", "mme error 2", "mme error 6", "device unavailable",
                              "not found", "no such device", "unplugged")):
        return RecorderError(
            f"O microfone{name} não está disponível: foi desconectado, desativado ou está em uso. "
            f"Confira o cabo/USB, escolha outro na lista e tente de novo. (detalhe técnico: {raw})", "missing")
    if any(t in low for t in ("sample rate", "number of channels", "invalid number", "format")):
        return RecorderError(
            f"O microfone{name} não aceita gravar em 16 kHz mono. Escolha outro dispositivo. "
            f"(detalhe técnico: {raw})", "format")
    return RecorderError(
        f"Não consegui abrir o microfone{name}: {raw}. Verifique se ele está conectado, se não está em uso "
        "e se o Windows permite o acesso (Configurações > Privacidade > Microfone).", "other")


def rescan_devices() -> None:
    """Força o PortAudio a reler a lista de dispositivos (para ver aparelhos conectados depois).

    Usa as funções internas ``_terminate``/``_initialize`` do sounddevice; só chame sem streams abertos.
    Falha silenciosa (log) se a versão não as tiver.
    """
    try:
        sd = load_sounddevice()
        sd._terminate()
        sd._initialize()
        log.info("lista de dispositivos de áudio reinicializada")
    except Exception as exc:  # noqa: BLE001 - interno do sounddevice; nunca derrubar a UI
        log.warning("não consegui reler os dispositivos de áudio: %s", exc)


def list_input_choices(rescan: bool = False) -> list[InputChoice]:
    """Microfones para a interface: um por aparelho (melhor API host), ordenados por nome.

    Levanta ``DeviceError`` se o PortAudio não responder.
    """
    if rescan:
        rescan_devices()
    devices = [d for d in list_devices() if d.supports("input") and d.api_rank < _EXCLUDED_RANK]
    groups: dict[str, list[AudioDevice]] = {}
    for d in devices:
        groups.setdefault(" ".join(d.name.casefold().split())[:28], []).append(d)
    choices: list[InputChoice] = []
    for group in groups.values():
        best = min(group, key=lambda d: (d.api_rank, d.index))
        choices.append(InputChoice(best.index, best.name, any(d.is_default_input for d in group)))
    choices.sort(key=lambda c: c.label.casefold())
    return choices


class MicRecorder:
    """Grava ``duration_s`` segundos de um microfone (16 kHz, mono, float32)."""

    def __init__(self, duration_s: float, *, device: DeviceSpec = None, sample_rate: int = SAMPLE_RATE) -> None:
        if not MIN_DURATION_S <= duration_s <= MAX_DURATION_S:
            raise ValueError(f"duration_s deve estar em {MIN_DURATION_S}..{MAX_DURATION_S}")
        if sample_rate <= 0:
            raise ValueError("sample_rate inválido")
        self._duration = float(duration_s)
        self._rate = int(sample_rate)
        self._total = int(round(self._duration * self._rate))
        self._device_spec: DeviceSpec = device
        self._lock = threading.Lock()
        self._state = RecorderState.IDLE
        self._error: RecorderError | None = None
        self._samples: NDArray[np.float32] | None = None
        self._device: AudioDevice | None = None
        self._thread: threading.Thread | None = None
        # estado do take atual
        self._buffer: NDArray[np.float32] = np.zeros(0, dtype=np.float32)
        self._pos = 0
        self._t0 = 0.0
        self._elapsed_final = 0.0
        self._last_cb = 0.0
        self._overflows = 0
        self._cb_error: BaseException | None = None
        self._full = threading.Event()
        self._stop_req = threading.Event()
        self._discard = False
        self._level_window = max(1, int(LEVEL_WINDOW_S * self._rate))

    # ------------------------------------------------------------------ consulta
    @property
    def duration_s(self) -> float:
        return self._duration

    @property
    def state(self) -> RecorderState:
        return self._state

    @property
    def error(self) -> RecorderError | None:
        return self._error

    @property
    def samples(self) -> NDArray[np.float32] | None:
        """Áudio entregue (``FINISHED``): exatamente ``duration_s`` se completou; menor se parado antes."""
        return self._samples

    @property
    def device(self) -> AudioDevice | None:
        return self._device

    def set_device(self, spec: DeviceSpec) -> None:
        """Dispositivo da PRÓXIMA gravação (None = padrão do Windows)."""
        self._device_spec = spec

    @property
    def elapsed_s(self) -> float:
        if self._state is RecorderState.RECORDING:
            return min(self._duration, time.monotonic() - self._t0)
        if self._state in (RecorderState.FINISHED, RecorderState.ERROR):
            return self._elapsed_final
        return 0.0

    @property
    def remaining_s(self) -> float:
        if self._state is RecorderState.RECORDING:
            return max(0.0, self._duration - (time.monotonic() - self._t0))
        return self._duration if self._state is RecorderState.IDLE else 0.0

    @property
    def progress(self) -> float:
        return min(1.0, self.elapsed_s / self._duration)

    def level(self) -> LevelReading:
        """Pico e RMS (0..1) do trecho mais recente (~50 ms). Zero fora da gravação."""
        if self._state is not RecorderState.RECORDING:
            return _SILENT
        pos, buf = self._pos, self._buffer
        if pos <= 0:
            return _SILENT
        seg = buf[max(0, pos - self._level_window):pos]
        if seg.size == 0:
            return _SILENT
        return LevelReading(float(np.max(np.abs(seg))), float(np.sqrt(np.mean(seg * seg))))

    # ------------------------------------------------------------------ controle
    def start(self) -> None:
        """Abre o microfone e começa a gravar; volta imediatamente. Levanta ``RecorderError``."""
        with self._lock:
            if self._state is RecorderState.RECORDING:
                raise RecorderError("Já existe uma gravação em andamento.", "other")
            previous = self._thread
        if previous is not None and previous.is_alive():
            previous.join(JOIN_TIMEOUT_S)
        self._reset_take()

        try:
            device = resolve_device(self._device_spec, "input")
        except DeviceError as exc:
            raise self._fail(RecorderError(str(exc), "missing")) from exc
        self._device = device

        stream: Any = None
        try:
            sd = load_sounddevice()
            stream = sd.InputStream(
                samplerate=self._rate, channels=1, dtype="float32", device=device.index,
                blocksize=BLOCK_SIZE, callback=self._callback, extra_settings=stream_extra_settings(device))
            stream.start()
        except DeviceError as exc:
            self._close_stream(stream)
            raise self._fail(RecorderError(str(exc), "other")) from exc
        except Exception as exc:  # noqa: BLE001 - PortAudioError, ValueError, OSError...
            self._close_stream(stream)
            log.warning("falha ao abrir o microfone %s: %s", device.label, exc)
            raise self._fail(translate_error(exc, device)) from exc

        self._t0 = time.monotonic()
        self._last_cb = self._t0
        thread = threading.Thread(target=self._watch, args=(stream,), name="mic-recorder", daemon=True)
        with self._lock:
            self._state = RecorderState.RECORDING
            self._thread = thread
        log.info("gravando %.1f s de %s", self._duration, device.label)
        thread.start()

    def stop(self, *, discard: bool = False) -> None:
        """Para a gravação e garante o stream fechado ao voltar. Idempotente.

        Por padrão mantém o que foi gravado até agora (``samples`` com menos de ``duration_s``);
        com ``discard=True`` descarta e volta a ``IDLE``.
        """
        with self._lock:
            thread = self._thread
            if self._state is not RecorderState.RECORDING:
                return
            self._discard = discard
            self._stop_req.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(JOIN_TIMEOUT_S)
            if thread.is_alive():
                log.error("a thread de gravação não terminou em %.1f s", JOIN_TIMEOUT_S)

    def reset(self) -> None:
        """Volta a ``IDLE`` descartando resultado/erro (só se não estiver gravando)."""
        with self._lock:
            if self._state is RecorderState.RECORDING:
                return
            self._state = RecorderState.IDLE
            self._error = None
            self._samples = None

    def wait(self, timeout: float | None = None) -> bool:
        """Espera o fim da gravação. True se terminou (qualquer estado final)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return self._state is not RecorderState.RECORDING

    # ------------------------------------------------------------------ internos
    def _reset_take(self) -> None:
        with self._lock:
            self._error = None
            self._samples = None
            self._buffer = np.zeros(self._total, dtype=np.float32)
            self._pos = 0
            self._elapsed_final = 0.0
            self._overflows = 0
            self._cb_error = None
            self._discard = False
            self._full.clear()
            self._stop_req.clear()
            self._state = RecorderState.IDLE

    def _fail(self, error: RecorderError) -> RecorderError:
        with self._lock:
            self._error = error
            self._state = RecorderState.ERROR
        return error

    def _callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        """Roda na thread de áudio: só copia. Nada de log, lock ou cálculo."""
        try:
            if status:
                self._overflows += 1
            pos = self._pos
            n = min(frames, self._total - pos)
            if n > 0:
                self._buffer[pos:pos + n] = indata[:n, 0]
                self._pos = pos + n
                self._last_cb = time.monotonic()
            if self._pos >= self._total:
                self._full.set()
        except Exception as exc:  # noqa: BLE001 - nunca propagar para o PortAudio
            self._cb_error = exc

    @staticmethod
    def _close_stream(stream: Any) -> None:
        if stream is None:
            return
        for action in ("abort", "close"):
            try:
                getattr(stream, action)()
            except Exception as exc:  # noqa: BLE001
                log.debug("stream.%s falhou: %s", action, exc)

    def _monitor(self, stream: Any) -> str:
        deadline = self._t0 + self._duration + DEADLINE_GRACE_S
        while True:
            if self._full.wait(WATCH_INTERVAL_S):
                return "full"
            if self._stop_req.is_set():
                return "stop"
            if self._cb_error is not None:
                return "callback"
            now = time.monotonic()
            if now >= deadline:
                return "deadline"
            if now - self._last_cb > STALL_TIMEOUT_S:
                return "stalled"
            try:
                if not stream.active:
                    return "lost"
            except Exception:  # noqa: BLE001 - stream já inválido
                return "lost"

    def _watch(self, stream: Any) -> None:
        reason = "crash"
        try:
            reason = self._monitor(stream)
        except Exception:  # noqa: BLE001
            log.exception("erro inesperado na thread de gravação")
        finally:
            self._close_stream(stream)                     # SEMPRE fecha antes de publicar o resultado
            try:
                self._conclude(reason)
            except Exception:  # noqa: BLE001
                log.exception("erro ao concluir a gravação")
                self._fail(RecorderError("Erro interno ao concluir a gravação.", "other"))

    def _conclude(self, reason: str) -> None:
        pos = min(self._pos, self._total)
        elapsed = min(self._duration, time.monotonic() - self._t0)
        if self._overflows:
            log.warning("o microfone reportou %d falha(s)/estouro(s) de buffer durante a gravação", self._overflows)

        if reason == "full":
            self._publish(self._buffer.copy(), elapsed)
        elif reason == "stop":
            if self._discard or pos == 0:
                with self._lock:
                    self._state, self._samples = RecorderState.IDLE, None
            else:
                self._publish(self._buffer[:pos].copy(), elapsed)
        elif pos >= self._total * SHORTFALL_TOLERANCE:      # prazo/queda no fim: completa com silêncio
            log.warning("gravação encerrada (%s) com %d/%d amostras; completada com silêncio", reason, pos, self._total)
            self._publish(self._buffer.copy(), elapsed)
        else:
            detail = f" ({self._cb_error})" if self._cb_error else ""
            name = f" \"{self._device.name}\"" if self._device else ""
            self._fail(RecorderError(
                f"O microfone{name} parou de enviar áudio durante a gravação{detail}. Ele pode ter sido "
                "desconectado ou desativado. Confira e tente de novo.", "stalled"))
            log.error("gravação falhou (%s): %d/%d amostras", reason, pos, self._total)

    def _publish(self, samples: NDArray[np.float32], elapsed: float) -> None:
        with self._lock:
            self._samples = samples
            self._elapsed_final = elapsed
            self._state = RecorderState.FINISHED
        log.info("gravação concluída: %.2f s", samples.size / self._rate)
