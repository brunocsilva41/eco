"""Base das paginas: coluna de leitura (max 720 px) com titulo e frase de apoio, e o contrato que a janela usa
(``filter``, ``ensure_loaded``, ``shutdown``, ``scroll_to``). Sem regra de negocio."""
from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..kit.base import Label, set_a11y
from ..theme import SIZE, SPACE
from .searching import matches
from .texts import T

_COLUMN_SHARE = 100          # a coluna ocupa quase tudo; o excedo acima de 720 px vai para a margem direita


class PageLike(Protocol):
    """O que a janela espera de qualquer pagina da pilha."""

    key: str

    def filter(self, query: str) -> int: ...
    def ensure_loaded(self) -> None: ...
    def shutdown(self) -> None: ...
    def scroll_to(self, key: str) -> None: ...


class PageBase(QScrollArea):
    """Pagina rolavel: ``self.col`` e o layout vertical da coluna de leitura."""

    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key
        self.title, self.subtitle = T.page(key)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        column = QWidget()
        column.setMaximumWidth(SIZE.reading_width)
        self.col = QVBoxLayout(column)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(0)
        self.col.addWidget(Label(self.title, "title"))
        sub = Label(self.subtitle, "help", wrap=True)
        sub.setVisible(bool(self.subtitle))
        self.col.addSpacing(SPACE.xs)
        self.col.addWidget(sub)
        host = QWidget()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xxl)
        lay.addWidget(column, _COLUMN_SHARE)
        lay.addStretch(1)
        self.setWidget(host)
        set_a11y(self, self.title, self.subtitle)

    def finish(self) -> None:
        """Chame depois de adicionar tudo: empurra o conteudo para cima."""
        self.col.addStretch(1)

    # ---- contrato com a janela (padrao: pagina inteira casa ou nao com a busca)
    def search_text(self) -> str:
        return f"{self.title} {self.subtitle}"

    def filter(self, query: str) -> int:
        return 1 if matches(query, self.search_text()) else 0

    def ensure_loaded(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def scroll_to(self, key: str) -> None:
        return None
