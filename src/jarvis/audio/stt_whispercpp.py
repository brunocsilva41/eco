"""Motor de reconhecimento whisper.cpp (backend Vulkan = GPU AMD/NVIDIA/Intel), ligado por um shim em C (`native\\jarvis_whisper.c`).

Mesma interface mínima do `faster_whisper.WhisperModel.transcribe`, para o `Transcriber` usar os dois motores sem mudar o resto.
Medido na RX 580 (modelo small, frases de 1,4–3,4 s): 0,88 s de computação na GPU contra 4,37 s do mesmo modelo na CPU e
2,5 s do faster-whisper small; o `base` da CPU leva 0,86 s com WER pior. Falha ao carregar ou ao rodar -> o `Transcriber` cai para a CPU.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

_OUT_CAP = 8192
_BRACKETED = re.compile(r"^\s*[\[(][^\])]{0,40}[\])]\s*$")          # "[BLANK_AUDIO]", "(música)"...


class WhisperCppError(RuntimeError):
    pass


@dataclass
class _Segment:
    text: str
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0
    compression_ratio: float = 0.0


@dataclass
class _Info:
    language: str = "pt"


def _ansi(path: Path) -> bytes:
    """O whisper.cpp abre o arquivo com fopen (página de código ANSI do Windows). Caminho com acento fora dela usa o nome curto 8.3."""
    text = str(path)
    try:
        return text.encode("mbcs")
    except UnicodeEncodeError:
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(text, buf, 1024):  # type: ignore[attr-defined]
            return buf.value.encode("mbcs")
        raise WhisperCppError(f"caminho não representável na página de código ANSI: {text}") from None


class WhisperCppModel:
    def __init__(self, bin_dir: Path, model_path: Path, *, use_gpu: bool = True, threads: int = 2) -> None:
        dll = bin_dir / "jarvis_whisper.dll"
        if not dll.is_file():
            raise WhisperCppError(f"faltam os binários do whisper.cpp em {bin_dir} (jarvis_whisper.dll)")
        if not model_path.is_file():
            raise WhisperCppError(f"modelo ggml não encontrado: {model_path}")
        if use_gpu and not (bin_dir / "ggml-vulkan.dll").is_file():
            raise WhisperCppError(f"ggml-vulkan.dll ausente em {bin_dir}")
        try:
            os.add_dll_directory(str(bin_dir))
            self._lib = ctypes.CDLL(str(dll))
        except OSError as exc:
            raise WhisperCppError(f"não consegui carregar {dll.name}: {exc}") from exc
        lib = self._lib
        lib.jw_init.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p]
        lib.jw_init.restype = ctypes.c_void_p
        lib.jw_transcribe.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        lib.jw_transcribe.restype = ctypes.c_int
        lib.jw_free.argtypes = [ctypes.c_void_p]
        lib.jw_free.restype = None
        self._threads = max(1, int(threads))
        self.use_gpu = use_gpu
        self._lock = threading.Lock()
        self._ctx = lib.jw_init(_ansi(model_path), 1 if use_gpu else 0, 0, str(bin_dir).encode("mbcs", "replace"))
        if not self._ctx:
            raise WhisperCppError("whisper_init falhou (modelo inválido, memória de vídeo insuficiente ou Vulkan indisponível)")

    def transcribe(self, samples: np.ndarray, language: str | None = "pt", beam_size: int = 5, vad_filter: bool = False,
                   condition_on_previous_text: bool = False, initial_prompt: str | None = None, **_: Any) -> tuple[list[_Segment], _Info]:
        pcm = np.ascontiguousarray(samples, dtype=np.float32)
        out = ctypes.create_string_buffer(_OUT_CAP)
        with self._lock:                                    # um contexto, uma decodificação por vez
            ctx = self._ctx
            if not ctx:
                raise WhisperCppError("modelo já foi liberado")
            n = self._lib.jw_transcribe(ctx, pcm.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), int(pcm.size),
                                        (language or "pt").encode(), (initial_prompt or "").encode("utf-8"),
                                        max(1, int(beam_size)), self._threads, out, _OUT_CAP)
        if n < 0:
            raise WhisperCppError("whisper_full falhou")
        text = out.value.decode("utf-8", "replace").strip()
        if not text or _BRACKETED.match(text):
            return [], _Info(language or "pt")
        return [_Segment(text)], _Info(language or "pt")

    def close(self) -> None:
        with self._lock:
            ctx, self._ctx = self._ctx, None
        if ctx:
            self._lib.jw_free(ctx)
