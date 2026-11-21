"""Dependencias externas do gravador (microfone, saida de som, lista de dispositivos) atras de contratos.

A janela usa os servicos reais por padrao. Quem precisar simular (capturas de tela, ensaio sem hardware)
passa outros ``Services``: nada aqui abre microfone sozinho.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from ...audio.devices import DeviceSpec
from ...config import AudioCfg
from ...recording.player import Player
from ...recording.recorder import (InputChoice, LevelReading, MicRecorder, RecorderError, RecorderState,
                                   list_input_choices)


class RecorderLike(Protocol):
    @property
    def state(self) -> RecorderState: ...
    @property
    def error(self) -> RecorderError | None: ...
    @property
    def samples(self) -> NDArray[np.float32] | None: ...
    @property
    def remaining_s(self) -> float: ...
    @property
    def progress(self) -> float: ...
    def level(self) -> LevelReading: ...
    def set_device(self, spec: DeviceSpec) -> None: ...
    def start(self) -> None: ...
    def stop(self, *, discard: bool = False) -> None: ...
    def reset(self) -> None: ...


class PlayerLike(Protocol):
    @property
    def is_playing(self) -> bool: ...
    def play(self, samples: NDArray[np.floating], sample_rate: int = ...) -> None: ...
    def stop(self) -> None: ...


@dataclass(frozen=True)
class Services:
    make_recorder: Callable[[float], RecorderLike] = MicRecorder
    make_player: Callable[[AudioCfg], PlayerLike] = Player
    list_choices: Callable[[bool], list[InputChoice]] = list_input_choices
