"""Catálogo único de ferramentas: monta o registro completo e descreve as ferramentas (para a tela de Configurações e o doctor).

Um só lugar decide QUAIS módulos de ferramentas existem; app, doctor, CLI e interface usam isto.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass

from ..config import Config
from ..core.events import EventBus
from .registry import ToolRegistry

log = logging.getLogger(__name__)

# módulos de ferramentas, na ordem de registro. Cada um expõe `register(registry, cfg)`; `builtin` expõe `register_all`.
_MODULES: tuple[str, ...] = ("builtin", "memory_tools", "files_tools", "terminal_tools")


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    risk: int                      # 0 READ, 1 CONTROL, 2 RISKY
    enabled: bool


def register_everything(registry: ToolRegistry, cfg: Config) -> list[str]:
    """Registra todas as ferramentas. Um módulo que falhe é isolado e devolvido na lista de falhas (e logado em ERROR)."""
    failed: list[str] = []
    for mod_name in _MODULES:
        try:
            mod = importlib.import_module(f"{__package__}.{mod_name}")
            if hasattr(mod, "register_all"):
                failed += [f"{mod_name}.{m}" for m in (mod.register_all(registry, cfg) or [])]
            else:
                mod.register(registry, cfg)
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.endswith(mod_name):
                log.warning("módulo de ferramentas ausente: %s", mod_name)      # ainda não existe nesta instalação
            else:
                log.exception("módulo de ferramentas %s falhou ao importar", mod_name)
                failed.append(mod_name)
        except Exception:  # noqa: BLE001
            log.exception("módulo de ferramentas %s falhou ao registrar", mod_name)
            failed.append(mod_name)
    return failed


def describe_tools(cfg: Config) -> list[ToolInfo]:
    """Todas as ferramentas registradas, com risco e se estão ligadas na config (sem executar nada)."""
    registry = ToolRegistry(cfg, EventBus())
    register_everything(registry, cfg)
    off = set(cfg.tools.disabled)
    out: list[ToolInfo] = []
    for name in registry.names():
        spec = registry.get(name)
        assert spec is not None
        out.append(ToolInfo(name, spec.description, int(spec.risk), name not in off))
    return out
