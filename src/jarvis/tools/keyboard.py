"""Ferramentas de teclado: digitar texto e apertar atalhos da allowlist."""
from __future__ import annotations

import logging
from typing import Any

from ..config import Config
from ..win import input as win_input
from ..win import windows as win
from ..win.keys import KeyError_, parse_combo
from .registry import Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec

log = logging.getLogger(__name__)


def _allowed_hotkeys(cfg: Config) -> frozenset[str]:
    """Formas normalizadas dos atalhos válidos da configuração."""
    allowed: set[str] = set()
    for raw in cfg.apps.hotkeys:
        try:
            norm = parse_combo(raw).norm
        except KeyError_ as exc:
            log.warning("apps.hotkeys: atalho inválido ignorado (%s)", exc)
            continue
        allowed.add(norm)
    return frozenset(allowed)


def register(registry: ToolRegistry, cfg: Config) -> None:
    max_chars = max(1, cfg.safety.max_typed_chars)
    allowed = _allowed_hotkeys(cfg)

    def digitar_texto(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        text = str(args["texto"])
        if not text.strip():
            return ToolResult(False, "Não há texto para digitar.")
        if len(text) > max_chars:
            return ToolResult(False, f"O texto passa do limite de {max_chars} caracteres.")
        if win.foreground_window() is None:
            return ToolResult(False, "Nenhuma janela está em foco para receber o texto.")
        try:
            typed = win_input.send_text(text, ctx.cancel)
        except win_input.InputBlockedError as exc:
            return ToolResult(False, str(exc))
        if ctx.cancel.cancelled:
            return ToolResult(False, f"Interrompido; digitei {typed} caracteres.")
        return ToolResult(True, f"Digitei {typed} caracteres.")

    def apertar_atalho(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        raw = str(args["atalho"])
        try:
            combo = parse_combo(raw)
        except KeyError_:
            return ToolResult(False, f"'{raw.strip()[:30]}' não é um atalho válido. Exemplo: ctrl+c.")
        if combo.norm not in allowed:
            return ToolResult(False, f"O atalho {combo.norm} não está liberado. "
                                     f"Liberados: {', '.join(sorted(allowed))}.")
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        try:
            win_input.send_combo(combo)
        except win_input.InputBlockedError as exc:
            return ToolResult(False, str(exc))
        return ToolResult(True, f"Apertei {combo.norm}.")

    registry.register(ToolSpec(
        name="digitar_texto",
        description=("Digita um texto no campo da janela que está em foco, como se fosse o teclado. "
                     f"No máximo {max_chars} caracteres. Antes, garanta o foco certo com focar_janela."),
        parameters={
            "type": "object",
            "properties": {"texto": {"type": "string", "minLength": 1, "maxLength": max_chars,
                                     "description": "Texto a digitar."}},
            "required": ["texto"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=digitar_texto,
        redact=frozenset({"texto"}),
        confirm_text=lambda a: "Digitar texto na janela em foco",
    ))
    registry.register(ToolSpec(
        name="apertar_atalho",
        description=("Aperta um atalho de teclado na janela em foco, como 'ctrl+c' ou 'enter'. "
                     "Só estes são aceitos: " + ", ".join(sorted(allowed)) + "."),
        parameters={
            "type": "object",
            "properties": {"atalho": {"type": "string", "minLength": 1, "maxLength": 40,
                                      "description": "Atalho no formato ctrl+c, alt+tab, enter."}},
            "required": ["atalho"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=apertar_atalho,
        confirm_text=lambda a: f"Apertar o atalho {str(a.get('atalho', ''))[:40]}",
    ))
