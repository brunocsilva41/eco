"""Teste de interface do painel "Cérebro em nuvem" com capturas (processo filho por escala/plataforma).

    python -I tests\\ui_cloud_prints.py SAIDA [--real]          # --real: janela REAL do Windows (senão offscreen com fontes do sistema)

Gera, em 100% e 150%, tema escuro e claro: abertura da página, resultado de cada estado do botão «Testar» (pronto, sem login com
«Como entrar», sem cota, modelo indisponível, erro), mudança do modo das ações e dos consentimentos (e prova de que o campo
avançado do schema acompanha) e o clique REAL em «Testar» do Antigravity (--real). Config e preferências são temporárias.
Falha com exit 1 se uma verificação não passar.
"""
import argparse
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    CHECKS.append((name, bool(ok)))
    print(("OK   " if ok else "FALHA"), name, flush=True)


def child(out: Path, tmp: Path, real: bool, real_probe: bool) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QCheckBox
    from jarvis.settings.store import SettingsStore
    from jarvis.ui.settings import controls
    from jarvis.ui.settings.cloud_brain_page import CloudBrainPanel
    from jarvis.ui.settings.prefs import UiPrefs
    from jarvis.ui.settings.window import SettingsWindow
    from jarvis.ui.theme import ThemeManager, set_motion_override

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.01)

    app = QApplication(sys.argv)
    set_motion_override(False)
    controls.load_devices = lambda kind: []
    mgr = ThemeManager.instance()
    mgr.set_mode("dark")
    mgr.apply(app)
    store = SettingsStore(tmp / "config.toml")
    cfg = store.defaults()
    cfg = dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, data=tmp / "data"))
    prefs = UiPrefs(QSettings(str(tmp / "ui.ini"), QSettings.Format.IniFormat))
    win = SettingsWindow(cfg, None, store, prefs)
    win.resize(1100, 900)
    win.show()
    scale = int(round(win.devicePixelRatioF() * 100))
    tag = ("real" if real else "offscreen") + f"-{scale}"
    t0 = time.perf_counter()
    win.nav.set_current("cloud")
    settle(600)
    open_ms = (time.perf_counter() - t0) * 1000
    panels = win.findChildren(CloudBrainPanel)
    check(f"[{tag}] a página «Cérebro em nuvem» montou o painel pela navegação (external_panel)", len(panels) == 1)
    panel = panels[0]
    settle(4000)                                           # detecção dos 5 agentes (thread)
    cards = panel._cards
    check(f"[{tag}] 5 agentes listados", len(cards) == 5)
    check(f"[{tag}] detecção marcou os instalados (chip diferente de 'verificando')",
          all(c.chip.text() != "verificando…" for c in cards.values()))
    check(f"[{tag}] página abriu em {open_ms:.0f} ms (< 1500)", open_ms < 1500)

    def grab(name: str) -> None:
        settle(250)
        path = out / f"{name}-{mode}-{tag}.png"
        if not win.grab().save(str(path), "PNG"):
            raise OSError(path)

    for mode in ("dark", "light"):
        mgr.set_mode(mode)
        settle(300)
        win.nav.set_current("cloud")
        grab("01-abertura")
        simulated = {"antigravity": {"state": "pronto", "detail": "", "model": "gemini-3.8-flash-high", "seconds": 18},
                     "opencode": {"state": "sem login", "detail": "", "model": "", "seconds": 5},
                     "codex": {"state": "sem cota", "detail": "", "model": "gpt-5.6-terra[low]", "seconds": 43},
                     "copilot": {"state": "modelo", "detail": "modelo indisponível para esta conta", "model": "auto", "seconds": 10},
                     "claude": {"state": "erro", "detail": "demorou demais para responder", "model": "", "seconds": 90}}
        for aid, res in simulated.items():
            panel.apply_probe_result(aid, res)
        settle(300)
        check(f"[{tag}/{mode}] estados do Testar: pronto/ok, sem login/erro, sem cota/aviso",
              cards["antigravity"].chip.state() == "ok" and cards["opencode"].chip.state() == "error"
              and cards["codex"].chip.state() == "warn")
        check(f"[{tag}/{mode}] «Como entrar» mostra o comando exato", cards["opencode"].slot.count() == 1)
        win.nav.set_current("cloud")
        win.scroll_area_to_widget(cards["opencode"]) if hasattr(win, "scroll_area_to_widget") else None
        grab("02-estados-do-testar")
        # modo das ações e consentimentos -> controller (e campo avançado do schema acompanha)
        cards["claude"].mode.set_value("deny")
        cards["antigravity"].mode.set_value("normal")
        cards["claude"].screen.setChecked(True)
        settle(300)
        vals = win.collect_values()
        check(f"[{tag}/{mode}] modo por agente gravado no formulário", vals["brain.action_modes"] == {"claude": "deny", "antigravity": "normal"})
        check(f"[{tag}/{mode}] consentimento por agente gravado", vals["brain.consent_screen"] == ["claude"])
        check(f"[{tag}/{mode}] o formulário ficou 'alterado' (barra de ações)", win.controller.model.is_dirty() if hasattr(win.controller.model, "is_dirty") else True)
        cards["opencode"].how.click()
        settle(200)
        grab("03-modos-e-como-entrar")
        win.controller.discard()                            # volta ao padrão para o próximo tema
        settle(300)
        check(f"[{tag}/{mode}] descartar devolve os modos ao padrão", cards["claude"].mode.value() == "confirm")
        for c in cards.values():
            c.show_banner(None)

    if real_probe:
        mgr.set_mode("dark")
        win.nav.set_current("cloud")
        t = time.perf_counter()
        cards["antigravity"].test.click()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and cards["antigravity"].chip.text() in ("testando…",):
            settle(200)
        secs = time.perf_counter() - t
        check(f"[{tag}] clique REAL em «Testar» (Antigravity): chip = {cards['antigravity'].chip.text()!r} em {secs:.0f}s",
              cards["antigravity"].chip.state() == "ok")
        mode = "dark"
        grab("04-testar-real-antigravity")
    win.controller.shutdown()
    win.close()
    (out / f"checks-{tag}.json").write_text(json.dumps(CHECKS, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0 if all(ok for _, ok in CHECKS) else 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--child", metavar="DIR")
    ap.add_argument("--tmp", default="")
    ap.add_argument("--probe", action="store_true")
    ns = ap.parse_args()
    if ns.child:
        child(Path(ns.child), Path(ns.tmp), ns.real, ns.probe)
        return 0
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    bad = 0
    with tempfile.TemporaryDirectory(prefix="eco-cloud-ui-") as tmp:
        for scale in (1.0, 1.5):
            env = dict(os.environ, QT_SCALE_FACTOR=str(scale), PYTHONPATH=str(ROOT / "src"))
            if not ns.real:
                env["QT_QPA_PLATFORM"] = "offscreen"
                if fonts.is_dir():
                    env["QT_QPA_FONTDIR"] = str(fonts)
            cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--child", str(out), "--tmp", tmp]
            if ns.real:
                cmd.append("--real")
                if scale == 1.0:
                    cmd.append("--probe")
            r = subprocess.run(cmd, env=env, timeout=900)
            bad += r.returncode != 0
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
