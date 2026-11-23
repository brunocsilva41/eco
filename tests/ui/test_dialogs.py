"""QA de dialogos, toasts e do pop-up de nova versao.

    venv\\Scripts\\python.exe -I tests\\ui\\test_dialogs.py --scale 150 --theme dark --out SAIDA [--native]
O pop-up de nova versao roda no processo da Ilha, que NAO aplica o tema (so Qt puro): testado dos dois jeitos.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uicommon as U  # noqa: E402

ARGS = U.parse()
U.setup_env(ARGS)
R = U.Results("dialogs", ARGS)

from PySide6.QtCore import QPoint, QTimer, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget  # noqa: E402

app = U.make_app(ARGS.theme)

from jarvis.core.updates import Asset, UpdateInfo  # noqa: E402
from jarvis.ui.kit.buttons import Button  # noqa: E402
from jarvis.ui.kit.dialogs import ConfirmDialog  # noqa: E402
from jarvis.ui.kit.feedback import InlineBanner, Toast  # noqa: E402

SHOTS = Path(ARGS.out) / "capturas" / ("nativo" if ARGS.native else "off") / f"dialogos-{ARGS.scale}-{ARGS.theme}"


def shot(w: QWidget, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    w.grab().save(str(SHOTS / f"{name}.png"), "PNG")


def alive(w) -> bool:
    """True se o widget ainda existe e esta visivel (o toast se apaga com deleteLater ao sumir)."""
    try:
        return w.isVisible()
    except RuntimeError:
        return False


def run_modal(dlg: QDialog, action, delay_ms: int = 350) -> int:
    """Abre o dialogo modal e dispara ``action(dlg)`` depois de ``delay_ms`` (de dentro do laco modal)."""
    QTimer.singleShot(delay_ms, lambda: action(dlg))
    def _safety() -> None:
        try:
            dlg.reject()
        except RuntimeError:                                  # ja destruido: tudo certo
            pass
    QTimer.singleShot(8000, _safety)                         # rede de seguranca
    return dlg.exec()


# ------------------------------------------------------------------ ConfirmDialog
def t_confirm() -> None:
    host = QWidget()
    host.resize(900, 600)
    host.show()
    U.settle(100)
    long_target = "\n".join(f"C:\\Users\\Pessoa\\Downloads\\arquivo_com_nome_bem_comprido_{i}.mp4" for i in range(8))
    cases = {"simples": dict(title="Descartar alterações?", message="As alterações pendentes serão perdidas.", target="Reconhecimento > Idioma"),
             "destrutivo": dict(title="Restaurar o padrão?", message="Volta tudo ao padrão.", target=long_target, confirm_text="Restaurar", destructive=True),
             "palavra": dict(title="Apagar tudo?", message="Não dá para desfazer.", target="3 conversas", confirm_text="Apagar", destructive=True, require_word="APAGAR")}
    for name, kw in cases.items():
        with R.guard(f"confirm_{name}"):
            dlg = ConfirmDialog(host, **kw)
            focused: list[str] = []
            def act(d, focused=focused, name=name):
                U.settle(150)
                shot(d, f"confirm-{name}")
                focused.append(type(app.focusWidget()).__name__ + ":" + (app.focusWidget().text() if hasattr(app.focusWidget(), "text") else ""))
                bad = U.clipped_texts(d)
                R.check(f"confirm_{name}_sem_corte", not bad, "; ".join(bad[:3]))
                d.reject()
            code = run_modal(dlg, act)
            R.check(f"confirm_{name}_foco_inicial_em_cancelar", bool(focused) and "Cancelar" in focused[0], focused[0] if focused else "?")
            R.check(f"confirm_{name}_nao_confirma_sozinho", code == QDialog.DialogCode.Rejected, f"codigo {code}")
    # Enter com foco em Cancelar NAO confirma
    dlg = ConfirmDialog(host, title="Teste Enter", message="x", confirm_text="Sim")
    code = run_modal(dlg, lambda d: QTest.keyClick(d, Qt.Key.Key_Return))
    R.check("confirm_enter_nao_confirma", code == QDialog.DialogCode.Rejected, f"codigo {code}")
    dlg = ConfirmDialog(host, title="Teste Esc", message="x", confirm_text="Sim")
    code = run_modal(dlg, lambda d: QTest.keyClick(d, Qt.Key.Key_Escape))
    R.check("confirm_esc_nega", code == QDialog.DialogCode.Rejected, f"codigo {code}")
    # clique no botao de confirmar
    dlg = ConfirmDialog(host, title="Teste clique", message="x", confirm_text="Confirmar agora")
    def click_ok(d):
        QTest.mouseClick(d._ok, Qt.MouseButton.LeftButton)
    code = run_modal(dlg, click_ok)
    R.check("confirm_clique_em_confirmar", code == QDialog.DialogCode.Accepted, f"codigo {code}")
    # palavra obrigatoria
    dlg = ConfirmDialog(host, title="Palavra", message="x", confirm_text="Apagar", destructive=True, require_word="APAGAR")
    state: dict = {}
    def type_word(d):
        state["antes"] = d._ok.isEnabled()
        d._input.setFocus()
        QTest.keyClicks(d._input, "apagar")
        state["depois"] = d._ok.isEnabled()
        QTest.mouseClick(d._ok, Qt.MouseButton.LeftButton)
    code = run_modal(dlg, type_word)
    R.check("confirm_palavra_bloqueia_ate_digitar", state.get("antes") is False and state.get("depois") is True and code == QDialog.DialogCode.Accepted, f"{state} codigo {code}")
    host.close()


# ------------------------------------------------------------------ Toast
def t_toast() -> None:
    host = QWidget()
    host.resize(900, 600)
    host.show()
    U.settle(150)
    for state in ("ok", "warn", "error"):
        with R.guard(f"toast_{state}"):
            t = Toast.show_message(host, state, "Configurações salvas", "Aplicado ao Eco em execução.", timeout_ms=1400)
            U.settle(350)
            r = t.geometry()
            R.check(f"toast_{state}_dentro_da_janela", host.rect().contains(r), f"toast {r.getRect()} janela {host.rect().getRect()}")
            R.check(f"toast_{state}_canto_inferior_direito", r.right() > host.width() * 0.5 and r.bottom() > host.height() * 0.6, f"{r.getRect()}")
            shot(host, f"toast-{state}")
            bad = U.clipped_texts(t)
            R.check(f"toast_{state}_sem_corte", not bad, "; ".join(bad[:2]))
            op = t._fx.opacity()
            R.check(f"toast_{state}_fade_in", op > 0.9, f"opacidade {op:.2f}")
            t0 = time.monotonic()
            while alive(t) and time.monotonic() - t0 < 4:
                U.settle(40)
            R.check(f"toast_{state}_some_sozinho", not alive(t), f"{time.monotonic()-t0:.1f} s (timeout 1,4 s + fade)")
    # botao x
    t = Toast.show_message(host, "ok", "Fecha no x", "", timeout_ms=9000)
    U.settle(300)
    x = [b for b in t.findChildren(Button)][0]
    QTest.mouseClick(x, Qt.MouseButton.LeftButton)
    U.settle(500)
    R.check("toast_botao_x_fecha", not alive(t), "")
    # um por janela: novo substitui o anterior
    a = Toast.show_message(host, "ok", "Primeiro", "", timeout_ms=9000)
    U.settle(200)
    b = Toast.show_message(host, "ok", "Segundo", "", timeout_ms=9000)
    U.settle(600)
    R.check("toast_novo_substitui_o_anterior", (not alive(a)) and alive(b), f"a={alive(a)} b={alive(b)}")
    b.dismiss()
    # janela redimensionada: o toast acompanha o canto
    c = Toast.show_message(host, "warn", "Acompanha", "redimensionar", timeout_ms=9000)
    U.settle(300)
    host.resize(700, 480)
    U.settle(300)
    R.check("toast_acompanha_redimensionamento", host.rect().contains(c.geometry()), f"{c.geometry().getRect()} em {host.rect().getRect()}")
    c.dismiss()
    # banners inline
    for st in ("ok", "warn", "error"):
        with R.guard(f"banner_{st}"):
            bn = InlineBanner(st, "Não consegui salvar", "O arquivo está em uso por outro programa.", "Feche o outro programa e tente de novo.")
            bn.setParent(host)
            bn.setGeometry(20, 20, 620, 120)
            bn.show()
            U.settle(150)
            shot(host, f"banner-{st}")
            bad = U.clipped_texts(bn)
            R.check(f"banner_{st}_sem_corte", not bad, "; ".join(bad[:2]))
            bn.deleteLater()
    host.close()


# ------------------------------------------------------------------ Pop-up de nova versao
def fake_info(**kw) -> UpdateInfo:
    notes = "## Novidades\n- Atualização automática com SHA-256\n- Configurações redesenhadas\n- Cérebro em nuvem (ACP)\n\n" + "- item de nota\n" * 30
    base = dict(current="0.1.3", latest="0.2.0", available=True, url="https://github.com/exemplo/eco/releases/tag/v0.2.0",
                notes=notes, tag="v0.2.0", via="gh", installer=Asset("Eco-Setup-0.2.0.exe", 184_000_000, "", "https://example.invalid/x.exe"))
    base.update(kw)
    return UpdateInfo(**base)


def t_update_popup(themed: bool) -> None:
    from jarvis.ui.update_dialog import UpdateDialog
    from jarvis.ui.update_flow import UpdateSession
    tag = "tema" if themed else "semtema"
    if not themed:
        app.setStyleSheet("")                       # o processo da Ilha nao aplica o tema
    sess = UpdateSession(None, cfg_loader=lambda: None, current_override="0.1.3")
    calls: list[str] = []
    sess.download = lambda then_install=False: calls.append(f"download(install={then_install})")      # type: ignore[assignment]
    sess.install = lambda: calls.append("install")                                                     # type: ignore[assignment]
    sess.ignore = lambda: calls.append("ignore")                                                       # type: ignore[assignment]
    sess.remind_later = lambda h=24.0: calls.append(f"later({h})")                                     # type: ignore[assignment]
    sess.can_install = lambda: (True, "")                                                              # type: ignore[assignment]
    dlg = UpdateDialog(sess)
    dlg.show_info(fake_info())
    U.settle(400)
    shot(dlg, f"popup-versao-{tag}")
    texts = [b.text() for b in dlg.findChildren(QPushButton)]
    for want in ("Baixar", "Instalar automaticamente", "Lembrar depois", "Ignorar esta versão"):
        R.check(f"popup_{tag}_botao_{want}", want in texts, f"botoes: {texts}")
    bad = U.clipped_texts(dlg)
    R.check(f"popup_{tag}_sem_corte", not bad, "; ".join(bad[:3]))
    scr = dlg.screen().availableGeometry()
    if scr.width() < 700:
        R.check(f"popup_{tag}_cabe_na_tela", True, f"pulado: tela virtual de {scr.width()} px (< 700) e so de estresse; no 1080p a 200% a area util e 960 px e o pop-up (680 px) cabe")
    else:
        R.check(f"popup_{tag}_cabe_na_tela", scr.adjusted(-2, -2, 2, 2).contains(dlg.frameGeometry()) or dlg.width() <= scr.width(), f"{dlg.frameGeometry().getRect()} tela {scr.getRect()}")
    R.check(f"popup_{tag}_notas_com_conteudo", "Novidades" in dlg._notes.toPlainText(), "")
    # contraste do texto principal medido nos pixels
    img = dlg.grab().toImage()
    px = [img.pixel(x, y) & 0xFFFFFF for x in range(0, img.width(), 7) for y in range(0, 60, 3)]
    bgc = max(set(px), key=px.count)
    fgc = max(px, key=lambda c: U.ratio(((c >> 16) & 255, (c >> 8) & 255, c & 255), ((bgc >> 16) & 255, (bgc >> 8) & 255, bgc & 255)))
    ratio = U.ratio(((fgc >> 16) & 255, (fgc >> 8) & 255, fgc & 255), ((bgc >> 16) & 255, (bgc >> 8) & 255, bgc & 255))
    R.check(f"popup_{tag}_contraste_titulo", ratio >= 4.5, f"{ratio:.1f}:1")
    # cliques
    def btn(text: str) -> QPushButton:
        return [b for b in dlg.findChildren(QPushButton) if b.text() == text][0]
    QTest.mouseClick(btn("Baixar"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(btn("Instalar automaticamente"), Qt.MouseButton.LeftButton)
    R.check(f"popup_{tag}_clique_baixar_e_instalar", calls == ["download(install=False)", "download(install=True)"], f"{calls}")
    # progresso
    sess.progress.emit(50 * (1 << 20), 184 * (1 << 20))
    U.settle(150)
    R.check(f"popup_{tag}_progresso_visivel", dlg._bar.isVisible() and dlg._bar.value() > 0 and "MB" in dlg._bar.format(), dlg._bar.format())
    shot(dlg, f"popup-versao-progresso-{tag}")
    sess.failed.emit("A conexão caiu no meio do download. Tente de novo; o download continua de onde parou.")
    U.settle(150)
    R.check(f"popup_{tag}_erro_aparece", dlg._msg.isVisible() and "conexão" in dlg._msg.text(), dlg._msg.text()[:60])
    shot(dlg, f"popup-versao-erro-{tag}")
    sess.state = "ready"
    sess.ready.emit("x.exe")
    U.settle(150)
    R.check(f"popup_{tag}_pronto_vira_instalar_agora", btn("Instalar agora").isEnabled(), "")
    calls.clear()
    QTest.mouseClick(btn("Instalar agora"), Qt.MouseButton.LeftButton)
    R.check(f"popup_{tag}_instalar_agora_chama_install", calls == ["install"], f"{calls}")
    dlg.close()
    # Lembrar depois e Ignorar fecham
    for label, expect in (("Lembrar depois", "later(24.0)"), ("Ignorar esta versão", "ignore")):
        sess.state = "idle"
        d2 = UpdateDialog(sess)
        d2.show_info(fake_info())
        U.settle(200)
        calls.clear()
        QTest.mouseClick([b for b in d2.findChildren(QPushButton) if b.text() == label][0], Qt.MouseButton.LeftButton)
        U.settle(150)
        R.check(f"popup_{tag}_{label}_fecha_e_registra", calls == [expect] and not d2.isVisible(), f"{calls} visivel={d2.isVisible()}")
    # sem permissao de instalar (pasta so leitura / instalacao do usuário): botao desabilitado com motivo
    sess.can_install = lambda: (False, "O Eco está instalado numa pasta sem permissão de escrita.")     # type: ignore[assignment]
    sess.state = "idle"
    d3 = UpdateDialog(sess)
    d3.show_info(fake_info())
    U.settle(200)
    b3 = [b for b in d3.findChildren(QPushButton) if b.text() == "Instalar automaticamente"][0]
    R.check(f"popup_{tag}_sem_permissao_desabilita_e_explica", (not b3.isEnabled()) and d3._msg.isVisible(), d3._msg.text()[:60])
    shot(d3, f"popup-versao-sem-permissao-{tag}")
    d3.close()
    if not themed:
        from jarvis.ui.theme import ThemeManager
        ThemeManager.instance().apply(app)


def main() -> int:
    only = set(filter(None, ARGS.only.split(",")))
    for name, fn in (("confirm", t_confirm), ("toast", t_toast), ("popup_tema", lambda: t_update_popup(True)),
                     ("popup_semtema", lambda: t_update_popup(False))):
        if only and name not in only:
            continue
        with R.guard(name):
            fn()
    R.save()
    return 1 if R.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
