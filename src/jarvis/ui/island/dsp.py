"""DSP do espectro (sem Qt) e fonte de audio SINTETICA para o prototipo.

Analisador: janela Hann + rFFT, bandas em escala logaritmica (80 Hz a 8 kHz), suavizacao com
constante de tempo (independente do fps): ataque rapido, queda lenta. A fonte sintetica imita fala
(formantes + silabas) so para animar; na fase I1 troca-se por microfone/TTS real (mesma interface).
"""
from __future__ import annotations

from typing import Protocol

import numpy as np

SR = 22050            # taxa do Piper
N_FFT = 1024
F_MIN, F_MAX = 80.0, 8000.0


class SpectrumAnalyzer:
    def __init__(self, bands: int = 28, sr: int = SR, n_fft: int = N_FFT,
                 attack_s: float = 0.02, release_s: float = 0.05) -> None:
        self.bands, self.sr, self.n_fft = bands, sr, n_fft
        self._win = np.hanning(n_fft).astype(np.float32)
        self._norm = float(self._win.sum() / 2.0)
        edges = np.geomspace(F_MIN, F_MAX, bands + 1)
        bw = sr / n_fft
        self._slices: list[tuple[int, int]] = []
        for lo_f, hi_f in zip(edges[:-1], edges[1:]):
            lo = int(lo_f // bw)
            hi = max(lo + 1, int(np.ceil(hi_f / bw)))
            self._slices.append((lo, hi))
        centers = np.sqrt(edges[:-1] * edges[1:])
        self._tilt = (3.0 * np.log2(centers / F_MIN)).astype(np.float32)   # +3 dB/oitava: fala tem pouco agudo
        self._attack, self._release = attack_s, release_s
        self.value = np.zeros(bands, dtype=np.float32)

    def process(self, samples: np.ndarray, dt: float) -> np.ndarray:
        x = np.zeros(self.n_fft, dtype=np.float32)
        n = min(len(samples), self.n_fft)
        x[self.n_fft - n:] = samples[-n:]
        mag = np.abs(np.fft.rfft(x * self._win)) / self._norm
        raw = np.fromiter((mag[a:b].mean() for a, b in self._slices), dtype=np.float32, count=self.bands)
        db = 20.0 * np.log10(raw + 1e-9) + self._tilt
        target = np.clip((db + 66.0) / 54.0, 0.0, 1.0)
        a_up = 1.0 - np.exp(-dt / self._attack)
        a_dn = 1.0 - np.exp(-dt / self._release)
        coef = np.where(target > self.value, a_up, a_dn)
        self.value = (self.value + (target - self.value) * coef).astype(np.float32)
        return self.value

    def reset(self) -> None:
        self.value[:] = 0.0


class LevelSource(Protocol):
    """O que a Ilha consome: bandas 0..1 e nivel 0..1 do microfone (ouvindo) ou do TTS (falando)."""

    def read(self, speaking: bool, dt: float) -> tuple[np.ndarray, float]: ...


class SyntheticSource:
    """Fala falsa: pulso glotal com formantes que andam + envelope silabico (~4 Hz) + pausas de palavra."""

    def __init__(self, bands: int = 28) -> None:
        self._an = SpectrumAnalyzer(bands)
        self._t = 0.0
        self._rng = np.random.default_rng(7)

    def _render(self, t_end: float, speaking: bool) -> np.ndarray:
        n = N_FFT
        t = t_end - (np.arange(n, 0, -1) - 1) / SR
        f0 = (95.0 if speaking else 125.0) + 12.0 * np.sin(2 * np.pi * 0.7 * t)
        syl = 3.2 if speaking else 4.3
        env = np.clip(np.sin(2 * np.pi * syl * t), 0, None) ** 0.7
        gate = (np.sin(2 * np.pi * 0.45 * t + (0.0 if speaking else 1.3)) > -0.55).astype(np.float32)
        f1 = 500.0 + 350.0 * np.sin(2 * np.pi * 1.1 * t)
        f2 = 1500.0 + 700.0 * np.sin(2 * np.pi * 0.8 * t + 1.0)
        out = np.zeros(n, dtype=np.float64)
        phase = 2 * np.pi * np.cumsum(f0) / SR
        for k in range(1, 36):
            fk = k * f0
            amp = (1.0 / k) * (np.exp(-((fk - f1) / 260.0) ** 2) * 2.0 + np.exp(-((fk - f2) / 420.0) ** 2) + 0.05)
            out += amp * np.sin(k * phase)
        out = out * env * gate * (0.30 if speaking else 0.25)
        out += 0.0015 * self._rng.standard_normal(n)
        return out.astype(np.float32)

    def read(self, speaking: bool, dt: float) -> tuple[np.ndarray, float]:
        self._t += dt
        bands = self._an.process(self._render(self._t, speaking), dt)
        return bands, float(bands.mean())

    def reset(self) -> None:
        self._an.reset()
