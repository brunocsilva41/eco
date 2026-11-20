"""Ferramentas de UI Automation: listar e acionar controles da janela ativa, por nome.

Cada chamada percorre a árvore de controles na própria thread (objetos COM não atravessam threads)
e com orçamento de tempo/elementos, porque aplicativos grandes (navegadores) têm árvores enormes.
Nomes de controles são texto de terceiros: resultados são `untrusted=True`.

`clicar_controle` NUNCA aciona o controle na thread do registro: Invoke/Select/Toggle são chamadas COM
síncronas que, se o botão abre um diálogo modal, só voltam quando o diálogo fecha. Todo o trabalho COM
roda numa thread auxiliar dedicada (com COM próprio); o handler espera pouco e, se estourar, devolve
sucesso parcial. Enquanto uma thread auxiliar estiver pendente, novas chamadas são recusadas.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Final

import uiautomation as auto

from ..config import Config
from ..core.cancel import CancelToken
from ..core.textutil import fold
from ..win import input as win_input
from ._matching import best_matches, clip
from .registry import Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec

log = logging.getLogger(__name__)

_MAX_LISTED: Final = 40             # controles devolvidos por listar_controles
_MAX_COLLECTED: Final = 300         # controles guardados para a busca por nome
_MAX_DEPTH: Final = 8
_MAX_VISITED: Final = 2500          # elementos examinados no total
_WALK_BUDGET_S: Final = 6.0
_MAX_OPTIONS: Final = 6
_NAME_CLIP: Final = 60
_ACTION_WAIT_S: Final = 1.5         # quanto o handler espera o Invoke/Select/Toggle antes de devolver sucesso parcial
_RESOLVE_WAIT_S: Final = _WALK_BUDGET_S + 3.0   # teto para a thread auxiliar achar o controle
_POLL_S: Final = 0.05

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


def _collect(cancel: CancelToken, limit: int) -> tuple[list[_Entry], str | None]:
    """Percorre a janela ativa e devolve controles clicáveis, visíveis, habilitados e com nome."""
    root = auto.GetForegroundControl()
    if root is None:
        return [], "Nenhuma janela está em foco."
    entries: list[_Entry] = []
    deadline = time.monotonic() + _WALK_BUDGET_S
    visited = 0
    for control, _depth in auto.WalkControl(root, includeTop=False, maxDepth=_MAX_DEPTH):
        visited += 1
        if cancel.cancelled or visited > _MAX_VISITED or time.monotonic() > deadline:
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
    """Aciona o controle pelo padrão mais adequado; cai para o clique físico só se necessário.

    Roda SEMPRE na thread auxiliar da UIA (pode bloquear até um diálogo modal fechar).
    """
    for pattern_id, method in ((auto.PatternId.InvokePattern, "Invoke"),
                               (auto.PatternId.SelectionItemPattern, "Select"),
                               (auto.PatternId.TogglePattern, "Toggle")):
        pattern = control.GetPattern(pattern_id)
        if pattern is not None:
            getattr(pattern, method)(waitTime=0)
            return method
    rect = control.BoundingRectangle                 # pixels físicos (o processo é DPI-aware por monitor)
    if rect.width() <= 0 or rect.height() <= 0:
        raise RuntimeError("controle sem área clicável")
    win_input.click(rect.xcenter(), rect.ycenter())  # SendInput absoluto sobre a tela virtual (multi-monitor)
    return "Click"


# ----------------------------------------------------------------- thread auxiliar da UIA
_pending_lock = threading.Lock()
_pending = 0                                         # threads auxiliares da UIA ainda vivas (presas em diálogo modal etc.)


class _Job:
    """Estado compartilhado entre o handler e a thread auxiliar (só Events e valores simples)."""

    def __init__(self) -> None:
        self.resolved = threading.Event()            # a busca terminou (achou, falhou ou ficou ambígua)
        self.done = threading.Event()                # a ação terminou (ou a thread acabou)
        self.abandoned = threading.Event()           # o handler desistiu antes de agir: não aja
        self.failure: ToolResult | None = None       # motivo para não agir (nada, ambíguo, destrutivo...)
        self.name = ""
        self.kind = ""
        self.how: str | None = None
        self.error: str | None = None


def _resolve_target(job: _Job, query: str, cancel: CancelToken) -> Any | None:
    """Acha o controle (na thread auxiliar). Devolve o controle ou None com `job.failure` preenchido."""
    entries, problem = _collect(cancel, _MAX_COLLECTED)
    if problem:
        job.failure = ToolResult(False, problem)
        return None
    matches = best_matches(query, entries, key=lambda e: e.name)
    if not matches:
        job.failure = ToolResult(False, f"Não achei um controle chamado '{query[:40]}' na janela ativa.")
        return None
    if len(matches) > 1:
        options = [f"{clip(e.name, _NAME_CLIP)} ({e.kind})" for e in matches[:_MAX_OPTIONS]]
        job.failure = ToolResult(False, f"Mais de um controle combina com '{query[:40]}': "
                                        + "; ".join(options) + ". Diga o nome completo.",
                                 data={"opcoes": options}, untrusted=True)
        return None
    target = matches[0]
    if _is_destructive(target.name):
        job.failure = ToolResult(False, f"'{clip(target.name, _NAME_CLIP)}' parece uma ação de excluir, "
                                        "enviar, pagar ou instalar. Prefiro que você faça manualmente.",
                                 untrusted=True)
        return None
    job.name, job.kind = target.name, target.kind
    return target.control


def _uia_worker(job: _Job, query: str, cancel: CancelToken) -> None:
    global _pending
    try:
        with auto.UIAutomationInitializerInThread():     # COM próprio desta thread, liberado ao sair do bloco
            control = _resolve_target(job, query, cancel)
            job.resolved.set()
            if control is None:
                return
            if cancel.cancelled or job.abandoned.is_set():
                job.failure = ToolResult(False, "Cancelado.")
                return
            try:
                job.how = _invoke(control)
            except Exception as exc:  # noqa: BLE001 - COMError, elemento sumiu, sem padrão
                log.warning("falha ao acionar controle %r: %s", job.name, exc)
                job.error = type(exc).__name__
    except Exception:  # noqa: BLE001 - nada escapa da thread auxiliar
        log.exception("thread auxiliar da UIA falhou")
        job.error = job.error or "erro"
    finally:
        with _pending_lock:
            _pending -= 1
        job.resolved.set()
        job.done.set()


def _click_by_name(ctx: ToolContext, query: str) -> ToolResult:
    """Orquestra a thread auxiliar: busca, aciona e espera pouco. Nunca bloqueia no COM."""
    global _pending
    with _pending_lock:
        if _pending > 0:
            return ToolResult(False, "Ainda há um clique anterior pendente, talvez uma janela aberta esperando "
                                     "você. Resolva esse diálogo antes de eu clicar de novo.")
        _pending += 1
    job = _Job()
    try:
        threading.Thread(target=_uia_worker, args=(job, query, ctx.cancel), name="uia-action", daemon=True).start()
    except RuntimeError:
        with _pending_lock:
            _pending -= 1
        log.exception("não consegui iniciar a thread da UIA")
        return ToolResult(False, "Não consegui iniciar o clique agora.")

    deadline = time.monotonic() + _RESOLVE_WAIT_S
    while not job.resolved.wait(_POLL_S):
        if ctx.cancel.cancelled or time.monotonic() >= deadline:
            job.abandoned.set()
            if ctx.cancel.cancelled:
                return ToolResult(False, "Cancelado.")
            log.warning("a busca de controles passou de %.0fs; abandonada", _RESOLVE_WAIT_S)
            return ToolResult(False, "A janela demorou demais para responder; não cliquei.")
    if job.failure is not None:
        return job.failure
    name = clip(job.name, _NAME_CLIP)
    if not job.done.wait(_ACTION_WAIT_S):
        log.warning("acionamento de %r passou de %.1fs; provável diálogo modal", job.name, _ACTION_WAIT_S)
        return ToolResult(True, "Acionei o controle; pode haver uma janela aguardando você.", untrusted=True)
    if job.failure is not None:                      # cancelado entre achar e acionar
        return job.failure
    if job.error is not None:
        return ToolResult(False, f"Não consegui acionar '{name}'.", untrusted=True)
    log.info("controle acionado via %s (%s)", job.how, job.kind)
    return ToolResult(True, f"Cliquei em {name}.", untrusted=True)


def register(registry: ToolRegistry, cfg: Config) -> None:
    def listar_controles(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        with auto.UIAutomationInitializerInThread():
            entries, problem = _collect(ctx.cancel, _MAX_LISTED)
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
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        return _click_by_name(ctx, query)

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
