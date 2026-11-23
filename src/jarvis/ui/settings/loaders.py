"""Leituras pesadas da tela, feitas FORA da thread da interface (via ``ui.kit.tasks.run_async``).

Funcoes puras de proposito: nao tocam em widget. A tela chama estas funcoes dentro de ``run_async`` e recebe
o resultado ja pronto. Nada aqui abre microfone ou toca audio: so lista dispositivos e descreve ferramentas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from jarvis.audio.devices import list_devices
from jarvis.config import Config
from jarvis.tools.catalog import ToolInfo, describe_tools

log = logging.getLogger(__name__)

DeviceKind = Literal["input", "output"]
_EXCLUDED_RANK = 99          # WDM-KS e afins: o Eco so os usa por indice explicito, entao nao entram na lista


@dataclass(frozen=True)
class DeviceChoice:
    label: str
    value: str


def load_devices(kind: DeviceKind) -> list[DeviceChoice]:
    """Dispositivos de entrada ou saida sem repeticoes (o mesmo aparelho surge em varias APIs do Windows)."""
    seen: set[str] = set()
    out: list[DeviceChoice] = []
    for dev in sorted(list_devices(), key=lambda d: (d.api_rank, d.index)):
        key = dev.name.casefold()
        if not dev.supports(kind) or dev.api_rank >= _EXCLUDED_RANK or key in seen or not dev.name:
            continue
        seen.add(key)
        out.append(DeviceChoice(dev.name, dev.name))
    log.debug("%d dispositivos de %s listados", len(out), kind)
    return sorted(out, key=lambda c: c.label.casefold())


def load_tools(cfg: Config) -> list[ToolInfo]:
    """Catalogo de ferramentas (sem executar nenhuma), em ordem alfabetica."""
    return sorted(describe_tools(cfg), key=lambda t: t.name.casefold())
