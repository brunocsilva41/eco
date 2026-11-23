"""QA da etapa "Preparar o computador" do assistente: janela real, clique REAL do mouse (SendInput) com --native.

    venv\\Scripts\\python.exe -I tests\\ui\\test_setup_prepare.py --scale 150 --theme dark --out SAIDA [--native]

Raiz de dados TEMPORÁRIA (nada é gravado na instalação nem no repositório). Nada de terceiros é instalado: o download
oficial e o instalador são substituídos por dublês; a assinatura real e o download real ficam em tests\\prepare_live_proof.py.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uicommon as U  # noqa: E402

ARGS = U.parse()
U.setup_env(ARGS)
R = U.Results("setup_prepare", ARGS)

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

app = U.make_app(ARGS.theme)
DPR = app.primaryScreen().devicePixelRatio()

from jarvis.config import ROOT, from_dict  # noqa: E402
from jarvis.setup import prereqs as P  # noqa: E402
from jarvis.setup.manifest import load_manifest  # noqa: E402
from jarvis.setup.pages_prepare import PrepRow  # noqa: E402
from jarvis.setup.state import SetupState  # noqa: E402
from jarvis.setup.widgets import Ctx  # noqa: E402
from jarvis.setup.wizard import WizardWindow  # noqa: E402
from jarvis.ui.kit.buttons import Button  # noqa: E402
from jarvis.ui.kit.feedback import InlineBanner  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

# O runner do CI (e muitos PCs) não tem o Ollama: um executável de mentira (cópia do cmd.exe) no PATH prova a detecção automática.
if shutil.which("ollama") is None:
    _stub = Path(tempfile.mkdtemp(prefix="eco_stub_"))
    shutil.copy(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe", _stub / "ollama.exe")
    os.environ["PATH"] = str(_stub) + os.pathsep + os.environ.get("PATH", "")

WIN: list = [None]
SHOTS = Path(ARGS.out) / "capturas" / ("nativo" if ARGS.native else "off") / f"setup-preparar-{ARGS.scale}-{ARGS.theme}"
TMP = Path(tempfile.mkdtemp(prefix="eco-prep-"))


def shot(w: QWidget, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    w.grab().save(str(SHOTS / f"{name}.png"), "PNG")


def reveal(widget: QWidget) -> None:
    """Rola a área de rolagem até o widget aparecer inteiro (clique real só funciona no que está à vista)."""
    from PySide6.QtWidgets import QScrollArea
    w = widget.parentWidget()
    while w is not None and not isinstance(w, QScrollArea):
        w = w.parentWidget()
    if w is not None:
        w.ensureWidgetVisible(widget, 20, 60)
        U.settle(120)


def type_text(edit: QWidget, text: str) -> None:
    """Digita no campo: teclado REAL (SendInput unicode) com --native, senão QTest. Seleciona tudo antes (substitui)."""
    click(edit, 120)
    if ARGS.native:
        from jarvis.core.cancel import CancelToken
        from jarvis.win import input as winput
        from jarvis.win.keys import parse_combo
        U.require_foreground()
        winput.send_combo(parse_combo("ctrl+a"))
        U.settle(80)
        if text:
            winput.send_text(text, CancelToken())
        else:
            winput.tap_key(0x08)                                 # Backspace
    else:
        edit.selectAll()
        if text:
            if text.isascii():
                QTest.keyClicks(edit, text)
            else:
                edit.insert(text)               # QTest.keyClicks derruba o Qt offscreen com letras acentuadas; o modo --native digita de verdade
        else:
            QTest.keyClick(edit, Qt.Key.Key_Backspace)
    U.settle(150)


def click(widget: QWidget, settle: int = 300) -> None:
    """Clique no centro do widget: real (SendInput) com --native, senão QTest."""
    reveal(widget)
    if ARGS.native:
        g = widget.mapToGlobal(widget.rect().center())
        x, y = int(round(g.x() * DPR)), int(round(g.y() * DPR))
        for attempt in range(4):                       # outra janela (ex.: aviso de outro programa) pode cobrir o ponto: reergue e tenta de novo
            try:
                U.safe_move(x, y)
                U.settle(60)
                U.safe_click(x, y)
                break
            except RuntimeError as exc:
                if attempt == 3:
                    raise
                U.raise_test_window(WIN[0])
                U.settle(400)
                print("  (clique repetido:", str(exc)[:90], ")", flush=True)
    else:
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, widget.rect().center())
    U.settle(settle)


def modal_click(text: str, delay_ms: int = 600) -> None:
    """Agenda, para DENTRO do laço modal, o clique no botão `text` do diálogo ativo."""
    def go() -> None:
        dlg = QApplication.activeModalWidget()
        if dlg is None:
            R.check(f"modal '{text}' apareceu", False, "nenhum diálogo modal ativo")
            return
        btn = next((b for b in dlg.findChildren(Button) if b.text() == text), None)
        if btn is None:
            R.check(f"modal '{text}' tem o botão", False, f"botões: {[b.text() for b in dlg.findChildren(Button)]}")
            dlg.reject()
            return
        shot(dlg, f"dialogo-{text.replace(' ', '_')[:24]}")
        if ARGS.native:
            g = btn.mapToGlobal(btn.rect().center())
            U.safe_click(int(round(g.x() * DPR)), int(round(g.y() * DPR)))
        else:
            QTest.mouseClick(btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, btn.rect().center())
    QTimer.singleShot(delay_ms, go)
    QTimer.singleShot(9000, lambda: QApplication.activeModalWidget() and QApplication.activeModalWidget().reject())


def row_button(page, key: str) -> Button | None:
    for r in page.findChildren(PrepRow):
        if r.item.key == key:
            return r.button
    return None


def main() -> None:
    man = load_manifest(ROOT)
    state = SetupState()
    ctx = Ctx(root=TMP, manifest=man, state=state, cfg=from_dict({}), repair=False, demo=False)    # demo=False: a etapa checa sozinha ao abrir, como no uso real
    run = {"installer": [], "fetch": 0}
    ctx.extra["prep_run_installer"] = lambda path, args, elevate: run["installer"].append((str(path), args, elevate)) or 0
    win = WizardWindow(ctx)
    win.setProperty("autoconfirm", None)              # diálogos de confirmação REAIS
    WIN[0] = win
    win.show()
    if ARGS.native:
        U.raise_test_window(win)
        U.set_target(win)
    U.settle(300)
    page = win.pages["prepare"]

    with R.guard("abrir etapa"):
        with U.OrphanProbe() as probe:
            win.show_page("prepare")
            U.wait_until(lambda: not page._busy and bool(page.items), 60.0)
        R.check("checagem real termina e lista itens", bool(page.items), f"{len(page.items)} itens")
        R.check("sem janelas soltas ao abrir a etapa", probe.total() == 0, str(probe.hits))
        keys = {i.key for i in page.items}
        R.check("itens esperados", {"folders", "vcruntime", "gpu", "llama", "internet", "models", "ollama", "lmstudio"} <= keys, str(sorted(keys)))
        R.check("botões habilitados em repouso", page.btn_again.isEnabled() and page.btn_repair.isEnabled())
        shot(win, "01-aberta")
        R.check("sem texto cortado", not U.clipped_texts(page), str(U.clipped_texts(page)[:3]))

    with R.guard("trilho"):
        R.check("etapa 'Preparar o computador' no trilho", "Preparar o computador" in [r.title for r in win.rail.rows.values()])
        R.check("11 passos", len(win.rail.rows) == 11, str(len(win.rail.rows)))

    with R.guard("verificar de novo"):
        seen = {"busy": [], "shown": 0}
        orig_busy, orig_show = page._set_busy, page.show_items
        page._set_busy = lambda b: (seen["busy"].append(b), orig_busy(b))[1]                      # type: ignore[method-assign]
        page.show_items = lambda items: (seen.__setitem__("shown", seen["shown"] + 1), orig_show(items))[1]   # type: ignore[method-assign]
        click(page.btn_again, 200)
        U.wait_until(lambda: seen["shown"] >= 1, 60.0)
        page._set_busy, page.show_items = orig_busy, orig_show
        R.check("durante a checagem os botões travam e depois liberam", seen["busy"][:1] == [True] and seen["busy"][-1] is False, str(seen["busy"]))
        R.check("clique em 'Verificar de novo' refaz as linhas", seen["shown"] == 1 and len(page.findChildren(PrepRow)) >= 8, f"{seen['shown']} vez(es)")

    with R.guard("relatório"):
        click(page.btn_report, 300)
        rp = TMP / "data" / "setup" / "prepare-report.json"
        R.check("'Salvar relatório' grava o arquivo", rp.is_file(), str(rp))
        text = rp.read_text(encoding="utf-8") if rp.is_file() else ""
        data = json.loads(text) if text else {}
        R.check("relatório com itens e sem segredos", bool(data.get("items")) and "token" not in text.lower())
        R.check("relatório traz versão e origem de cada ferramenta", any(i.get("version") and i.get("where") for i in data.get("items", [])))

    # ---- verificação total: lista completa com versão, onde foi achado e botões
    with R.guard("verificação total"):
        keys = {i.key for i in page.items}
        R.check("lista tem o catálogo todo (git, PowerShell, agentes...)", {"git", "powershell", "python", "ffmpeg", "opencode", "claude", "codex", "copilot",
                                                                           "antigravity", "git_bash", "whispercpp", "models_dir", "data_dir"} <= keys, str(sorted(keys)))
        R.check("há mais de 20 itens", len(page.items) > 20, str(len(page.items)))
        git_row = next((r for r in page.findChildren(PrepRow) if r.item.key == "git"), None)
        R.check("linha do Git mostra versão e onde foi achado", bool(git_row and git_row.item.version and git_row.item.where), str(git_row and (git_row.item.version, git_row.item.where)))
        R.check("toda linha de ferramenta tem 'Personalizar'", all(r.custom_button is not None for r in page.findChildren(PrepRow) if r.item.tool))
        R.check("resumo contado na tela", "ok" in page.summary.text() and "faltando" in page.summary.text(), page.summary.text())
        shot(win, "01b-verificacao-total")
        # 'Salvar relatório' também grava o texto
        R.check("relatório em texto ao lado do JSON", (TMP / "data" / "setup" / "prepare-report.txt").is_file())

    # ---- personalizar caminho: diálogo REAL, teclado e mouse reais
    saved: list[tuple[str, str]] = []
    from jarvis.setup.tool_dialog import ToolPathDialog
    ctx.extra["tool_dialog_factory"] = lambda key, parent: ToolPathDialog(key, parent, saver=lambda k, v: saved.append((k, v)))
    acc = TMP / "Programas do João é ação" / "Ferramentas"
    acc.mkdir(parents=True, exist_ok=True)
    (acc / "git.cmd").write_text("@echo off\r\necho git version 2.50.0.windows.1\r\n", encoding="utf-8")
    ps51 = Path(__import__("os").environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"

    def dlg_state(dlg) -> tuple[str, str, bool]:
        return dlg.chip._text, dlg.msg.text(), dlg.btn_save.isEnabled()

    def wait_chip(dlg, words: tuple[str, ...], secs: float = 25.0) -> bool:
        return U.wait_until(lambda: dlg.chip._text in words, secs)

    def scenario_custom() -> None:
        dlg = QApplication.activeModalWidget()
        with R.guard("diálogo: cenários"):
            R.check("diálogo abre em 'Automático' e Salvar desligado", dlg.chip._text == "Automático" and not dlg.btn_save.isEnabled(), str(dlg_state(dlg)))
            shot(dlg, "10-dialogo-aberto")
            edit = dlg.field._edit
            type_text(edit, r"C:\pasta\que\nao\existe\git.exe")
            R.check("caminho inexistente: Inválido", wait_chip(dlg, ("Inválido",)) and "Não existe" in dlg.msg.text(), str(dlg_state(dlg)))
            R.check("inexistente: Salvar fica desligado", not dlg.btn_save.isEnabled())
            shot(dlg, "11-dialogo-inexistente")
            type_text(edit, str(ps51))
            R.check("programa de outra ferramenta: Inválido e diz qual", wait_chip(dlg, ("Inválido",)) and "PowerShell" in dlg.msg.text(), str(dlg_state(dlg)))
            shot(dlg, "12-dialogo-outra-ferramenta")
            type_text(edit, r"\\servidor\pasta\git.exe")
            R.check("caminho de rede: Inválido", wait_chip(dlg, ("Inválido",)) and "rede" in dlg.msg.text(), str(dlg_state(dlg)))
            type_text(edit, str(acc / "git.cmd"))
            R.check("espaços e acentos: aceito, pede confirmação (fora das pastas confiáveis, sem assinatura)",
                    wait_chip(dlg, ("Atenção", "Válido")) and dlg.btn_save.isEnabled(), str(dlg_state(dlg)))
            R.check("versão 2.50.0 lida do programa", "2.50.0" in dlg.msg.text(), dlg.msg.text())
            shot(dlg, "13-dialogo-aceito")
            modal_click("Confio, usar este programa", 700)
            click(dlg.btn_save, 600)
            R.check("Salvar gravou o caminho certo no config", saved and saved[-1] == ("toolpaths.git", str(acc / "git.cmd")), str(saved))

    with R.guard("personalizar: caminho válido com confirmação"):
        page.show_items([i for i in page.items])                 # garante linhas visíveis
        git_btn = next(r.custom_button for r in page.findChildren(PrepRow) if r.item.key == "git")
        QTimer.singleShot(700, scenario_custom)
        click(git_btn, 300)
        R.check("diálogo fechou depois de salvar", QApplication.activeModalWidget() is None)
        U.wait_until(lambda: not page._busy and bool(page.findChildren(PrepRow)), 90.0)      # salvar refaz a verificação sozinho
        R.check("salvar refez a verificação (as linhas voltaram)", bool(page.findChildren(PrepRow)))

    def scenario_detect_restore() -> None:
        dlg = QApplication.activeModalWidget()
        with R.guard("diálogo: detectar e restaurar"):
            click(dlg.btn_detect, 200)
            U.wait_until(lambda: bool(dlg.field.value()) or dlg.chip._text == "Não achei", 20.0)
            found = dlg.field.value()
            R.check("'Detectar automaticamente' preenche com o programa real", bool(found) and Path(found).name.lower().startswith("ollama"), found or dlg.msg.text())
            wait_chip(dlg, ("Válido", "Atenção"), 30.0)
            shot(dlg, "14-dialogo-detectado")
            click(dlg.btn_reset, 300)
            R.check("'Restaurar padrão' esvazia o campo (automático)", dlg.field.value() == "" and dlg.chip._text == "Automático", str(dlg_state(dlg)))
            click(dlg.btn_save, 500)

    with R.guard("personalizar: detectar e restaurar"):
        saved.clear()
        ollama_btn = next(r.custom_button for r in page.findChildren(PrepRow) if r.item.key == "ollama")
        QTimer.singleShot(700, scenario_detect_restore)
        click(ollama_btn, 300)
        R.check("restaurar gravou vazio (volta ao automático)", saved == [("toolpaths.ollama", "")], str(saved))
        U.wait_until(lambda: not page._busy and bool(page.findChildren(PrepRow)), 90.0)

    def scenario_cancel() -> None:
        dlg = QApplication.activeModalWidget()
        type_text(dlg.field._edit, r"C:\qualquer\coisa\ffmpeg.exe")
        click(dlg.btn_cancel, 300)

    with R.guard("personalizar: cancelar não grava"):
        saved.clear()
        ff = next(r.custom_button for r in page.findChildren(PrepRow) if r.item.key == "ffmpeg")
        QTimer.singleShot(700, scenario_cancel)
        click(ff, 300)
        R.check("Cancelar não grava nada", saved == [], str(saved))

    with R.guard("abrir site oficial"):
        opened: list[str] = []
        ctx.extra["open_url"] = opened.append
        ctx.extra.pop("tool_dialog_factory", None)
        fake_missing = [P.Item("ffmpeg", "FFmpeg", "info", "não instalado", "Opcional.", "open_url", "Abrir o site oficial", True, tool="ffmpeg",
                               url="https://www.gyan.dev/ffmpeg/builds/", category="Opcional")]
        page.show_items(fake_missing)
        click(next(r.button for r in page.findChildren(PrepRow) if r.item.key == "ffmpeg"), 300)
        R.check("'Abrir o site oficial' abre só https", opened == ["https://www.gyan.dev/ffmpeg/builds/"], str(opened))
        page.show_items([P.Item("x", "X", "info", "", "", "open_url", "Abrir", True, url="http://inseguro.example/x")])
        click(next(r.button for r in page.findChildren(PrepRow) if r.item.key == "x"), 200)
        R.check("endereço sem https nunca abre", opened == ["https://www.gyan.dev/ffmpeg/builds/"], str(opened))
        page.recheck()
        U.wait_until(lambda: not page._busy, 60.0)

    # ---- instalador de terceiro: dublê do download + diálogos REAIS
    fake = [P.Item("vcruntime", "Biblioteca do Visual C++", "fail", "faltam: vcruntime140.dll", "O servidor do modelo precisa dela.",
                   "install_vcredist", "Baixar e instalar (Microsoft)"),
            P.Item("models", "Modelos, voz e escuta", "fail", "faltam 4 de 10 arquivo(s), 486 MB", "", "download_models", "Baixar o que falta"),
            P.Item("ollama", "Ollama (opcional)", "info", "não instalado", "Opcional.", "install_ollama", "Baixar do site oficial (opcional)", True)]
    exe = TMP / "vc_redist.x64.exe"
    exe.write_bytes(b"MZ-teste")
    sig = P.Signature(True, "Valid", "CN=Microsoft Windows, O=Microsoft Corporation, L=Redmond", "AB", "ok")

    def fake_fetch(spec, dest, progress=None, cancel=None, **k):
        run["fetch"] += 1
        if progress:
            progress(5_000_000, 25_000_000)
            progress(25_000_000, 25_000_000)
        return exe, sig

    with R.guard("recusar o download"):
        page.show_items(fake)
        U.settle(200)
        shot(win, "02-itens-faltando")
        with mock.patch.object(P, "fetch_verified", fake_fetch), mock.patch.object(page, "recheck"):
            modal_click("Voltar")
            click(row_button(page, "vcruntime"), 400)
            R.check("'Voltar' no diálogo: nada baixado", run["fetch"] == 0 and not run["installer"], f"fetch={run['fetch']}")

    with R.guard("baixar e instalar com confirmação"):
        with mock.patch.object(P, "fetch_verified", fake_fetch), mock.patch.object(page, "recheck") as rc:
            modal_click("Baixar do site oficial", 500)
            QTimer.singleShot(2600, lambda: modal_click("Instalar", 100))
            click(row_button(page, "vcruntime"), 300)
            U.wait_until(lambda: bool(run["installer"]), 12.0)
            R.check("download foi pedido uma vez", run["fetch"] == 1, str(run["fetch"]))
            R.check("instalador oficial rodou com /quiet e UAC", bool(run["installer"]) and run["installer"][0][2] is True and "/quiet" in run["installer"][0][1], str(run["installer"]))
            U.wait_until(lambda: rc.called, 6.0)
            R.check("depois de instalar a lista é verificada de novo", rc.called)
            shot(win, "03-instalado")
            U.wait_until(lambda: not page._busy, 6.0)
            R.check("tela volta a ficar livre", not page._busy)

    with R.guard("assinatura inválida"):
        run["installer"].clear()
        err = P.PrepError("signature", "A assinatura digital do instalador NÃO é válida (HashMismatch). Ele foi apagado e não será executado.")
        with mock.patch.object(P, "fetch_verified", side_effect=err):
            page.show_items(fake)
            modal_click("Baixar do site oficial", 500)
            click(row_button(page, "vcruntime"), 300)
            U.wait_until(lambda: not page._busy, 10.0)
        R.check("assinatura inválida: instalador NÃO roda", not run["installer"])
        R.check("assinatura inválida: aviso de erro na tela", bool(page.findChildren(InlineBanner)))
        shot(win, "04-assinatura-invalida")

    with R.guard("UAC negado"):
        def deny(path, args, elevate):
            raise P.PrepError("cancelled", "Você não deu a permissão do Windows. Nada foi instalado.")
        ctx.extra["prep_run_installer"] = deny
        with mock.patch.object(P, "fetch_verified", fake_fetch), mock.patch.object(page, "recheck"):
            page.show_items(fake)
            modal_click("Baixar do site oficial", 500)
            QTimer.singleShot(2600, lambda: modal_click("Instalar", 100))
            click(row_button(page, "vcruntime"), 300)
            U.wait_until(lambda: not page._busy and bool(page.findChildren(InlineBanner)), 14.0)
        R.check("UAC negado: tela libera e mostra aviso", not page._busy and bool(page.findChildren(InlineBanner)))
        shot(win, "05-uac-negado")

    with R.guard("avançar com pendência"):
        page.show_items(fake)
        modal_click("Voltar", 500)
        ok = page.on_leave(True)
        R.check("sair com item crítico pendente pede confirmação (Voltar = fica)", ok is False)

    with R.guard("navegação"):
        win.show_page("hardware")
        win.next()
        R.check("'Avançar' do 'Seu computador' leva à etapa 'prepare'", win.key == "prepare", win.key)
        win.back()
        R.check("'Voltar' da etapa volta ao 'Seu computador'", win.key == "hardware", win.key)
        shot(win, "06-navegacao")

    win.closing_ok = True
    win.close()


main()
R.save()
sys.exit(1 if R.failed() else 0)
