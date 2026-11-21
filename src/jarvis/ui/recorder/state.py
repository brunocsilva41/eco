"""Dados que o controlador entrega a vista. Imutaveis e sem Qt: a vista so desenha o que recebe."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

NoticeState = Literal["ok", "warn", "error"]
BadgeState = Literal["ok", "warn", "error", "neutral"]
RowKind = Literal["ok", "warn", "neutral"]
IndicatorKind = Literal["idle", "listening", "recording"]
Mode = Literal["loading", "error", "empty", "ready"]


@dataclass(frozen=True)
class Badge:
    state: BadgeState
    text: str


@dataclass(frozen=True)
class Notice:
    """Aviso unico da tela. ``action`` (texto do botao) liga o sinal ``noticeAction`` da vista."""
    state: NoticeState
    what: str
    why: str = ""
    todo: str = ""
    action: str = ""
    detail: str = ""


@dataclass(frozen=True)
class RowView:
    number: int
    label: str
    status: str
    kind: RowKind
    tooltip: str


@dataclass(frozen=True)
class Controls:
    """Quais botoes estao ativos e o que dizem. A regra de negocio ja foi decidida pelo controlador."""
    recording: bool
    busy: bool
    can_record: bool
    can_listen: bool
    can_redo: bool
    can_skip: bool
    can_next: bool
    can_prev: bool
    playing: bool
    primary_next: bool
    has_items: bool
    set_locked: bool


@dataclass(frozen=True)
class StageView:
    position: str
    recorded: str
    progress: tuple[int, int]
    phrase: str
    instruction: str
    filename: str
    badge: Badge
    countdown_total: float
    hint: str


@dataclass(frozen=True)
class ResultView:
    samples: NDArray[np.float32] | None
    level_state: str            # "ok" | "warn" | "error" | "" (cor da onda)
    metrics: str
    recording: bool

