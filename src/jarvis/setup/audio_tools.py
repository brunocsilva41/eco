"""Áudio do assistente: lista de dispositivos, gravação com medidor, reprodução, fala de exemplo e calibragem do VAD.

Usa os mesmos módulos do Eco (`audio.devices`, `audio.vad`, `audio.tts`, `audio.playback`), então o teste é fiel ao uso real.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from ..audio.constants import SAMPLE_RATE
from ..audio.devices import AudioDevice, list_devices, load_sounddevice, resolve_device, stream_extra_settings
from ..config import Config

log = logging.getLogger("jarvis.setup.audio")

_SKIP = ("sound mapper", "mapeador de som", "primary sound", "driver de som primário", "driver de som primario")
WINDOW = 512


def device_choices(kind: str) -> list[tuple[str, str | None]]:
    """[(rótulo, valor)] para o seletor. O primeiro é sempre o padrão do Windows (valor None = segue o padrão atual)."""
    out: list[tuple[str, str | None]] = [("Padrão do Windows (recomendado)", None)]
    try:
        devs = [d for d in list_devices() if d.supports(kind) and d.api_rank < 99
                and not any(s in d.name.lower() for s in _SKIP)]
    except Exception:  # noqa: BLE001
        return out
    best: dict[str, AudioDevice] = {}
    for d in devs:
        key = d.name.lower()[:28]
        if key not in best or d.api_rank < best[key].api_rank:
            best[key] = d
    for d in best.values():
        out.append((d.name + ("  (padrão atual)" if d.is_default(kind) else ""), d.name))
    return out


def level_db(x: np.ndarray) -> float:
    if x.size == 0:
        return -90.0
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return 20 * math.log10(max(rms, 1e-6))


class Recorder:
    """Grava do microfone escolhido (16 kHz mono) numa thread do PortAudio; `level_db` é o nível dos últimos 100 ms."""

    def __init__(self, spec: str | int | None) -> None:
        self.spec = spec
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: Any = None
        self.level_db = -90.0
        self.peak_db = -90.0

    def start(self) -> None:
        sd = load_sounddevice()
        dev = resolve_device(self.spec, "input")
        self._frames = []

        def cb(indata: np.ndarray, frames: int, t: Any, status: Any) -> None:
            x = indata[:, 0].copy()
            with self._lock:
                self._frames.append(x)
            self.level_db = level_db(x)
            self.peak_db = max(self.peak_db - 0.5, self.level_db)

        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=1600, device=dev.index,
                                      latency="low", callback=cb, extra_settings=stream_extra_settings(dev))
        self._stream.start()
        self.device_name = dev.name

    def stop(self) -> np.ndarray:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:  # noqa: BLE001
                log.debug("fechando microfone", exc_info=True)
        with self._lock:
            data = np.concatenate(self._frames) if self._frames else np.zeros(0, dtype=np.float32)
        self.level_db = -90.0
        return data


def _cfg_with(cfg: Config, in_spec: str | None = None, out_spec: str | None = None) -> Config:
    return replace(cfg, audio=replace(cfg.audio, input_device=in_spec, output_device=out_spec))


def play_pcm(cfg: Config, out_spec: str | None, audio: np.ndarray, rate: int = SAMPLE_RATE,
             stop: threading.Event | None = None) -> bool:
    """Toca áudio float32 [-1,1] na saída escolhida. Devolve False se interrompido."""
    from ..audio.playback import Speaker
    spk = Speaker(replace(cfg.audio, output_device=out_spec), cfg.tts)
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    watcher_stop = threading.Event()

    def watch() -> None:
        while not watcher_stop.is_set():
            if stop is not None and stop.is_set():
                spk.stop()
                return
            time.sleep(0.05)

    threading.Thread(target=watch, daemon=True).start()
    try:
        return spk.play(pcm, rate)
    finally:
        watcher_stop.set()
        spk.close()


def speak_sample(cfg: Config, out_spec: str | None, text: str, stop: threading.Event | None = None) -> bool:
    """Fala `text` com a voz Piper e a saída escolhida (mesmo caminho da fala real)."""
    from ..audio.playback import Speaker
    from ..audio.tts import Synthesizer, clean_for_speech
    syn = Synthesizer(cfg.tts)
    spk = Speaker(replace(cfg.audio, output_device=out_spec), cfg.tts)
    watcher_stop = threading.Event()

    def watch() -> None:
        while not watcher_stop.is_set():
            if stop is not None and stop.is_set():
                spk.stop()
                return
            time.sleep(0.05)

    threading.Thread(target=watch, daemon=True).start()
    try:
        return spk.play_stream(syn.synthesize(clean_for_speech(text)))
    finally:
        watcher_stop.set()
        spk.close()
        syn.close()


@dataclass(frozen=True)
class Calibration:
    threshold: float
    noise_db: float
    speech_db: float
    noise_p95: float
    speech_p: float
    notes: tuple[str, ...]          # avisos legíveis (pt-BR)


def _probs(vad: Any, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(audio) // WINDOW
    vad.reset()
    p = np.zeros(n, dtype=np.float32)
    e = np.zeros(n, dtype=np.float32)
    for i in range(n):
        w = audio[i * WINDOW:(i + 1) * WINDOW]
        p[i] = vad.prob(w)
        e[i] = level_db(w)
    return p, e


def calibrate_vad(noise: np.ndarray, speech: np.ndarray, vad_path: Any = None) -> Calibration:
    """Escolhe o limiar do VAD entre o 'pior ruído' (silêncio) e a fala fraca do usuário. Simples e explicável."""
    from ..audio.vad import SileroVAD
    vad = SileroVAD(vad_path)
    pn, en = _probs(vad, noise)
    ps, es = _probs(vad, speech)
    if len(pn) < 10 or len(ps) < 10:
        raise ValueError("áudio curto demais para calibrar")
    noise_p95 = float(np.percentile(pn, 95))
    loud = ps[es >= np.percentile(es, 55)]                    # os quadros mais fortes da fala
    speech_p = float(np.percentile(loud, 25)) if loud.size else float(np.median(ps))
    noise_db = float(np.percentile(en, 90))
    speech_db = float(np.percentile(es, 90))
    notes: list[str] = []
    if speech_db < -38:
        notes.append("Sua voz chegou baixa. Aproxime o microfone ou aumente o volume de entrada no Windows.")
    if speech_db > -3:
        notes.append("Sua voz ficou muito alta (estourou). Afaste o microfone ou diminua o ganho.")
    if noise_db > -35:
        notes.append("Há bastante ruído de fundo. Um fone com microfone melhora muito o reconhecimento.")
    if speech_p < 0.45:
        notes.append("O detector teve pouca certeza de que era fala. Repita falando mais perto e com clareza.")
    if noise_p95 >= speech_p:
        thr = 0.6
        notes.append("O ruído parece fala para o detector; usei um limiar mais exigente (0,60).")
    else:
        thr = (noise_p95 + speech_p) / 2
    thr = min(0.7, max(0.3, round(thr / 0.05) * 0.05))
    return Calibration(round(thr, 2), noise_db, speech_db, noise_p95, speech_p, tuple(notes))
