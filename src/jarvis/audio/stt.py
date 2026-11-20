"""Reconhecimento de fala offline com faster-whisper (CPU).

Pontos de projeto:
* O áudio entra SEMPRE como array float32 mono 16 kHz. Nunca passamos caminho de arquivo: o
  faster-whisper 1.2.1 quebra com o ``av`` 19 do venv ao decodificar arquivos.
* O VAD já foi feito na captura, então ``vad_filter=False``; ``condition_on_previous_text=False``
  evita que um erro contamine a próxima janela.
* O modelo é carregado sob demanda (``preload()`` para aquecer).
* Privacidade: o texto transcrito só aparece em logs DEBUG; em INFO vão apenas durações.

Contrato de threads e cancelamento
----------------------------------
``Transcriber`` é thread-safe. A decodificação roda numa thread DESCARTÁVEL (daemon, "jarvis-stt-decode"),
enquanto a thread chamadora espera com polling (50 ms) do ``CancelToken``: ao cancelar, ``transcribe``
levanta ``Cancelled`` NA HORA, mesmo no meio da decodificação de uma janela (que o CTranslate2 não
consegue interromper). O resultado de uma execução abandonada é descartado e ela encerra sozinha no
próximo limite de segmento.

Decisão sobre o lock: transcrições "vivas" são serializadas por ``_run_lock``, que é segurado pela
thread CHAMADORA (nunca por uma execução abandonada), então um abandono não trava a próxima chamada.
Para não acumular CPU, no máximo ``_MAX_ABANDONED`` (1) execução abandonada roda ao mesmo tempo que
uma nova (teto de 2 decodificações simultâneas; com ``num_workers=1`` o CTranslate2 as enfileira
internamente). Se já houver uma abandonada, a nova inicia normalmente; se uma segunda for abandonada
enquanto a primeira ainda roda, a chamada seguinte espera (cancelável, com prazo) até uma terminar.
Há também um prazo total por chamada (``_BASE_TIMEOUT_S`` + ``_TIMEOUT_PER_S`` por segundo de áudio):
estourar vira ``TranscribeError`` e a execução é abandonada.

Entrada inválida levanta ``TypeError``/``ValueError``; falhas do modelo viram ``TranscribeError``.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..config import SttCfg
from ..core.cancel import Cancelled, CancelToken
from ..core.textutil import words
from .constants import SAMPLE_RATE
from .devices import AudioError

log = logging.getLogger(__name__)

MIN_AUDIO_S = 0.2                   # abaixo disso não há palavra: devolve texto vazio sem rodar o modelo
MAX_AUDIO_S = 60.0                  # acima disso o excedente é cortado (config limita a fala a 60 s)
MAX_BEAM_SIZE = 10
_SILENCE_PEAK = 1e-4                # pico abaixo disso = silêncio digital
_QUIET_RMS = 0.008                  # RMS abaixo disso = áudio "silencioso" (ruído de fundo)
_SHORT_AUDIO_S = 3.0                # áudio "muito curto" para frases típicas de alucinação
_MODEL_FILE = "model.bin"
_POLL_S = 0.05
_BASE_TIMEOUT_S = 30.0
_TIMEOUT_PER_S = 4.0
_MAX_TIMEOUT_S = 300.0
_MAX_ABANDONED = 1

# Filtro anti-alucinação (o Whisper inventa texto em ruído/silêncio)
_NO_SPEECH_DROP = 0.9               # quase certeza de não-fala: descarta sempre
_NO_SPEECH_PROB = 0.6               # provável não-fala E baixa confiança: descarta
_MIN_AVG_LOGPROB = -1.0
_MAX_COMPRESSION = 2.4              # texto muito repetitivo (limiar do próprio Whisper)
_WEAK_NO_SPEECH = 0.4               # frases fracas ("obrigado") só caem com esta probabilidade de não-fala
# frases típicas de legenda de vídeo que o Whisper "ouve" em silêncio (comparadas via core.textutil.words)
_HALLUCINATION_PHRASES: tuple[str, ...] = (
    "obrigado por assistir", "obrigada por assistir", "legendas pela comunidade amara org",
    "legenda adriana zanotto", "inscreva se no canal", "se inscreva no canal", "nao se esqueca de se inscrever",
    "ate o proximo video", "ate a proxima", "deixe seu like", "tchau tchau",
)
# frases que também são fala real curta: só descartadas com forte indício de não-fala
_WEAK_PHRASES = frozenset({"obrigado", "obrigada", "tchau", "valeu", "ate logo", "ate mais"})


class TranscribeError(AudioError):
    """Modelo ausente/ilegível ou falha interna na transcrição."""


@dataclass(frozen=True)
class Transcript:
    text: str                       # vazio se silêncio/ruído
    language: str
    duration_s: float               # duração do áudio entregue
    elapsed_s: float                # tempo gasto transcrevendo


def find_local_model(model_dir: Path) -> Path | None:
    """Pasta com ``model.bin``: ``model_dir`` direto ou um snapshot do cache Hugging Face dentro dele."""
    if not model_dir.is_dir():
        return None
    if (model_dir / _MODEL_FILE).is_file():
        return model_dir
    snapshots = [p for p in model_dir.glob(f"models--*/snapshots/*/{_MODEL_FILE}") if p.is_file()]
    if not snapshots:
        return None
    return max(snapshots, key=lambda p: p.stat().st_mtime).parent


def prepare_audio(audio: np.ndarray) -> np.ndarray:
    """Valida e normaliza para float32 1-D contíguo em [-1, 1], limitado a ``MAX_AUDIO_S``."""
    if not isinstance(audio, np.ndarray):
        raise TypeError(f"áudio deve ser np.ndarray, recebido {type(audio).__name__}")
    if audio.dtype == np.int16:
        samples = audio.astype(np.float32) / 32768.0
    elif audio.dtype.kind == "f":
        samples = audio.astype(np.float32, copy=False)
    else:
        raise TypeError(f"dtype de áudio não suportado: {audio.dtype} (use float32 ou int16)")
    if samples.ndim == 2 and 1 in samples.shape:
        samples = samples.reshape(-1)
    if samples.ndim != 1:
        raise ValueError(f"áudio deve ser mono (1-D); recebido shape {audio.shape}")
    if samples.size and not np.isfinite(samples).all():
        raise ValueError("áudio contém NaN/Inf")
    limit = int(MAX_AUDIO_S * SAMPLE_RATE)
    if samples.size > limit:
        log.warning("áudio de %.1f s excede %.0f s; o excedente será ignorado", samples.size / SAMPLE_RATE, MAX_AUDIO_S)
        samples = samples[:limit]
    if samples.size and float(np.max(np.abs(samples))) > 1.0:
        log.warning("amostras fora de [-1, 1]; aplicando clip (a escala do áudio está certa?)")
        samples = np.clip(samples, -1.0, 1.0)
    return np.ascontiguousarray(samples)


def is_hallucination(text: str, *, no_speech_prob: float, duration_s: float, rms: float) -> bool:
    """True se ``text`` parece alucinação do Whisper (frase de legenda em áudio curto/silencioso, ou repetição)."""
    ws = words(text)
    if not ws:
        return True
    flat = " ".join(ws)
    suspicious_audio = duration_s < _SHORT_AUDIO_S or rms < _QUIET_RMS or no_speech_prob > 0.3
    if suspicious_audio and any(phrase in flat for phrase in _HALLUCINATION_PHRASES):
        return True
    if flat in _WEAK_PHRASES and no_speech_prob > _WEAK_NO_SPEECH:
        return True
    if len(ws) >= 4 and len(set(ws)) / len(ws) <= 0.25:     # "obrigado obrigado obrigado obrigado ..."
        return True
    return False


def _keep_segment(seg: Any, duration_s: float, rms: float) -> bool:
    no_speech = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
    logprob = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
    compression = float(getattr(seg, "compression_ratio", 0.0) or 0.0)
    if no_speech >= _NO_SPEECH_DROP or (no_speech > _NO_SPEECH_PROB and logprob < _MIN_AVG_LOGPROB):
        log.debug("segmento descartado (no_speech=%.2f, logprob=%.2f)", no_speech, logprob)
        return False
    if compression > _MAX_COMPRESSION and logprob < _MIN_AVG_LOGPROB:
        log.debug("segmento repetitivo descartado (compressão=%.2f)", compression)
        return False
    if is_hallucination(seg.text, no_speech_prob=no_speech, duration_s=duration_s, rms=rms):
        log.debug("segmento descartado como alucinação (no_speech=%.2f)", no_speech)
        return False
    return True


@dataclass
class _Job:
    """Uma decodificação. Os campos de resultado só são lidos depois de ``done``."""
    abandon: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    finished: bool = False          # (sob _cv) a thread terminou
    abandoned: bool = False         # (sob _cv) o chamador desistiu dela
    text: str = ""
    language: str = ""
    error: BaseException | None = None


class Transcriber:
    def __init__(self, cfg: SttCfg) -> None:
        self._cfg = cfg
        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._run_lock = threading.Lock()                  # transcrições vivas, uma por vez (segurado pelo chamador)
        self._cv = threading.Condition()                   # protege _abandoned e os flags de _Job
        self._abandoned = 0
        lang = cfg.language.strip().lower()
        self._language: str | None = None if lang in ("", "auto") else lang

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        """Carrega o modelo agora (idempotente). Levanta ``TranscribeError`` se falhar."""
        self._ensure_model()

    def close(self) -> None:
        """Libera o modelo (será recarregado no próximo uso). Decodificações em curso terminam com a referência antiga."""
        with self._load_lock:
            self._model = None

    def _ensure_model(self) -> Any:
        model = self._model
        if model is not None:
            return model
        with self._load_lock:
            if self._model is not None:
                return self._model
            cfg = self._cfg
            local = find_local_model(cfg.model_dir)
            if local is None:
                # o Jarvis roda 100% local: nunca baixa modelo sozinho
                raise TranscribeError(
                    f"modelo Whisper não encontrado em {cfg.model_dir}. Baixe o modelo faster-whisper "
                    f"'{cfg.model_name}' para essa pasta (ou ajuste [stt] model_dir no config.toml).")
            source = str(local)
            t0 = time.perf_counter()
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel(source, device="cpu", compute_type=cfg.compute_type,
                                     cpu_threads=cfg.cpu_threads, num_workers=1)
            except Exception as exc:
                raise TranscribeError(f"não consegui carregar o modelo Whisper ({source}): {exc}") from exc
            self._model = model
            log.info("modelo Whisper carregado em %.1f s (%s, %s, %d threads)",
                     time.perf_counter() - t0, Path(source).name, cfg.compute_type, cfg.cpu_threads)
            return model

    # ------------------------------------------------------------------ decodificação
    def _decode(self, job: _Job, model: Any, samples: np.ndarray, beam: int, duration: float, rms: float) -> None:
        """Corpo da thread descartável. Nunca levanta; entrega resultado/erro em ``job``."""
        try:
            segments, info = model.transcribe(
                samples, language=self._language, beam_size=beam,
                vad_filter=False, condition_on_previous_text=False)
            job.language = str(getattr(info, "language", None) or "")
            parts: list[str] = []
            for seg in segments:
                if job.abandon.is_set():
                    return
                if not _keep_segment(seg, duration, rms):
                    continue
                piece = seg.text.strip()
                if piece:
                    parts.append(piece)
            job.text = " ".join(" ".join(parts).split())
        except BaseException as exc:  # noqa: BLE001 - entregue ao chamador
            job.error = exc
        finally:
            with self._cv:
                job.finished = True
                if job.abandoned:
                    self._abandoned -= 1
                    log.debug("decodificação abandonada terminou (%d restantes)", self._abandoned)
                self._cv.notify_all()
            job.done.set()

    def _abandon(self, job: _Job) -> None:
        job.abandon.set()
        with self._cv:
            if not job.finished and not job.abandoned:
                job.abandoned = True
                self._abandoned += 1

    def _acquire_run_lock(self, cancel: CancelToken, deadline: float) -> None:
        while not self._run_lock.acquire(timeout=_POLL_S):
            cancel.raise_if_cancelled()
            if time.monotonic() >= deadline:
                raise TranscribeError("o reconhecedor de fala está ocupado")

    def _wait_abandoned_slot(self, cancel: CancelToken, deadline: float) -> None:
        with self._cv:
            while self._abandoned > _MAX_ABANDONED:
                cancel.raise_if_cancelled()
                if time.monotonic() >= deadline:
                    raise TranscribeError("o reconhecedor de fala está ocupado com decodificações abandonadas")
                self._cv.wait(_POLL_S)

    def transcribe(self, audio: np.ndarray, cancel: CancelToken | None = None, *,
                   beam_size: int | None = None) -> Transcript:
        """Transcreve ``audio`` (float32/int16 mono 16 kHz). Texto vazio se for silêncio ou curto demais.

        Levanta ``Cancelled`` assim que ``cancel`` dispara (a decodificação em curso é abandonada).
        ``beam_size`` (1..10) sobrepõe ``cfg.beam_size`` nesta chamada: use 1 para respostas curtas
        ("sim"/"não"), onde a latência importa mais que a precisão.
        """
        cancel = cancel or CancelToken()
        if beam_size is not None and not 1 <= beam_size <= MAX_BEAM_SIZE:
            raise ValueError(f"beam_size deve estar em 1..{MAX_BEAM_SIZE}")
        beam = beam_size if beam_size is not None else max(1, int(self._cfg.beam_size))
        samples = prepare_audio(audio)
        duration = samples.size / SAMPLE_RATE
        language = self._language or ""
        cancel.raise_if_cancelled()
        peak = float(np.max(np.abs(samples), initial=0.0))
        if duration < MIN_AUDIO_S or peak < _SILENCE_PEAK:
            log.debug("áudio curto ou silencioso (%.2f s); sem transcrição", duration)
            return Transcript("", language, duration, 0.0)
        rms = float(np.sqrt(np.dot(samples, samples) / samples.size))

        model = self._ensure_model()
        cancel.raise_if_cancelled()
        timeout = min(_MAX_TIMEOUT_S, _BASE_TIMEOUT_S + _TIMEOUT_PER_S * duration)
        deadline = time.monotonic() + timeout
        t0 = time.perf_counter()
        job = _Job()
        self._acquire_run_lock(cancel, deadline)
        try:
            self._wait_abandoned_slot(cancel, deadline)
            worker = threading.Thread(target=self._decode, args=(job, model, samples, beam, duration, rms),
                                      name="jarvis-stt-decode", daemon=True)
            try:
                worker.start()
            except RuntimeError as exc:
                raise TranscribeError(f"não consegui iniciar a decodificação: {exc}") from exc
            while not job.done.wait(_POLL_S):
                if cancel.cancelled:
                    self._abandon(job)
                    log.debug("transcrição cancelada; decodificação abandonada")
                    raise Cancelled(cancel.reason)
                if time.monotonic() >= deadline:
                    self._abandon(job)
                    raise TranscribeError(f"a transcrição passou de {timeout:.0f} s e foi abandonada")
        finally:
            self._run_lock.release()

        cancel.raise_if_cancelled()                        # cancelou na última fatia: descarta o resultado
        if job.error is not None:
            raise TranscribeError(f"falha na transcrição: {job.error}") from job.error
        elapsed = time.perf_counter() - t0
        language = job.language or language
        log.info("transcrição: %.2f s de áudio em %.2f s (RTF %.2f), %d caracteres",
                 duration, elapsed, elapsed / duration, len(job.text))
        log.debug("texto transcrito: %r", job.text)
        return Transcript(job.text, language, duration, elapsed)
