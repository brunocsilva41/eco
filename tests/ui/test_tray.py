"""QA da bandeja do sistema: estrutura do menu, cada item chama seu callback, 'Verificar atualizacoes...' usa o fluxo
completo, avisos (showMessage) e, com --native, clique REAL (SendInput) no icone da bandeja e no item do menu.

    venv\\Scripts\\python.exe -I tests\\ui\\test_tray.py --scale 100 --theme dark --out SAIDA [--native]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uicommon as U  # noqa: E402

ARGS = U.parse()
U.setup_env(ARGS)
R = U.Results("tray", ARGS)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

app = U.make_app(ARGS.theme)
from jarvis.core.updates import UpdateInfo  # noqa: E402
from jarvis.ui.tray import TrayController, make_icon  # noqa: E402

SHOTS = Path(ARGS.out) / "capturas" / ("nativo" if ARGS.native else "off") / f"bandeja-{ARGS.scale}-{ARGS.theme}"
CALLS: list[str] = []


def cb(name: str):
    def f(*a):
        CALLS.append(f"{name}{a if a else ''}")
    return f


def build(check=None, with_check_cb=True) -> TrayController:
    cbs = {k: cb(k) for k in ("settings", "quit", "reveal", "toggle_visible", "toggle_pin", "set_size", "set_position",
                              "set_listen_mode_toggle", "set_mute")}
    if with_check_cb:
        cbs["check_updates"] = cb("check_updates")
    return TrayController(app, version="0.1.4", callbacks=cbs, check_updates=check)


def menu_actions(menu, prefix=""):
    out = []
    for a in menu.actions():
        if a.isSeparator():
            continue
        out.append((prefix + a.text(), a))
        if a.menu():
            out += menu_actions(a.menu(), prefix + a.text() + " > ")
    return out


def t_structure() -> None:
    CALLS.clear()
    tray = build()
    items = menu_actions(tray._menu)
    names = [n for n, _ in items]
    R.check("menu_tem_cabecalho_com_versao", names and names[0].startswith("Eco") and "0.1.4" in names[0], names[:1])
    for want in ("Abrir Configurações", "Mostrar a Ilha", "Ilha do Eco", "Escuta contínua", "Silenciar microfone",
                 "Verificar atualizações…", "Sobre o Eco", "Encerrar o Eco"):
        R.check(f"menu_item_{want}", want in names, "")
    sub = [n for n in names if n.startswith("Ilha do Eco > ")]
    R.check("menu_submenu_ilha_completo", len(sub) >= 9, f"{len(sub)} itens: {[s.split(' > ')[-1] for s in sub]}")
    R.check("menu_sem_itens_duplicados", len(names) == len(set(names)), "")
    R.check("menu_encerrar_e_o_ultimo", names[-1] == "Encerrar o Eco", names[-1])
    R.check("menu_cabecalho_desabilitado", not items[0][1].isEnabled(), "")
    # cada item aciona seu callback
    for label, key in (("Abrir Configurações", "settings"), ("Mostrar a Ilha", "reveal"), ("Encerrar o Eco", "quit")):
        CALLS.clear()
        dict(items)[label].trigger()
        R.check(f"menu_{key}_chama_callback", CALLS == [f"{key}"] or CALLS == [f"{key}()"], f"{CALLS}")
    for label, key, arg in (("Ilha do Eco > Fixar na tela", "toggle_pin", True), ("Escuta contínua", "set_listen_mode_toggle", True),
                            ("Silenciar microfone", "set_mute", True)):
        CALLS.clear()
        a = dict(items)[label]
        a.toggle()
        R.check(f"menu_{key}_alterna_e_chama", len(CALLS) == 1 and key in CALLS[0], f"{CALLS}")
    for label in ("Compacto", "Médio", "Expandido"):
        CALLS.clear()
        dict(items)[f"Ilha do Eco > Tamanho > {label}"].trigger()
        R.check(f"menu_tamanho_{label}", len(CALLS) == 1 and "set_size" in CALLS[0], f"{CALLS}")
    for label in ("Topo, acoplada", "Topo, flutuante", "Lateral direita", "Lateral esquerda"):
        CALLS.clear()
        dict(items)[f"Ilha do Eco > Posição > {label}"].trigger()
        R.check(f"menu_posicao_{label}", len(CALLS) == 1 and "set_position" in CALLS[0], f"{CALLS}")
    # exclusividade nos subgrupos (radio)
    group = [a for n, a in items if n.startswith("Ilha do Eco > Tamanho > ")]
    R.check("menu_tamanho_e_radio_exclusivo", sum(1 for a in group if a.isChecked()) == 1, f"marcados {[a.isChecked() for a in group]}")
    CALLS.clear()
    dict(items)["Verificar atualizações…"].trigger()
    R.check("menu_verificar_atualizacoes_usa_fluxo_completo", CALLS == ["check_updates"], f"{CALLS}")
    # estado do icone
    tray.set_status("ouvindo", muted=True, listening=True)
    R.check("icone_dica_reflete_estado", "ouvindo" in tray._tray.toolTip(), tray._tray.toolTip())
    for muted, listening in ((False, False), (True, False), (False, True)):
        ic = make_icon(muted, listening)
        R.check(f"icone_{'mudo' if muted else 'ouvindo' if listening else 'normal'}_nao_vazio", not ic.pixmap(32, 32).isNull(), "")
    U.grab(tray._menu, SHOTS / "menu.png")
    tray._menu.hide()


def t_update_without_flow() -> None:
    """Sem o fluxo completo (callback), a bandeja consulta e avisa com showMessage; cobre disponivel, atualizado e erro."""
    msgs: list[tuple[str, str]] = []
    for kind, info in (("disponivel", UpdateInfo(current="0.1.3", latest="0.2.0", available=True, url="https://github.com/x/y/releases/tag/v0.2.0")),
                       ("atualizado", UpdateInfo(current="0.2.0", latest="0.2.0")),
                       ("erro", UpdateInfo(current="0.2.0", error="sem internet"))):
        msgs.clear()
        import webbrowser
        opened: list[str] = []
        real = webbrowser.open
        webbrowser.open = lambda u, *a, **k: opened.append(u) or True          # type: ignore[assignment]
        try:
            tray = build(check=lambda info=info: info, with_check_cb=False)
            tray._tray.showMessage = lambda t, x, *a, **k: msgs.append((t, x))   # type: ignore[assignment]
            tray.check_updates()
            t0 = time.monotonic()
            while time.monotonic() - t0 < 3 and not any(m for m in msgs if m[0] != "Eco"):
                U.settle(50)
        finally:
            webbrowser.open = real
        last = msgs[-1] if msgs else ("", "")
        want = {"disponivel": "0.2.0", "atualizado": "mais recente", "erro": "sem internet"}[kind]
        R.check(f"verificar_sem_fluxo_{kind}", want in last[1], f"{last}")
        if kind == "disponivel":
            R.check("verificar_sem_fluxo_abre_https", opened and opened[0].startswith("https://"), f"{opened}")


def _walk(ctrl, depth=0, maxd=6):
    if depth > maxd:
        return
    for ch in ctrl.GetChildren():
        yield ch
        yield from _walk(ch, depth + 1, maxd)


def find_tray_icon() -> tuple[int, int] | None:
    """Centro (px fisicos) do icone 'Eco' na area de notificacao: primeiro entre os promovidos; senao abre a divisa e procura no transbordo."""
    import uiautomation as auto
    tb = auto.PaneControl(ClassName="Shell_TrayWnd", searchDepth=1)
    if not tb.Exists(2):
        return None
    for c in _walk(tb, 0, 5):
        if c.ControlTypeName == "ButtonControl" and "eco" in (c.Name or "").lower():
            r = c.BoundingRectangle
            return (r.left + r.right) // 2, (r.top + r.bottom) // 2
    notify = auto.PaneControl(ClassName="TrayNotifyWnd")
    chev = next((c for c in notify.GetChildren() if c.ControlTypeName == "ButtonControl" and c.ClassName == "Button"), None)
    if chev is None:
        return None
    r = chev.BoundingRectangle
    U.safe_click((r.left + r.right) // 2, (r.top + r.bottom) // 2, "left", allow_classes=U.TRAY_CLASSES)
    U.settle(900)
    flyout = auto.PaneControl(ClassName="NotifyIconOverflowWindow")
    if flyout.Exists(2):
        for c in _walk(flyout, 0, 6):
            if c.ControlTypeName == "ButtonControl" and "eco" in (c.Name or "").lower():
                rr = c.BoundingRectangle
                return (rr.left + rr.right) // 2, (rr.top + rr.bottom) // 2
    return None


def t_native() -> None:
    from jarvis.win import input as winput
    if not QSystemTrayIcon.isSystemTrayAvailable():
        R.check("nativo_bandeja_disponivel", False, "a bandeja do Windows nao esta disponivel nesta sessao")
        return
    CALLS.clear()
    tray = build()
    tray.show()
    U.settle(900)
    g = tray._tray.geometry()
    uia_center = None
    if g.isEmpty():                                   # o Windows nao informa a geometria de icones na area oculta: acha pelo UI Automation
        uia_center = find_tray_icon()
        R.check("nativo_icone_achado_pelo_ui_automation", uia_center is not None, f"centro (px fisicos) {uia_center}")
        if uia_center is None:
            return
    else:
        R.check("nativo_icone_tem_geometria", True, f"{g.getRect()}")
    dpr = app.primaryScreen().devicePixelRatio()
    cx, cy = uia_center if uia_center else (int(g.center().x() * dpr), int(g.center().y() * dpr))
    # a geometria pode apontar para o botao "^" (area oculta); entao o clique abre o transbordo, nao o menu
    winput.move_to(cx, cy)
    U.settle(150)
    U.safe_click(cx, cy, "right", allow_classes=U.TRAY_CLASSES)
    U.settle(700)
    shown = tray._menu.isVisible()
    R.check("nativo_clique_direito_abre_menu", shown, f"icone em {g.getRect()} (px fisicos {cx},{cy}); menu visivel={shown}")
    if shown:
        U.grab(tray._menu, SHOTS / "menu-real.png")
        acts = {a.text(): a for a in tray._menu.actions() if not a.isSeparator()}
        ag = tray._menu.actionGeometry(acts["Abrir Configurações"])
        gp = tray._menu.mapToGlobal(ag.center())
        CALLS.clear()
        U.safe_click(int(gp.x() * dpr), int(gp.y() * dpr), "left", allow_classes=U.TRAY_CLASSES)
        U.settle(500)
        R.check("nativo_clique_real_em_abrir_configuracoes", any(c.startswith("settings") for c in CALLS), f"{CALLS}")
        # reabre e escolhe 'Verificar atualizacoes...'
        U.safe_click(cx, cy, "right", allow_classes=U.TRAY_CLASSES)
        U.settle(600)
        if tray._menu.isVisible():
            acts = {a.text(): a for a in tray._menu.actions() if not a.isSeparator()}
            gp = tray._menu.mapToGlobal(tray._menu.actionGeometry(acts["Verificar atualizações…"]).center())
            CALLS.clear()
            U.safe_click(int(gp.x() * dpr), int(gp.y() * dpr), "left", allow_classes=U.TRAY_CLASSES)
            U.settle(500)
            R.check("nativo_clique_real_em_verificar_atualizacoes", CALLS == ["check_updates"], f"{CALLS}")
        # Esc fecha o menu
        U.safe_click(cx, cy, "right", allow_classes=U.TRAY_CLASSES)
        U.settle(500)
        if tray._menu.isVisible():
            winput.tap_key(0x1B)
            U.settle(300)
            R.check("nativo_esc_fecha_menu", not tray._menu.isVisible(), "")
    # clique esquerdo = revelar a Ilha
    CALLS.clear()
    U.safe_click(cx, cy, "left", allow_classes=U.TRAY_CLASSES)
    U.settle(600)
    R.check("nativo_clique_esquerdo_revela_a_ilha", any(c.startswith("reveal") for c in CALLS), f"{CALLS}")
    # balao de aviso
    tray.notify("Atualização disponível", "Versão 0.2.0 (você tem 0.1.4).")
    U.settle(600)
    R.check("nativo_notify_sem_erro", True, "showMessage executado (o balao do Windows nao e capturavel pelo Qt)")
    tray.hide()


def main() -> int:
    with R.guard("estrutura"):
        t_structure()
    with R.guard("sem_fluxo"):
        t_update_without_flow()
    if ARGS.native:
        with R.guard("nativo"):
            t_native()
    R.save()
    return 1 if R.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
