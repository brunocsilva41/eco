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
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Final

import uiautomation as auto

from ..config import Config
from ..core.cancel import CancelToken
from ..core.textutil import fold
from ..win import input as win_input
from ..win import windows as win
from ._matching import best_matches, clip
from .registry import Prepared, Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec
from .windows_tools import audit_label

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


# Botões que costumam APROVAR algo (diálogos de aviso, "salvar", "permitir"...): não são recusados, mas exigem
# confirmação FORTE ("confirmo") mostrando o nome do controle e a janela. Palavras curtas só valem inteiras
# (para "sim" não pegar "simples"); radicais longos valem como início de palavra.
CONFIRM_WORDS: Final[frozenset[str]] = frozenset({
    "sim", "ok", "yes", "run", "allow", "save", "apply", "close", "accept", "agree"})
CONFIRM_STEMS: Final[tuple[str, ...]] = (
    "executar", "execute", "permitir", "permita", "continuar", "continue", "salvar", "salve",
    "aplicar", "aplique", "fechar", "feche", "aceitar", "aceite", "concord")


def needs_strong_confirm(text: str) -> bool:
    """True se o nome do controle é de um botão que aprova/confirma algo (Sim, OK, Executar, Salvar, Fechar...)."""
    words = re.findall(r"[a-z0-9]+", fold(text))
    return any(w in CONFIRM_WORDS or w.startswith(CONFIRM_STEMS) for w in words)


class _Aborted(Exception):
    """A janela mudou ou o ponto de clique saiu dela: não clica. A mensagem pode ser falada."""


@dataclass(frozen=True)
class _ClickTarget:
    """Janela em foco no momento do `prepare` de clicar_controle."""
    hwnd: int
    pid: int


@dataclass
class _Entry:
    name: str
    kind: str                 # rótulo em português
    control: Any              # auto.Control (só vale na thread que o criou)
    hwnd: int = 0             # janela em foco quando a varredura começou


def _collect(cancel: CancelToken, limit: int, expect_hwnd: int | None = None) -> tuple[list[_Entry], str | None]:
    """Percorre a janela ativa e devolve controles clicáveis, visíveis, habilitados e com nome.

    Com `expect_hwnd`, só varre se a janela em foco for exatamente essa, e descarta tudo se o foco mudar durante a varredura.
    """
    scan_hwnd = win.foreground_hwnd()
    if expect_hwnd is not None and scan_hwnd != expect_hwnd:
        return [], "A janela em foco mudou; não cliquei."
    root = auto.GetForegroundControl()
    if root is None or not scan_hwnd:
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
        entries.append(_Entry(name, kind, control, scan_hwnd))
        if len(entries) >= limit:
            break
    if expect_hwnd is not None and win.foreground_hwnd() != scan_hwnd:
        return [], "A janela em foco mudou durante a busca; não cliquei."
    return entries, None


def _hit_is_control(control: Any, x: int, y: int) -> bool:
    """O elemento REAL sob o ponto (ControlFromPoint) é o controle alvo ou um descendente dele?
    Se outra janela/menu/tooltip cobre o ponto, o clique por coordenadas acertaria o alvo errado."""
    try:
        want = control.GetRuntimeId()
        hit = auto.ControlFromPoint(x, y)
        for _ in range(8):
            if hit is None:
                return False
            if hit.GetRuntimeId() == want:
                return True
            hit = hit.GetParentControl()
    except Exception:  # noqa: BLE001 - sem prova de que o ponto é o alvo, não clica
        log.warning("não consegui verificar o elemento sob o ponto do clique", exc_info=True)
    return False


def _invoke(control: Any, scan_hwnd: int) -> str:
    """Aciona o controle pelo padrão mais adequado; cai para o clique físico só se necessário.

    Roda SEMPRE na thread auxiliar da UIA (pode bloquear até um diálogo modal fechar). O clique por coordenadas
    só acontece se a janela em foco ainda é a da varredura (`scan_hwnd`) E o ponto está dentro dela; senão
    levanta `_Aborted` sem clicar.
    """
    if not scan_hwnd or win.foreground_hwnd() != scan_hwnd:
        raise _Aborted("A janela em foco mudou antes do clique; não cliquei.")
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
    x, y = rect.xcenter(), rect.ycenter()
    if not scan_hwnd or win.foreground_hwnd() != scan_hwnd:
        raise _Aborted("A janela em foco mudou antes do clique; não cliquei.")
    bounds = win.window_rect(scan_hwnd)
    if bounds is None or not (bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3]):
        raise _Aborted("O controle ficou fora da janela; não cliquei.")
    if not _hit_is_control(control, x, y):
        raise _Aborted("Há outra coisa na frente do controle; não cliquei.")
    win_input.click(x, y)                            # SendInput absoluto sobre a tela virtual (multi-monitor)
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
        self.scan_hwnd = 0                           # janela da varredura (guarda do clique por coordenadas)
        self.name = ""
        self.kind = ""
        self.how: str | None = None
        self.error: str | None = None


def _resolve_target(job: _Job, query: str, cancel: CancelToken, expect_hwnd: int) -> Any | None:
    """Acha o controle (na thread auxiliar). Devolve o controle ou None com `job.failure` preenchido."""
    entries, problem = _collect(cancel, _MAX_COLLECTED, expect_hwnd)
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
    if needs_strong_confirm(target.name) and not needs_strong_confirm(query):
        # o que o Bruno confirmou foi o nome pedido; o controle achado é outro e aprova algo: peça pelo nome inteiro
        job.failure = ToolResult(False, f"O controle achado é '{clip(target.name, _NAME_CLIP)}', que pode aprovar "
                                        "uma ação. Peça pelo nome completo para eu confirmar com você.",
                                 untrusted=True)
        return None
    job.name, job.kind, job.scan_hwnd = target.name, target.kind, target.hwnd
    return target.control


def _uia_worker(job: _Job, query: str, cancel: CancelToken, expect_hwnd: int) -> None:
    global _pending
    try:
        with auto.UIAutomationInitializerInThread():     # COM próprio desta thread, liberado ao sair do bloco
            control = _resolve_target(job, query, cancel, expect_hwnd)
            job.resolved.set()
            if control is None:
                return
            if cancel.cancelled or job.abandoned.is_set():
                job.failure = ToolResult(False, "Cancelado.")
                return
            try:
                job.how = _invoke(control, job.scan_hwnd)
            except _Aborted as exc:
                log.warning("clique abortado: %s", exc)
                job.failure = ToolResult(False, str(exc))
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


def _click_by_name(ctx: ToolContext, query: str, expect_hwnd: int) -> ToolResult:
    """Orquestra a thread auxiliar: busca, aciona e espera pouco. Nunca bloqueia no COM."""
    global _pending
    with _pending_lock:
        if _pending > 0:
            return ToolResult(False, "Ainda há um clique anterior pendente, talvez uma janela aberta esperando "
                                     "você. Resolva esse diálogo antes de eu clicar de novo.")
        _pending += 1
    job = _Job()
    try:
        threading.Thread(target=_uia_worker, args=(job, query, ctx.cancel, expect_hwnd), name="uia-action", daemon=True).start()
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

    def prepare_clicar(ctx: ToolContext, args: dict[str, Any]) -> Prepared | ToolResult:
        """Fixa a janela em foco AGORA (recusa a do próprio Jarvis) e monta a pergunta com controle e janela."""
        query = str(args["nome"]).strip()
        if _is_destructive(query):
            return ToolResult(False, "Isso parece uma ação de excluir, enviar, pagar ou instalar. "
                                     "Prefiro que você faça manualmente.")
        info = win.foreground_window()
        if info is None:
            return ToolResult(False, "Nenhuma janela identificável está em foco.")
        if win.is_own_process_window(info, ctx.cfg):
            log.warning("clicar_controle recusado: janela do próprio Jarvis")
            return ToolResult(False, win.OWN_WINDOW_MESSAGE)
        warn = "ATENÇÃO, este botão pode aprovar uma ação. " if needs_strong_confirm(query) else ""
        where = f"«{clip(info.title, 50)}» ({info.process or 'programa desconhecido'})"
        return Prepared(text=f"{warn}Clicar em '{clip(query, _NAME_CLIP)}' na janela {where}",
                        state=_ClickTarget(info.hwnd, info.pid))

    def confirm_clicar(args: dict[str, Any], tainted: bool) -> bool:
        return needs_strong_confirm(str(args.get("nome", "")))

    def clicar_controle(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = str(args["nome"]).strip()
        target = ctx.prepared
        if not isinstance(target, _ClickTarget):
            return ToolResult(False, "Não consegui confirmar a janela de destino; não cliquei.")
        if _is_destructive(query):
            return ToolResult(False, "Isso parece uma ação de excluir, enviar, pagar ou instalar. "
                                     "Prefiro que você faça manualmente.")
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        if win.foreground_hwnd() != target.hwnd or win.pid_of(target.hwnd) != target.pid:
            return ToolResult(False, "A janela em foco mudou; não cliquei.")
        result = _click_by_name(ctx, query, target.hwnd)
        if not result.ok and result.message.startswith("Não achei um controle") and not ctx.cancel.cancelled:
            from . import mouse_tools                     # reserva: o controle não existe na UIA (ícone, imagem, app web): olha a tela
            visual = mouse_tools.click_by_description(ctx, query, target.hwnd)
            if visual.ok or not visual.message.startswith("Não encontrei"):
                return visual
        return result

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
        description=("Clica com o mouse em qualquer botão, aba, link, ícone ou item visível, pelo nome ou por uma descrição curta "
                     "('7', 'botão de mais', 'ícone de salvar'). Tenta achar o controle pelo nome e, se não achar, "
                     "localiza na tela sozinho. Recusa ações de excluir, enviar, pagar ou instalar; botões como Sim, OK, "
                     "Salvar ou Permitir pedem confirmação forte."),
        parameters={
            "type": "object",
            "properties": {"nome": {"type": "string", "minLength": 1, "maxLength": 80,
                                    "description": "Nome do controle como aparece na janela."}},
            "required": ["nome"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=clicar_controle,
        timeout_s=60.0,
        prepare=prepare_clicar,
        confirm_if=confirm_clicar,
        audit_args=lambda a: audit_label(a, "nome"),
    ))
