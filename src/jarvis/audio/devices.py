"""Descoberta e resolução de dispositivos de áudio (entrada/saída) via PortAudio/sounddevice.

Regras de resolução (``cfg.audio.input_device`` / ``output_device``):

* ``None`` ou ``""``  -> dispositivo padrão do Windows (padrão da melhor API host disponível);
* ``int`` (ou texto só com dígitos) -> índice do PortAudio, validado;
* ``str``  -> trecho do nome, sem diferenciar caixa nem acentos (``core.textutil.fold``). O mesmo aparelho aparece uma vez por
  API host (MME, DirectSound, WASAPI...); isso conta como UM candidato e escolhemos a melhor API.
  Dois aparelhos diferentes que casem com o trecho geram ``DeviceError`` de ambiguidade.

Preferência de API host: MME > WASAPI > DirectSound. MME vem primeiro porque o Windows reamostra
para qualquer taxa (16 kHz na captura, 22,05 kHz no Piper) e o "padrão" segue o dispositivo padrão do
sistema; no WASAPI compartilhado a taxa precisa bater com a do mixer, o que resolvemos com
``auto_convert`` (ver ``stream_extra_settings``). WDM-KS nunca é escolhido automaticamente (acesso
exclusivo, falha com frequência); só por índice explícito.

Limitação conhecida: o PortAudio lê a lista de dispositivos uma vez por processo. Aparelhos
conectados depois de iniciar o Jarvis só aparecem após reiniciá-lo.

Contrato de threads: funções sem estado, seguras para chamar de qualquer thread. Nada aqui abre
stream, microfone ou toca som: só consulta.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..config import AudioCfg
from ..core.textutil import fold

log = logging.getLogger(__name__)

Kind = Literal["input", "output"]
DeviceSpec = str | int | None

_KIND_LABEL: dict[str, str] = {"input": "entrada", "output": "saída"}
_EXCLUDED_RANK = 99                 # WDM-KS e afins: só por índice explícito
_NAME_KEY_LEN = 28                  # o MME trunca nomes em 31 caracteres; comparamos o prefixo comum


class AudioError(RuntimeError):
    """Raiz dos erros do subsistema de áudio (captura, reprodução, STT, TTS)."""


class DeviceError(AudioError):
    """Dispositivo inexistente, ambíguo, sem canais do tipo pedido, ou PortAudio indisponível."""


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    is_default_input: bool = False
    is_default_output: bool = False

    def supports(self, kind: Kind) -> bool:
        return (self.max_input_channels if kind == "input" else self.max_output_channels) > 0

    def is_default(self, kind: Kind) -> bool:
        return self.is_default_input if kind == "input" else self.is_default_output

    @property
    def api_rank(self) -> int:
        """Menor = preferida."""
        api = self.hostapi.lower()
        if "mme" in api:
            return 0
        if "wasapi" in api:
            return 1
        if "directsound" in api:
            return 2
        if "wdm" in api:
            return _EXCLUDED_RANK
        return 3

    @property
    def label(self) -> str:
        chans = f"{self.max_input_channels} in/{self.max_output_channels} out"
        return f"[{self.index}] {self.name} ({self.hostapi}, {chans}, {self.default_samplerate:.0f} Hz)"


# ----------------------------------------------------------------------------- acesso ao PortAudio
def load_sounddevice() -> Any:
    """Importa ``sounddevice`` sob demanda; PortAudio ausente vira ``DeviceError`` com mensagem clara."""
    try:
        import sounddevice
    except (ImportError, OSError) as exc:
        raise DeviceError(f"sounddevice/PortAudio indisponível: {exc}") from exc
    return sounddevice


def list_devices() -> list[AudioDevice]:
    """Todos os dispositivos conhecidos pelo PortAudio, na ordem dos índices."""
    sd = load_sounddevice()
    try:
        raw = list(sd.query_devices())
        apis = list(sd.query_hostapis())
    except Exception as exc:  # sd.PortAudioError e falhas de inicialização do host
        raise DeviceError(f"não consegui listar os dispositivos de áudio: {exc}") from exc
    result: list[AudioDevice] = []
    for index, info in enumerate(raw):
        api_index = int(info.get("hostapi", -1))
        api = apis[api_index] if 0 <= api_index < len(apis) else {}
        result.append(AudioDevice(
            index=index,
            name=str(info.get("name", "")).strip(),
            hostapi=str(api.get("name", "?")),
            max_input_channels=int(info.get("max_input_channels", 0)),
            max_output_channels=int(info.get("max_output_channels", 0)),
            default_samplerate=float(info.get("default_samplerate", 0.0)),
            is_default_input=api.get("default_input_device", -1) == index,
            is_default_output=api.get("default_output_device", -1) == index,
        ))
    return result


def stream_extra_settings(device: AudioDevice) -> Any | None:
    """Ajustes extras de stream. No WASAPI ativa ``auto_convert`` (aceita qualquer taxa no modo compartilhado)."""
    if "wasapi" not in device.hostapi.lower():
        return None
    sd = load_sounddevice()
    try:
        return sd.WasapiSettings(auto_convert=True)
    except (AttributeError, TypeError):
        log.debug("WasapiSettings(auto_convert) indisponível nesta versão do sounddevice")
        return None


# ----------------------------------------------------------------------------- resolução
def _best(devices: Sequence[AudioDevice]) -> AudioDevice:
    return min(devices, key=lambda d: (d.api_rank, d.index))


def _available_text(devices: Sequence[AudioDevice]) -> str:
    seen: dict[str, AudioDevice] = {}
    for d in sorted(devices, key=lambda x: (x.api_rank, x.index)):
        if d.api_rank < _EXCLUDED_RANK:
            seen.setdefault(fold(d.name)[:_NAME_KEY_LEN], d)
    return "; ".join(f"[{d.index}] {d.name}" for d in seen.values()) or "(nenhum)"


def resolve_device(spec: DeviceSpec, kind: Kind) -> AudioDevice:
    """Resolve ``spec`` para um dispositivo do tipo ``kind``. Levanta ``DeviceError`` se não achar ou for ambíguo."""
    label = _KIND_LABEL[kind]
    everything = list_devices()
    capable = [d for d in everything if d.supports(kind)]
    if not capable:
        raise DeviceError(f"nenhum dispositivo de áudio de {label} encontrado (cabo solto ou driver desativado?)")

    if isinstance(spec, bool):
        raise DeviceError(f"dispositivo de {label} inválido: {spec!r}")
    if isinstance(spec, str):
        spec = spec.strip()
        if spec.isdigit():
            spec = int(spec)
        elif not spec:
            spec = None

    if spec is None:
        usable = [d for d in capable if d.api_rank < _EXCLUDED_RANK]
        defaults = [d for d in usable if d.is_default(kind)]
        if not usable:
            log.warning("só há dispositivos WDM-KS de %s (sem MME/WASAPI/DirectSound): o serviço de áudio do Windows "
                        "pode estar reiniciando; usando %s mesmo assim", label, capable[0].label)
        chosen = _best(defaults or usable or capable)
        log.debug("dispositivo de %s padrão: %s", label, chosen.label)
        return chosen

    if isinstance(spec, int):
        for d in everything:
            if d.index == spec:
                if not d.supports(kind):
                    raise DeviceError(f"o dispositivo {d.label} não tem canais de {label}")
                return d
        raise DeviceError(f"não existe dispositivo de áudio com índice {spec} (0..{len(everything) - 1})")

    needle = fold(spec)
    usable = [d for d in capable if d.api_rank < _EXCLUDED_RANK]
    matches = [d for d in usable if needle in fold(d.name)]
    if not matches:
        raise DeviceError(f"dispositivo de {label} {spec!r} não encontrado. Disponíveis: {_available_text(capable)}")
    exact = [d for d in matches if fold(d.name) == needle]
    matches = exact or matches

    groups: dict[str, list[AudioDevice]] = {}
    for d in matches:
        groups.setdefault(fold(d.name)[:_NAME_KEY_LEN], []).append(d)
    if len(groups) > 1:
        names = "; ".join(f"[{_best(g).index}] {_best(g).name}" for g in groups.values())
        raise DeviceError(f"dispositivo de {label} {spec!r} é ambíguo ({names}). Use um trecho maior ou o índice")
    chosen = _best(next(iter(groups.values())))
    log.debug("dispositivo de %s %r -> %s", label, spec, chosen.label)
    return chosen


def resolve_input_device(cfg: AudioCfg) -> AudioDevice:
    return resolve_device(cfg.input_device, "input")


def resolve_output_device(cfg: AudioCfg) -> AudioDevice:
    return resolve_device(cfg.output_device, "output")


def format_devices(devices: Sequence[AudioDevice] | None = None) -> list[str]:
    """Linhas legíveis para o ``doctor``; marca os padrões de cada API com ``*``."""
    items = list_devices() if devices is None else devices
    lines: list[str] = []
    for d in items:
        marks = ("*in" if d.is_default_input else "") + (" *out" if d.is_default_output else "")
        lines.append(f"{d.label} {marks}".rstrip())
    return lines
