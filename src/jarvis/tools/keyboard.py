"""Ferramentas de teclado: digitar texto e apertar atalhos da allowlist.

Digitar/atalhar na janela errada equivale a executar comandos (terminal, Executar, Explorer). Por isso:
- `prepare` resolve a janela em foco AGORA e recusa programas bloqueados ou fora da lista permitida;
- o handler reconfere que o foco continua no mesmo `hwnd` antes de começar e a cada bloco de 16 caracteres;
- a confirmação Sim/Não é feita pelo registro (via `confirm_if`), mostrando programa, título e prévia do texto.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any, Final

from ..config import HARD_DENIED_TYPING, Config
from ..win import input as win_input
from ..win import windows as win
from ..win.keys import Combo, KeyError_, parse_combo
from ._matching import clip
from .registry import Prepared, Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec

log = logging.getLogger(__name__)

_PREVIEW_CHARS: Final = 24
_TITLE_CLIP: Final = 50
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
    return _Target(info.hwnd, info.pid, info.process.lower(), info.title)


def _still_focused(target: _Target) -> bool:
    """True se a janela em foco continua sendo exatamente a preparada (mesmo hwnd e mesmo processo)."""
    hwnd = win.foreground_hwnd()
    return hwnd == target.hwnd and win.pid_of(hwnd) == target.pid


def _looks_risky_text(text: str) -> bool:
    return win_input.has_control_chars(text) or bool(_COMMANDISH.search(text))


def _text_fingerprint(text: str) -> dict[str, Any]:
    return {"chars": len(text), "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]}


def register(registry: ToolRegistry, cfg: Config) -> None:
    max_chars = max(1, cfg.safety.max_typed_chars)
    typing_confirm = cfg.safety.typing_confirm
    allowed_procs = _lower_set(cfg.safety.typing_allowed_processes)
    denied_procs = HARD_DENIED_TYPING | _lower_set(cfg.safety.typing_denied_extra)
    allowed = _norm_combos(cfg.apps.hotkeys, "apps.hotkeys")
    confirm_combos = _norm_combos(cfg.apps.hotkeys_confirm, "apps.hotkeys_confirm")
    reserved = _norm_combos((cfg.safety.emergency_hotkey, cfg.safety.mute_hotkey, cfg.safety.confirm_yes_hotkey,
                             cfg.safety.confirm_no_hotkey, cfg.safety.talk_key), "safety")

    # ------------------------------------------------------------- digitar_texto
    def prepare_digitar(ctx: ToolContext, args: dict[str, Any]) -> Prepared | ToolResult:
        text = str(args["texto"])
        if not text.strip():
            return ToolResult(False, "Não há texto para digitar.")
        if len(text) > max_chars:
            return ToolResult(False, f"O texto passa do limite de {max_chars} caracteres.")
        if win_input.has_control_chars(text):
            return ToolResult(False, "Só digito uma linha de texto; Enter e quebras de linha são outra ferramenta.")
        target = _focused_target()
        if isinstance(target, ToolResult):
            return target
        allowed_txt = ", ".join(sorted(allowed_procs)) or "nenhum programa"
        if target.process in denied_procs:
            log.warning("digitar_texto recusado: programa bloqueado %s", target.process)
            return ToolResult(False, f"Não digito em {target.process} por segurança. Só em: {allowed_txt}.")
        if target.process not in allowed_procs:
            log.info("digitar_texto recusado: %s fora da lista permitida", target.process)
            return ToolResult(False, f"A janela em foco é {target.process}, e só digito em: {allowed_txt}.")
        preview = text[:_PREVIEW_CHARS] + ("…" if len(text) > _PREVIEW_CHARS else "")
        return Prepared(
            text=(f"Digitar {len(text)} caracteres em {target.process} ({clip(target.title, _TITLE_CLIP)}): "
                  f"«{preview}»"),
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
        return Prepared(text=f"Apertar {combo.norm} em {target.process} ({clip(target.title, _TITLE_CLIP)})",
                        state=(target, combo))

    def confirm_atalho(args: dict[str, Any], tainted: bool) -> bool:
        try:
            return parse_combo(str(args.get("atalho", ""))).norm in confirm_combos
        except KeyError_:
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
                                     "description": "Texto de uma linha a digitar."}},
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
                                      "description": "Atalho no formato ctrl+c, alt+tab, enter."}},
            "required": ["atalho"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=apertar_atalho,
        prepare=prepare_atalho,
        confirm_if=confirm_atalho,
    ))
