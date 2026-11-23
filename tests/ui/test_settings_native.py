"""QA NATIVO das Configuracoes: janela REAL do Windows e entrada REAL (SendInput): clique de mouse nos itens da navegacao, no
cabecalho recolhivel, na lista suspensa e no interruptor; digitacao real na busca; Salvar/Descartar/Restaurar com dialogo;
Ctrl+F, Tab, Esc; tela cheia; tempo de abertura; ajuste a tela pequena (escala 150/200%).

    venv\\Scripts\\python.exe -I tests\\ui\\test_settings_native.py --native --scale 150 --theme dark --out SAIDA
So usa janelas de TESTE com config.toml/QSettings temporarios; nunca toca no Eco instalado.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uicommon as U  # noqa: E402

import faulthandler  # noqa: E402
faulthandler.dump_traceback_later(150, repeat=True)          # se travar, mostra onde (nunca fica mudo)
ARGS = U.parse()
ARGS.native = True
U.setup_env(ARGS)
R = U.Results("settings_native", ARGS)

from PySide6.QtCore import QPoint, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QPushButton  # noqa: E402

app = U.make_app(ARGS.theme)

from jarvis.core.cancel import CancelToken  # noqa: E402
from jarvis.ui.kit.cards import SectionCard  # noqa: E402
from jarvis.ui.kit.feedback import Toast  # noqa: E402
from jarvis.ui.settings import controls  # noqa: E402
from jarvis.ui.settings.window import SettingsWindow  # noqa: E402
from jarvis.win import input as winput  # noqa: E402

controls.load_devices = lambda kind: []
SHOTS = Path(ARGS.out) / "capturas" / "nativo-real" / f"{ARGS.scale}-{ARGS.theme}"
DPR = app.primaryScreen().devicePixelRatio()


def phys(widget, pos: QPoint) -> tuple[int, int]:
    g = widget.mapToGlobal(pos)
    return int(round(g.x() * DPR)), int(round(g.y() * DPR))


def real_click(widget, pos: QPoint | None = None, settle: int = 280) -> None:
    pos = pos if pos is not None else widget.rect().center()
    x, y = phys(widget, pos)
    U.safe_move(x, y)
    U.settle(60)
    U.safe_click(x, y)
    U.settle(settle)


def screen_shot(name: str) -> None:
    """Pixels REAIS da tela (inclui popups, menus e bordas do Windows)."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    app.primaryScreen().grabWindow(0).save(str(SHOTS / f"{name}.png"), "PNG")


def new_window():
    tmp, store, cfg, prefs = U.tmp_env()
    t0 = time.perf_counter()
    win = SettingsWindow(cfg, None, store, prefs)
    win.show()
    app.processEvents()
    ms = (time.perf_counter() - t0) * 1000
    return win, ms, tmp, store, prefs


def modal_then(action, delay_ms: int = 600):
    """Agenda ``action(dialog)`` para depois que um dialogo modal abrir (exec bloqueia o teste)."""
    EXPECT_MODAL[0] = True
    QTimer.singleShot(8000, lambda: EXPECT_MODAL.__setitem__(0, False))

    def fire() -> None:
        dlg = QApplication.activeModalWidget()
        if dlg is None:
            R.check("dialogo_modal_apareceu", False, "nenhum dialogo modal ativo")
            return
        action(dlg)
    QTimer.singleShot(delay_ms, fire)
    QTimer.singleShot(9000, lambda: QApplication.activeModalWidget() and QApplication.activeModalWidget().reject())


def key(vk: int) -> None:
    U.require_foreground()
    winput.tap_key(vk)
    U.settle(180)


def t_open_time() -> None:
    import psutil
    psutil.cpu_percent(None)
    time.sleep(0.4)
    load = psutil.cpu_percent(None)
    times = []
    for _ in range(5):
        win, ms, *_ = new_window()
        times.append(ms)
        U.settle(250)
        win.controller.discard()
        win.close()
        U.settle(100)
    times_s = sorted(times)
    R.check("nativo_abertura_ms", times_s[2] < 1000, f"construir+mostrar (5x): {', '.join(f'{t:.0f}' for t in times)} ms; mediana {times_s[2]:.0f} (meta < 1000); carga de CPU ao medir {load:.0f}%")


def t_fit(win) -> None:
    scr = win.screen()
    av = scr.availableGeometry()
    fg = win.frameGeometry()
    R.check("nativo_janela_cabe_na_area_util", av.adjusted(-1, -1, 1, 1).contains(fg),
            f"escala {ARGS.scale}%: area util {av.getRect()} janela {fg.getRect()}")
    bar = win.bar
    gp = bar.mapToGlobal(QPoint(0, bar.height()))
    R.check("nativo_barra_de_acoes_visivel_na_tela", gp.y() <= av.bottom() + 1, f"base da barra em y={gp.y()} (area util ate {av.bottom()})")


def t_nav_and_collapse(win) -> None:
    # navegacao por clique real
    for key in ("voice", "listening", "tools", "updates", "about", "general"):
        item = win.nav.item(win._keys.index(key))
        win.nav.scrollToItem(item)                  # em tela pequena/escala alta a lista rola: traz o item para a vista antes do clique
        U.settle(120)
        rect = win.nav.visualItemRect(item)
        real_click(win.nav.viewport(), rect.center())
        R.check(f"nativo_clique_nav_{key}", win.nav.current_key() == key, f"pagina atual {win.nav.current_key()}")
    screen_shot("geral")
    # recolher com clique real
    win.nav.set_current("listening")
    U.settle(300)
    page = win.pages["listening"]
    sec = page._section_by_id["perf"]
    page.ensureWidgetVisible(sec, 0, 40)
    U.settle(250)
    was = sec.expanded()
    heights = []
    x, y = phys(sec._head, sec._head.rect().center())
    U.safe_move(x, y)
    U.settle(60)
    U.safe_click(x, y)
    for _ in range(20):
        U.settle(16)
        heights.append(sec.height())
    U.settle(300)
    R.check("nativo_clique_real_no_cabecalho_alterna", sec.expanded() != was, f"{was} -> {sec.expanded()}")
    seq = heights
    inc = all(b >= a - 1 for a, b in zip(seq, seq[1:])) or all(b <= a + 1 for a, b in zip(seq, seq[1:]))
    R.check("nativo_animacao_do_cartao_suave", inc and len(set(seq)) >= 3, f"alturas {seq[:14]}")
    page.ensureWidgetVisible(sec, 0, 40)
    U.settle(250)
    screen_shot("recolhivel-aberto")
    real_click(sec._head)
    U.settle(300)
    R.check("nativo_segundo_clique_recolhe", sec.expanded() == was, "")


def t_combo_and_toggle(win) -> None:
    win.nav.set_current("voice")
    U.settle(300)
    page = win.pages["voice"]
    combos = [c for c in page.findChildren(QComboBox) if c.isVisibleTo(win) and c.isEnabled() and c.count() >= 2]
    R.check("nativo_ha_lista_suspensa_na_pagina", bool(combos), f"{len(combos)} listas")
    if combos:
        cb = combos[0]
        page.ensureWidgetVisible(cb)
        U.settle(200)
        before = cb.currentIndex()
        real_click(cb)
        U.settle(250)
        view = cb.view()
        R.check("nativo_lista_abre_com_clique_real", view.isVisible(), "")
        if view.isVisible():
            screen_shot("lista-suspensa-aberta")
            vg = view.window().frameGeometry()
            gp = cb.mapToGlobal(QPoint(0, 0))
            R.check("nativo_lista_nao_cobre_o_campo", vg.top() >= gp.y() + cb.height() - 3 or vg.bottom() <= gp.y() + 3,
                    f"campo y={gp.y()}..{gp.y()+cb.height()} lista y={vg.top()}..{vg.bottom()}")
            target = 1 if before != 1 else 0
            idx = view.model().index(target, 0)
            r = view.visualRect(idx)
            real_click(view.viewport(), r.center())
            R.check("nativo_clique_real_escolhe_item", cb.currentIndex() == target and win.change_count() >= 1,
                    f"indice {before} -> {cb.currentIndex()}; alteracoes pendentes {win.change_count()}")
    screen_shot("com-alteracao-pendente")
    R.check("nativo_barra_mostra_pendencia", win.bar.isVisible() and win.change_count() >= 1, f"{win.change_count()} alteracao(oes)")


def t_search_and_keys(win) -> None:
    win.nav.set_current("general")
    U.settle(250)
    real_click(win.search)
    U.require_foreground()
    winput.send_text("memoria", CancelToken())
    U.settle(1000)
    R.check("nativo_digitacao_real_na_busca", win.search.text() == "memoria" and win.summary.isVisible(), f"{win.search.text()!r} / {win.summary.text()!r}")
    screen_shot("busca-real")
    key(0x1B)                                   # Esc: limpa a busca (campo focado)
    U.wait_until(lambda: win.search.text() == "", 3.0)
    R.check("nativo_esc_limpa_a_busca", win.search.text() == "", f"{win.search.text()!r}")
    win.nav.setFocus()
    U.require_foreground()
    winput._press(0x11)                         # Ctrl
    winput.tap_key(0x46)                        # F
    winput._release(0x11)
    U.settle(250)
    fw = app.focusWidget()
    R.check("nativo_ctrl_f_real_foca_a_busca", fw is win.search or win.search.isAncestorOf(fw), type(fw).__name__)
    seen = []
    for _ in range(12):
        key(0x09)                               # Tab real
        w = app.focusWidget()
        seen.append(type(w).__name__ if w else "-")
    R.check("nativo_tab_real_percorre", len(set(seen)) >= 3, f"{seen}")


def t_save_discard_reset(win, store) -> None:
    win.nav.set_current("llm")
    U.settle(300)
    base_pending = win.change_count()                        # a lista suspensa do passo anterior ja deixou 1 alteracao
    values = win.collect_values()
    values["llm.temperature"] = 0.45
    win.apply_values(values)
    U.settle(250)
    # Descartar -> dialogo -> Cancelar (mantem)
    discard_btn = win.bar.findChildren(QPushButton)
    names = {b.text(): b for b in discard_btn}
    R.check("nativo_botoes_da_barra", {"Salvar", "Descartar"} <= set(names), f"{sorted(names)}")
    seen = {}

    def cancel(dlg):
        seen["foco"] = dlg.focusWidget().text() if dlg.focusWidget() is not None and hasattr(dlg.focusWidget(), "text") else ""
        screen_shot("dialogo-descartar")
        cancel_btn = [b for b in dlg.findChildren(QPushButton) if b.text() == "Cancelar"][0]
        real_click(cancel_btn)
    modal_then(cancel)
    real_click(names["Descartar"], settle=900)
    R.check("nativo_descartar_abre_dialogo_com_foco_em_cancelar", "Cancelar" in seen.get("foco", ""), f"foco em {seen.get('foco')!r}")
    R.check("nativo_cancelar_mantem_alteracoes", win.change_count() == base_pending + 1, f"{win.change_count()} pendentes (esperado {base_pending + 1})")
    # Salvar real
    got = []
    win.saved.connect(lambda o: got.append(o))
    real_click(names["Salvar"], settle=900)
    t_end = time.monotonic() + 6
    while not got and time.monotonic() < t_end:
        U.settle(50)
    txt = store.path.read_text(encoding="utf-8") if store.path.exists() else ""
    R.check("nativo_salvar_real_grava_o_arquivo", bool(got) and "0.45" in txt, f"saved={bool(got)}; arquivo contem 0.45={'0.45' in txt}")
    U.settle(400)
    toasts = [t for t in win.findChildren(Toast) if t.isVisible()]
    R.check("nativo_toast_de_salvo_aparece", bool(toasts) or win.banners.isVisible(), f"toasts visiveis {len(toasts)}; banner visivel {win.banners.isVisible()}")
    screen_shot("salvo-toast")
    R.check("nativo_pendencias_zeradas_apos_salvar", win.change_count() == 0, f"{win.change_count()}")
    # Restaurar padrao -> dialogo destrutivo -> Cancelar
    modal_then(lambda d: real_click([b for b in d.findChildren(QPushButton) if b.text() == "Cancelar"][0]))
    reset = [b for b in win.bar.findChildren(QPushButton) if "Restaurar" in b.text()]
    if reset:
        real_click(reset[0], settle=900)
        R.check("nativo_restaurar_cancelar_mantem_arquivo", "0.45" in store.path.read_text(encoding="utf-8"), "")


def t_fullscreen_and_close(win) -> None:
    win.showFullScreen()
    U.settle(700)
    sg = win.screen().geometry()
    R.check("nativo_tela_cheia", win.isFullScreen() and win.width() >= sg.width() - 2 and win.height() >= sg.height() - 2, f"{win.width()}x{win.height()} em {sg.width()}x{sg.height()}")
    screen_shot("tela-cheia")
    win.nav.set_current("tools")
    U.settle(400)
    screen_shot("tela-cheia-ferramentas")
    win.showNormal()
    U.settle(500)
    R.check("nativo_sair_da_tela_cheia", not win.isFullScreen(), "")
    win.showMaximized()
    U.settle(600)
    av = win.screen().availableGeometry()
    R.check("nativo_maximizada_na_area_util", win.isMaximized() and win.width() <= av.width() + 16, f"{win.width()}x{win.height()} area {av.getRect()}")
    screen_shot("maximizada")
    win.showNormal()
    U.settle(400)
    # fechar com Esc real (sem pendencias)
    win.controller.discard()
    U.settle(200)
    win.activateWindow()
    real_click(win.nav.viewport(), win.nav.visualItemRect(win.nav.item(0)).center())
    key(0x1B)
    U.settle(500)
    R.check("nativo_esc_real_fecha_a_janela", not win.isVisible(), "")


EXPECT_MODAL = [False]


def _watchdog() -> None:
    """Um dialogo modal que ninguem pediu (ex.: 'descartar alteracoes?' ao apertar Esc) trava o teste para sempre: fecha e acusa."""
    dlg = QApplication.activeModalWidget()
    if dlg is not None and not EXPECT_MODAL[0]:
        R.check("sem_dialogo_modal_inesperado", False, f"apareceu {type(dlg).__name__} {dlg.windowTitle()!r}: o ultimo comando abriu um dialogo que ninguem pediu")
        dlg.reject()


def main() -> int:
    wd = QTimer()
    wd.timeout.connect(_watchdog)
    wd.start(2500)
    with R.guard("abertura"):
        t_open_time()
    win, ms, tmp, store, prefs = new_window()
    U.settle(1000)
    U.set_target(win)
    R.check("nativo_janela_ficou_por_cima_e_em_foco", U.raise_test_window(win), "")
    U.settle(300)
    R.check("nativo_janela_abriu", win.isVisible() and app.platformName() == "windows", f"plataforma {app.platformName()}, dpr {win.devicePixelRatioF()}, {ms:.0f} ms")
    for name, fn, args in (("ajuste", t_fit, (win,)), ("nav", t_nav_and_collapse, (win,)), ("combo", t_combo_and_toggle, (win,)),
                           ("busca", t_search_and_keys, (win,)), ("salvar", t_save_discard_reset, (win, store)),
                           ("telacheia", t_fullscreen_and_close, (win,))):
        with R.guard(name):
            fn(*args)
    try:
        win.controller.discard()
        win.close()
    except Exception:  # noqa: BLE001
        pass
    R.save()
    return 1 if R.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
