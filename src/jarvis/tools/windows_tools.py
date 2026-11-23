"""Ferramentas de janelas: listar, ver a ativa, focar e fechar.

Títulos de janela vêm de programas externos (páginas web, documentos): sempre `untrusted=True`.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Config
from ..core.auditkey import digest
from ..win import windows as win
from .registry import Prepared, Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec
from ._matching import best_matches, clip

log = logging.getLogger(__name__)

_AUDIT_HEAD = 12          # caracteres de um título/nome que podem ir para a auditoria


def audit_label(args: dict[str, Any], field: str) -> dict[str, Any]:
    """Para a auditoria: primeiros 12 caracteres + tamanho + HMAC do texto (título de janela, nome de controle).

    Tolerante a argumento ausente ou de tipo errado (roda ANTES da validação). Nunca devolve o texto inteiro.
    """
    value = args.get(field)
    if not isinstance(value, str):
        return {field: None}
    return {field: " ".join(value.split())[:_AUDIT_HEAD], "tamanho": len(value), "digest": digest(value, 12)}

_MAX_LISTED = 25          # janelas devolvidas por listar_janelas
_MAX_OPTIONS = 6          # opções mostradas quando o título é ambíguo
_TITLE_CLIP = 70
_CLOSE_WAIT_S = 2.0       # quanto esperar a janela sumir depois do pedido de fechamento

_TITLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"titulo": {"type": "string", "minLength": 2, "maxLength": 100,
                              "description": "Parte do título da janela."}},
    "required": ["titulo"],
    "additionalProperties": False,
}


def _describe(info: win.WindowInfo) -> str:
    return f"{clip(info.title, _TITLE_CLIP)} ({info.process})" if info.process else clip(info.title, _TITLE_CLIP)


def _resolve(query: str) -> tuple[win.WindowInfo | None, ToolResult | None]:
    """Acha UMA janela pelo trecho do título; senão devolve o ToolResult explicando (nada, ou ambígua)."""
    matches = best_matches(query, win.list_windows(), key=lambda w: w.title)
    shown = query.strip()[:40]
    if not matches:
        return None, ToolResult(False, "Não achei nenhuma janela com esse trecho no título.")   # sem eco: a auditoria registra a mensagem
    if len(matches) > 1:
        options = [_describe(w) for w in matches[:_MAX_OPTIONS]]
        extra = f" e mais {len(matches) - _MAX_OPTIONS}" if len(matches) > _MAX_OPTIONS else ""
        return None, ToolResult(False, f"Mais de uma janela combina com '{shown}': "
                                       + "; ".join(options) + extra + ". Diga um trecho mais específico.",
                                data={"opcoes": options}, untrusted=True)
    return matches[0], None


def register(registry: ToolRegistry, cfg: Config) -> None:
    def listar_janelas(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        windows = win.list_windows()
        if not windows:
            return ToolResult(True, "Não há janelas abertas.", data={"janelas": []}, untrusted=True)
        items = [{"titulo": clip(w.title, _TITLE_CLIP), "processo": w.process} for w in windows[:_MAX_LISTED]]
        text = "; ".join(_describe(w) for w in windows[:_MAX_LISTED])
        more = f" (e mais {len(windows) - _MAX_LISTED})" if len(windows) > _MAX_LISTED else ""
        return ToolResult(True, f"{len(windows)} janelas abertas: {text}{more}.",
                          data={"janelas": items}, untrusted=True)

    def janela_ativa(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        info = win.foreground_window()
        if info is None:
            return ToolResult(True, "Nenhuma janela está em foco.", untrusted=True)
        return ToolResult(True, f"Janela ativa: {_describe(info)}.",
                          data={"titulo": clip(info.title, _TITLE_CLIP), "processo": info.process},
                          untrusted=True)

    def focar_janela(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        target, problem = _resolve(str(args["titulo"]))
        if problem is not None:
            return problem
        assert target is not None
        if win.is_own_process_window(target, ctx.cfg):
            log.warning("focar_janela recusado: janela do próprio Eco")
            return ToolResult(False, win.OWN_WINDOW_MESSAGE)
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        if win.focus_window(target.hwnd):
            return ToolResult(True, f"Trouxe para frente: {_describe(target)}.", untrusted=True)
        return ToolResult(False, "O Windows não deixou trazer essa janela para frente.", untrusted=True)

    def janela_acao(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("titulo", "") or "").strip()
        if query:
            target, problem = _resolve(query)
            if problem is not None:
                return problem
        else:
            target = win.foreground_window()
        if target is None:
            return ToolResult(False, "Não há janela em foco.")
        if win.is_own_process_window(target, ctx.cfg):
            return ToolResult(False, win.OWN_WINDOW_MESSAGE)
        action = str(args["acao"])
        left, top, right, bottom = win.work_area()
        width, height = right - left, bottom - top
        if action == "minimizar":
            ok = win.show_window(target.hwnd, win.SW_MINIMIZE)
        elif action == "maximizar":
            ok = win.show_window(target.hwnd, win.SW_MAXIMIZE)
        elif action == "restaurar":
            ok = win.show_window(target.hwnd, 9)
        elif action == "esquerda":
            ok = win.move_window(target.hwnd, left, top, width // 2, height)
        elif action == "direita":
            ok = win.move_window(target.hwnd, left + width // 2, top, width // 2, height)
        else:                                                    # centralizar
            w, h = int(width * 0.7), int(height * 0.7)
            ok = win.move_window(target.hwnd, left + (width - w) // 2, top + (height - h) // 2, w, h)
        if not ok:
            return ToolResult(False, "O Windows não deixou mexer nessa janela.", untrusted=True)
        return ToolResult(True, f"Fiz '{action}' na janela {_describe(target)}.", untrusted=True)

    def prepare_fechar(ctx: ToolContext, args: dict[str, Any]) -> Prepared | ToolResult:
        """Resolve UMA janela agora; ambígua ou inexistente nem chega à confirmação."""
        target, problem = _resolve(str(args["titulo"]))
        if problem is not None:
            return problem
        assert target is not None
        if win.is_own_process_window(target, ctx.cfg):
            log.warning("fechar_janela recusado: janela do próprio Eco")
            return ToolResult(False, win.OWN_WINDOW_MESSAGE)
        proc = target.process or "programa desconhecido"
        return Prepared(
            text=(f"Fechar a janela «{clip(target.title, _TITLE_CLIP)}» do {proc}? "
                  "Trabalho não salvo pode ser perdido."),
            state=target)

    def fechar_janela(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        target = ctx.prepared
        if not isinstance(target, win.WindowInfo):
            return ToolResult(False, "Não consegui confirmar qual janela fechar; não fechei nada.")
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        now = win.describe_window(target.hwnd)
        if now is None:
            return ToolResult(False, "Essa janela já não existe; não fechei nada.", untrusted=True)
        if now.title != target.title or now.pid != target.pid:
            log.warning("fechar_janela: a janela 0x%X mudou entre a confirmação e a execução", target.hwnd)
            return ToolResult(False, "A janela mudou depois da confirmação; não fechei nada.", untrusted=True)
        if win.is_own_process_window(now, ctx.cfg):
            return ToolResult(False, win.OWN_WINDOW_MESSAGE)
        if not win.close_window(target.hwnd):
            return ToolResult(False, "Não consegui pedir o fechamento dessa janela.", untrusted=True)
        # Espera a janela sumir; se ela pergunta "salvar?", continua aberta e avisamos.
        waited = 0.0
        while waited < _CLOSE_WAIT_S:
            if not win.is_window(target.hwnd):
                return ToolResult(True, f"Fechei: {_describe(target)}.", untrusted=True)
            if ctx.cancel.wait(0.1):
                return ToolResult(False, "Cancelado. O pedido de fechamento já foi enviado.", effect_unknown=True)
            waited += 0.1
        return ToolResult(True, f"Pedi para fechar {_describe(target)}, mas ela ainda está aberta; "
                                "talvez esteja perguntando se deve salvar.", untrusted=True)

    registry.register(ToolSpec(
        name="listar_janelas",
        description="Lista as janelas abertas no computador (título e programa). Use para saber o que está aberto.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        risk=Risk.READ,
        handler=listar_janelas,
    ))
    registry.register(ToolSpec(
        name="janela_acao",
        description=("Controla uma janela aberta: minimizar, maximizar, restaurar, colocar na metade esquerda ou direita da tela "
                     "ou centralizar. Sem 'titulo' age na janela em foco."),
        parameters={"type": "object", "properties": {
            "acao": {"type": "string", "enum": ["minimizar", "maximizar", "restaurar", "esquerda", "direita", "centralizar"]},
            "titulo": {"type": "string", "maxLength": 80, "description": "Opcional: parte do título da janela."}},
            "required": ["acao"], "additionalProperties": False},
        risk=Risk.CONTROL,
        handler=janela_acao,
        audit_args=lambda a: {"acao": a.get("acao")},
    ))
    registry.register(ToolSpec(
        name="janela_ativa",
        description="Diz qual janela está em primeiro plano agora (a que o usuário está vendo).",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        risk=Risk.READ,
        handler=janela_ativa,
    ))
    registry.register(ToolSpec(
        name="focar_janela",
        description=("Traz uma janela já aberta para frente, pelo título ou parte dele "
                     "(ex.: 'bloco de notas', 'chrome'). Se várias combinarem, devolve as opções."),
        parameters=_TITLE_SCHEMA,
        risk=Risk.CONTROL,
        handler=focar_janela,
        confirm_text=lambda a: f"Trazer para frente a janela '{str(a.get('titulo', ''))[:60]}'",
        audit_args=lambda a: audit_label(a, "titulo"),
    ))
    registry.register(ToolSpec(
        name="fechar_janela",
        description=("Fecha uma janela aberta pelo título ou parte dele. Pode perder trabalho não salvo, "
                     "por isso pede confirmação."),
        parameters=_TITLE_SCHEMA,
        risk=Risk.RISKY,
        handler=fechar_janela,
        prepare=prepare_fechar,
        audit_args=lambda a: audit_label(a, "titulo"),
    ))
