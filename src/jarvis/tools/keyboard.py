"""Ferramentas de teclado: digitar texto e apertar atalhos da allowlist.

Digitar/atalhar na janela errada equivale a executar comandos (terminal, Executar, Explorer). Por isso:
- `prepare` resolve a janela em foco AGORA e recusa programas bloqueados ou fora da lista permitida;
- o handler reconfere que o foco continua no mesmo `hwnd` antes de começar e a cada bloco de 16 caracteres;
- a confirmação Sim/Não é feita pelo registro (via `confirm_if`), mostrando programa, título e prévia do texto.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Final

from ..config import HARD_DENIED_TYPING, Config
from ..core.auditkey import digest
from ..win import input as win_input
from ..win import windows as win
from ..win.keys import Combo, KeyError_, parse_combo
from ..core.textutil import fold
from ._matching import clip
from .registry import Prepared, Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec

log = logging.getLogger(__name__)

_PREVIEW_FULL: Final = 80           # até aqui o texto é mostrado inteiro na confirmação
_PREVIEW_HEAD: Final = 40
_PREVIEW_TAIL: Final = 20
_TITLE_CLIP: Final = 50
_UNSAFE_TEXT_MESSAGE: Final = {
    "linha": "Só digito uma linha de texto; Enter e quebras de linha são outra ferramenta.",
    "invisivel": "O texto tem caracteres invisíveis ou de direção (como U+202E); não digito para você não ser enganado.",
}
# Em programa bloqueado (terminal, Explorer, Executar...) só estes atalhos, e só se estiverem em apps.hotkeys.
_SAFE_IN_DENIED: Final = frozenset({"alt+tab", "win+d", "win+e", "esc", "f5"})
# Texto que lembra comando de shell/script: pede confirmação mesmo no modo "untrusted_or_multiline".
_COMMANDISH: Final = re.compile(
    r"&&|\|\||[|;`<>^]|\$\(|%\w+%|\.\./|[a-z]:\\|\\\\|^\s*(sudo|cmd|powershell|pwsh|curl|wget|rm|del|start|reg|net|sc|iex|irm)\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class _Target:
    """Janela em foco no momento do `prepare`."""
    hwnd: int
    pid: int
    process: str
    title: str
    dialog: bool = False         # a janela parece um diálogo (Salvar como, Abrir, Imprimir...)


def _lower_set(values: tuple[str, ...]) -> frozenset[str]:
    return frozenset(v.strip().lower() for v in values if v.strip())


def _norm_combos(values: tuple[str, ...], where: str) -> frozenset[str]:
    """Formas normalizadas dos atalhos de uma lista da configuração (inválidos são ignorados com aviso)."""
    out: set[str] = set()
    for raw in values:
        try:
            out.add(parse_combo(raw).norm)
        except KeyError_ as exc:
            log.warning("%s: atalho inválido ignorado (%s)", where, exc)
    return frozenset(out)


def _focused_target() -> _Target | ToolResult:
    """Janela em foco agora, ou um ToolResult de falha se não dá para identificá-la."""
    info = win.foreground_window()
    if info is None:
        return ToolResult(False, "Nenhuma janela identificável está em foco.")
    if not info.process:
        return ToolResult(False, "Não consegui identificar o programa da janela em foco; por segurança não faço nada.")
    return _Target(info.hwnd, info.pid, info.process.lower(), info.title, win.is_dialog_window(info))


def _still_focused(target: _Target) -> bool:
    """True se a janela em foco continua sendo exatamente a preparada (mesmo hwnd e mesmo processo)."""
    hwnd = win.foreground_hwnd()
    return hwnd == target.hwnd and win.pid_of(hwnd) == target.pid


def _looks_risky_text(text: str) -> bool:
    return win_input.has_control_chars(text) or bool(_COMMANDISH.search(text))


def _text_fingerprint(text: str) -> dict[str, Any]:
    """Só tamanho + HMAC com chave local (nunca o texto, nem hash puro que se quebra por força bruta)."""
    return {"chars": len(text), "digest": digest(text, 16)}


def _typed_preview(text: str) -> str:
    """Texto inteiro até 80 caracteres; acima disso início (40) + '[N caracteres ocultos]' + fim (20)."""
    if len(text) <= _PREVIEW_FULL:
        return text
    hidden = len(text) - _PREVIEW_HEAD - _PREVIEW_TAIL
    return f"{text[:_PREVIEW_HEAD]}…[{hidden} caracteres ocultos]…{text[-_PREVIEW_TAIL:]}"


def register(registry: ToolRegistry, cfg: Config) -> None:
    max_chars = max(1, cfg.safety.max_typed_chars)
    typing_confirm = cfg.safety.typing_confirm
    allowed_procs = _lower_set(cfg.safety.typing_allowed_processes)
    allowed_titles = tuple(fold(t) for t in cfg.safety.typing_allowed_titles if t.strip())

    def _focus_requested(args: dict[str, Any]) -> ToolResult | None:
        """Parâmetro opcional `janela`: traz essa janela para frente ANTES de preparar (app recém-aberto não vem sozinho)."""
        query = str(args.get("janela", "") or "").strip()
        if not query:
            return None
        from .windows_tools import _resolve
        info, problem = _resolve(query)
        if problem is not None:
            return problem
        assert info is not None
        if win.is_own_process_window(info, cfg):
            return ToolResult(False, win.OWN_WINDOW_MESSAGE)
        if not win.focus_window(info.hwnd):
            return ToolResult(False, "O Windows não deixou trazer essa janela para frente; clique nela e peça de novo.")
        time.sleep(0.25)
        return None
    denied_procs = HARD_DENIED_TYPING | _lower_set(cfg.safety.typing_denied_extra)
    allowed = _norm_combos(cfg.apps.hotkeys, "apps.hotkeys")
    confirm_combos = _norm_combos(cfg.apps.hotkeys_confirm, "apps.hotkeys_confirm")
    reserved = _norm_combos((cfg.safety.emergency_hotkey, cfg.safety.mute_hotkey, cfg.safety.confirm_yes_hotkey,
                             cfg.safety.confirm_no_hotkey, cfg.safety.talk_key, cfg.safety.open_listen_hotkey or cfg.safety.talk_key,
                             *((cfg.safety.yolo_hotkey,) if cfg.safety.yolo_hotkey.strip() else ())), "safety")

    # ------------------------------------------------------------- digitar_texto
    def prepare_digitar(ctx: ToolContext, args: dict[str, Any]) -> Prepared | ToolResult:
        failed = _focus_requested(args)
        if failed is not None:
            return failed
        text = str(args["texto"])
        if not text.strip():
            return ToolResult(False, "Não há texto para digitar.")
        if len(text) > max_chars:
            return ToolResult(False, f"O texto passa do limite de {max_chars} caracteres.")
        bad = win_input.unsafe_char_kind(text)
        if bad is not None:
            return ToolResult(False, _UNSAFE_TEXT_MESSAGE[bad])
        target = _focused_target()
        if isinstance(target, ToolResult):
            return target
        allowed_txt = ", ".join(sorted(allowed_procs)) or "nenhum programa"
        if target.process in denied_procs:
            log.warning("digitar_texto recusado: programa bloqueado %s", target.process)
            return ToolResult(False, f"Não digito em {target.process} por segurança. Só em: {allowed_txt}.")
        uwp_ok = target.process == "applicationframehost.exe" and any(t in fold(target.title) for t in allowed_titles)
        if target.process not in allowed_procs and not uwp_ok:
            log.info("digitar_texto recusado: %s fora da lista permitida", target.process)
            return ToolResult(False, f"A janela em foco é {target.process}, e só digito em: {allowed_txt}.")
        if target.dialog:
            log.warning("digitar_texto recusado: %s está num diálogo (%r)", target.process, target.title[:40])
            return ToolResult(False, "A janela em foco é um diálogo (Salvar como, Abrir, Imprimir...); "
                                     "não digito ali por segurança. Faça isso você mesmo.")
        return Prepared(
            text=(f"Digitar {len(text)} caracteres em {target.process} ({clip(target.title, _TITLE_CLIP)}): "
                  f"«{_typed_preview(text)}»"),
            state=target)

    def confirm_digitar(args: dict[str, Any], tainted: bool) -> bool:
        if typing_confirm == "always" or tainted:
            return True
        return _looks_risky_text(str(args.get("texto", "")))

    def digitar_texto(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        text = str(args["texto"])
        target = ctx.prepared
        if not isinstance(target, _Target):
            return ToolResult(False, "Não consegui confirmar a janela de destino; não digitei nada.")
        if not text.strip() or len(text) > max_chars or win_input.has_control_chars(text):
            return ToolResult(False, "O texto não é válido para digitar.")
        if target.dialog or win.is_dialog_window(target.hwnd):
            return ToolResult(False, "A janela em foco virou um diálogo; não digitei nada.")
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        if not _still_focused(target):
            return ToolResult(False, f"A janela em foco mudou; não digitei nada. Era {target.process}.")
        typed = 0
        try:
            typed = win_input.send_text(text, ctx.cancel, guard=lambda: _still_focused(target))
        except win_input.InputBlockedError as exc:
            return ToolResult(False, str(exc), effect_unknown=True)
        except ValueError:
            return ToolResult(False, "O texto não é válido para digitar.")
        finally:
            win_input.release_all()                  # nada fica pressionado, mesmo em erro ou cancelamento
        if ctx.cancel.cancelled and typed < len(text):
            return ToolResult(False, f"Interrompido; digitei {typed} caracteres.", effect_unknown=True)
        log.info("digitar_texto: %d caracteres em %s", typed, target.process)
        return ToolResult(True, f"Digitei {typed} caracteres.")

    # ------------------------------------------------------------- apertar_atalho
    def prepare_atalho(ctx: ToolContext, args: dict[str, Any]) -> Prepared | ToolResult:
        failed = _focus_requested(args)
        if failed is not None:
            return failed
        raw = str(args["atalho"])
        try:
            combo = parse_combo(raw)
        except KeyError_:
            return ToolResult(False, f"'{raw.strip()[:30]}' não é um atalho válido. Exemplo: ctrl+c.")
        if combo.norm in reserved:
            log.warning("apertar_atalho recusado: %s é tecla de segurança do Jarvis", combo.norm)
            return ToolResult(False, f"O atalho {combo.norm} é uma tecla de segurança do Jarvis; não posso apertá-lo.")
        if combo.norm not in allowed:
            return ToolResult(False, f"O atalho {combo.norm} não está liberado. "
                                     f"Liberados: {', '.join(sorted(allowed))}.")
        target = _focused_target()
        if isinstance(target, ToolResult):
            return target
        if target.process in denied_procs and combo.norm not in _SAFE_IN_DENIED:
            return ToolResult(False, f"A janela em foco é {target.process}; ali só aperto: "
                                     f"{', '.join(sorted(_SAFE_IN_DENIED))}.")
        where = f"{target.process} ({clip(target.title, _TITLE_CLIP)})"
        if combo.norm == "enter" and target.dialog:
            return Prepared(text=(f"ATENÇÃO: apertar enter num DIÁLOGO de {where}. Isso pode salvar, abrir, "
                                  "imprimir ou aprovar algo. Confirma?"),
                            state=(target, combo))
        return Prepared(text=f"Apertar {combo.norm} em {where}", state=(target, combo))

    def confirm_atalho(args: dict[str, Any], tainted: bool) -> bool:
        try:
            norm = parse_combo(str(args.get("atalho", ""))).norm
        except KeyError_:
            return False
        if norm in confirm_combos:
            return True
        if norm == "enter":                                 # enter em diálogo: confirmação forte
            info = win.foreground_window()
            return info is None or win.is_dialog_window(info)
        return False

    def apertar_atalho(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        state = ctx.prepared
        if not (isinstance(state, tuple) and len(state) == 2 and isinstance(state[0], _Target)
                and isinstance(state[1], Combo)):
            return ToolResult(False, "Não consegui confirmar a janela de destino; não apertei nada.")
        target, combo = state
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        if not _still_focused(target):
            return ToolResult(False, f"A janela em foco mudou; não apertei nada. Era {target.process}.")
        try:
            win_input.send_combo(combo)
        except win_input.InputBlockedError as exc:
            return ToolResult(False, str(exc), effect_unknown=True)
        return ToolResult(True, f"Apertei {combo.norm}.")

    registry.register(ToolSpec(
        name="digitar_texto",
        description=("Digita UMA linha de texto no campo da janela em foco, como se fosse o teclado "
                     f"(até {max_chars} caracteres; sem quebra de linha). Só funciona em: "
                     f"{', '.join(sorted(allowed_procs)) or 'nenhum programa'}. Antes, use focar_janela."),
        parameters={
            "type": "object",
            "properties": {"texto": {"type": "string", "minLength": 1, "maxLength": max_chars,
                                     "description": "Texto de uma linha a digitar. Na Calculadora, digite a conta ('12+7=')."},
                           "janela": {"type": "string", "maxLength": 80,
                                      "description": "Opcional: título (ou parte) da janela onde digitar; o Jarvis a traz para frente antes."}},
            "required": ["texto"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=digitar_texto,
        redact=frozenset({"texto"}),
        prepare=prepare_digitar,
        confirm_if=confirm_digitar,
        audit_args=lambda a: _text_fingerprint(str(a.get("texto", ""))),
    ))
    registry.register(ToolSpec(
        name="apertar_atalho",
        description=("Aperta um atalho de teclado na janela em foco, como 'ctrl+c' ou 'esc'. "
                     "Só estes são aceitos: " + ", ".join(sorted(allowed)) + ". Alguns pedem confirmação."),
        parameters={
            "type": "object",
            "properties": {"atalho": {"type": "string", "minLength": 1, "maxLength": 40,
                                      "description": "Atalho no formato ctrl+c, alt+tab, enter."},
                           "janela": {"type": "string", "maxLength": 80,
                                      "description": "Opcional: título (ou parte) da janela onde apertar; o Jarvis a traz para frente antes."}},
            "required": ["atalho"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=apertar_atalho,
        prepare=prepare_atalho,
        confirm_if=confirm_atalho,
    ))
