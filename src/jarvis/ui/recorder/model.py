"""Modelo do gravador: regras de negocio sem Qt (carregar conjunto, avaliar e salvar take, editar frases).

Tudo aqui pode rodar numa thread de fundo (``ui.kit.tasks.run_async``); nenhuma funcao toca widget.
O que e gravacao e analise de audio continua em ``jarvis.recording``: aqui so a cola.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from ...audio.devices import DeviceSpec
from ...config import Config
from ...recording.audio_analysis import PEAK_LOW_DBFS, Assessment, assess
from ...recording.phrasebook import PhraseBook, PhraseError
from ...recording.recorder import InputChoice
from ...recording.session import (ItemStatus, OverwriteError, RecordingSession, SessionError, sentences_set,
                                  wakeword_set)
from .texts import T

log = logging.getLogger(__name__)

SET_FRASES = "frases"
SET_JARVIS = "jarvis"
SET_NAMES: tuple[str, ...] = (SET_FRASES, SET_JARVIS)

MIN_TAKE_S = 0.5                     # gravacao mais curta que isso nao e salva
METER_FLOOR_DB = -60.0
METER_LOW_DB = PEAK_LOW_DBFS         # mesmo limiar do veredito "baixo"
METER_HIGH_DB = -6.0                 # folga de seguranca antes do corte (0 dBFS); padrao do medidor do kit

TakeVerdict = Literal["save", "silence", "short"]
SaveOutcome = Literal["saved", "exists", "failed"]


def check_set_name(name: str) -> str:
    """Valida o nome do conjunto ("frases" ou "jarvis"). Levanta ``ValueError`` com mensagem clara."""
    if name not in SET_NAMES:
        raise ValueError(T.api.invalid_set.format(value=name))
    return name


@dataclass(frozen=True)
class LoadedSet:
    name: str
    session: RecordingSession
    book: PhraseBook | None
    book_error: str = ""             # detalhe tecnico quando o arquivo de frases nao pode ser lido


def load_set(cfg: Config, name: str) -> LoadedSet:
    """Monta o conjunto pedido. Se o arquivo de frases estiver ilegivel, a lista abre vazia e protegida."""
    check_set_name(name)
    if name == SET_JARVIS:
        return LoadedSet(name, RecordingSession(wakeword_set(cfg)), None)
    book = PhraseBook(cfg.paths.root / "tests" / "frases_pt.txt", autoload=False)
    problem = ""
    try:
        book.load()
    except PhraseError as exc:
        problem = str(exc)
        log.warning("arquivo de frases ilegivel: %s", exc)
    return LoadedSet(name, RecordingSession(sentences_set(cfg, book)), book, problem)


@dataclass(frozen=True)
class LoadedTake:
    index: int
    samples: NDArray[np.float32] | None
    assessment: Assessment | None
    error: str = ""


def load_take(session: RecordingSession, index: int) -> LoadedTake:
    """Le a gravacao existente do item e a avalia (``samples=None`` se nao houver ou nao puder ser lida)."""
    if session.status(index) is not ItemStatus.RECORDED:
        return LoadedTake(index, None, None)
    try:
        samples = session.load(index)
    except SessionError as exc:
        log.warning("gravacao do item %d ilegivel: %s", index, exc)
        return LoadedTake(index, None, None, str(exc))
    return LoadedTake(index, samples, assess(samples, session.recording_set.sample_rate))


@dataclass(frozen=True)
class TakeDecision:
    verdict: TakeVerdict
    assessment: Assessment
    duration_s: float


def decide_take(samples: NDArray[np.float32], sample_rate: int) -> TakeDecision:
    """Decide se a gravacao feita vale ser salva: curta demais e silencio nunca sao salvos."""
    assessment = assess(samples, sample_rate)
    duration = samples.size / sample_rate
    if duration < MIN_TAKE_S:
        return TakeDecision("short", assessment, duration)
    if assessment.level == "silencio":
        return TakeDecision("silence", assessment, duration)
    return TakeDecision("save", assessment, duration)


def save_take(session: RecordingSession, index: int, samples: NDArray[np.float32], overwrite: bool) -> tuple[SaveOutcome, str]:
    """Grava o WAV. ``overwrite`` so vale True depois de uma confirmacao explicita do usuario."""
    try:
        session.save(index, samples, overwrite=overwrite)
    except OverwriteError:
        return "exists", ""
    except SessionError as exc:
        log.error("falha ao salvar a gravacao %d: %s", index, exc)
        return "failed", str(exc)
    return "saved", ""


def build_mic_items(choices: list[InputChoice], previous: DeviceSpec) -> tuple[list[tuple[str, DeviceSpec]], int]:
    """Itens do seletor de microfone e o indice a selecionar (mantem a escolha anterior ou a do config)."""
    default = next((c for c in choices if c.is_default), None)
    items: list[tuple[str, DeviceSpec]] = [
        (T.mics.default_named(default.label) if default else T.mics.default, None)]
    for c in choices:
        items.append((T.mics.marked_default(c.label) if c.is_default else c.label, c.spec))
    pos = next((i for i, (_label, spec) in enumerate(items) if spec == previous), -1)
    if pos < 0 and previous not in (None, ""):
        if isinstance(previous, str):                 # nome configurado: casa por trecho
            needle = previous.casefold()
            pos = next((i for i in range(1, len(items)) if needle in items[i][0].casefold()), -1)
        if pos < 0:
            items.append((T.mics.missing(str(previous)), previous))
            pos = len(items) - 1
    return items, max(pos, 0)


class PhraseEditor:
    """Edicao da lista de frases (so conjunto editavel). Cada operacao grava o arquivo e sincroniza a sessao.

    Os arquivos de audio sao ligados as frases pelo numero: quem chama deve pedir confirmacao quando
    ``has_recording`` for True antes de editar, remover ou mover.
    """

    def __init__(self, session: RecordingSession, book: PhraseBook) -> None:
        self._session = session
        self._book = book

    @property
    def writable(self) -> bool:
        return self._book.writable

    def has_recording(self, index: int) -> bool:
        return self._session.exists(index)

    def phrase(self, index: int) -> str:
        return self._book[index]

    def check(self, text: str, ignore: int | None = None) -> str:
        """Frase normalizada ou ``PhraseError`` (tamanho, caracteres, duplicata)."""
        return self._book.validate(text, ignore)

    def add(self, text: str) -> int:
        position = self._book.add(text)
        self._sync(position)
        return position

    def edit(self, index: int, text: str) -> int:
        self._book.edit(index, text)
        self._sync(index)
        return index

    def remove(self, index: int) -> int:
        self._book.remove(index)
        self._sync(index)
        return self._session.index

    def move(self, index: int, delta: int) -> int | None:
        """Nova posicao do item movido, ou None se ja estava na ponta."""
        target = index + delta
        if not 0 <= target < self._session.count:
            return None
        final = self._book.move(index, target)
        self._sync(final)
        return final

    def _sync(self, select: int) -> None:
        self._session.set_phrases(self._book.phrases)
        if self._session.count:
            self._session.goto(max(0, min(select, self._session.count - 1)))
