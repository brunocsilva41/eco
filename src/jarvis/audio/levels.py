"""Medidor de nível de áudio para a animação (evento ``level`` do EventBus).

Compartilhado por captura (``source='mic'``) e reprodução (``source='tts'``) para não duplicar a
suavização e a limitação de taxa.

O valor publicado em ``rms`` é o RMS suavizado (ataque rápido, queda lenta) e mapeado de -60..-10 dBFS
para 0..1, de modo que fala normal fique na faixa média e o ruído de fundo perto de zero.

Contrato de threads: uma instância deve ser alimentada por UMA thread por vez (não há lock).
``EventBus.publish`` é thread-safe e isola assinantes com defeito.
"""
from __future__ import annotations

import math
import time
from typing import Literal

import numpy as np

from ..core.events import EventBus

LevelSource = Literal["mic", "tts"]


def rms_of(samples: np.ndarray) -> float:
    """RMS de amostras float (qualquer forma). Vazio -> 0.0."""
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.dot(x, x) / x.size))


class LevelMeter:
    def __init__(
        self,
        bus: EventBus | None,
        source: LevelSource,
        *,
        max_hz: float = 20.0,
        attack: float = 0.6,
        release: float = 0.2,
        floor_db: float = -60.0,
        ceil_db: float = -10.0,
    ) -> None:
        if max_hz <= 0 or not 0 < attack <= 1 or not 0 < release <= 1 or ceil_db <= floor_db:
            raise ValueError("parâmetros inválidos para LevelMeter")
        self._bus = bus
        self._source = source
        self._interval = 1.0 / max_hz
        self._attack = attack
        self._release = release
        self._floor_db = floor_db
        self._span_db = ceil_db - floor_db
        self._smoothed = 0.0
        self._last_pub = 0.0
        self._dirty = False

    @property
    def enabled(self) -> bool:
        return self._bus is not None

    def feed(self, samples: np.ndarray) -> None:
        """Alimenta com um bloco de amostras float32 em [-1, 1]."""
        if self._bus is not None:
            self.feed_rms(rms_of(samples))

    def feed_rms(self, rms: float) -> None:
        """Alimenta com um RMS já calculado (0..1)."""
        if self._bus is None:
            return
        db = 20.0 * math.log10(max(float(rms), 1e-9))
        target = min(1.0, max(0.0, (db - self._floor_db) / self._span_db))
        coef = self._attack if target > self._smoothed else self._release
        self._smoothed += coef * (target - self._smoothed)
        now = time.monotonic()
        if now - self._last_pub >= self._interval:
            self._last_pub = now
            self._dirty = True
            self._bus.publish("level", source=self._source, rms=round(self._smoothed, 4))

    def finish(self) -> None:
        """Publica um último nível 0.0 (se algo foi publicado) para a animação assentar."""
        if self._bus is not None and self._dirty:
            self._smoothed = 0.0
            self._dirty = False
            self._last_pub = time.monotonic()
            self._bus.publish("level", source=self._source, rms=0.0)
