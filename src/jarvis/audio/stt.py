"""Reconhecimento de fala offline com faster-whisper (CPU).

Pontos de projeto:
* O áudio entra SEMPRE como array float32 mono 16 kHz. Nunca passamos caminho de arquivo: o
  faster-whisper 1.2.1 quebra com o ``av`` 19 do venv ao decodificar arquivos.
* O VAD já foi feito na captura, então ``vad_filter=False``; ``condition_on_previous_text=False``
  evita que um erro contamine a próxima janela.
* O modelo é carregado sob demanda (``preload()`` para aquecer) e só uma transcrição roda por vez.
* Privacidade: o texto transcrito só aparece em logs DEBUG; em INFO vão apenas durações.

Contrato de threads: ``Transcriber`` é thread-safe. O carregamento é protegido por um lock e as
transcrições são serializadas por outro (uma de cada vez; as demais esperam). Não cria threads.
``transcribe`` levanta ``Cancelled`` (de ``core.cancel``) se o token disparar antes ou entre segmentos
(o segmento em curso do CTranslate2 não é interrompível: a latência de cancelamento é de um segmento).
Entrada inválida levanta ``TypeError``/``ValueError``; falhas do modelo viram ``TranscribeError``.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..config import SttCfg
from ..core.cancel import Cancelled, CancelToken
from .devices import AudioError

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MIN_AUDIO_S = 0.2                   # abaixo disso não há palavra: devolve texto vazio sem rodar o modelo
MAX_AUDIO_S = 60.0                  # acima disso o excedente é cortado (config limita a fala a 60 s)
_SILENCE_PEAK = 1e-4                # pico abaixo disso = silêncio digital
_NO_SPEECH_PROB = 0.6               # segmento provavelmente sem fala E com baixa confiança é descartado
_MIN_AVG_LOGPROB = -1.0
_MODEL_FILE = "model.bin"


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


class Transcriber:
    def __init__(self, cfg: SttCfg) -> None:
        self._cfg = cfg
        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._run_lock = threading.Lock()
        lang = cfg.language.strip().lower()
        self._language: str | None = None if lang in ("", "auto") else lang

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        """Carrega o modelo agora (idempotente). Levanta ``TranscribeError`` se falhar."""
        self._ensure_model()

    def close(self) -> None:
        """Libera o modelo (será recarregado no próximo uso)."""
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
                    f"modelo Whisper não encontrado em {cfg.model_dir}. Baixe-o antes (ex.: src\\f2\\dl_whisper.py) "
                    f"ou ajuste [stt] model_dir no config.toml.")
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

    def transcribe(self, audio: np.ndarray, cancel: CancelToken | None = None) -> Transcript:
        """Transcreve ``audio`` (float32/int16 mono 16 kHz). Texto vazio se for silêncio ou curto demais."""
        cancel = cancel or CancelToken()
        samples = prepare_audio(audio)
        duration = samples.size / SAMPLE_RATE
        language = self._language or ""
        cancel.raise_if_cancelled()
        if duration < MIN_AUDIO_S or float(np.max(np.abs(samples), initial=0.0)) < _SILENCE_PEAK:
            log.debug("áudio curto ou silencioso (%.2f s); sem transcrição", duration)
            return Transcript("", language, duration, 0.0)

        model = self._ensure_model()
        with self._run_lock:
            cancel.raise_if_cancelled()
            t0 = time.perf_counter()
            parts: list[str] = []
            try:
                segments, info = model.transcribe(
                    samples, language=self._language, beam_size=self._cfg.beam_size,
                    vad_filter=False, condition_on_previous_text=False)
                language = str(getattr(info, "language", None) or language)
                for seg in segments:
                    cancel.raise_if_cancelled()
                    if seg.no_speech_prob > _NO_SPEECH_PROB and seg.avg_logprob < _MIN_AVG_LOGPROB:
                        log.debug("segmento descartado (no_speech=%.2f, logprob=%.2f)", seg.no_speech_prob, seg.avg_logprob)
                        continue
                    piece = seg.text.strip()
                    if piece:
                        parts.append(piece)
            except Cancelled:
                raise
            except Exception as exc:
                raise TranscribeError(f"falha na transcrição: {exc}") from exc
            elapsed = time.perf_counter() - t0

        text = " ".join(" ".join(parts).split())
        log.info("transcrição: %.2f s de áudio em %.2f s (RTF %.2f), %d caracteres",
                 duration, elapsed, elapsed / duration, len(text))
        log.debug("texto transcrito: %r", text)
        return Transcript(text, language, duration, elapsed)
