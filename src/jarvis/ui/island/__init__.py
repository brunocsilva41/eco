"""Ilha do Jarvis (interface estilo Dynamic Island). Fase I0: prototipo visual com dados falsos."""
from __future__ import annotations

from typing import Any

__all__ = ["IslandWindow", "IslandSize", "IslandState", "LevelSource", "SpectrumAnalyzer", "SyntheticSource"]

# Importacao PREGUICOSA: o nucleo (sem Qt) importa `ui.island.link`, e isso nao pode carregar o PySide6.
_LAZY = {"IslandWindow": "window", "IslandSize": "tokens", "IslandState": "tokens", "LevelSource": "bridge",
         "SpectrumAnalyzer": "dsp", "SyntheticSource": "dsp"}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        import importlib
        return getattr(importlib.import_module(f".{_LAZY[name]}", __name__), name)
    raise AttributeError(name)
