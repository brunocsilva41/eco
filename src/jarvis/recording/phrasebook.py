"""Livro de frases: arquivo UTF-8, uma frase por linha (linhas vazias e iniciadas por ``#`` são ignoradas).

Garantias:

* gravação ATÔMICA (temporário + ``os.replace``); se falhar, a lista em memória e o arquivo ficam como estavam;
* cada alteração valida antes (tamanho 3..300, sem duplicata ignorando caixa e espaços repetidos);
* se o arquivo existente não pôde ser lido, o livro recusa qualquer alteração (para nunca sobrescrever
  um arquivo que não conseguimos ler);
* antes da primeira gravação de cada instância, o arquivo original é copiado para ``<nome>.bak``
  (comentários ``#`` não são preservados no arquivo regravado).
"""
from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path

from .wavio import atomic_write_bytes

log = logging.getLogger(__name__)

MIN_PHRASE_LEN = 3
MAX_PHRASE_LEN = 300


class PhraseError(ValueError):
    """Frase inválida, duplicada ou índice fora da lista."""


class PhraseStorageError(PhraseError):
    """Falha ao ler ou gravar o arquivo de frases."""


def normalize_phrase(text: str) -> str:
    """Remove espaços nas pontas e colapsa qualquer sequência de espaços/quebras em um espaço."""
    return " ".join(text.split())


def _key(text: str) -> str:
    return normalize_phrase(text).casefold()


def validate_phrase(text: str) -> str:
    """Devolve a frase normalizada ou levanta ``PhraseError``."""
    clean = normalize_phrase(text)
    if len(clean) < MIN_PHRASE_LEN:
        raise PhraseError(f"A frase precisa ter pelo menos {MIN_PHRASE_LEN} caracteres.")
    if len(clean) > MAX_PHRASE_LEN:
        raise PhraseError(f"A frase passa de {MAX_PHRASE_LEN} caracteres ({len(clean)}).")
    if clean.startswith("#"):
        raise PhraseError("A frase não pode começar com '#' (essas linhas são comentários).")
    if not clean.isprintable():
        raise PhraseError("A frase contém caracteres de controle.")
    return clean


class PhraseBook:
    def __init__(self, path: Path, *, autoload: bool = True) -> None:
        self._path = Path(path)
        self._phrases: list[str] = []
        self._load_ok = True
        self._backed_up = False
        if autoload:
            self.load()

    # ------------------------------------------------------------------ leitura
    @property
    def path(self) -> Path:
        return self._path

    @property
    def phrases(self) -> tuple[str, ...]:
        return tuple(self._phrases)

    @property
    def writable(self) -> bool:
        """False se o arquivo existente não pôde ser lido (alterações são recusadas)."""
        return self._load_ok

    def __len__(self) -> int:
        return len(self._phrases)

    def __iter__(self) -> Iterator[str]:
        return iter(tuple(self._phrases))

    def __getitem__(self, index: int) -> str:
        return self._phrases[index]

    def load(self) -> None:
        """Relê o arquivo. Arquivo ausente = livro vazio. Duplicatas são ignoradas (com aviso no log)."""
        if not self._path.exists():
            self._phrases, self._load_ok = [], True
            log.info("arquivo de frases ainda não existe: %s", self._path)
            return
        try:
            text = self._path.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            self._phrases, self._load_ok = [], False
            raise PhraseStorageError(f"Não consegui ler {self._path.name}: {exc}") from exc
        phrases: list[str] = []
        seen: set[str] = set()
        for number, line in enumerate(text.splitlines(), start=1):
            clean = normalize_phrase(line)
            if not clean or clean.startswith("#"):
                continue
            key = clean.casefold()
            if key in seen:
                log.warning("%s linha %d: frase duplicada ignorada", self._path.name, number)
                continue
            seen.add(key)
            phrases.append(clean)
        self._phrases, self._load_ok = phrases, True
        log.info("%d frases carregadas de %s", len(phrases), self._path)

    # ------------------------------------------------------------------ gravação
    def save(self) -> None:
        self._write(self._phrases)

    def _write(self, phrases: Sequence[str]) -> None:
        if not self._load_ok:
            raise PhraseStorageError(
                f"O arquivo {self._path.name} não pôde ser lido; por segurança não vou sobrescrevê-lo.")
        if not self._backed_up and self._path.exists():
            try:
                shutil.copy2(self._path, self._path.with_name(self._path.name + ".bak"))
            except OSError as exc:
                log.warning("não consegui criar o backup de %s: %s", self._path, exc)
            self._backed_up = True
        payload = ("\n".join(phrases) + ("\n" if phrases else "")).encode("utf-8")
        try:
            atomic_write_bytes(self._path, payload)
        except OSError as exc:
            raise PhraseStorageError(f"Não consegui salvar {self._path.name}: {exc}") from exc

    def _commit(self, new: list[str]) -> None:
        """Grava primeiro; só troca a lista em memória se a gravação deu certo."""
        self._write(new)
        self._phrases = new

    # ------------------------------------------------------------------ edição
    def _check_unique(self, clean: str, ignore: int | None = None) -> None:
        key = clean.casefold()
        for i, existing in enumerate(self._phrases):
            if i != ignore and existing.casefold() == key:
                raise PhraseError("Essa frase já existe na lista.")

    def _check_index(self, index: int, *, allow_end: bool = False) -> None:
        limit = len(self._phrases) + (1 if allow_end else 0)
        if not 0 <= index < limit:
            raise PhraseError(f"Posição inválida: {index}.")

    def validate(self, text: str, ignore: int | None = None) -> str:
        """Devolve a frase normalizada se for válida (tamanho, caracteres, sem duplicata) ou levanta
        ``PhraseError``. Não altera nada; ``ignore`` é a posição que está sendo editada."""
        clean = validate_phrase(text)
        self._check_unique(clean, ignore=ignore)
        return clean

    def add(self, text: str, index: int | None = None) -> int:
        """Insere a frase (no fim se ``index`` for None). Devolve a posição."""
        clean = validate_phrase(text)
        self._check_unique(clean)
        position = len(self._phrases) if index is None else index
        self._check_index(position, allow_end=True)
        new = list(self._phrases)
        new.insert(position, clean)
        self._commit(new)
        return position

    def edit(self, index: int, text: str) -> None:
        self._check_index(index)
        clean = validate_phrase(text)
        self._check_unique(clean, ignore=index)
        new = list(self._phrases)
        new[index] = clean
        self._commit(new)

    def remove(self, index: int) -> str:
        self._check_index(index)
        new = list(self._phrases)
        removed = new.pop(index)
        self._commit(new)
        return removed

    def move(self, index: int, new_index: int) -> int:
        """Move a frase para ``new_index`` (limitado às pontas). Devolve a posição final."""
        self._check_index(index)
        target = max(0, min(new_index, len(self._phrases) - 1))
        if target == index:
            return index
        new = list(self._phrases)
        new.insert(target, new.pop(index))
        self._commit(new)
        return target
