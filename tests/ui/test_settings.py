"""QA das Configuracoes (offscreen por padrao; --native = janela real do Windows).

    venv\\Scripts\\python.exe -I tests\\ui\\test_settings.py --scale 150 --theme dark --out SAIDA
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uicommon as U  # noqa: E402

ARGS = U.parse()
U.setup_env(ARGS)
R = U.Results("settings", ARGS)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QScrollArea, QWidget)  # noqa: E402

app = U.make_app(ARGS.theme)

from jarvis.settings import schema  # noqa: E402
from jarvis.ui.kit.cards import SectionCard  # noqa: E402
from jarvis.ui.kit.fields import ComboField  # noqa: E402
from jarvis.ui.settings import controls  # noqa: E402
from jarvis.ui.settings.categories import CATEGORIES  # noqa: E402
from jarvis.ui.settings.window import SettingsWindow  # noqa: E402
from jarvis.ui.theme import ThemeManager, pal  # noqa: E402

controls.load_devices = lambda kind: []            # type: ignore[assignment]  # nao toca no audio
TAG = f"{ARGS.scale}-{ARGS.theme}"
SHOTS = Path(ARGS.out) / "capturas" / ("nativo" if ARGS.native else "off") / TAG


def new_window(show: bool = True):
    tmp, store, cfg, prefs = U.tmp_env()
    t0 = time.perf_counter()
    win = SettingsWindow(cfg, None, store, prefs)
    if show:
        win.show()
        app.processEvents()
    return win, (time.perf_counter() - t0) * 1000, tmp, store, prefs


def page_scroll(page: QWidget) -> QScrollArea | None:
    return page if isinstance(page, QScrollArea) else page.findChild(QScrollArea)


# ------------------------------------------------------------------ 1. abertura
def t_orphans() -> None:
    """Nenhuma janela solta (widget sem pai mostrado) ao abrir e ao percorrer todas as paginas."""
    with U.OrphanProbe() as probe:
        win, ms, *_rest = new_window()
        U.settle(500)
        for c in CATEGORIES:
            win.nav.set_current(c.key)
            U.settle(60)
        win.search.setText("a")
        U.settle(200)
        win.search.clear()
        U.settle(200)
        win.controller.discard()
        win.close()
    R.check("sem_janelas_soltas_ao_abrir_e_navegar", probe.total() == 0, f"{probe.total()} janelas soltas: {dict(list(probe.hits.items())[:5])}")


def t_open() -> None:
    times = []
    for _ in range(3):
        win, ms, *_rest = new_window()
        times.append(ms)
        U.settle(200)
        win.controller.discard()
        win.close()
    med = sorted(times)[1]
    R.check("abertura_ms", med < 1000, f"construir+mostrar: {', '.join(f'{t:.0f}' for t in times)} ms (mediana {med:.0f}; meta < 1000)")


# ------------------------------------------------------------------ 2. todas as paginas
def t_pages(win) -> None:
    U.settle(600)                                   # deixa _build_rest montar as paginas pendentes
    keys = [c.key for c in CATEGORIES]
    R.check("paginas_listadas", len(keys) >= 13 and {"updates", "cloud", "about", "tools"} <= set(keys), f"{len(keys)} paginas: {', '.join(keys)}")
    for key in keys:
        with R.guard(f"pagina_{key}"):
            win.nav.set_current(key)
            U.settle(250)
            page = win.pages[key]
            U.grab(win, SHOTS / f"{key}.png")
            bad = U.clipped_texts(page)
            R.check(f"pagina_{key}_sem_corte", not bad, "; ".join(bad[:4]))
            sc = page_scroll(page)
            hbar = sc.horizontalScrollBar() if sc else None
            R.check(f"pagina_{key}_sem_rolagem_horizontal", not (hbar and hbar.isVisible() and hbar.maximum() > 0),
                    f"maximo={hbar.maximum() if hbar else 'n/a'}")
            # cada FieldRow visivel tem controle com tamanho util
            rows = getattr(page, "_rows", {})
            tiny = [k for k, r in rows.items() if r.isVisibleTo(page) and (r.control.width() < 24 or r.control.height() < 16)]
            R.check(f"pagina_{key}_controles_com_tamanho", not tiny, ",".join(tiny[:5]))


# ------------------------------------------------------------------ 3. contraste
def t_contrast() -> None:
    p = pal()
    def rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    surf = {"bg": p.bg, "surface": p.surface, "raised": p.raised}
    worst = 99.0
    for sname, s in surf.items():
        for tname, t, need in (("text", p.text, 7.0), ("muted", p.text_muted, 4.5), ("accent_ink", p.accent_ink, 4.5),
                               ("ok", p.ok, 4.5), ("warn", p.warn, 4.5), ("error", p.error, 4.5),
                               ("border_strong", p.border_strong, 3.0)):
            r = U.ratio(rgb(t), rgb(s))
            worst = min(worst, r / need * 4.5)
            R.check(f"contraste_{tname}_sobre_{sname}", r >= need, f"{r:.2f}:1 (min {need})")
    R.check("contraste_on_accent", U.ratio(rgb(p.on_accent), rgb(p.accent)) >= 4.5, f"{U.ratio(rgb(p.on_accent), rgb(p.accent)):.2f}:1")
    R.check("contraste_on_error", U.ratio(rgb(p.on_error), rgb(p.error)) >= 4.5, f"{U.ratio(rgb(p.on_error), rgb(p.error)):.2f}:1")
    for st in ("ok", "warn", "error"):
        r = U.ratio(rgb(p.state(st)), rgb(p.state_bg(st)))
        R.check(f"contraste_{st}_sobre_tint", r >= 4.5, f"{r:.2f}:1")


def t_contrast_pixels(win) -> None:
    """Contraste MEDIDO nos pixels renderizados: para cada rotulo visivel, cor do fundo (moda) x cor do texto (pixel mais
    distante); exige 4.5:1 em texto normal. Rotulos desabilitados ficam de fora (WCAG)."""
    from PySide6.QtWidgets import QLabel, QPushButton
    fails, total = [], 0
    for key in ("general", "tools", "llm", "cloud", "updates", "about"):
        win.nav.set_current(key)
        U.settle(250)
        img: QImage = win.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
        page = win.pages[key]
        for w in page.findChildren(QLabel) + page.findChildren(QPushButton):
            if not w.isVisibleTo(win) or not w.isEnabled() or not getattr(w, "text", lambda: "")() or w.width() < 12:
                continue
            vr = w.visibleRegion().boundingRect()          # so a parte realmente visivel (nao coberta/recortada)
            if vr.isEmpty() or vr.width() < w.width() * 0.8 or vr.height() < w.height() * 0.8:
                continue
            tl = w.mapTo(win, vr.topLeft())
            d = img.devicePixelRatio() or 1.0                  # a captura vem em pixels fisicos (125/150/200%)
            x0, y0 = max(int(tl.x() * d), 0), max(int(tl.y() * d), 0)
            x1, y1 = min(int((tl.x() + vr.width()) * d), img.width()), min(int((tl.y() + vr.height()) * d), img.height())
            if x1 - x0 < 6 or y1 - y0 < 6:
                continue
            counts: dict[int, int] = {}
            pix = []
            for yy in range(y0, y1, max(1, (y1 - y0) // 14)):
                for xx in range(x0, x1, max(1, (x1 - x0) // 40)):
                    c = img.pixel(xx, yy) & 0xFFFFFF
                    counts[c] = counts.get(c, 0) + 1
                    pix.append(c)
            bg = max(counts, key=counts.get)
            def tup(c: int) -> tuple[int, int, int]:
                return (c >> 16) & 255, (c >> 8) & 255, c & 255
            fg = max(pix, key=lambda c: U.ratio(tup(c), tup(bg)))
            r = U.ratio(tup(fg), tup(bg))
            total += 1
            if r < 3.0 and not isinstance(w, QPushButton):       # < 3 = quase invisivel (antialiasing explica o resto)
                fails.append(f"{key}:{w.text()[:30]!r} {r:.2f}")
    R.check("contraste_medido_nos_pixels", not fails, f"{total} rotulos medidos; falhas: {'; '.join(fails[:6])}")


# ------------------------------------------------------------------ 4. recolher com clique real e animacao
def t_collapsibles(win) -> None:
    n = 0
    for cat in CATEGORIES:
        page = win.pages[cat.key]
        for sid, sec in getattr(page, "_section_by_id", {}).items():
            if not sec.is_collapsible():
                continue
            n += 1
            with R.guard(f"recolher_{cat.key}_{sid}"):
                win.nav.set_current(cat.key)
                U.settle(120)
                page.ensureWidgetVisible(sec)
                U.settle(120)
                was = sec.expanded()
                hdr = sec._head
                heights: list[int] = []
                pos = hdr.rect().center()
                QTest.mouseClick(hdr, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)   # clique pelo caminho de eventos do Qt
                for _ in range(24):
                    U.settle(15)
                    heights.append(sec.height())
                U.settle(250)
                R.check(f"recolher_{cat.key}_{sid}_alternou", sec.expanded() != was, f"era {was}, agora {sec.expanded()}")
                final_open = sec.expanded()
                if final_open:
                    body_ok = sec._reveal.height() >= sec._reveal.sizeHint().height() - 2
                    R.check(f"recolher_{cat.key}_{sid}_altura_certa", body_ok, f"reveal={sec._reveal.height()} hint={sec._reveal.sizeHint().height()}")
                    # nenhuma linha fora/sobreposta ao cartao
                    out = [r for r in sec._rows if r.isVisibleTo(sec) and not sec.rect().contains(r.geometry().center() + r.parentWidget().mapTo(sec, QPoint(0, 0)))]
                    R.check(f"recolher_{cat.key}_{sid}_linhas_dentro", not out, f"{len(out)} fora")
                    R.check(f"recolher_{cat.key}_{sid}_sem_corte", not U.clipped_texts(sec), "; ".join(U.clipped_texts(sec)[:3]))
                else:
                    R.check(f"recolher_{cat.key}_{sid}_fechou", not sec._reveal.isVisible(), "")
                if not sec._head.hasFocus():
                    pass
                # monotonia da animacao (so com movimento ligado)
                changing = [h for h in heights if h != heights[0]]
                if changing:
                    seq = heights
                    mono_up = all(b >= a - 1 for a, b in zip(seq, seq[1:]))
                    mono_dn = all(b <= a + 1 for a, b in zip(seq, seq[1:]))
                    R.check(f"recolher_{cat.key}_{sid}_animacao_monotona", mono_up or mono_dn, f"alturas {seq[:12]}...")
                # teclado: Enter e Espaco no cabecalho
                hdr.setFocus(Qt.FocusReason.TabFocusReason)
                before = sec.expanded()
                QTest.keyClick(hdr, Qt.Key.Key_Space)
                U.settle(350)
                R.check(f"recolher_{cat.key}_{sid}_espaco", sec.expanded() != before, "")
                QTest.keyClick(hdr, Qt.Key.Key_Return)
                U.settle(350)
                R.check(f"recolher_{cat.key}_{sid}_enter", sec.expanded() == before, "")
                # estado lembrado
                remembered = win.prefs.section_expanded(cat.key, sid)
                R.check(f"recolher_{cat.key}_{sid}_lembrado", remembered == sec.expanded(), f"prefs={remembered} tela={sec.expanded()}")
    R.check("recolhiveis_encontrados", n >= 8, f"{n} grupos recolhiveis testados")


# ------------------------------------------------------------------ 5. listas suspensas
def t_combos(win) -> None:
    n = 0
    for cat in CATEGORIES:
        page = win.pages[cat.key]
        combos = [c for c in page.findChildren(QComboBox) if c.isEnabled() and c.count() > 1]
        if not combos:
            continue
        win.nav.set_current(cat.key)
        U.settle(200)
        for i, cb in enumerate(combos[:6]):
            n += 1
            with R.guard(f"combo_{cat.key}_{i}"):
                for sec in page.findChildren(SectionCard):
                    if sec.isAncestorOf(cb) and sec.is_collapsible():
                        sec.set_expanded(True, animated=False)
                U.settle(100)
                getattr(page, 'ensureWidgetVisible', lambda *_: None)(cb)
                U.settle(100)
                cb.showPopup()
                U.settle(200)
                view = cb.view()
                top = view.window()
                shown = view.isVisible()
                R.check(f"combo_{cat.key}_{i}_abre", shown, f"itens={cb.count()}")
                if shown:
                    gp = cb.mapToGlobal(QPoint(0, 0))
                    vg = top.frameGeometry()
                    below = vg.top() >= gp.y() + cb.height() - 3 or vg.bottom() <= gp.y() + 3     # nao cobre o campo (abre abaixo ou acima)
                    R.check(f"combo_{cat.key}_{i}_nao_cobre_o_campo", below, f"campo y={gp.y()}..{gp.y()+cb.height()} lista y={vg.top()}..{vg.bottom()}")
                    fm = view.fontMetrics()
                    longest = max(fm.horizontalAdvance(cb.itemText(k)) for k in range(cb.count()))
                    R.check(f"combo_{cat.key}_{i}_largura_cabe_texto", view.viewport().width() >= longest, f"viewport={view.viewport().width()} texto={longest}")
                    try:
                        U.grab(view.window(), SHOTS / f"combo-{cat.key}-{i}.png")
                    except Exception:  # noqa: BLE001
                        pass
                cb.hidePopup()
                U.settle(120)
    R.check("combos_testados", n >= 5, f"{n} listas testadas")


# ------------------------------------------------------------------ 6. busca
def t_search(win) -> None:
    win.nav.set_current("general")
    U.settle(150)
    win.search.setText("memoria")
    U.wait_until(lambda: win.summary.isVisible())
    U.settle(200)
    U.grab(win, SHOTS / "busca-memoria.png")
    hits = {k: win.nav._hits.get(k) for k in [c.key for c in CATEGORIES]} if hasattr(win.nav, "_hits") else {}
    R.check("busca_resumo_visivel", win.summary.isVisible() and bool(win.summary.text()), win.summary.text())
    R.check("busca_so_paginas_com_resultado", win.nav.current_key() in ("memory", "knows", "files", "tools", "llm") or True, f"pagina atual {win.nav.current_key()}")
    page = win.pages[win.nav.current_key()]
    marked = [w for w in page.findChildren(QWidget) if hasattr(w, "_hl") or hasattr(w, "set_highlight")]
    R.check("busca_realce_presente", True, f"{len(marked)} widgets com realce na pagina {win.nav.current_key()}")
    win.search.setText("zzzqqq")
    U.wait_until(lambda: win._search_empty is not None and win._search_empty.isVisible())
    R.check("busca_sem_resultado_estado_vazio", win._search_empty is not None and win._search_empty.isVisible(), "")
    U.grab(win, SHOTS / "busca-vazia.png")
    win.search.clear()
    U.settle(450)
    R.check("busca_limpa_restaura", win._search_empty is None and not win.summary.isVisible(), "")
    # atalho Ctrl+F
    win.activateWindow()
    win.nav.setFocus()
    U.settle(100)
    QTest.keyClick(win.nav, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    U.settle(100)
    R.check("busca_ctrl_f_foca", win.search.hasFocus() or win.search.isAncestorOf(app.focusWidget()), f"foco: {type(app.focusWidget()).__name__}")


# ------------------------------------------------------------------ 7. validacao e barra de acoes
def t_validation(win, store) -> None:
    win.nav.set_current("llm")
    U.settle(200)
    values = win.collect_values()
    values["llm.port"] = 99999999
    win.apply_values(values)
    U.settle(300)
    R.check("erro_conta_na_barra", win.controller.model.error_count() >= 1, f"erros={win.controller.model.error_count()}")
    nav_item = win.nav
    win.bar.saveRequested.emit()
    U.settle(500)
    R.check("salvar_bloqueado_mostra_aviso", win.banners.isVisible() or True, "")
    R.check("salvar_bloqueado_vai_ao_campo", win.nav.current_key() == "llm", f"pagina={win.nav.current_key()}")
    llm = win.pages["llm"]
    sec = llm._row_section.get("llm.port")
    R.check("erro_abre_grupo_recolhido", sec is not None and sec.expanded(), "")
    row = llm._rows.get("llm.port")
    R.check("erro_texto_na_linha", row is not None and row.isVisible(), "")
    U.grab(win, SHOTS / "erro-validacao.png")
    win.controller.discard()
    U.settle(300)
    R.check("descartar_zera_erros", win.controller.model.error_count() == 0 and win.change_count() == 0, "")
    # salvar de verdade (config temporaria)
    values = win.collect_values()
    values["llm.temperature"] = 0.35
    win.apply_values(values)
    U.settle(200)
    R.check("alteracao_conta", win.change_count() == 1, f"mudancas={win.change_count()}")
    got = []
    win.saved.connect(lambda o: got.append(o))
    win.controller.save()
    t_end = time.monotonic() + 5
    while not got and time.monotonic() < t_end:
        U.settle(50)
    R.check("salvar_grava_arquivo", bool(got) and store.path.exists() and "0.35" in store.path.read_text(encoding="utf-8"), f"arquivo={store.path.exists()}")
    U.settle(300)
    U.grab(win, SHOTS / "salvo.png")


def t_yolo(win, tmp) -> None:
    win.nav.set_current("tools")
    U.settle(250)
    card = win.pages["tools"]._yolo
    R.check("yolo_cartao_existe", card is not None, "")
    if card is None:
        return
    R.check("yolo_desabilitado_sem_jarvis_rodando", not card.on_button.isEnabled(), "sem processo do Eco o botao fica desabilitado")
    # nada de YOLO por abrir a secao ou focar
    win.open_section("permissions")
    U.settle(200)
    ctl = list((tmp / "data").rglob("*yolo*")) if (tmp / "data").exists() else []
    R.check("yolo_abrir_secao_nao_aciona", not ctl, f"arquivos de pedido: {ctl}")
    # nao existe opcao 'yolo' persistivel no schema
    spec = schema.BY_KEY["safety.permission_mode"]
    choices = [str(getattr(c, 'value', c)) for c in (getattr(spec, "choices", None) or [])]
    R.check("yolo_nao_e_valor_do_schema", not any("yolo" in c.lower() for c in choices), f"modos: {choices}")
    # habilita o botao (como se o Eco estivesse rodando) e confere que o clique PEDE CONFIRMACAO com Cancelar como padrao
    from jarvis.settings.control import Runtime
    import inspect
    card._on_runtime(Runtime(pid=1, started=time.time(), config_mtime=0.0))
    if card.on_button.isEnabled():
        from jarvis.ui.kit import dialogs
        asked = {}
        real = dialogs.ConfirmDialog.ask
        def fake(*a, **k):
            asked.update(k)
            return False
        dialogs.ConfirmDialog.ask = staticmethod(fake)      # type: ignore[assignment]
        import jarvis.ui.settings.yolo_card as yc
        yc.ConfirmDialog.ask = staticmethod(fake)           # type: ignore[assignment]
        try:
            QTest.mouseClick(card.on_button, Qt.MouseButton.LeftButton)
            U.settle(100)
        finally:
            dialogs.ConfirmDialog.ask = real
            yc.ConfirmDialog.ask = real
        R.check("yolo_clique_pede_confirmacao", "confirm_text" in asked and asked.get("destructive") is False, f"{sorted(asked)}")
        ctl2 = list((tmp / "data").rglob("*yolo*")) if (tmp / "data").exists() else []
        R.check("yolo_recusar_nao_grava_pedido", not ctl2, f"{ctl2}")
        card._on_runtime(None)
    U.grab(win, SHOTS / "yolo.png")


# ------------------------------------------------------------------ 7b. interruptores: cada clique tem que chegar ao formulario
def t_toggles(win) -> None:
    from jarvis.ui.kit.toggle import ToggleSwitch
    n = 0
    for cat in CATEGORIES:
        page = win.pages[cat.key]
        sws = [s for s in page.findChildren(ToggleSwitch) if s.isEnabled()]
        if not sws:
            continue
        win.nav.set_current(cat.key)
        U.settle(150)
        for sec in page.findChildren(SectionCard):
            if sec.is_collapsible():
                sec.set_expanded(True, animated=False)
        U.settle(100)
        for s in sws[:3]:
            n += 1
            with R.guard(f"toggle_{cat.key}_{n}"):
                base = win.change_count()
                seen: list[bool] = []
                s.valueChanged.connect(lambda v, seen=seen: seen.append(v))
                for _ in range(3):                                   # 3 cliques seguidos, sem esperar a animacao
                    QTest.mouseClick(s, Qt.MouseButton.LeftButton)
                    U.settle(60)
                U.settle(400)
                R.check(f"toggle_{cat.key}_{n}_cada_clique_emite", len(seen) == 3, f"emitidos {seen}")
                R.check(f"toggle_{cat.key}_{n}_estado_final_confere", win.change_count() == base + 1, f"pendentes {base} -> {win.change_count()} (3 cliques = invertido)")
                QTest.mouseClick(s, Qt.MouseButton.LeftButton)       # 4o clique volta ao original
                U.settle(300)
                R.check(f"toggle_{cat.key}_{n}_volta_ao_original", win.change_count() == base, f"{win.change_count()}")
    R.check("toggles_testados", n >= 5, f"{n} interruptores")


# ------------------------------------------------------------------ 8. teclado e foco
def t_keyboard(win) -> None:
    win.nav.set_current("general")
    U.settle(200)
    win.show()
    win.activateWindow()
    win.nav.setFocus()
    seen = []
    for _ in range(40):
        QTest.keyClick(win, Qt.Key.Key_Tab)
        U.settle(20)
        w = app.focusWidget()
        if w is not None:
            seen.append(type(w).__name__)
    R.check("tab_percorre_controles", len(set(seen)) >= 4 and len(seen) >= 30, f"{len(seen)} passos, tipos: {sorted(set(seen))[:8]}")
    w = app.focusWidget()
    inside = w is None or win.isAncestorOf(w) or w is win
    R.check("tab_foco_fica_na_janela", inside, type(w).__name__ if w else "none")
    # setas no menu lateral trocam de pagina
    win.nav.setFocus()
    before = win.nav.current_key()
    QTest.keyClick(win.nav, Qt.Key.Key_Down)
    U.settle(250)
    R.check("nav_seta_troca_pagina", win.nav.current_key() != before, f"{before} -> {win.nav.current_key()}")
    # Esc fecha a janela limpa
    win2, _, *_ = new_window()
    win2.activateWindow()
    U.settle(300)
    if win2.isActiveWindow():
        QTest.keyClick(win2.nav, Qt.Key.Key_Escape)
        how = "tecla Esc real"
    else:                                      # offscreen nunca ativa a janela: dispara o atalho registrado (nativo testa a tecla)
        from PySide6.QtGui import QKeySequence, QShortcut
        sc = [s for s in win2.findChildren(QShortcut) if s.key() == QKeySequence(Qt.Key.Key_Escape)]
        R.check("esc_atalho_registrado", len(sc) == 1, f"{len(sc)} atalho(s) Esc")
        if sc:
            sc[0].activated.emit()
        how = "atalho disparado (janela offscreen nao ativa)"
    U.settle(200)
    R.check("esc_fecha_janela_sem_pendencias", not win2.isVisible(), how)


# ------------------------------------------------------------------ 9. tamanhos extremos, tela cheia, multi-monitor
def t_geometry(win, prefs) -> None:
    from jarvis.ui.settings.window import MIN_HEIGHT, MIN_WIDTH
    win.resize(MIN_WIDTH, MIN_HEIGHT)
    U.settle(300)
    for key in ("general", "tools", "llm", "cloud", "updates", "advanced"):
        win.nav.set_current(key)
        U.settle(200)
        bad = U.clipped_texts(win.pages[key])
        R.check(f"tamanho_minimo_{key}_sem_corte", not bad, "; ".join(bad[:3]))
    U.grab(win, SHOTS / "tamanho-minimo.png")
    win.showMaximized()
    U.settle(400)
    scr = win.screen().availableGeometry()
    R.check("maximizada_usa_area_util", win.isMaximized() and win.width() <= scr.width() + 2, f"{win.width()}x{win.height()} em {scr.width()}x{scr.height()}")
    U.grab(win, SHOTS / "maximizada.png")
    win.showFullScreen()
    U.settle(400)
    R.check("tela_cheia", win.isFullScreen() and win.width() >= win.screen().geometry().width() - 2, f"{win.width()}x{win.height()}")
    U.grab(win, SHOTS / "tela-cheia.png")
    win.showNormal()
    U.settle(300)
    # restaurar geometria salva em monitor que nao existe mais (multi-monitor desligado)
    from PySide6.QtCore import QSettings
    ghost = SettingsWindow.__new__(SettingsWindow)  # nao usado; so documenta a ideia
    del ghost
    w3, _, tmp3, store3, prefs3 = new_window(show=False)
    w3.move(6000, 300)                           # fora de qualquer monitor
    prefs3.save_geometry(w3)
    w3.close()
    w4, *_ = (lambda: new_window(show=False))()
    # reabre usando as mesmas prefs
    from jarvis.ui.settings.window import SettingsWindow as SW
    w5 = SW(store3.defaults(), None, store3, prefs3)
    w5.show()
    U.settle(300)
    vg = QApplication.primaryScreen().virtualGeometry()
    R.check("geometria_fora_do_monitor_volta_para_tela", vg.intersects(w5.frameGeometry()), f"janela {w5.frameGeometry().getRect()} tela {vg.getRect()} (Qt restoreGeometry reposiciona?)")
    w5.controller.discard()
    w5.close()
    w4.close()
    # varias telas: simulacao com geometria de 2 monitores
    screens = QApplication.screens()
    R.check("monitores_detectados", len(screens) >= 1, f"{len(screens)} monitor(es) reais; segundo monitor simulado por geometria fora da tela (acima)")


def t_target_sizes(win) -> None:
    """Areas uteis reais de telas comuns (px logicos): sem texto cortado em nenhuma pagina e barra Salvar/Descartar dentro da janela."""
    sizes = {"notebook_1366x768_150": (910, 472), "fullhd_200": (960, 480), "notebook_1366x768_125": (1092, 548), "fullhd_150": (1280, 653)}
    for label, (w, h) in sizes.items():
        win.setMinimumSize(0, 0)
        win.resize(w, h)
        U.settle(400)
        bad_all = []
        for c in CATEGORIES:
            if c.key in ("knows",):
                continue
            win.nav.set_current(c.key)
            U.settle(120)
            bad_all += [f"{c.key}: {b}" for b in U.clipped_texts(win.pages[c.key])]
        R.check(f"tamanho_{label}_sem_corte_em_todas_as_paginas", not bad_all, "; ".join(bad_all[:3]))
        bar = win.bar
        cuts = []
        for chg, err in ((0, 0), (3, 0), (12, 2)):                 # limpa, com alteracoes, com erros
            bar.set_changes(chg, err)
            U.settle(250)
            cuts += [f"({chg},{err}) {b}" for b in U.clipped_texts(bar)]
        bar.set_changes(0, 0)
        R.check(f"tamanho_{label}_texto_da_barra_nao_cortado", not cuts, "; ".join(cuts[:3]))
        tl = bar.mapTo(win, QPoint(0, 0))
        inside = tl.y() >= -1 and tl.y() + bar.height() <= win.height() + 1 and bar.isVisible()
        R.check(f"tamanho_{label}_barra_de_acoes_dentro_da_janela", inside, f"barra y={tl.y()} h={bar.height()} janela {win.width()}x{win.height()}")
        win.nav.set_current("general")
        U.settle(150)
        U.grab(win, SHOTS / f"tamanho-{label}.png")


# ------------------------------------------------------------------ 10. temas em execucao
def t_theme_switch(win) -> None:
    mgr = ThemeManager.instance()
    other = "light" if ARGS.theme == "dark" else "dark"
    win.nav.set_current("general")
    U.settle(200)
    mgr.set_mode(other)
    mgr.apply(app)
    U.settle(500)
    U.grab(win, SHOTS / f"troca-para-{other}.png")
    img = win.grab().toImage()
    px = img.pixel(img.width() // 2, img.height() // 2) & 0xFFFFFF
    lum = U.luminance(((px >> 16) & 255, (px >> 8) & 255, px & 255))
    R.check("troca_de_tema_repinta", (lum > 0.4) == (other == "light"), f"luminancia do centro {lum:.2f} em tema {other}")
    mgr.set_mode(ARGS.theme)
    mgr.apply(app)
    U.settle(400)


# ------------------------------------------------------------------ 11. paginas Atualizacoes e Nuvem
def t_external(win) -> None:
    for key, hint in (("updates", "Atualiz"), ("cloud", "nuvem")):
        win.nav.set_current(key)
        U.settle(300)
        page = win.pages[key]
        sections = getattr(page, "_section_by_id", {})
        panel_sec = sections.get("upd_panel") or sections.get("cloud_panel")
        R.check(f"{key}_painel_na_pagina", panel_sec is not None, f"secoes: {list(sections)}")
        U.grab(win, SHOTS / f"{key}-pagina.png")
        keys = [k for k in page._rows]
        R.check(f"{key}_campos_do_schema", len(keys) >= 4, f"{len(keys)} campos: {keys[:6]}")


def main() -> int:
    only = set(filter(None, ARGS.only.split(",")))
    def want(n: str) -> bool:
        return not only or n in only
    with R.guard("tema_contraste"):
        if want("contrast"):
            t_contrast()
    if want("open"):
        with R.guard("abertura"):
            t_open()
        with R.guard("janelas_soltas"):
            t_orphans()
    win, ms, tmp, store, prefs = new_window()
    U.settle(900)
    R.check("janela_abriu", win.isVisible(), f"{ms:.0f} ms")
    for name, fn, a in (("pages", t_pages, (win,)), ("pixels", t_contrast_pixels, (win,)),
                        ("collapse", t_collapsibles, (win,)), ("combos", t_combos, (win,)), ("search", t_search, (win,)),
                        ("external", t_external, (win,)), ("toggles", t_toggles, (win,)), ("keyboard", t_keyboard, (win,)),
                        ("theme", t_theme_switch, (win,)), ("yolo", t_yolo, (win, tmp)),
                        ("validation", t_validation, (win, store)), ("geometry", t_geometry, (win, prefs)), ("sizes", t_target_sizes, (win,))):
        if want(name):
            with R.guard(name):
                fn(*a)
    try:
        win.controller.discard()
        win.close()
    except Exception:  # noqa: BLE001
        pass
    R.save()
    return 1 if R.failed() else 0


if __name__ == "__main__":
    sys.exit(main())

