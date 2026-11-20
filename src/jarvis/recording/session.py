"""Conjuntos de gravação e sessão (estado de cada item, o que já existe em disco, regras de não sobrescrever).

Os arquivos são associados às frases PELO NÚMERO (``07.wav`` = 7ª frase). Reordenar/remover frases muda
essa associação: a interface avisa antes de editar uma frase que já tem gravação.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ..config import Config
from .phrasebook import PhraseBook
from .wavio import SAMPLE_RATE, WavError, read_wav, write_wav

log = logging.getLogger(__name__)

SENTENCES_DURATION_S = 20.0
WAKEWORD_DURATION_S = 3.0
WAKEWORD_DEFAULT_COUNT = 30
WAKEWORD_MAX_COUNT = 500
_SAFE_WORD = re.compile(r"[^a-z0-9_-]+")


class SessionError(Exception):
    """Operação inválida na sessão (índice fora do conjunto, amostras vazias...)."""


class OverwriteError(SessionError):
    """O arquivo já existe e ``overwrite=False``."""


class ItemStatus(Enum):
    PENDING = "pendente"
    RECORDED = "gravado"
    SKIPPED = "pulado"


@dataclass(frozen=True)
class RecordingSet:
    key: str
    title: str
    phrases: tuple[str, ...]
    duration_s: float
    out_dir: Path
    name_pattern: str = "{n:02d}.wav"          # ``n`` começa em 1
    prefix: str = ""                           # prefixo do nome do arquivo (ex.: "jarvis_")
    instruction: str = "Leia a frase em voz alta."
    item_label: str | None = None              # ex.: "Amostra {n:02d}"; None = usa a própria frase
    phrases_file: Path | None = None           # presente = lista editável pelo usuário
    sample_rate: int = SAMPLE_RATE

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError("duration_s deve ser positivo")
        name = self.filename(0)
        if Path(name).name != name or not name.lower().endswith(".wav"):
            raise ValueError(f"padrão de nome inválido: {name!r} (precisa ser um nome simples terminado em .wav)")

    @property
    def editable(self) -> bool:
        return self.phrases_file is not None

    def filename(self, index: int) -> str:
        return f"{self.prefix}{self.name_pattern.format(n=index + 1)}"

    def label(self, index: int) -> str:
        if self.item_label:
            return self.item_label.format(n=index + 1)
        return self.phrases[index]

    def with_phrases(self, phrases: Sequence[str]) -> RecordingSet:
        return replace(self, phrases=tuple(phrases))


class RecordingSession:
    def __init__(self, recording_set: RecordingSet) -> None:
        self._set = recording_set
        self._status: list[ItemStatus] = [ItemStatus.PENDING] * len(recording_set.phrases)
        self._index = 0
        self.rescan()
        pending = self.first_pending()
        self._index = pending if pending is not None else 0

    # ------------------------------------------------------------------ consulta
    @property
    def recording_set(self) -> RecordingSet:
        return self._set

    @property
    def count(self) -> int:
        return len(self._set.phrases)

    @property
    def index(self) -> int:
        return self._index

    @property
    def current_phrase(self) -> str:
        return self._set.phrases[self._index] if self.count else ""

    @property
    def statuses(self) -> tuple[ItemStatus, ...]:
        return tuple(self._status)

    @property
    def recorded_count(self) -> int:
        return sum(1 for s in self._status if s is ItemStatus.RECORDED)

    @property
    def progress_text(self) -> str:
        """Gravadas/total, ex.: ``7/20``."""
        return f"{self.recorded_count}/{self.count}"

    @property
    def position_text(self) -> str:
        """Posição atual/total, ex.: ``8/20`` (``0/0`` se vazio)."""
        return f"{self._index + 1 if self.count else 0}/{self.count}"

    @property
    def is_complete(self) -> bool:
        return self.count > 0 and all(s is not ItemStatus.PENDING for s in self._status)

    def _check(self, index: int) -> None:
        if not 0 <= index < self.count:
            raise IndexError(f"item {index} fora do conjunto (0..{self.count - 1})")

    def status(self, index: int) -> ItemStatus:
        self._check(index)
        return self._status[index]

    def path(self, index: int) -> Path:
        self._check(index)
        return self._set.out_dir / self._set.filename(index)

    def exists(self, index: int) -> bool:
        return self.path(index).is_file()

    def would_overwrite(self, index: int) -> bool:
        """True se gravar no item ``index`` substituiria um arquivo existente."""
        return self.exists(index)

    def first_pending(self, start: int = 0) -> int | None:
        for i in range(max(0, start), self.count):
            if self._status[i] is ItemStatus.PENDING:
                return i
        return None

    # ------------------------------------------------------------------ navegação
    def goto(self, index: int) -> None:
        self._check(index)
        self._index = index

    def next(self) -> bool:
        """Avança um item. False se já estava no último."""
        if self._index + 1 < self.count:
            self._index += 1
            return True
        return False

    def previous(self) -> bool:
        if self._index > 0:
            self._index -= 1
            return True
        return False

    def next_pending(self) -> int | None:
        """Vai ao próximo item pendente depois do atual (dá a volta); None se não houver nenhum."""
        for i in list(range(self._index + 1, self.count)) + list(range(0, self._index)):
            if self._status[i] is ItemStatus.PENDING:
                self._index = i
                return i
        return None

    # ------------------------------------------------------------------ estado
    def rescan(self) -> None:
        """Relê a pasta: arquivo existente = gravado; sem arquivo mantém pendente/pulado."""
        for i in range(self.count):
            if self.exists(i):
                self._status[i] = ItemStatus.RECORDED
            elif self._status[i] is ItemStatus.RECORDED:
                self._status[i] = ItemStatus.PENDING        # o arquivo sumiu

    def skip(self, index: int | None = None) -> None:
        """Marca como pulado (item já gravado continua gravado)."""
        i = self._index if index is None else index
        self._check(i)
        if self._status[i] is not ItemStatus.RECORDED:
            self._status[i] = ItemStatus.SKIPPED

    def set_phrases(self, phrases: Sequence[str]) -> None:
        """Troca a lista de frases (após editar) preservando 'pulado' por posição e relendo o disco."""
        old = self._status
        self._set = self._set.with_phrases(phrases)
        self._status = [old[i] if i < len(old) and old[i] is ItemStatus.SKIPPED else ItemStatus.PENDING
                        for i in range(self.count)]
        self.rescan()
        self._index = min(self._index, max(0, self.count - 1))

    # ------------------------------------------------------------------ arquivos
    def save(self, index: int, samples: NDArray[np.floating] | NDArray[np.integer], overwrite: bool = False) -> Path:
        """Grava o WAV do item. Levanta ``OverwriteError`` se existir e ``overwrite`` for False."""
        self._check(index)
        if np.asarray(samples).size == 0:
            raise SessionError("gravação vazia: nada para salvar")
        target = self.path(index)
        if target.exists() and not overwrite:
            raise OverwriteError(f"{target.name} já existe")
        try:
            write_wav(target, samples, self._set.sample_rate)
        except WavError as exc:
            raise SessionError(str(exc)) from exc
        self._status[index] = ItemStatus.RECORDED
        return target

    def load(self, index: int) -> NDArray[np.float32]:
        """Lê a gravação existente do item. Levanta ``SessionError`` se faltar ou for inválida."""
        try:
            return read_wav(self.path(index))
        except WavError as exc:
            raise SessionError(str(exc)) from exc


# ---------------------------------------------------------------------- conjuntos prontos
def sentences_set(cfg: Config, phrasebook: PhraseBook | None = None) -> RecordingSet:
    """20 frases de ``tests/frases_pt.txt``, 20 s cada, saída ``tests/audio_bruno/NN.wav``.

    Se ``phrasebook`` vier de fora (a interface compartilha o mesmo objeto para editar), é usado como está.
    Levanta ``PhraseError`` se o arquivo existir e não puder ser lido.
    """
    tests_dir = cfg.paths.root / "tests"
    book = phrasebook if phrasebook is not None else PhraseBook(tests_dir / "frases_pt.txt")
    return RecordingSet(
        key="sentences",
        title="Frases",
        phrases=book.phrases,
        duration_s=SENTENCES_DURATION_S,
        out_dir=tests_dir / "audio_bruno",
        instruction="Leia a frase abaixo em voz alta, em tom natural.",
        phrases_file=book.path,
    )


def wakeword_set(cfg: Config, word: str = "jarvis", count: int = WAKEWORD_DEFAULT_COUNT,
                 duration_s: float = WAKEWORD_DURATION_S) -> RecordingSet:
    """Base para amostras da palavra de ativação: ``count`` amostras de ``duration_s`` s em
    ``<cfg.paths.data>/wakeword/<word>/NN.wav``. Sem texto livre (lista fixa, não editável)."""
    slug = _SAFE_WORD.sub("", word.strip().lower())
    if not slug:
        raise ValueError(f"palavra inválida: {word!r}")
    if not 1 <= count <= WAKEWORD_MAX_COUNT:
        raise ValueError(f"count deve estar em 1..{WAKEWORD_MAX_COUNT}")
    shown = word.strip().capitalize()
    return RecordingSet(
        key="wakeword",
        title="Palavra de ativação",
        phrases=tuple(f"Diga: {shown}" for _ in range(count)),
        duration_s=duration_s,
        out_dir=cfg.paths.data / "wakeword" / slug,
        name_pattern="{n:03d}.wav" if count > 99 else "{n:02d}.wav",
        instruction=f"Diga \"{shown}\" uma vez, claramente, e fique em silêncio até o fim da contagem. "
                    "Varie a distância e o tom entre as amostras.",
        item_label="Amostra {n:02d}",
    )
