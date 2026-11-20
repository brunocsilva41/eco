"""VAD Silero (onnx) em CPU. Janelas de 512 amostras float32 a 16 kHz (32 ms).

Contrato de threads: uma instância guarda estado recorrente do modelo, portanto NÃO é thread-safe;
use uma instância por captura/thread e chame ``reset()`` a cada nova fala (ou ao descartar ruído).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from .constants import SAMPLE_RATE
from .devices import AudioError

log = logging.getLogger(__name__)

WINDOW_SAMPLES = 512                                  # 32 ms a 16 kHz
VAD_RELATIVE_PATH = Path("silero") / "silero_vad.onnx"
MIN_MODEL_BYTES = 100_000                             # abaixo disso o arquivo está truncado
_CONTEXT_SAMPLES = 64                                 # contexto do modelo v5 (últimas 64 amostras da janela anterior)
_REQUIRED_INPUTS = frozenset({"input", "state", "sr"})


class VadError(AudioError):
    """Modelo do VAD ausente, inválido ou impossível de carregar."""


def default_model_path(models_dir: Path | None = None) -> Path:
    """``<models>/silero/silero_vad.onnx`` (``models_dir`` padrão = ``PathsCfg.models``)."""
    if models_dir is None:
        from ..config import PathsCfg
        models_dir = PathsCfg().models
    return Path(models_dir) / VAD_RELATIVE_PATH


def validate_model_file(path: Path | str) -> int:
    """Confere que o arquivo do VAD existe e não está truncado. Devolve o tamanho; ``VadError`` se falhar.

    É a MESMA checagem usada pelo runtime (``SileroVAD``) e pelo ``doctor``.
    """
    path = Path(path)
    if not path.is_file():
        raise VadError(f"modelo do VAD não encontrado: {path} (coloque silero_vad.onnx em <paths.models>/silero/)")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise VadError(f"não consegui ler o modelo do VAD {path}: {exc}") from exc
    if size < MIN_MODEL_BYTES:
        raise VadError(f"modelo do VAD {path.name} com {size} bytes: parece truncado")
    return size


class SileroVAD:
    def __init__(self, model_path: Path | str | None = None) -> None:
        path = Path(model_path) if model_path is not None else default_model_path()
        validate_model_file(path)
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise VadError(f"onnxruntime indisponível: {exc}") from exc
        try:
            options = ort.SessionOptions()
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = 1
            self._session: Any = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        except Exception as exc:
            raise VadError(f"não consegui carregar o VAD {path}: {exc}") from exc
        names = {i.name for i in self._session.get_inputs()}
        if not _REQUIRED_INPUTS <= names:
            raise VadError(f"VAD {path.name} com entradas inesperadas {sorted(names)}; esperado {sorted(_REQUIRED_INPUTS)}")
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._ctx = np.zeros((1, _CONTEXT_SAMPLES), dtype=np.float32)
        self.reset()

    def reset(self) -> None:
        """Zera o estado recorrente (chamar ao iniciar uma nova fala)."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._ctx = np.zeros((1, _CONTEXT_SAMPLES), dtype=np.float32)

    def prob(self, chunk: np.ndarray) -> float:
        """Probabilidade (0..1) de fala em ``chunk``: exatamente 512 amostras de ponto flutuante em [-1, 1]."""
        arr = np.asarray(chunk)
        if arr.dtype.kind != "f":
            raise TypeError(f"chunk deve ser float (recebido {arr.dtype}); converta int16 dividindo por 32768")
        if arr.size != WINDOW_SAMPLES:
            raise ValueError(f"chunk deve ter {WINDOW_SAMPLES} amostras (recebido {arr.size})")
        x = np.ascontiguousarray(arr, dtype=np.float32).reshape(1, -1)
        if not np.isfinite(x).all():
            raise ValueError("chunk contém NaN/Inf")
        x = np.concatenate([self._ctx, x], axis=1)
        out, self._state = self._session.run(None, {"input": x, "state": self._state, "sr": self._sr})
        self._ctx = x[:, -_CONTEXT_SAMPLES:]
        return float(out[0][0])
