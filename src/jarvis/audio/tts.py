"""Síntese de voz offline com Piper (CPU) e helper ``speak`` em pipeline.

* ``clean_for_speech`` / ``split_sentences``: preparam o texto do LLM para ser FALADO (sem markdown,
  emojis, URLs, abreviações cruas).
* ``Synthesizer.synthesize``: gerador de ``AudioChunk`` (int16 mono) por sentença. O pipeline
  síntese -> reprodução contínua (um único stream por resposta) vive em ``voice.Voice``.

Contrato de threads
-------------------
* ``Synthesizer`` é thread-safe: um lock protege o carregamento da voz e outro serializa as chamadas
  ao Piper (uma sentença por vez; o Piper não é reentrante no fonemizador).
* ``synthesize`` é um gerador executado na thread de quem o consome (não cria threads). Quando o
  ``CancelToken`` dispara ele simplesmente ENCERRA entre sentenças (confira ``cancel.cancelled`` se
  precisar distinguir); uma sentença em síntese não é interrompível (centenas de ms).
* Erros de síntese viram ``TtsError``; entrada de texto não-str levanta ``TypeError``.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterator
from typing import Any

import numpy as np

from ..config import TtsCfg
from ..core.cancel import CancelToken
from .speech_text import normalize
from .devices import AudioError
from .playback import AudioChunk

log = logging.getLogger(__name__)

__all__ = ["Synthesizer", "TtsError", "clean_for_speech", "split_sentences"]

MAX_TEXT_CHARS = 2000               # por chamada; o excedente é cortado numa fronteira de sentença
MAX_SENTENCE_CHARS = 240            # sentenças maiores são quebradas em vírgula/espaço


class TtsError(AudioError):
    """Voz ausente/ilegível ou falha na síntese."""


# ----------------------------------------------------------------------------- limpeza de texto
_CODE_BLOCK = re.compile(r"```.*?(?:```|\Z)", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]*)`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.M)
_BULLET = re.compile(r"^[ \t]*(?:[-*+•][ \t]+)", re.M)
_QUOTE = re.compile(r"^[ \t]*>[ \t]?", re.M)
_TABLE_RULE = re.compile(r"^[ \t|:\-]+$", re.M)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿\U0001F1E6-\U0001F1FF️‍⃣]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​‌⁠﻿]")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")

_ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bSra\."), "senhora"),
    (re.compile(r"\bSr\."), "senhor"),
    (re.compile(r"\bDra\."), "doutora"),
    (re.compile(r"\bDr\."), "doutor"),
    (re.compile(r"\bProfa\."), "professora"),
    (re.compile(r"\bProf\."), "professor"),
    (re.compile(r"\bp\.\s?ex\.:?", re.I), "por exemplo"),
    (re.compile(r"\bex\.:", re.I), "por exemplo:"),
    (re.compile(r"\bobs\.:?", re.I), "observação:"),
    (re.compile(r"\betc\.(?=\s+[A-ZÀ-Ý]|\s*$)"), "etcétera."),         # fim de frase mantém o ponto
    (re.compile(r"\betc\.", re.I), "etcétera"),
    (re.compile(r"(\d)\s?km/h\b", re.I), r"\1 quilômetros por hora"),
    (re.compile(r"R\$\s*(\d[\d.]*(?:,\d+)?)"), r"\1 reais"),
    (re.compile(r"\s?[°º]\s?C\b"), " graus Celsius"),
    (re.compile(r"\s?%"), " por cento"),
    (re.compile(r"\s&\s"), " e "),
)


def clean_for_speech(text: str) -> str:
    """Remove markdown, emojis, URLs e controles; expande abreviações comuns; normaliza espaços.

    Mantém quebras de linha como fronteiras de sentença (o resultado nunca tem linhas em branco duplas).
    """
    if not isinstance(text, str):
        raise TypeError(f"texto deve ser str, recebido {type(text).__name__}")
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    s = _CODE_BLOCK.sub(" ", s)
    s = _IMAGE.sub(" ", s)
    s = _LINK.sub(r"\1", s)
    s = _URL.sub(" link ", s)
    s = _INLINE_CODE.sub(r"\1", s)
    s = _HTML_TAG.sub(" ", s)
    s = _HEADING.sub("", s)
    s = _QUOTE.sub("", s)
    s = _TABLE_RULE.sub("", s)
    s = _BULLET.sub("", s)
    s = s.replace("|", ", ").replace("*", "").replace("~", "").replace("_", " ")
    s = _EMOJI.sub(" ", s)
    s = _CONTROL.sub("", s)
    for pattern, repl in _ABBREVIATIONS:
        s = pattern.sub(repl, s)
    lines = (" ".join(line.split()).strip(" ,;") for line in s.split("\n"))
    return normalize("\n".join(line for line in lines if line))


def _break_long(sentence: str, limit: int) -> Iterator[str]:
    rest = sentence
    while len(rest) > limit:
        cut = max(rest.rfind(", ", 0, limit), rest.rfind("; ", 0, limit), rest.rfind(": ", 0, limit))
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        head, rest = rest[:cut + 1].strip(), rest[cut + 1:].strip()
        if head:
            yield head
    if rest:
        yield rest


def split_sentences(text: str, *, max_chars: int = MAX_TEXT_CHARS, max_sentence: int = MAX_SENTENCE_CHARS) -> list[str]:
    """Divide texto JÁ limpo em sentenças falaveis, limitando o total a ``max_chars`` (corta em fronteira)."""
    sentences: list[str] = []
    total = 0
    for line in text.split("\n"):
        for raw in _SENTENCE_END.split(line):
            for piece in _break_long(raw.strip(), max_sentence):
                if not any(c.isalnum() for c in piece):
                    continue
                if total + len(piece) > max_chars:
                    log.warning("texto para fala excede %d caracteres; o restante foi cortado", max_chars)
                    return sentences
                sentences.append(piece)
                total += len(piece)
    return sentences


# ----------------------------------------------------------------------------- síntese
class Synthesizer:
    def __init__(self, cfg: TtsCfg) -> None:
        self._cfg = cfg
        self._voice: Any | None = None
        self._syn_config: Any | None = None
        self._sample_rate: int | None = None
        self._load_lock = threading.Lock()
        self._run_lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._voice is not None

    @property
    def sample_rate(self) -> int:
        """Taxa da voz (carrega a voz se preciso)."""
        self._ensure_voice()
        assert self._sample_rate is not None
        return self._sample_rate

    def preload(self) -> None:
        """Carrega a voz agora (idempotente). Levanta ``TtsError`` se faltar arquivo ou falhar."""
        self._ensure_voice()

    def close(self) -> None:
        with self._load_lock:
            self._voice = None
            self._syn_config = None

    def _ensure_voice(self) -> Any:
        voice = self._voice
        if voice is not None:
            return voice
        with self._load_lock:
            if self._voice is not None:
                return self._voice
            cfg = self._cfg
            for label, path in (("modelo", cfg.voice_onnx), ("configuração", cfg.voice_json)):
                if not path.is_file():
                    raise TtsError(f"{label} da voz Piper não encontrado: {path}")
            if cfg.length_scale is not None and not 0.1 <= cfg.length_scale <= 5.0:
                raise TtsError(f"tts.length_scale fora de 0.1..5.0: {cfg.length_scale}")
            if cfg.device == "gpu":
                log.warning("tts.device = gpu: este motor roda só na CPU (DirectML foi medido mais lento); usando a CPU")
            t0 = time.perf_counter()
            try:
                from piper import PiperVoice
                voice = PiperVoice.load(cfg.voice_onnx, cfg.voice_json, use_cuda=False)
                syn_config = self._build_syn_config()
                sample_rate = int(voice.config.sample_rate)
            except TtsError:
                raise
            except Exception as exc:
                raise TtsError(f"não consegui carregar a voz Piper {cfg.voice_onnx.name}: {exc}") from exc
            self._syn_config, self._sample_rate, self._voice = syn_config, sample_rate, voice
            log.info("voz Piper carregada em %.1f s (%s, %d Hz)", time.perf_counter() - t0, cfg.voice_onnx.name, sample_rate)
            return voice

    def _build_syn_config(self) -> Any | None:
        if self._cfg.length_scale is None:
            return None
        try:
            from piper import SynthesisConfig
            return SynthesisConfig(length_scale=float(self._cfg.length_scale))
        except (ImportError, TypeError) as exc:
            log.warning("este piper-tts não aceita length_scale (%s); usando o padrão da voz", exc)
            return None

    def synthesize(self, text: str, cancel: CancelToken | None = None) -> Iterator[AudioChunk]:
        """Gera o áudio sentença a sentença (cancelável entre sentenças; ao cancelar, apenas encerra)."""
        cancel = cancel or CancelToken()
        sentences = split_sentences(clean_for_speech(text))
        if not sentences:
            log.debug("texto sem conteúdo falável")
            return
        voice = self._ensure_voice()
        for index, sentence in enumerate(sentences, 1):
            if cancel.cancelled:
                log.debug("síntese cancelada antes da sentença %d/%d", index, len(sentences))
                return
            t0 = time.perf_counter()
            try:
                with self._run_lock:
                    chunks = [self._to_chunk(c) for c in voice.synthesize(sentence, syn_config=self._syn_config)]
            except Exception as exc:
                raise TtsError(f"falha ao sintetizar a sentença {index}/{len(sentences)}: {exc}") from exc
            audio_s = sum(c.duration_s for c in chunks)
            log.debug("sentença %d/%d: %.2f s de áudio em %.2f s", index, len(sentences), audio_s, time.perf_counter() - t0)
            yield from chunks

    @staticmethod
    def _to_chunk(piper_chunk: Any) -> AudioChunk:
        pcm = np.ascontiguousarray(piper_chunk.audio_int16_array, dtype=np.int16).reshape(-1)
        return AudioChunk(pcm, int(piper_chunk.sample_rate))
