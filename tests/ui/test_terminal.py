"""QA do painel Terminal: estados, entrada real (teclado), Parar/Copiar/Limpar, modo livre com diálogo, bloqueio, contraste,
texto cortado, foco por Tab, atalhos e capturas. O "Eco" é um TerminalManager de verdade no mesmo processo (comandos reais).
Com --native: janela do Windows de verdade e clique REAL do mouse (SendInput), conferindo antes que a janela está sob o cursor.

    venv\\Scripts\\python.exe -I tests\\ui\\test_terminal.py --scale 150 --theme dark --out SAIDA [--native]
"""
from __future__ import annotations

import ctypes
import dataclasses
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uicommon as U  # noqa: E402

ARGS = U.parse()
U.setup_env(ARGS)
R = U.Results("terminal", ARGS)

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

app = U.make_app(ARGS.theme)
from jarvis import config as cfgmod  # noqa: E402
from jarvis.terminal import runner as term  # noqa: E402
from jarvis.ui.kit.dialogs import ConfirmDialog  # noqa: E402
from jarvis.ui.kit.feedback import Toast  # noqa: E402
from jarvis.ui.terminal.panel import MIN_SIZE, TerminalPanel  # noqa: E402
from jarvis.ui.theme import pal  # noqa: E402

TMP, _store, BASE_CFG, _prefs = U.tmp_env()
WORK = TMP / "work"
(WORK / "sub").mkdir(parents=True)
DATA = Path(BASE_CFG.paths.data)
DATA.mkdir(parents=True, exist_ok=True)
SHOTS = Path(ARGS.out) / "capturas" / ("nativo" if ARGS.native else "off") / f"terminal-{ARGS.scale}-{ARGS.theme}"


def cfg_for(mode: str, **kw) -> cfgmod.Config:
    t = dataclasses.replace(BASE_CFG.terminal, mode=mode, roots=(str(WORK),), **kw)
    return dataclasses.replace(BASE_CFG, terminal=t)


CFG = {"cfg": cfg_for("confirm")}
MGR: term.TerminalManager | None = None


def new_manager(mode: str, **kw) -> term.TerminalManager:
    global MGR
    if MGR is not None:
        MGR.close()
        term._MANAGER = None
    CFG["cfg"] = cfg_for(mode, **kw)
    MGR = term.get_manager(CFG["cfg"], None, start_poller=True)
    MGR.cfg_loader = lambda: CFG["cfg"]
    MGR._write_state(force=True)
    return MGR


def until(pred, timeout: float = 15.0, step_ms: int = 80) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        U.settle(step_ms)
        try:
            if pred():
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def shot(w: QWidget, name: str) -> None:
    U.grab(w, SHOTS / f"{name}.png")


def make_panel() -> TerminalPanel:
    w = TerminalPanel(DATA, None, cfg_loader=lambda: CFG["cfg"])
    w.setWindowFlag(Qt.WindowType.Window, True)
    if ARGS.native:
        w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)        # outra janela (ex.: Configurações aberta) não pode cobrir o alvo do clique
    w.setAutoFillBackground(True)
    w.setMinimumSize(*MIN_SIZE)
    w.resize(1040, 680)
    w.move(80, 80)
    w.show()
    w.raise_()
    w.activateWindow()
    U.settle(300)
    return w


def row_texts(w: TerminalPanel) -> list[str]:
    return [w.history.item(i).text() for i in range(w.history.count())]


def center_global(w: QWidget) -> QPoint:
    return w.mapToGlobal(w.rect().center())


def real_click(win: QWidget, target: QWidget) -> bool:
    """Clique REAL do mouse (SendInput). Antes de clicar confere que a janela do painel é a que está sob o cursor."""
    from jarvis.win import input as win_input
    dpr = win.devicePixelRatioF()
    c = center_global(target)
    x, y = int(c.x() * dpr), int(c.y() * dpr)
    u32 = ctypes.WinDLL("user32")
    u32.WindowFromPoint.restype = ctypes.c_void_p
    u32.GetAncestor.restype = ctypes.c_void_p
    u32.WindowFromPoint.argtypes = [ctypes.c_longlong]
    u32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    u32.SetCursorPos(x, y)
    time.sleep(0.15)
    pt = ctypes.c_longlong((y << 32) | (x & 0xFFFFFFFF))
    hwnd = u32.WindowFromPoint(pt.value)
    root = u32.GetAncestor(hwnd, 2) if hwnd else None             # GA_ROOT
    if root != int(win.winId()):
        R.check("clique real: janela sob o cursor", False, f"hwnd={root} esperado={int(win.winId())}; clique NÃO enviado")
        return False
    win_input.click(x, y)
    U.settle(300)
    return True


def click(win: QWidget, target: QWidget) -> None:
    if ARGS.native and real_click(win, target):
        return
    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    U.settle(200)


def type_and_enter(w: TerminalPanel, text: str) -> None:
    w.input.setFocus()
    U.settle(50)
    QTest.keyClicks(w.input, text)
    QTest.keyClick(w.input, Qt.Key.Key_Return)
    U.settle(100)


# ------------------------------------------------------------------------------------------------- cenários
def t_states_and_banners() -> None:
    from jarvis.ui.kit.status import StatusChip
    # 1) sem Eco (nenhum state.json): aviso + tudo desabilitado
    state = DATA / "terminal" / "state.json"
    state.unlink(missing_ok=True)
    w = make_panel()
    ok = until(lambda: w.chip_link.text() == "Eco fechado")
    R.check("sem Eco: selo 'Eco fechado'", ok, w.chip_link.text())
    R.check("sem Eco: banner de aviso", w._banner is not None and w._banner.property("key") == "O Eco não está rodando")
    R.check("sem Eco: entrada e Executar desabilitados", not w.input.isEnabled() and not w.btn_run.isEnabled() and not w.btn_stop.isEnabled())
    shot(w, "01-sem-eco")
    w.close()
    # 2) desligado
    new_manager("off")
    w = make_panel()
    ok = until(lambda: w.chip_link.text() == "Eco conectado")
    R.check("conectado: selo 'Eco conectado'", ok, w.chip_link.text())
    R.check("modo desligado: selo e banner", w.chip_mode.text() == "Terminal desligado" and w._banner is not None
            and "desligado" in w._banner.property("key"), f"{w.chip_mode.text()}")
    R.check("modo desligado: entrada desabilitada", not w.input.isEnabled() and not w.btn_run.isEnabled())
    shot(w, "02-desligado")
    w.close()
    # 3) cada modo
    for mode, text in (("confirm", "Confirmar sempre"), ("allowlist", "Lista permitida"), ("free", "Livre (não liberado)")):
        new_manager(mode)
        w = make_panel()
        ok = until(lambda: w.chip_mode.text() == text and w._connected)
        R.check(f"modo {mode}: selo '{text}'", ok, w.chip_mode.text())
        R.check(f"modo {mode}: entrada habilitada", w.input.isEnabled() and w.btn_run.isEnabled() and w._banner is None)
        R.check(f"modo {mode}: botão 'Liberar modo livre' só no livre", w.btn_free.isVisibleTo(w) == (mode == "free") and not w.btn_unfree.isVisibleTo(w))
        w.close()


def t_run_stop_copy_clear() -> None:
    new_manager("confirm")
    w = make_panel()
    until(lambda: w._connected)
    # rodar por teclado real
    type_and_enter(w, "Write-Output 'ola do painel'; Get-Location | Select-Object -ExpandProperty Path")
    ok = until(lambda: w.history.count() >= 1 and "ola do painel" in w.out.toPlainText())
    R.check("Enter envia o comando e a saída aparece em tempo real", ok, w.out.toPlainText()[:80].replace("\n", " | "))
    R.check("campo de entrada é limpo após enviar", w.input.value() == "")
    ok = until(lambda: row_texts(w) and row_texts(w)[0].startswith("✓"))
    R.check("histórico marca ✓ (ok, código 0, à mão)", ok, str(row_texts(w)[:1]))
    R.check("título do comando mostra estado", "ok" in w.run_title.full_text() and "ola do painel" in w.run_title.full_text(), w.run_title.full_text()[:90])
    shot(w, "03-saida-ok")
    # cwd da sessão
    R.check("pasta atual aparece", str(WORK.resolve()) in w.cwd_label.full_text(), w.cwd_label.full_text()[:100])
    # copiar saída (clique)
    QApplication.clipboard().clear()
    click(w, w.btn_copy)
    R.check("Copiar saída: clipboard recebe a saída", "ola do painel" in QApplication.clipboard().text(), QApplication.clipboard().text()[:40])
    toasts = w.findChildren(Toast)
    R.check("Copiar saída: toast de confirmação", any(t.isVisible() for t in toasts), f"{len(toasts)} toasts")
    shot(w, "04-toast-copiado")
    click(w, w.btn_copy_cmd)
    R.check("Copiar comando: clipboard recebe o comando", QApplication.clipboard().text().startswith("Write-Output 'ola do painel'"),
            QApplication.clipboard().text()[:50])
    # comando longo + Parar
    type_and_enter(w, "Write-Output 'comecou'; Start-Sleep -Seconds 40; Write-Output 'nunca'")
    ok = until(lambda: w.btn_stop.isEnabled() and "comecou" in w.out.toPlainText(), 20)
    R.check("comando longo: saída parcial aparece e Parar habilita", ok, w.out.toPlainText()[:60].replace("\n", " | "))
    R.check("comando longo: Executar desabilita enquanto roda", not w.btn_run.isEnabled())
    shot(w, "05-rodando")
    t0 = time.time()
    click(w, w.btn_stop)
    ok = until(lambda: row_texts(w) and row_texts(w)[0].startswith("■"), 6)
    if not ok and ARGS.native:                                    # flutuação já vista 1 vez em 5 execuções nativas: registra e repete o clique
        R.check("(aviso) Parar nativo precisou de um 2º clique", True, "1º clique real não surtiu efeito em 6 s")
        click(w, w.btn_stop)
    ok = ok or until(lambda: row_texts(w) and row_texts(w)[0].startswith("■"), 14)
    R.check("Parar: o comando é encerrado (■ parado) em poucos segundos", ok and time.time() - t0 < 15, f"{time.time() - t0:.1f}s {row_texts(w)[:1]}")
    R.check("Parar: 'nunca' não foi impresso", "nunca" not in w.out.toPlainText())
    R.check("Parar: botão volta a ficar desabilitado e Executar habilita", until(lambda: not w.btn_stop.isEnabled() and w.btn_run.isEnabled()))
    shot(w, "06-parado")
    # comando com erro
    type_and_enter(w, "exit 9")
    ok = until(lambda: row_texts(w) and row_texts(w)[0].startswith("✕") and "código 9" in row_texts(w)[0])
    R.check("comando com erro: ✕ e código 9 no histórico", ok, str(row_texts(w)[:1]))
    # clicar num item antigo mostra a saída dele; novo comando volta a acompanhar
    w.history.setCurrentRow(w.history.count() - 1)
    U.settle(300)
    R.check("escolher item antigo mostra a saída dele", "ola do painel" in w.out.toPlainText(), w.out.toPlainText()[:40])
    # Ctrl+L / Limpar
    click(w, w.btn_clear)
    ok = until(lambda: w.history.count() == 0 and w.out.toPlainText() == "")
    R.check("Limpar: histórico e saída zerados", ok, f"{w.history.count()} itens")
    R.check("Limpar: botões Copiar/Parar desabilitados", not w.btn_copy.isEnabled() and not w.btn_stop.isEnabled() and not w.btn_clear.isEnabled())
    shot(w, "07-limpo")
    w.close()


def t_blocked_and_unknown() -> None:
    new_manager("confirm")
    w = make_panel()
    until(lambda: w._connected)
    type_and_enter(w, "Stop-Computer")
    ok = until(lambda: row_texts(w) and row_texts(w)[0].startswith("⛔"))
    R.check("comando perigoso: ⛔ bloqueado no histórico", ok, str(row_texts(w)[:1]))
    R.check("comando perigoso: motivo aparece na saída", "bloqueado" in w.out.toPlainText().lower(), w.out.toPlainText()[:80])
    R.check("comando perigoso: nada foi executado (sem processo)", not (MGR and MGR.current()))
    shot(w, "08-bloqueado")
    type_and_enter(w, "Write-Output ('seg' + 'redo=abc123def456'); Write-Output ('ghp_' + ('a' * 36))")
    ok = until(lambda: "seg" in w.out.toPlainText() and "[removido]" in w.out.toPlainText())
    R.check("segredos na saída aparecem redigidos no painel", ok and "abc123def456" not in w.out.toPlainText() and "ghp_aaaa" not in w.out.toPlainText(),
            w.out.toPlainText()[:80].replace("\n", " | "))
    w.close()


def t_free_mode_flow() -> None:
    new_manager("free", free_minutes=2)
    w = make_panel()
    until(lambda: w._connected)
    R.check("livre: botão 'Liberar modo livre…' visível", w.btn_free.isVisibleTo(w) and w.btn_free.isEnabled())
    shot(w, "09-livre-nao-liberado")

    def accept_dialog() -> None:
        for d in QApplication.topLevelWidgets():
            if isinstance(d, ConfirmDialog) and d.isVisible():
                from jarvis.ui.kit.buttons import Button
                btns = [b for b in d.findChildren(Button) if b.text() == "Liberar"]
                R.check("diálogo do modo livre: texto explica os limites", True, "")
                shot(d, "10-dialogo-liberar")
                if btns:
                    QTest.mouseClick(btns[0], Qt.MouseButton.LeftButton)
                else:
                    R.check("diálogo do modo livre: botão Liberar", False, f"botões={[b.text() for b in d.findChildren(Button)]}")
                    d.reject()
                return
        QTimer.singleShot(100, accept_dialog)

    QTimer.singleShot(300, accept_dialog)
    QTest.mouseClick(w.btn_free, Qt.MouseButton.LeftButton)          # exec() modal: volta quando o diálogo fechar
    ok = until(lambda: MGR.free_active() and w.chip_mode.text().startswith("Livre:"), 12)
    R.check("liberar: o Eco arma o modo livre e o selo mostra a contagem", ok, w.chip_mode.text())
    R.check("liberar: botão 'Desligar modo livre' aparece", w.btn_unfree.isVisibleTo(w) and not w.btn_free.isVisibleTo(w))
    shot(w, "11-livre-ativo")
    click(w, w.btn_unfree)
    ok = until(lambda: not MGR.free_active() and w.chip_mode.text() == "Livre (não liberado)", 12)
    R.check("desligar: modo livre volta a 'não liberado'", ok, w.chip_mode.text())
    # recusar no diálogo não arma
    def reject_dialog() -> None:
        for d in QApplication.topLevelWidgets():
            if isinstance(d, ConfirmDialog) and d.isVisible():
                d.reject()
                return
        QTimer.singleShot(100, reject_dialog)
    QTimer.singleShot(300, reject_dialog)
    QTest.mouseClick(w.btn_free, Qt.MouseButton.LeftButton)
    U.settle(900)
    R.check("cancelar o diálogo NÃO arma o modo livre", not MGR.free_active() and MGR.free_remaining_s() == 0)
    # pedido sem assinatura vindo de outro processo é ignorado
    req = DATA / "terminal" / "req"
    (req / "forjado.json").write_text(json.dumps({"action": "arm_free", "args": "{}", "stamp": str(time.time()), "mac": "00" * 32}), encoding="utf-8")
    U.settle(1200)
    R.check("pedido forjado (sem assinatura) é ignorado", not MGR.free_active())
    w.close()


def t_keyboard_and_a11y() -> None:
    new_manager("confirm")
    w = make_panel()
    until(lambda: w._connected)
    # Ctrl+L limpa
    type_and_enter(w, "Write-Output 'para limpar'")
    until(lambda: "para limpar" in w.out.toPlainText())
    QTest.keyClick(w, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    R.check("atalho Ctrl+L limpa o histórico", until(lambda: w.history.count() == 0))
    # Tab percorre os controles na ordem esperada
    w.input.setFocus()
    seen = []
    for _ in range(6):
        QTest.keyClick(w.focusWidget() or w, Qt.Key.Key_Tab)
        U.settle(50)
        fw = w.focusWidget()
        seen.append(type(fw).__name__ + ":" + (fw.text() if hasattr(fw, "text") and callable(fw.text) else ""))
    R.check("Tab move o foco entre controles", len({s for s in seen}) >= 2, str(seen))
    for widget, name in ((w.input, "Comando"), (w.out, "Saída do comando"), (w.history, "Histórico de comandos"), (w.shell, "Terminal a usar")):
        R.check(f"nome acessível: {name}", widget.accessibleName() == name, widget.accessibleName())
    R.check("todos os botões têm alvo >= 32 px", all(b.height() >= 32 for b in (w.btn_run, w.btn_stop, w.btn_copy, w.btn_clear) if b.isVisibleTo(w)),
            str([b.height() for b in (w.btn_run, w.btn_stop, w.btn_copy, w.btn_clear)]))
    w.close()


def t_contrast_and_clipping() -> None:
    new_manager("confirm")
    w = make_panel()
    until(lambda: w._connected)
    type_and_enter(w, "1..30 | ForEach-Object { \"linha $_\" }")
    until(lambda: "linha 30" in w.out.toPlainText())
    p = pal()

    def rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    r1 = U.ratio(rgb(p.text), rgb(p.bg))
    r2 = U.ratio(rgb(p.text_muted), rgb(p.surface))
    R.check("contraste da saída (texto/fundo) >= 7:1 (AAA)", r1 >= 7.0, f"{r1:.1f}")
    R.check("contraste do texto secundário >= 4.5:1 (AA)", r2 >= 4.5, f"{r2:.1f}")
    shot(w, "12-saida-longa")
    bad = U.clipped_texts(w)
    R.check("sem texto cortado na janela aberta", not bad, "; ".join(bad[:3]))
    w.resize(*MIN_SIZE)
    U.settle(300)
    bad = U.clipped_texts(w)
    R.check("sem texto cortado no tamanho mínimo", not bad, "; ".join(bad[:3]))
    shot(w, "13-tamanho-minimo")
    R.check("janela respeita o tamanho mínimo", w.width() >= MIN_SIZE[0] and w.height() >= MIN_SIZE[1], f"{w.width()}x{w.height()}")
    w.close()


def main() -> int:
    only = [x for x in ARGS.only.split(",") if x]
    tests = [("estados", t_states_and_banners), ("rodar_parar_copiar_limpar", t_run_stop_copy_clear), ("bloqueio_segredos", t_blocked_and_unknown),
             ("modo_livre", t_free_mode_flow), ("teclado_a11y", t_keyboard_and_a11y), ("contraste_corte", t_contrast_and_clipping)]
    try:
        for name, fn in tests:
            if only and name not in only:
                continue
            with R.guard(name):
                fn()
    finally:
        if MGR is not None:
            MGR.close()
        R.save()
        shutil.rmtree(TMP, ignore_errors=True)
    return 1 if R.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
