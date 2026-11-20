"""Ferramentas de aplicativos: abrir apps da allowlist e listar quais podem ser abertos."""
from __future__ import annotations

import logging
import os
from typing import Any

from ..config import Config
from .registry import Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec
from ._matching import best_matches, fold

log = logging.getLogger(__name__)

_FUZZY_CUTOFF = 0.72


def _allowlist(cfg: Config) -> dict[str, str]:
    """Nome falado -> alvo, indexado pelo nome sem acento/caixa. Nomes repetidos após a normalização: vale o primeiro."""
    index: dict[str, tuple[str, str]] = {}
    for name, target in cfg.apps.launch.items():
        key = fold(name)
        if not key or not target.strip():
            log.warning("apps.launch: entrada inválida ignorada: %r", name)
            continue
        if key in index:
            log.warning("apps.launch: %r repete %r após normalizar; ignorado", name, index[key][0])
            continue
        index[key] = (name, target.strip())
    return {name: target for name, target in index.values()}


def register(registry: ToolRegistry, cfg: Config) -> None:
    apps = _allowlist(cfg)
    names = list(apps)

    def abrir_app(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = str(args["nome"])
        matches = best_matches(query, names, key=lambda n: n, query_contains_item=True,
                               fuzzy_cutoff=_FUZZY_CUTOFF)
        if not matches:
            return ToolResult(False, f"Não tenho permissão para abrir '{query.strip()[:40]}'. "
                                     f"Posso abrir: {', '.join(names) or 'nenhum app'}.",
                              data={"apps": names})
        if len(matches) > 1:
            return ToolResult(False, "Qual deles? " + ", ".join(matches) + ".", data={"opcoes": matches})
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        name = matches[0]
        try:
            # Alvo vem só da configuração; nenhum argumento do modelo é repassado ao programa.
            os.startfile(apps[name])  # noqa: S606 - allowlist, sem shell
        except OSError as exc:
            log.warning("falha ao abrir %r: %s", name, exc)
            return ToolResult(False, f"Não consegui abrir {name}.")
        return ToolResult(True, f"Abri {name}.")

    def listar_apps_permitidos(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if not names:
            return ToolResult(True, "Nenhum aplicativo está liberado para abrir.", data={"apps": []})
        return ToolResult(True, "Posso abrir: " + ", ".join(names) + ".", data={"apps": names})

    registry.register(ToolSpec(
        name="abrir_app",
        description=("Abre um aplicativo do computador pelo nome, por exemplo 'bloco de notas' ou "
                     "'calculadora'. Só funciona com os apps da lista permitida "
                     "(veja listar_apps_permitidos)."),
        parameters={
            "type": "object",
            "properties": {"nome": {"type": "string", "minLength": 1, "maxLength": 60,
                                    "description": "Nome falado do aplicativo."}},
            "required": ["nome"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=abrir_app,
        confirm_text=lambda a: f"Abrir o aplicativo {str(a.get('nome', ''))[:60]}",
    ))
    registry.register(ToolSpec(
        name="listar_apps_permitidos",
        description="Diz quais aplicativos o Jarvis pode abrir. Use quando perguntarem o que ele consegue abrir.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        risk=Risk.READ,
        handler=listar_apps_permitidos,
    ))
