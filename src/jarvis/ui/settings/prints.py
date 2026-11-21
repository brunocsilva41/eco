"""Capturas offscreen das Configuracoes (mesmo metodo de ``ui/kit/gallery.py``): um processo filho por escala,
com ``QT_SCALE_FACTOR``, e troca de tema em tempo de execucao. Usa config.toml e QSettings TEMPORARIOS (nunca
os reais), lista de dispositivos vazia (nao toca audio) e dados fora da pasta real.

    python -m jarvis.ui.settings.prints SAIDA          # gera 100%, 150% e 200% (escuro e claro)
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from jarvis.settings.control import Runtime
from jarvis.settings.store import Changes, SaveResult, SettingsStore

from ..theme import ThemeManager, set_motion_override
from . import controls
from .categories import CATEGORIES
from .model import SaveOutcome
from .prefs import UiPrefs
from .window import SettingsWindow

_WAIT_MS = 1500
_TOOLS_WAIT_MS = 4000


def _settle(ms: int = 250) -> None:
    """Roda o laco de eventos por ms. Dorme com time.sleep (solta o GIL; QTest.qWait nao solta e deixa as
    tarefas em segundo plano sem rodar)."""
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def _grab(win: SettingsWindow, path: Path) -> None:
    _settle()
    if not win.grab().save(str(path), "PNG"):
        raise OSError(f"nao consegui gravar {path}")


def _child(out: Path, tmp: Path) -> None:
    app = QApplication(sys.argv)
    set_motion_override(False)
    controls.load_devices = lambda kind: []          # type: ignore[assignment]  # sem tocar em audio
    mgr = ThemeManager.instance()
    mgr.set_mode("dark")
    mgr.apply(app)
    store = SettingsStore(tmp / "config.toml")
    cfg = store.defaults()
    cfg = dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, data=tmp / "data"))
    prefs = UiPrefs(QSettings(str(tmp / "ui.ini"), QSettings.Format.IniFormat))
    win = SettingsWindow(cfg, None, store, prefs)
    win.show()
    scale = int(round(win.devicePixelRatioF() * 100))
    win.nav.set_current("tools")           # a primeira leitura do catalogo importa modulos e demora
    _settle(_TOOLS_WAIT_MS)
    win.nav.set_current("general")
    _settle(_WAIT_MS)
    for mode in ("dark", "light"):
        mgr.set_mode(mode)  # type: ignore[arg-type]
        for cat in CATEGORIES:
            win.nav.set_current(cat.key)
            _settle(_WAIT_MS if cat.key in ("tools", "knows") else 250)
            _grab(win, out / f"{cat.key}-{mode}-{scale}.png")
        win.nav.set_current("listening")
        values = win.collect_values()
        values["stt.language"] = "xx1"                       # invalido: erro junto do campo
        values["safety.talk_key"] = "F10"
        win.apply_values(values)
        _settle(600)
        _grab(win, out / f"reconhecimento-alteracoes-e-erro-{mode}-{scale}.png")
        win.controller.discard()
        win.search.setText("microfone")
        _settle(600)
        _grab(win, out / f"busca-{mode}-{scale}.png")
        win.search.clear()
        win.banners.show_saved(SaveOutcome(SaveResult(cfg, Changes(("llm.temperature",), ("llm.ctx",))), False, True, ()))
        win.banners.set_runtime(Runtime(1, 0.0, 0.0))
        _grab(win, out / f"aviso-salvo-{mode}-{scale}.png")
        win.banners.show_write_error("permission", "")
        win.banners.show_disk(True)
        _grab(win, out / f"avisos-erro-e-disco-{mode}-{scale}.png")
        win.banners.clear()
    win.controller.shutdown()
    win.close()


def render(out_dir: Path, scales: tuple[float, ...] = (1.0, 1.5, 2.0)) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    src_root = str(Path(__file__).resolve().parents[3])
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    with tempfile.TemporaryDirectory(prefix="jarvis-cfg-prints-") as tmp:
        for scale in scales:
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=str(scale), PYTHONPATH=src_root)
            if fonts.is_dir():
                env["QT_QPA_FONTDIR"] = str(fonts)
            cmd = [sys.executable, "-m", "jarvis.ui.settings.prints", "--child", str(out_dir), "--tmp", tmp]
            subprocess.run(cmd, env=env, check=True, timeout=600)
    return sorted(out_dir.glob("*.png"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Capturas offscreen das Configuracoes")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--child", metavar="DIR")
    ap.add_argument("--tmp", default="")
    ns = ap.parse_args()
    if ns.child:
        _child(Path(ns.child), Path(ns.tmp))
    elif ns.out:
        render(Path(ns.out))
    else:
        ap.error("informe a pasta de saida")
