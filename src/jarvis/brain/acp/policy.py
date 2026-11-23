"""Privacidade e permissões do cérebro em nuvem.

Regras (valem para QUALQUER agente):
1. Só TEXTO vai à nuvem por padrão: o que o usuário pediu e o que as ferramentas liberadas devolvem.
2. Tela (imagens, títulos de janelas, controles), memória/conversas e arquivos só ficam disponíveis a um agente que o usuário
   AUTORIZOU por categoria (`brain.consent_screen|memory|files`, lista de ids de agente). Sem consentimento a ferramenta
   nem aparece na lista do MCP: o agente não consegue chamá-la nem saber que existe.
3. Ferramentas que AGEM no PC passam pelo mesmo ToolRegistry (allowlist, validação, travas duras) e SEMPRE pedem
   confirmação FORTE com o nome do agente (`cloud_label`). Consultas simples (hora, volume...) são livres.
4. Ferramentas PRÓPRIAS do agente (shell, editar arquivos, web) pedem permissão por `session/request_permission`: o padrão é
   NEGAR; com `brain.builtin_tools = "ask"` cada pedido vira uma confirmação forte na Ilha. fs/* e terminal/* do cliente
   nunca são oferecidos.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from ...config import BrainCfg
from ...core.cancel import CancelToken
from ...core.risk import Risk

log = logging.getLogger(__name__)

SCREEN_TOOLS = frozenset({"ver_tela", "localizar_na_tela", "listar_controles", "listar_janelas", "janela_ativa"})
MEMORY_TOOLS = frozenset({"abrir_conversa", "buscar_conversas", "buscar_memoria", "editar_memoria", "esquecer", "lembrar",
                          "listar_conversas", "listar_memorias", "nova_conversa", "resumir_conversa"})
FILE_TOOLS = frozenset({"apagar_arquivo", "copiar_arquivo", "criar_arquivo", "desfazer", "editar_arquivo", "ler_arquivo",
                        "listar_pasta", "mover_arquivo", "abrir_pasta"})
# Ferramentas que o agente da nuvem nunca recebe (mudar o que o Eco "lembra" do usuário é decisão do usuário, não do agente)
NEVER_CLOUD = frozenset({"editar_memoria", "esquecer", "lembrar"})
TERMINAL_TOOLS = frozenset({"executar_comando", "terminal_saida", "terminal_cancelar", "terminal_historico"})   # só com `brain.consent_terminal`
MCP_SERVER_NAME = "eco"


def allowed_tools(cfg_brain: BrainCfg, agent_id: str, all_names: list[str]) -> list[str]:
    """Nomes de ferramentas que ESTE agente pode ver, dado o consentimento por categoria."""
    out: list[str] = []
    for name in all_names:
        if name in NEVER_CLOUD:
            continue
        if name in SCREEN_TOOLS and agent_id not in cfg_brain.consent_screen:
            continue
        if name in MEMORY_TOOLS and agent_id not in cfg_brain.consent_memory:
            continue
        if name in FILE_TOOLS and agent_id not in cfg_brain.consent_files:
            continue
        if name in TERMINAL_TOOLS and agent_id not in cfg_brain.consent_terminal:
            continue
        out.append(name)
    return out


def _pick(options: list[dict[str, Any]], *kinds: str) -> str | None:
    for kind in kinds:
        for opt in options:
            if opt.get("kind") == kind and opt.get("optionId"):
                return str(opt["optionId"])
    return None


def _selected(option_id: str | None) -> dict[str, Any]:
    return {"outcome": {"outcome": "selected", "optionId": option_id}} if option_id else {"outcome": {"outcome": "cancelled"}}


_JARVIS_TITLE = re.compile(r"(?:^|[\s/])(?:mcp[_.:])?" + MCP_SERVER_NAME + r"[_.:]([a-z0-9_]+)\s*$")


def is_jarvis_tool(tool_call: dict[str, Any], jarvis_tool_names: set[str]) -> bool:
    """O pedido de permissão é de uma ferramenta DO ECO (via nosso MCP)? Título no formato `jarvis_<ferramenta>` (com ou sem
    `mcp_` e prefixo como "Run"). O título vem do agente: serve só para não perguntar duas vezes; quem trava de verdade é o
    ToolRegistry, que confirma cada ação no PC."""
    m = _JARVIS_TITLE.search(str(tool_call.get("title", "")).lower().strip())
    return bool(m and m.group(1) in jarvis_tool_names)


def decide_permission(params: dict[str, Any], *, label: str, builtin_policy: str, jarvis_tools: set[str],
                      confirm: Callable[[str, Risk, CancelToken], bool], cancel: CancelToken,
                      audit: Callable[[str, dict[str, Any]], None]) -> dict[str, Any]:
    """Resposta a `session/request_permission`. Nunca libera "sempre" (allow_always): cada uso é decidido de novo."""
    tc = params.get("toolCall") or {}
    options = [o for o in (params.get("options") or []) if isinstance(o, dict)]
    title = str(tc.get("title", "") or tc.get("kind", "") or "ferramenta")[:120]
    reject = _pick(options, "reject_once", "reject_always")
    if cancel.cancelled:
        return {"outcome": {"outcome": "cancelled"}}
    if is_jarvis_tool(tc, jarvis_tools):
        allow = _pick(options, "allow_once")
        audit("permission_jarvis_tool", {"title": title, "allowed": bool(allow)})
        return _selected(allow or reject)
    if builtin_policy == "ask":
        ok = confirm(f"O agente {label}, na nuvem, quer usar uma ferramenta DELE no seu PC: {title}", Risk.RISKY, cancel)
        audit("permission_builtin", {"title": title, "asked": True, "allowed": ok})
        return _selected(_pick(options, "allow_once") if ok else reject)
    audit("permission_builtin", {"title": title, "asked": False, "allowed": False})
    return _selected(reject)
