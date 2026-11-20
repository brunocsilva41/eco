"""Ferramentas de notas do Bruno (memória SQLite)."""
from __future__ import annotations

import time

from ..config import Config
from ..memory import MemoryError_
from .registry import Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec


def _anotar(ctx: ToolContext, args: dict) -> ToolResult:
    if ctx.memory is None:
        return ToolResult(False, "A memória não está disponível.")
    try:
        ctx.memory.add_note(args["texto"])
    except MemoryError_ as exc:
        return ToolResult(False, str(exc))
    return ToolResult(True, "Anotado.")


def _ler_notas(ctx: ToolContext, args: dict) -> ToolResult:
    if ctx.memory is None:
        return ToolResult(False, "A memória não está disponível.")
    notes = ctx.memory.list_notes(limit=int(args.get("quantidade", 5)), contains=args.get("busca") or None)
    if not notes:
        return ToolResult(True, "Não achei nenhuma nota.")
    lines = [f"{time.strftime('%d/%m %H:%M', time.localtime(n.created))}: {n.text}" for n in notes]
    return ToolResult(True, "; ".join(lines), data={"notas": [n.text for n in notes]})


def register(registry: ToolRegistry, cfg: Config) -> None:
    registry.register(ToolSpec(
        name="anotar",
        description="Guarda uma nota de texto para o Bruno lembrar depois. Nunca use para senhas, PINs ou cartões.",
        parameters={"type": "object", "properties": {"texto": {"type": "string", "minLength": 1, "maxLength": 1000}},
                    "required": ["texto"], "additionalProperties": False},
        risk=Risk.CONTROL, handler=_anotar))
    registry.register(ToolSpec(
        name="ler_notas",
        description="Lê as notas mais recentes do Bruno, opcionalmente filtrando por uma palavra.",
        parameters={"type": "object", "properties": {
            "quantidade": {"type": "integer", "minimum": 1, "maximum": 20},
            "busca": {"type": "string", "maxLength": 100}},
            "additionalProperties": False},
        risk=Risk.READ, handler=_ler_notas))
