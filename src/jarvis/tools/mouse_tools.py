"""Mouse por posição: `clicar_na_tela` e `rolar_tela`, sobre o que o modelo VIU em `ver_tela`.

Coordenadas relativas 0..1000 (o sistema nativo do Qwen-VL): independem da resolução e do reescalonamento da imagem.
Guardas: exige uma `ver_tela` recente; recusa janelas do próprio Eco, janelas de segurança/senha, diálogos e botões que
aprovam algo (Salvar, OK, Executar...): para esses o caminho é `clicar_controle`, que pede confirmação. Confere de novo a
janela sob o ponto imediatamente antes de clicar.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable

import uiautomation as auto

from ..config import Config
from ..win import input as win_input
from ..win import windows as win
from . import screen
from .registry import Prepared, Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec
from .uia import needs_strong_confirm

log = logging.getLogger(__name__)

_NEVER_CLICK = frozenset({"consent.exe", "logonui.exe", "credentialuibroker.exe", "keepass.exe", "keepassxc.exe", "1password.exe",
                          "bitwarden.exe", "lastpass.exe", "securityhealthsystray.exe", "windowsdefender.exe"})
_COORD = {"type": "integer", "minimum": 0, "maximum": 1000}
_NEED_SHOT = "Primeiro use ver_tela para eu enxergar a tela; depois indico a posição."


def _to_pixels(x: int, y: int) -> tuple[int, int] | None:
    geom = screen.last_capture()
    if geom is None:
        return None
    left, top, w, h = geom
    return left + min(w - 1, round(x / 1000 * w)), top + min(h - 1, round(y / 1000 * h))


def _control_name_at(px: int, py: int) -> str:
    try:
        with auto.UIAutomationInitializerInThread():
            ctl = auto.ControlFromPoint(px, py)
            return (ctl.Name or "").strip() if ctl is not None else ""
    except Exception:  # noqa: BLE001 - sem o nome, segue só com a janela
        log.debug("não consegui ler o controle sob o ponto", exc_info=True)
        return ""


# --- localização visual: o PRÓPRIO modelo de visão acha o alvo na imagem (ligado em app.py via set_grounder)
_ground: Callable[[bytes, str], str] | None = None
_FULL_SIDE = 1024                                       # 768 foi testado: mais rápido (5 s) mas só 3 de 5 acertos; 1024 mantém a precisão
_AGREE_PX = 70                                          # as duas leituras (janela e tela inteira) precisam cair a esta distância


def set_grounder(llm: Any) -> None:
    """Liga a localização visual ao cliente do modelo (uma chamada sem ferramentas, temperatura 0, resposta curta)."""
    from ..core.cancel import CancelToken
    from ..llm.client import image_content

    def ground(jpeg: bytes, prompt: str) -> str:
        reply = llm.chat([{"role": "user", "content": image_content(prompt, jpeg, "image/jpeg")}], CancelToken(),
                         max_tokens=40, temperature=0.0)
        return reply.content

    global _ground
    _ground = ground


def _parse_point(text: str) -> tuple[int, int] | None:
    """Aceita {"x": 12, "y": 34} e também a variante torta {"x": 12, 34} que o modelo às vezes devolve."""
    m = re.search(r'"x"\s*:\s*(-?\d+)[^0-9\-]+?(?:"y"\s*:\s*)?(-?\d+)', text, re.S)
    if not m:
        return None
    x, y = int(m[1]), int(m[2])
    return (x, y) if 0 <= x <= 1000 and 0 <= y <= 1000 else None


def _locate(description: str, target_hwnd: int = 0) -> tuple[tuple[int, int] | None, str]:
    """Acha `description` na tela: lê a janela em foco (recorte, mais nítido) e a tela inteira; só aceita se concordam."""
    from PIL import Image  # noqa: F401  (tipos)
    assert _ground is not None
    prompt = (f"Esta é uma captura de tela. Encontre: {description}. Responda SOMENTE um JSON "
              '{"x": N, "y": N} com o centro desse elemento, em coordenadas relativas de 0 a 1000 '
              "(0,0 = canto superior esquerdo). Se ele não estiver visível, responda {\"x\": -1, \"y\": -1}.")
    img = screen._capture_primary()
    geom = screen.last_capture()
    if geom is None:
        return None, "Não consegui capturar a tela."
    left, top, width, height = geom
    max_side = max(64, cfg_vision_side())
    full_jpeg, _ = screen._encode(img.copy(), min(max_side, _FULL_SIDE), 80)
    points: list[tuple[float, float]] = []
    rect = win.window_rect(target_hwnd) if target_hwnd else None
    if rect is not None:
        x0, y0 = max(left, rect[0]), max(top, rect[1])
        x1, y1 = min(left + width, rect[2]), min(top + height, rect[3])
        if x1 - x0 >= 120 and y1 - y0 >= 120 and (x1 - x0) * (y1 - y0) < 0.85 * width * height:
            crop = img.crop((x0 - left, y0 - top, x1 - left, y1 - top))
            jpeg, _ = screen._encode(crop, max_side, 80)
            p = _parse_point(_ground(jpeg, prompt))
            if p:
                points.append((x0 + p[0] / 1000 * (x1 - x0), y0 + p[1] / 1000 * (y1 - y0)))
    p = _parse_point(_ground(full_jpeg, prompt))
    if p:
        points.append((left + p[0] / 1000 * width, top + p[1] / 1000 * height))
    img.close()
    if not points:
        return None, f"Não encontrei «{description[:40]}» na tela."
    if len(points) == 2:
        (ax, ay), (bx, by) = points
        if ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 > _AGREE_PX:
            return None, f"Não tenho certeza de onde está «{description[:40]}»; não cliquei. Descreva melhor ou diga a posição."
        return (round(ax), round(ay)), ""                        # recorte da janela: mais nítido
    return (round(points[0][0]), round(points[0][1])), ""


def cfg_vision_side() -> int:
    return _vision_side


_vision_side = 1024
_click_impl: Callable[[ToolContext, dict[str, Any]], ToolResult] | None = None


def click_by_description(ctx: ToolContext, description: str, hwnd: int = 0) -> ToolResult:
    """Clica no que `description` descreve, localizando na tela com o modelo de visão (reserva de clicar_controle)."""
    if _click_impl is None:
        return ToolResult(False, "A visão ainda não está pronta.")
    return _click_impl(ctx, {"descricao": description, "_hwnd": hwnd})


def register(registry: ToolRegistry, cfg: Config) -> None:
    global _vision_side
    _vision_side = cfg.vision.max_side_px

    def clicar_em(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if _ground is None:
            return ToolResult(False, "A visão ainda não está pronta.")
        desc = str(args["descricao"]).strip()
        if not desc:
            return ToolResult(False, "Diga o que clicar.")
        fg = win.foreground_window()
        want_hwnd = int(args.get("_hwnd") or (fg.hwnd if fg is not None else 0))
        if not want_hwnd or win.foreground_hwnd() != want_hwnd:
            return ToolResult(False, "A janela em foco mudou; não cliquei.")
        where = f" (na janela «{fg.title[:40]}»)" if fg is not None and fg.title else ""
        point, why = _locate(f"o botão ou controle «{desc}»{where}" if len(desc) <= 12 else f"{desc}{where}", want_hwnd)
        if point is not None and win.foreground_hwnd() != want_hwnd:
            return ToolResult(False, "A janela em foco mudou durante a busca; não cliquei.")
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        if point is None:
            return ToolResult(False, why)
        px, py = point
        info = win.window_at(px, py)
        if info is None:
            return ToolResult(False, "Não há janela no ponto achado; não cliquei.")
        if info.hwnd != want_hwnd:
            return ToolResult(False, "O ponto achado está fora da janela em foco (outra janela por cima ou mudou); não cliquei.")
        if win.is_own_process_window(info, cfg):
            return ToolResult(False, "O ponto achado é uma janela do próprio Eco; não cliquei.")
        if (info.process or "").lower() in _NEVER_CLICK:
            return ToolResult(False, f"O ponto achado é {info.process}, uma janela de segurança ou de senhas; não clico ali.")
        if win.is_dialog_window(info):
            return ToolResult(False, "O ponto achado está num diálogo (Salvar, Abrir, Permitir...); use clicar_controle com o nome do botão.")
        name = _control_name_at(px, py)
        if name and needs_strong_confirm(name):
            return ToolResult(False, f"O controle achado é «{name[:40]}», que aprova ou confirma algo; use clicar_controle com esse nome.")
        button = "right" if args.get("botao") == "direito" else "left"
        try:
            win_input.click(px, py, button)
            if args.get("duplo"):
                time.sleep(0.08)
                win_input.click(px, py, button)
        except win_input.InputBlockedError as exc:
            return ToolResult(False, str(exc), effect_unknown=True)
        except ValueError as exc:
            return ToolResult(False, f"Ponto inválido: {exc}")
        log.info("clicar_em %r: (%d,%d) em %s controle=%r", desc[:40], px, py, info.process, name[:30])
        return ToolResult(True, f"Cliquei em {desc[:40]}" + (f" (controle «{name[:40]}»)" if name else "") + ". Use ver_tela para conferir.")

    def _find(ctx: ToolContext, desc: str, want_hwnd: int) -> tuple[tuple[int, int] | None, str, Any]:
        """Localiza `desc` na janela em foco e valida o ponto (mesmas travas do clique). (ponto, motivo da recusa, janela)."""
        point, why = _locate(desc, want_hwnd)
        if point is None:
            return None, why, None
        if win.foreground_hwnd() != want_hwnd:
            return None, "A janela em foco mudou durante a busca; não mexi.", None
        info = win.window_at(*point)
        if info is None or info.hwnd != want_hwnd:
            return None, "O ponto achado está fora da janela em foco; não mexi.", None
        if win.is_own_process_window(info, cfg):
            return None, "O ponto achado é uma janela do próprio Eco; não mexi.", None
        if (info.process or "").lower() in _NEVER_CLICK:
            return None, f"O ponto achado é {info.process}, uma janela de segurança ou de senhas; não mexo ali.", None
        if win.is_dialog_window(info):
            return None, "O ponto achado está num diálogo (Salvar, Abrir, Permitir...); não mexo por posição.", None
        return point, "", info

    def _focused(ctx: ToolContext) -> tuple[int, str] | ToolResult:
        if _ground is None:
            return ToolResult(False, "A visão ainda não está pronta.")
        fg = win.foreground_window()
        if fg is None:
            return ToolResult(False, "Nenhuma janela em foco.")
        return fg.hwnd, (f" (na janela «{fg.title[:40]}»)" if fg.title else "")

    def localizar_na_tela(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        got = _focused(ctx)
        if isinstance(got, ToolResult):
            return got
        hwnd, where = got
        desc = str(args["descricao"]).strip()
        point, why, info = _find(ctx, f"{desc}{where}", hwnd)
        if point is None:
            return ToolResult(False, why)
        name = _control_name_at(*point)
        left, top, w, h = screen.last_capture() or (0, 0, 1, 1)
        rel = (round((point[0] - left) / max(1, w) * 1000), round((point[1] - top) / max(1, h) * 1000))
        return ToolResult(True, f"Achei «{desc[:40]}» na janela {info.process}" + (f" (controle «{name[:40]}»)" if name else "")
                          + f", na posição x={rel[0]}, y={rel[1]} (0 a 1000).", data={"x": rel[0], "y": rel[1], "controle": name}, untrusted=True)

    def mover_mouse(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        got = _focused(ctx)
        if isinstance(got, ToolResult):
            return got
        hwnd, where = got
        desc = str(args["alvo"]).strip()
        point, why, info = _find(ctx, f"{desc}{where}", hwnd)
        if point is None:
            return ToolResult(False, why)
        try:
            win_input.move_to(*point)
        except (win_input.InputBlockedError, ValueError) as exc:
            return ToolResult(False, f"Não consegui mover o mouse: {exc}")
        return ToolResult(True, f"Mouse sobre «{desc[:40]}» (sem clicar). Use ver_tela para ver o que apareceu (dica, menu).")

    def arrastar(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        got = _focused(ctx)
        if isinstance(got, ToolResult):
            return got
        hwnd, where = got
        a = str(args["origem"]).strip()
        b = str(args["destino"]).strip()
        p1, why, _ = _find(ctx, f"{a}{where}", hwnd)
        if p1 is None:
            return ToolResult(False, f"Origem: {why}")
        p2, why, _ = _find(ctx, f"{b}{where}", hwnd)
        if p2 is None:
            return ToolResult(False, f"Destino: {why}")
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        try:
            win_input.drag(p1[0], p1[1], p2[0], p2[1])
        except win_input.InputBlockedError as exc:
            return ToolResult(False, str(exc), effect_unknown=True)
        except ValueError as exc:
            return ToolResult(False, f"Ponto inválido: {exc}")
        log.info("arrastar %r -> %r: (%d,%d) -> (%d,%d)", a[:30], b[:30], *p1, *p2)
        return ToolResult(True, f"Arrastei «{a[:30]}» até «{b[:30]}». Use ver_tela para conferir.")

    def prepare_clique(ctx: ToolContext, args: dict[str, Any]) -> Prepared | ToolResult:
        pt = _to_pixels(int(args["x"]), int(args["y"]))
        if pt is None:
            return ToolResult(False, _NEED_SHOT)
        info = win.window_at(*pt)
        if info is None:
            return ToolResult(False, "Não há janela nesse ponto (área de trabalho ou janela sem título); não cliquei.")
        if win.is_own_process_window(info, cfg):
            return ToolResult(False, "Esse ponto é uma janela do próprio Eco; não cliquei.")
        if (info.process or "").lower() in _NEVER_CLICK:
            return ToolResult(False, f"Esse ponto é {info.process}, uma janela de segurança ou de senhas; não clico ali.")
        if win.is_dialog_window(info):
            return ToolResult(False, "Esse ponto está num diálogo (Salvar, Abrir, Permitir...); não clico por posição. "
                                     "Use clicar_controle com o nome do botão.")
        name = _control_name_at(*pt)
        if name and needs_strong_confirm(name):
            return ToolResult(False, f"O controle nesse ponto é «{name[:40]}», que aprova ou confirma algo; "
                                     "use clicar_controle com esse nome, que pede confirmação.")
        who = f"{info.process or 'janela'} ({info.title[:40]})" + (f", controle «{name[:40]}»" if name else "")
        return Prepared(text=f"Clicar com o mouse em {who}", state=(pt, info.hwnd, name))

    def clicar_na_tela(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        prepared = ctx.prepared
        if not (isinstance(prepared, tuple) and len(prepared) == 3):
            return ToolResult(False, "Não consegui preparar o clique; não cliquei.")
        (px, py), hwnd, name = prepared
        button = "right" if args.get("botao") == "direito" else "left"
        now = win.window_at(px, py)
        if now is None or now.hwnd != hwnd:
            return ToolResult(False, "A janela sob esse ponto mudou; não cliquei. Use ver_tela de novo.")
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        try:
            win_input.click(px, py, button)
            if args.get("duplo"):
                time.sleep(0.08)
                win_input.click(px, py, button)
        except win_input.InputBlockedError as exc:
            return ToolResult(False, str(exc), effect_unknown=True)
        except ValueError as exc:
            return ToolResult(False, f"Ponto inválido: {exc}")
        log.info("clicar_na_tela: (%d,%d) em %s", px, py, now.process)
        what = f" em «{name[:40]}»" if name else ""
        return ToolResult(True, f"Cliquei{what} na janela {now.process or ''}. Use ver_tela para conferir o resultado.")

    def prepare_rolagem(ctx: ToolContext, args: dict[str, Any]) -> Prepared | ToolResult:
        at = None
        if "x" in args and "y" in args:
            at = _to_pixels(int(args["x"]), int(args["y"]))
            if at is None:
                return ToolResult(False, _NEED_SHOT)
        info = win.window_at(*at) if at is not None else win.foreground_window()
        if info is not None and win.is_own_process_window(info, cfg):
            return ToolResult(False, "Essa é uma janela do próprio Eco; não rolei.")
        where = f"{info.process} ({info.title[:40]})" if info is not None else "a janela em foco"
        return Prepared(text=f"Rolar {args['direcao']} em {where}", state=at)

    def rolar_tela(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        n = max(1, min(10, int(args.get("quantidade", 3))))
        direction = str(args["direcao"])
        notches = {"cima": n, "baixo": -n, "direita": n, "esquerda": -n}[direction]
        try:
            win_input.scroll(notches, horizontal=direction in ("direita", "esquerda"), at=ctx.prepared)
        except (win_input.InputBlockedError, ValueError) as exc:
            return ToolResult(False, f"Não consegui rolar: {exc}")
        return ToolResult(True, f"Rolei {direction} {n} vezes. Use ver_tela para ver o resultado.")

    global _click_impl
    _click_impl = clicar_em
    registry.register(ToolSpec(
        name="clicar_em",
        description=("Clica com o MOUSE em algo que você descreve em palavras ('o botão 7 da calculadora', 'o ícone de salvar', "
                     "'o link Entrar'). O Eco olha a tela, acha o alvo sozinho e clica. Use quando clicar_controle não achar "
                     "o controle ou quando só dá para ver na tela. Prefira esta a clicar_na_tela."),
        parameters={"type": "object", "properties": {
            "descricao": {"type": "string", "minLength": 2, "maxLength": 120,
                          "description": "O que clicar, com a janela/app se ajudar. Ex.: botão 7 da calculadora."},
            "botao": {"type": "string", "enum": ["esquerdo", "direito"], "description": "Padrão: esquerdo."},
            "duplo": {"type": "boolean", "description": "Duplo clique. Padrão: falso."}},
            "required": ["descricao"], "additionalProperties": False},
        risk=Risk.CONTROL, handler=clicar_em, timeout_s=60.0,
    ))
    registry.register(ToolSpec(
        name="localizar_na_tela",
        description=("Diz ONDE está algo na janela em foco (por descrição curta) sem tocar em nada: devolve a posição (0 a 1000) "
                     "e o nome do controle sob o ponto. Use para conferir antes de agir ou para responder 'onde fica X'."),
        parameters={"type": "object", "properties": {"descricao": {"type": "string", "minLength": 2, "maxLength": 120}},
                    "required": ["descricao"], "additionalProperties": False},
        risk=Risk.READ, handler=localizar_na_tela, timeout_s=60.0,
    ))
    registry.register(ToolSpec(
        name="mover_mouse",
        description=("Move o mouse para cima de algo da janela em foco (descrição curta), sem clicar: abre dicas e menus de passar o mouse."),
        parameters={"type": "object", "properties": {"alvo": {"type": "string", "minLength": 2, "maxLength": 120}},
                    "required": ["alvo"], "additionalProperties": False},
        risk=Risk.CONTROL, handler=mover_mouse, timeout_s=60.0,
    ))
    registry.register(ToolSpec(
        name="arrastar",
        description=("Arrasta com o mouse de um item até outro da janela em foco (ambos por descrição curta): mover arquivo, "
                     "reordenar, soltar numa pasta, ajustar controle deslizante."),
        parameters={"type": "object", "properties": {"origem": {"type": "string", "minLength": 2, "maxLength": 120},
                                                     "destino": {"type": "string", "minLength": 2, "maxLength": 120}},
                    "required": ["origem", "destino"], "additionalProperties": False},
        risk=Risk.CONTROL, handler=arrastar, timeout_s=120.0,
    ))
    registry.register(ToolSpec(
        name="clicar_na_tela",
        description=("Clica com o MOUSE numa posição da tela que você acabou de ver com ver_tela. x e y vão de 0 a 1000 "
                     "sobre a imagem (0,0 = canto superior esquerdo; 1000,1000 = canto inferior direito; o centro é 500,500). "
                     "Use quando clicar_controle não achar o controle. Para botões Salvar/OK/Executar use clicar_controle."),
        parameters={"type": "object", "properties": {
            "x": {**_COORD, "description": "Posição horizontal, 0 a 1000."},
            "y": {**_COORD, "description": "Posição vertical, 0 a 1000."},
            "botao": {"type": "string", "enum": ["esquerdo", "direito"], "description": "Padrão: esquerdo."},
            "duplo": {"type": "boolean", "description": "Duplo clique (abrir arquivo/pasta). Padrão: falso."}},
            "required": ["x", "y"], "additionalProperties": False},
        risk=Risk.CONTROL, handler=clicar_na_tela, prepare=prepare_clique,
    ))
    registry.register(ToolSpec(
        name="rolar_tela",
        description=("Rola a roda do mouse (página, lista, site). 'direcao': cima, baixo, esquerda ou direita; 'quantidade' 1 a 10 "
                     "(cada uma ~3 linhas). x e y (0 a 1000 sobre a imagem de ver_tela) escolhem onde rolar; sem eles rola onde o mouse está."),
        parameters={"type": "object", "properties": {
            "direcao": {"type": "string", "enum": ["cima", "baixo", "esquerda", "direita"]},
            "quantidade": {"type": "integer", "minimum": 1, "maximum": 10},
            "x": _COORD, "y": _COORD}, "required": ["direcao"], "additionalProperties": False},
        risk=Risk.CONTROL, handler=rolar_tela, prepare=prepare_rolagem,
    ))
