"""Análise pura (numpy) de uma gravação: pico, RMS em dBFS, saturação, silêncio e um veredito em pt-BR.

Todas as funções aceitam float (-1..1) ou int16 e ignoram NaN/inf. Sem I/O, sem estado.

Limiares (ajustáveis aqui, em um só lugar):

* ``CLIP_LEVEL``: amostra com |x| >= 0,999 conta como "cortada" (clipping).
* ``CLIP_RATE_SATURATED`` e ``CLIP_MIN_SAMPLES``: saturado se pelo menos 0,1 % das amostras estiver cortado
  E houver ao menos 8 amostras cortadas (um estalo isolado não reprova a gravação).
* ``PEAK_SILENCE_DBFS``: pico abaixo de -50 dBFS = praticamente só ruído de fundo -> ``silencio``.
* ``PEAK_LOW_DBFS``: pico abaixo de -24 dBFS (~6 % da escala) = voz fraca demais -> ``baixo``.
* ``SILENT_FRAME_DBFS`` / ``FRAME_MS``: um quadro de 20 ms com RMS abaixo de -50 dBFS é "quadro silencioso".
* ``SILENCE_FRACTION_LIMIT``: se 99,5 % ou mais dos quadros forem silenciosos -> ``silencio``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

SAMPLE_RATE = 16000
FLOOR_DBFS = -120.0
CLIP_LEVEL = 0.999
CLIP_RATE_SATURATED = 0.001
CLIP_MIN_SAMPLES = 8
PEAK_SILENCE_DBFS = -50.0
PEAK_LOW_DBFS = -24.0
FRAME_MS = 20
SILENT_FRAME_DBFS = -50.0
SILENCE_FRACTION_LIMIT = 0.995

Level = Literal["ok", "baixo", "saturado", "silencio"]


@dataclass(frozen=True)
class Assessment:
    level: Level
    message: str
    peak: float                 # 0..1
    peak_dbfs: float
    rms_dbfs: float
    clip_rate: float            # 0..1
    clipped_samples: int
    silence_fraction: float     # 0..1 (quadros de 20 ms abaixo de SILENT_FRAME_DBFS)
    duration_s: float


def _as_float(samples: ArrayLike) -> NDArray[np.float64]:
    arr = np.asarray(samples)
    if arr.dtype == np.int16:
        flat = arr.reshape(-1).astype(np.float64) / 32768.0
    else:
        flat = arr.reshape(-1).astype(np.float64)
    return np.nan_to_num(flat, nan=0.0, posinf=1.0, neginf=-1.0)


def to_dbfs(linear: float) -> float:
    if linear <= 0.0:
        return FLOOR_DBFS
    return max(FLOOR_DBFS, 20.0 * math.log10(linear))


def peak(samples: ArrayLike) -> float:
    x = _as_float(samples)
    return float(np.max(np.abs(x))) if x.size else 0.0


def rms(samples: ArrayLike) -> float:
    x = _as_float(samples)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def rms_dbfs(samples: ArrayLike) -> float:
    return to_dbfs(rms(samples))


def clipped_count(samples: ArrayLike, level: float = CLIP_LEVEL) -> int:
    x = _as_float(samples)
    return int(np.count_nonzero(np.abs(x) >= level)) if x.size else 0


def clipping_rate(samples: ArrayLike, level: float = CLIP_LEVEL) -> float:
    x = _as_float(samples)
    return clipped_count(x, level) / x.size if x.size else 0.0


def silence_fraction(samples: ArrayLike, sample_rate: int = SAMPLE_RATE, frame_ms: int = FRAME_MS,
                     threshold_dbfs: float = SILENT_FRAME_DBFS) -> float:
    """Fração (0..1) de quadros cujo RMS fica abaixo de ``threshold_dbfs``. Vazio = 1.0 (tudo silêncio)."""
    x = _as_float(samples)
    frame = max(1, int(sample_rate * frame_ms / 1000))
    count = x.size // frame
    if count == 0:
        return 1.0 if x.size == 0 or rms_dbfs(x) < threshold_dbfs else 0.0
    frames = x[: count * frame].reshape(count, frame)
    levels = np.sqrt(np.mean(frames * frames, axis=1))
    return float(np.count_nonzero(levels < 10.0 ** (threshold_dbfs / 20.0)) / count)


def assess(samples: ArrayLike, sample_rate: int = SAMPLE_RATE) -> Assessment:
    """Veredito da gravação. Ordem de prioridade: silêncio > saturado > baixo > ok."""
    x = _as_float(samples)
    duration = x.size / sample_rate if sample_rate > 0 else 0.0
    pk = peak(x)
    pk_db = to_dbfs(pk)
    rms_db = rms_dbfs(x)
    clipped = clipped_count(x)
    clip_rate = clipped / x.size if x.size else 0.0
    silent = silence_fraction(x, sample_rate)

    def build(level: Level, message: str) -> Assessment:
        return Assessment(level, message, pk, pk_db, rms_db, clip_rate, clipped, silent, duration)

    if x.size == 0:
        return build("silencio", "Não há áudio nesta gravação.")
    if pk_db < PEAK_SILENCE_DBFS or silent >= SILENCE_FRACTION_LIMIT:
        return build("silencio", "Quase só silêncio: o microfone não captou sua voz. "
                                 "Confira se é o microfone certo e se não está mudo.")
    if clipped >= CLIP_MIN_SAMPLES and clip_rate >= CLIP_RATE_SATURATED:
        return build("saturado", "Áudio saturado (estourou). Afaste-se um pouco do microfone "
                                 "ou diminua o ganho de entrada e regrave.")
    if pk_db < PEAK_LOW_DBFS:
        return build("baixo", "Nível baixo. Fale mais perto do microfone ou aumente o ganho de entrada.")
    return build("ok", "Nível bom.")
