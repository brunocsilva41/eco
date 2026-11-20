"""Leitura e escrita de WAV 16 kHz mono PCM16 (só stdlib ``wave`` + numpy), com escrita atômica.

A escrita monta o arquivo inteiro em memória e o grava num temporário na mesma pasta antes de
``os.replace``: um travamento ou queda de energia nunca deixa um WAV pela metade no destino.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
import wave
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2                    # bytes (PCM16)
_INT16_MAX = 32767.0
_INT16_SCALE = 32768.0


class WavError(Exception):
    """WAV ilegível, em formato diferente de 16 kHz/mono/16 bits, ou falha ao gravar."""


def float_to_int16(samples: NDArray[np.floating] | NDArray[np.integer]) -> NDArray[np.int16]:
    """Converte float (-1..1) para int16 com clip; NaN/inf viram 0 e fora da faixa satura. Entrada int16 passa direto."""
    arr = np.asarray(samples)
    if arr.dtype == np.int16:
        return np.ascontiguousarray(arr.reshape(-1))
    flat = np.nan_to_num(arr.reshape(-1).astype(np.float64), nan=0.0, posinf=1.0, neginf=-1.0)
    return np.rint(np.clip(flat, -1.0, 1.0) * _INT16_MAX).astype(np.int16)


def int16_to_float(samples: NDArray[np.int16]) -> NDArray[np.float32]:
    return (samples.astype(np.float32) / _INT16_SCALE).astype(np.float32, copy=False)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Grava ``data`` em ``path`` via arquivo temporário + ``os.replace`` (cria a pasta se preciso)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def encode_wav(samples: NDArray[np.floating] | NDArray[np.integer], sample_rate: int = SAMPLE_RATE) -> bytes:
    pcm = float_to_int16(samples)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.astype("<i2", copy=False).tobytes())
    return buffer.getvalue()


def write_wav(path: Path, samples: NDArray[np.floating] | NDArray[np.integer], sample_rate: int = SAMPLE_RATE) -> Path:
    """Grava WAV mono PCM16 de forma atômica. Sobrescreve se existir (quem chama decide se pode). Levanta ``WavError``."""
    if sample_rate != SAMPLE_RATE:
        raise WavError(f"taxa {sample_rate} Hz não suportada (o formato do projeto é {SAMPLE_RATE} Hz)")
    if np.asarray(samples).size == 0:
        raise WavError("nenhuma amostra para gravar")
    try:
        atomic_write_bytes(Path(path), encode_wav(samples, sample_rate))
    except OSError as exc:
        raise WavError(f"não consegui gravar {path}: {exc}") from exc
    log.info("WAV gravado: %s", path)
    return Path(path)


def read_wav(path: Path) -> NDArray[np.float32]:
    """Lê um WAV 16 kHz mono PCM16 como float32 (-1..1). Levanta ``WavError`` se faltar ou o formato divergir."""
    path = Path(path)
    try:
        with wave.open(str(path), "rb") as wav:
            channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
            if (channels, width, rate) != (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE):
                raise WavError(
                    f"{path.name}: formato {channels} canal(is), {width * 8} bits, {rate} Hz; "
                    f"esperado mono, 16 bits, {SAMPLE_RATE} Hz")
            raw = wav.readframes(frames)
    except (OSError, wave.Error, EOFError) as exc:
        raise WavError(f"não consegui ler {path}: {exc}") from exc
    pcm = np.frombuffer(raw, dtype="<i2")
    return int16_to_float(pcm.astype(np.int16, copy=False))
