"""QA da Ilha: estados, tamanhos, 4 posicoes (topo acoplado/flutuante, lateral direita/esquerda), alfinete, avisos (flash/erro),
popup de permissao (Sim/Nao por clique, Enter/Esc, tempo esgotado), aviso de uso de nuvem, animacoes (duracao, monotonia,
cadencia de quadros), teclado e (com --native) cliques REAIS por SendInput na janela real.

    venv\\Scripts\\python.exe -I tests\\ui\\test_island.py --scale 150 --theme dark --out SAIDA [--native]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uicommon as U  # noqa: E402

ARGS = U.parse()
U.setup_env(ARGS)
R = U.Results("island", ARGS)

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = U.make_app(ARGS.theme)

from jarvis.core.events import EventBus  # noqa: E402
from jarvis.ui.island.bridge import IslandBridge, LevelFeed  # noqa: E402
from jarvis.ui.island.conf import IslandConfig  # noqa: E402
from jarvis.ui.island.dsp import SyntheticSource  # noqa: E402
from jarvis.ui.island.tokens import IslandSize, IslandState  # noqa: E402
from jarvis.ui.island.window import IslandWindow  # noqa: E402

SHOTS = Path(ARGS.out) / "capturas" / ("nativo" if ARGS.native else "off") / f"ilha-{ARGS.scale}-{ARGS.theme}"
NATIVE = ARGS.native


def make(mode: str = "docked", **kw) -> IslandWindow:
    cfg = IslandConfig(mode=mode, autohide=kw.pop("autohide", False), **kw)
    w = IslandWindow(SyntheticSource(), cfg=cfg)
    w.start()
    U.settle(350)
    return w


def shot(w: IslandWindow, name: str) -> Path:
    p = SHOTS / f"{name}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    w.grab().save(str(p), "PNG")
    return p


def opaque_pixels(w: IslandWindow) -> int:
    img = w.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            if (img.pixel(x, y) >> 24) > 40:
                n += 1
    return n


def body_center(w: IslandWindow, b) -> QPoint:
    m = w._margin()
    return QPoint(int(m + b.x + b.w / 2), int(m + b.y + b.h / 2))


def leave(w: IslandWindow) -> None:
    """Tira o mouse de cima da Ilha (no nativo move o cursor real para longe; offscreen envia o evento Leave)."""
    if NATIVE:
        from jarvis.win import input as winput
        sg = w.screen().geometry()
        dpr = w.devicePixelRatioF()
        winput.move_to(int(sg.center().x() * dpr), int((sg.bottom() - 40) * dpr))
    else:
        from PySide6.QtGui import QCursor
        sg = w.screen().geometry()
        QCursor.setPos(sg.center().x(), sg.bottom() - 20)
        QApplication.sendEvent(w, QEvent(QEvent.Type.Leave))
    U.settle(120)


def click_btn(w: IslandWindow, b) -> None:
    """Clique pela fila de eventos do Qt (offscreen) ou REAL por SendInput (nativo)."""
    pos = body_center(w, b)
    if NATIVE:
        from jarvis.win import input as winput
        g = w.mapToGlobal(pos)
        dpr = w.devicePixelRatioF()
        U.safe_move(int(g.x() * dpr), int(g.y() * dpr))
        U.settle(80)
        U.safe_click(int(g.x() * dpr), int(g.y() * dpr))
        U.settle(250)
    else:
        QTest.mouseMove(w, pos)
        U.settle(60)
        QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
        U.settle(120)


# ------------------------------------------------------------------ 1. matriz modo x tamanho x estado
def t_matrix() -> None:
    sizes = (IslandSize.COMPACT, IslandSize.MEDIUM, IslandSize.LARGE)
    states = (IslandState.IDLE, IslandState.LISTENING, IslandState.TRANSCRIBING, IslandState.THINKING, IslandState.ACTING,
              IslandState.SPEAKING, IslandState.ERROR)
    for mode in ("docked", "floating", "dock_right", "dock_left"):
        w = make(mode)
        scr = w.screen().geometry()
        bad_geo, blank = [], []
        for sz in sizes:
            w.pin_size(sz)
            for st in states:
                w.set_transcript("abre o bloco de notas e escreve a lista de compras de hoje")
                w.set_reply("Pronto, abri o bloco de notas e escrevi a lista: leite, pão, ovos e café.")
                if st is IslandState.ERROR:
                    w.set_error("Não consegui falar com o modelo agora.")
                elif st is IslandState.ACTING:
                    w.set_action("abrir_app", "Abrindo o Bloco de Notas", "start")
                    w.set_state(st)
                else:
                    w.set_state(st)
                U.settle(420)
                fg = w.frameGeometry()
                m = w._margin()
                body = fg.adjusted(m, m, -m, -m)                   # a moldura inclui a margem translucida; o corpo visivel e o que conta
                inside = scr.adjusted(-2, -2, 2, 2).contains(body) or (not NATIVE and scr.width() < 700)   # tela virtual < 700 px e so de estresse
                if not inside:
                    bad_geo.append(f"{sz.name}/{st.name} corpo {body.getRect()} fora de {scr.getRect()}")
                if opaque_pixels(w) < 200:
                    blank.append(f"{sz.name}/{st.name}")
                if st in (IslandState.IDLE, IslandState.ERROR, IslandState.ACTING):
                    shot(w, f"{mode}-{sz.name.lower()}-{st.name.lower()}")
        R.check(f"matriz_{mode}_dentro_da_tela", not bad_geo, "; ".join(bad_geo[:3]))
        R.check(f"matriz_{mode}_pinta_algo", not blank, "; ".join(blank[:3]))
        if mode in ("dock_right", "dock_left"):
            fg = w.frameGeometry()
            edge_ok = abs(fg.right() - scr.right()) <= 24 if mode == "dock_right" else abs(fg.left() - scr.left()) <= 24
            R.check(f"matriz_{mode}_encostada_na_borda", edge_ok, f"frame {fg.getRect()} tela {scr.getRect()}")
        if mode == "docked":
            fg = w.frameGeometry()
            R.check("matriz_docked_no_topo_centralizada", fg.top() <= scr.top() + 24 and abs(fg.center().x() - scr.center().x()) <= 6,
                    f"frame {fg.getRect()}")
        w.close()


# ------------------------------------------------------------------ 2. animacoes
def t_animation() -> None:
    w = make("docked")
    w.pin_size(IslandSize.COMPACT)
    U.settle(500)
    samples: list[tuple[float, float, float]] = []
    t0 = time.perf_counter()
    w.pin_size(IslandSize.LARGE)
    while time.perf_counter() - t0 < 1.2:
        app.processEvents()
        samples.append((time.perf_counter() - t0, w._cur[0], w._cur[1]))
        time.sleep(0.004)
    widths = [s[1] for s in samples]
    final = widths[-1]
    reach = next((t for t, wd, _h in samples if abs(wd - final) < 1.0), 9.9)
    R.check("morfose_compacta_para_grande_chega_ao_fim", final > widths[0] + 20, f"largura {widths[0]:.0f} -> {final:.0f}")
    R.check("morfose_duracao_razoavel", 0.12 <= reach <= 0.8, f"completa em {reach*1000:.0f} ms (esperado 120-800)")
    span = max(widths) - min(widths)
    back = max((a - b) for a, b in zip(widths, widths[1:]))
    R.check("morfose_sem_cintilar", back <= 0.08 * span, f"maior recuo {back:.2f} px de {span:.0f} (overshoot da curva elastica e intencional; limite 8%)")
    changes = [t for (t, wd, _), (_, wd2, _) in zip(samples, samples[1:]) if wd2 != wd]
    gaps = [b - a for a, b in zip(changes, changes[1:]) if b - a < 0.2]
    worst = max(gaps) if gaps else 0
    R.check("morfose_cadencia_de_quadros", (not gaps) or worst < 0.06, f"{len(changes)} quadros distintos; maior intervalo {worst*1000:.0f} ms")
    # presenca (aparecer/sumir)
    w2 = make("docked", autohide=True, hide_delay_s=0.5)
    w2.reveal()
    U.settle(500)
    R.check("presenca_aparece", w2.isVisible() and w2.presence > 0.9, f"presenca {w2.presence:.2f}")
    t0 = time.perf_counter()
    w2.set_state(IslandState.IDLE)
    while w2.isVisible() and time.perf_counter() - t0 < 9:
        app.processEvents()
        time.sleep(0.01)
    R.check("presenca_some_sozinha", not w2.isVisible(), f"sumiu em {time.perf_counter()-t0:.1f} s (hide_delay 0.5 + saida)")
    w2.close()
    # movimento reduzido: sem animacao, vai direto
    from jarvis.ui.kit.platform import set_motion_override
    set_motion_override(False)
    w3 = make("docked")
    w3.pin_size(IslandSize.COMPACT)
    U.settle(300)
    w3.pin_size(IslandSize.LARGE)
    U.settle(60)
    R.check("movimento_reduzido_vai_direto", w3._morph is None or abs(w3._cur[0] - w3._dim(IslandSize.LARGE)[0]) < 2, f"morph={w3._morph is not None}")
    set_motion_override(True)
    w3.close()
    w.close()


# ------------------------------------------------------------------ 3. popup de permissao
def t_permission() -> None:
    w = make("docked")
    ans: list[bool] = []
    w.confirm_answered.connect(lambda v: ans.append(v))
    w.ask_confirmation("Apagar 3 arquivos da pasta Downloads?", 20, "c1")
    U.settle(700)
    R.check("popup_aparece_no_estado_confirmando", w.state is IslandState.CONFIRMING and w.isVisible(), f"estado {w.state.name}")
    R.check("popup_botoes_sim_nao_visiveis", w.b_yes.visible and w.b_no.visible and w.b_yes.w > 20 and w.b_no.w > 20,
            f"yes {w.b_yes.rect().getRect()} no {w.b_no.rect().getRect()}")
    shot(w, "popup-permissao")
    click_btn(w, w.b_yes)
    R.check("popup_clique_em_sim", ans == [True], f"respostas {ans}")
    U.settle(300)
    ans.clear()
    w.ask_confirmation("Digitar 5 caracteres no Bloco de Notas?", 20, "c2")
    U.settle(600)
    click_btn(w, w.b_no)
    R.check("popup_clique_em_nao", ans == [False], f"respostas {ans}")
    ans.clear()
    w.ask_confirmation("Enter/Esc?", 20, "c3")
    U.settle(500)
    w.setFocus()
    QTest.keyClick(w, Qt.Key.Key_Escape)
    U.settle(100)
    R.check("popup_esc_nega", ans == [False], f"{ans}")
    ans.clear()
    w.ask_confirmation("Enter?", 20, "c4")
    U.settle(500)
    QTest.keyClick(w, Qt.Key.Key_Return)
    U.settle(100)
    R.check("popup_enter_confirma", ans == [True], f"{ans}")
    # tempo esgotado: sem resposta = Nao (nunca Sim)
    ans.clear()
    w.ask_confirmation("Vai expirar?", 1, "c5")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 4 and w.state is IslandState.CONFIRMING:
        U.settle(50)
    R.check("popup_tempo_esgotado_nunca_aprova", True not in ans, f"estado {w.state.name} respostas {ans}")
    # contador desce
    w.ask_confirmation("Contagem?", 10, "c6")
    U.settle(1300)
    R.check("popup_contador_decresce", 0 < w.confirm_left < 10 or w.confirm_frac() < 0.99, f"restam {w.confirm_left}s frac {w.confirm_frac():.2f}")
    # teclado local: Tab percorre botoes
    w.setFocus()
    seq = []
    for _ in range(3):
        QTest.keyClick(w, Qt.Key.Key_Tab)
        seq.append(w._focus_btn.key if w._focus_btn else None)
    R.check("popup_tab_percorre_botoes", len(set(seq)) >= 2, f"foco: {seq}")
    w._answer(False)
    w.close()


# ------------------------------------------------------------------ 4. avisos (toast): flash, erro, nuvem
def t_notices() -> None:
    w = make("docked", autohide=True, hide_delay_s=1.0)
    w.flash("Microfone silenciado", hold=1.0)
    U.settle(400)
    R.check("aviso_flash_mostra", w.isVisible() and w._flash_label == "Microfone silenciado", f"visivel={w.isVisible()}")
    shot(w, "aviso-flash")
    U.settle(1800)
    R.check("aviso_flash_some_sozinho", w._flash_label == "", f"label={w._flash_label!r}")
    w.set_error("O microfone parou de enviar som.")
    U.settle(500)
    R.check("aviso_erro_mostra_texto", w.state is IslandState.ERROR and "microfone" in w.error_text, w.state.name)
    shot(w, "aviso-erro")
    w.set_yolo(60, flash=True)
    U.settle(400)
    shot(w, "aviso-yolo")
    R.check("aviso_yolo_visivel", w.isVisible() and w.yolo_left() is not None, f"restam {w.yolo_left()}")
    w.set_yolo(None, flash=True)
    w.close()
    # aviso de uso de nuvem: pelo EventBus real + bridge (action_step da ferramenta "nuvem")
    bus = EventBus()
    w2 = make("docked", autohide=True)
    IslandBridge(w2, bus, feed=LevelFeed())
    bus.publish("state", state="thinking")
    bus.publish("action_step", tool="nuvem", text="Nuvem: Google Antigravity", status="start", risk=0, result="")
    U.settle(900)
    act = w2.action or {}
    R.check("aviso_nuvem_chega_na_ilha", act.get("tool") == "nuvem" and "nuvem" in act.get("text", "").lower(), f"acao={act}")
    R.check("aviso_nuvem_ilha_visivel", w2.isVisible(), "")
    shot(w2, "aviso-nuvem")
    from jarvis.ui.island.link import sanitize
    out = sanitize("action_step", {"tool": "nuvem", "text": "Nuvem: X", "status": "start", "result": ""})
    R.check("aviso_nuvem_passa_pelo_filtro_do_link", bool(out) and out["tool"] == "nuvem", f"{out}")
    # confirmacao vinda pelo barramento -> popup -> resposta volta ao nucleo
    got: list[tuple[str, bool]] = []
    w3 = make("docked", autohide=True)
    IslandBridge(w3, bus, feed=LevelFeed(), on_confirm_answer=lambda i, v: got.append((i, v)))
    bus.publish("confirm_request", id="abc", text="O agente Google Antigravity, na nuvem, quer abrir o Bloco de Notas", timeout_s=20, risk=2)
    U.settle(900)
    R.check("confirmacao_pelo_barramento_abre_popup", w3.state is IslandState.CONFIRMING, w3.state.name)
    click_btn(w3, w3.b_yes)
    U.settle(200)
    R.check("confirmacao_resposta_volta_ao_nucleo", got == [("abc", True)], f"{got}")
    bus.publish("confirm_done", id="abc")
    U.settle(500)
    R.check("popup_fecha_quando_o_nucleo_conclui", w3.state is not IslandState.CONFIRMING, w3.state.name)
    w2.close()
    w3.close()


# ------------------------------------------------------------------ 5. alfinete, escuta, mudo, YOLO (nunca por clique)
def t_buttons() -> None:
    w = make("docked", autohide=True, hide_delay_s=0.6)
    pins: list[bool] = []
    w.pin_toggled.connect(lambda v: pins.append(v))
    w.reveal()
    U.settle(700)
    w.pin_size(IslandSize.LARGE)
    U.settle(700)
    if not w.b_pin.visible:
        w.pin_size(IslandSize.MEDIUM)
        U.settle(700)
    R.check("alfinete_botao_visivel", w.b_pin.visible, f"tamanho {w.size_target.name}")
    click_btn(w, w.b_pin)
    R.check("alfinete_clique_fixa", w.pinned and pins == [True], f"pinned={w.pinned} sinais={pins}")
    w.set_state(IslandState.IDLE)
    leave(w)
    U.settle(2200)
    R.check("alfinete_fixada_nao_some", w.isVisible(), "visivel apos 2,2 s (hide_delay 0,6)")
    shot(w, "alfinete-fixada")
    click_btn(w, w.b_pin)
    R.check("alfinete_clique_solta", (not w.pinned) and pins == [True, False], f"{pins}")
    leave(w)
    t0 = time.monotonic()
    while w.isVisible() and time.monotonic() - t0 < 6:
        U.settle(50)
    R.check("alfinete_solta_volta_a_esconder", not w.isVisible(), f"{time.monotonic()-t0:.1f} s")
    w.reveal()
    U.settle(700)
    # mudo
    muted: list[bool] = []
    w.mute_toggled.connect(lambda v: muted.append(v))
    w.pin_size(IslandSize.LARGE)
    U.settle(700)
    if w.b_mute.visible:
        click_btn(w, w.b_mute)
        R.check("mudo_clique", muted == [True] and w.muted, f"{muted}")
        click_btn(w, w.b_mute)
        R.check("mudo_clique_desliga", muted == [True, False], f"{muted}")
    else:
        R.check("mudo_botao_visivel", False, "botao mudo invisivel no tamanho grande")
    # YOLO nunca liga por clique
    req: list[str] = []
    w.settings_requested.connect(lambda s: req.append(s))
    yolo_on: list[object] = []
    if w.b_yolo.visible:
        click_btn(w, w.b_yolo)
        R.check("yolo_clique_so_abre_configuracoes", req == ["permissions"] and w.yolo_left() is None, f"pedidos {req}, yolo={w.yolo_left()}")
    else:
        R.check("yolo_botao_visivel_no_grande", False, "botao YOLO invisivel")
    if w.b_cfg.visible:
        req.clear()
        click_btn(w, w.b_cfg)
        R.check("engrenagem_abre_configuracoes", req == [""], f"{req}")
    # escuta aberta (otimista + reversao se o nucleo nao confirma)
    mode: list[str] = []
    w.listen_toggled.connect(lambda v: mode.append(v))
    if w.b_listen.visible:
        click_btn(w, w.b_listen)
        R.check("escuta_aberta_clique_emite", mode == ["open"] and w.listen_open, f"{mode}")
        U.settle(3400)
        R.check("escuta_aberta_reverte_sem_confirmacao_do_nucleo", not w.listen_open, f"listen_open={w.listen_open}")
    w.close()


# ------------------------------------------------------------------ 6. clique no corpo alterna tamanho
def t_body_click() -> None:
    w = make("docked")
    U.settle(300)
    first = w.size_target
    pos = QPoint(w.width() // 2, w._margin() + 4)
    if NATIVE:
        from jarvis.win import input as winput
        g = w.mapToGlobal(pos)
        dpr = w.devicePixelRatioF()
        U.safe_click(int(g.x() * dpr), int(g.y() * dpr))
    else:
        QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    U.settle(700)
    R.check("clique_no_corpo_muda_tamanho", w.size_target is not first or w._pinned is not None, f"{first.name} -> {w.size_target.name}")
    w.close()


# ------------------------------------------------------------------ 7. nativo: nao rouba foco
def t_native_focus() -> None:
    import ctypes
    u = ctypes.windll.user32
    before = u.GetForegroundWindow()
    w = make("docked")
    w.reveal()
    U.settle(800)
    after = u.GetForegroundWindow()
    R.check("nativo_ilha_nao_rouba_o_foco", before == after or after != int(w.winId()), f"antes={before} depois={after} ilha={int(w.winId())}")
    ex = u.GetWindowLongW(int(w.winId()), -20)
    R.check("nativo_ilha_topmost", bool(ex & 0x8), f"exstyle={ex:#x}")
    R.check("nativo_ilha_toolwindow_sem_barra_de_tarefas", bool(ex & 0x80), "")
    w.close()


def main() -> int:
    only = set(filter(None, ARGS.only.split(",")))
    for name, fn in (("matrix", t_matrix), ("animation", t_animation), ("permission", t_permission), ("notices", t_notices),
                     ("buttons", t_buttons), ("body", t_body_click), *((("focus", t_native_focus),) if NATIVE else ())):
        if only and name not in only:
            continue
        with R.guard(name):
            fn()
    R.save()
    return 1 if R.failed() else 0


if __name__ == "__main__":
    sys.exit(main())

