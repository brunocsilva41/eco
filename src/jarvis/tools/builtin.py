"""Registro de todas as ferramentas embutidas, com isolamento de falhas por módulo."""
from __future__ import annotations

import importlib
import logging
from typing import Final

from ..config import Config
from .registry import ToolRegistry

log = logging.getLogger(__name__)

# Módulos em jarvis.tools, cada um com `register(registry, cfg)`.
_MODULES: Final[tuple[str, ...]] = (
    "apps", "windows_tools", "keyboard", "screen", "uia", "system_tools",
)


def register_all(registry: ToolRegistry, cfg: Config) -> None:
    """Registra cada módulo; se um falhar ao importar ou registrar, loga e segue com os outros.

    Falha parcial dentro de um módulo (ex.: 2ª ferramenta duplicada) deixa as já registradas ativas.
    """
    failed: list[str] = []
    for name in _MODULES:
        try:
            module = importlib.import_module(f"{__package__}.{name}")
            module.register(registry, cfg)
        except Exception:  # noqa: BLE001 - fronteira de isolamento: nenhum módulo derruba os outros
            log.exception("ferramentas '%s' indisponíveis: falha ao carregar/registrar", name)
            failed.append(name)
    log.info("ferramentas carregadas: %d (%s)", len(registry.names()), ", ".join(registry.names()))
    if failed:
        log.warning("módulos de ferramentas com falha: %s", ", ".join(failed))
