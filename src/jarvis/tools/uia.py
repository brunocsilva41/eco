"""Ferramentas de UI Automation: listar e acionar controles da janela ativa, por nome.

Cada chamada percorre a árvore de controles na própria thread (objetos COM não atravessam threads)
e com orçamento de tempo/elementos, porque aplicativos grandes (navegadores) têm árvores enormes.
Nomes de controles são texto de terceiros: resultados são `untrusted=True`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

import uiautomation as auto

from ..config import Config
from .registry import Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec
from ._matching import best_matches, clip, fold

log = logging.getLogger(__name__)

_MAX_LISTED: Final = 40             # controles devolvidos por listar_controles
_MAX_COLLECTED: Final = 300         # controles guardados para a busca por nome
_MAX_DEPTH: Final = 8
_MAX_VISITED: Final = 2500          # elementos examinados no total
_WALK_BUDGET_S: Final = 6.0
_MAX_OPTIONS: Final = 6
_NAME_CLIP: Final = 60

# Tipos de controle "clicáveis" -> rótulo curto em português.
_CLICKABLE: Final[dict[str, str]] = {
    "ButtonControl": "botão",
    "SplitButtonControl": "botão",
    "MenuItemControl": "item de menu",
    "TabItemControl": "aba",
    "HyperlinkControl": "link",
    "CheckBoxControl": "caixa de seleção",
    "RadioButtonControl": "opção",
    "ListItemControl": "item de lista",
    "TreeItemControl": "item de árvore",
}

# Radicais (comparados com o início de cada palavra do nome, sem acento/caixa) de ações destrutivas,
# de envio, compra/pagamento, instalação ou desligamento: o agente não aciona sozinho.
DESTRUCTIVE_STEMS: Final[tuple[str, ...]] = (
    "exclu", "apag", "delet", "remov", "erase", "descart", "discard", "formatar",
    "enviar", "envie", "envio", "send", "submit", "publicar", "publish",
    "pagar", "pagamento", "pague", "pay", "comprar", "compre", "buy", "purchase", "checkout",
    "finaliz", "assinar", "subscribe",
    "instal", "desinstal", "uninstal", "atualiz", "update",
    "deslig", "reinici", "shutdown", "restart", "sair", "logout", "signout",
    "transfer", "confirm",
)


def _is_destructive(text: str) -> bool:
    words = fold(text).replace("-", " ").split()
    return any(w.startswith(DESTRUCTIVE_STEMS) for w in words)


@dataclass
class _Entry:
    name: str
    kind: str                 # rótulo em português
    control: Any              # auto.Control (só vale na thread que o criou)


def _collect(ctx: ToolContext, limit: int) -> tuple[list[_Entry], str | None]:
    """Percorre a janela ativa e devolve controles clicáveis, visíveis, habilitados e com nome."""
    root = auto.GetForegroundControl()
    if root is None:
        return [], "Nenhuma janela está em foco."
    entries: list[_Entry] = []
    deadline = time.monotonic() + _WALK_BUDGET_S
    visited = 0
    for control, _depth in auto.WalkControl(root, includeTop=False, maxDepth=_MAX_DEPTH):
        visited += 1
        if ctx.cancel.cancelled or visited > _MAX_VISITED or time.monotonic() > deadline:
            break
        try:
            kind = _CLICKABLE.get(control.ControlTypeName)
            if kind is None:
                continue
            name = (control.Name or "").strip()
            if not name or control.IsOffscreen or not control.IsEnabled:
                continue
        except Exception:  # noqa: BLE001 - elemento sumiu no meio da leitura (COMError)
            continue
        entries.append(_Entry(name, kind, control))
        if len(entries) >= limit:
            break
    return entries, None


def _invoke(control: Any) -> str:
    """Aciona o controle pelo padrão mais adequado; cai para o clique real só se necessário."""
    for pattern_id, method in ((auto.PatternId.InvokePattern, "Invoke"),
                               (auto.PatternId.SelectionItemPattern, "Select"),
                               (auto.PatternId.TogglePattern, "Toggle")):
        pattern = control.GetPattern(pattern_id)
        if pattern is not None:
            getattr(pattern, method)(waitTime=0.1)
            return method
    control.Click(simulateMove=False, waitTime=0.1)
    return "Click"


def register(registry: ToolRegistry, cfg: Config) -> None:
    def listar_controles(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        with auto.UIAutomationInitializerInThread():
            entries, problem = _collect(ctx, _MAX_LISTED)
            if problem:
                return ToolResult(False, problem)
            if ctx.cancel.cancelled:
                return ToolResult(False, "Cancelado.")
            items = [{"nome": clip(e.name, _NAME_CLIP), "tipo": e.kind} for e in entries]
        if not items:
            return ToolResult(True, "Não encontrei controles clicáveis na janela ativa.",
                              data={"controles": []}, untrusted=True)
        text = "; ".join(f"{i['nome']} ({i['tipo']})" for i in items)
        return ToolResult(True, f"{len(items)} controles: {text}.", data={"controles": items}, untrusted=True)

    def clicar_controle(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = str(args["nome"]).strip()
        if _is_destructive(query):
            return ToolResult(False, "Isso parece uma ação de excluir, enviar, pagar ou instalar. "
                                     "Prefiro que você faça manualmente.")
        with auto.UIAutomationInitializerInThread():
            entries, problem = _collect(ctx, _MAX_COLLECTED)
            if problem:
                return ToolResult(False, problem)
            matches = best_matches(query, entries, key=lambda e: e.name)
            if not matches:
                return ToolResult(False, f"Não achei um controle chamado '{query[:40]}' na janela ativa.")
            if len(matches) > 1:
                options = [f"{clip(e.name, _NAME_CLIP)} ({e.kind})" for e in matches[:_MAX_OPTIONS]]
                return ToolResult(False, f"Mais de um controle combina com '{query[:40]}': "
                                         + "; ".join(options) + ". Diga o nome completo.",
                                  data={"opcoes": options}, untrusted=True)
            target = matches[0]
            if _is_destructive(target.name):
                return ToolResult(False, f"'{clip(target.name, _NAME_CLIP)}' parece uma ação de excluir, "
                                         "enviar, pagar ou instalar. Prefiro que você faça manualmente.",
                                  untrusted=True)
            if ctx.cancel.cancelled:
                return ToolResult(False, "Cancelado.")
            try:
                how = _invoke(target.control)
            except Exception as exc:  # noqa: BLE001 - COMError, elemento sumiu, sem padrão
                log.warning("falha ao acionar controle %r: %s", target.name, exc)
                return ToolResult(False, f"Não consegui acionar '{clip(target.name, _NAME_CLIP)}'.",
                                  untrusted=True)
            log.info("controle acionado via %s (%s)", how, target.kind)
            return ToolResult(True, f"Cliquei em {clip(target.name, _NAME_CLIP)}.", untrusted=True)

    registry.register(ToolSpec(
        name="listar_controles",
        description=("Lista os botões, abas, links e itens de menu clicáveis da janela ativa (até 40). "
                     "Use antes de clicar_controle para saber os nomes."),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        risk=Risk.READ,
        handler=listar_controles,
        timeout_s=12.0,
    ))
    registry.register(ToolSpec(
        name="clicar_controle",
        description=("Clica num botão, aba, link ou item pelo nome visível, na janela ativa. "
                     "Recusa ações de excluir, enviar, pagar ou instalar."),
        parameters={
            "type": "object",
            "properties": {"nome": {"type": "string", "minLength": 1, "maxLength": 80,
                                    "description": "Nome do controle como aparece na janela."}},
            "required": ["nome"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=clicar_controle,
        timeout_s=12.0,
        confirm_text=lambda a: f"Clicar em '{str(a.get('nome', ''))[:60]}' na janela ativa",
    ))
