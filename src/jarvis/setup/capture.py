"""Capturas offscreen de TODAS as telas do assistente (desenvolvimento). Nunca grava no config.toml real nem no disco real:
o estado vai para uma pasta temporária e nenhuma página sai com `on_leave(True)`.

    Jarvis.cmd setup --capture PASTA [--theme dark|light]      (use QT_SCALE_FACTOR=1.5 para 150%)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


def _settle(ms: int = 300) -> None:
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def run_capture(out: Path, theme: str = "dark") -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    from ..audio.vad import SileroVAD  # noqa: F401  (só para falhar cedo se o onnx estiver quebrado)
    from ..config import ROOT, from_dict
    from ..ui.theme import ThemeManager, set_motion_override
    from . import hardware
    from .audio_tools import Calibration
    from .download import Progress
    from .manifest import load_manifest
    from .state import SetupState
    from .widgets import Ctx
    from .wizard import WizardWindow

    out.mkdir(parents=True, exist_ok=True)
    set_motion_override(False)
    mgr = ThemeManager.instance()
    mgr.set_mode(theme)  # type: ignore[arg-type]
    mgr.apply(app)  # type: ignore[arg-type]
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_setup_cap_"))
    man = load_manifest(ROOT)
    cfg = from_dict({})
    state = SetupState()
    ctx = Ctx(root=ROOT, manifest=man, state=state, cfg=cfg, repair=False, demo=True)
    win = WizardWindow(ctx)
    win.setProperty("autoconfirm", False)
    win.show()
    scale = round(win.devicePixelRatioF() * 100)
    tag = f"{theme}-{scale}"
    n = [0]

    def shot(name: str) -> None:
        _settle(350)
        n[0] += 1
        path = out / f"{n[0]:02d}-{name}-{tag}.png"
        if not win.grab().save(str(path), "PNG"):
            raise OSError(path)
        print(path)

    # 1 boas-vindas (primeira vez) e retomada
    win.show_page("welcome")
    shot("boas-vindas")
    state.step = "models"
    win.pages["welcome"].on_enter()
    shot("boas-vindas-retomar")
    state.step = "welcome"
    ctx.repair = True
    win.pages["welcome"].on_enter()
    shot("boas-vindas-reparar")
    ctx.repair = False
    win.pages["welcome"].on_enter()

    # 2 hardware (leitura REAL deste PC)
    win.show_page("hardware")
    win.pages["hardware"].show_results(hardware.run_all(ROOT, 3.5))
    shot("hardware")

    # 3 modelos: pendente, baixando, sem internet, tudo certo
    ctx.root = tmp                       # raiz vazia: mostra "falta baixar" (demo não grava estado em lugar nenhum)
    win.show_page("models")
    mp = win.pages["models"]
    mp.refresh()
    shot("modelos-pendente")
    mp._begin()
    mp._on_progress(Progress("Qwen3VL-4B-Instruct-Q4_K_M.gguf", 1_050_000_000, 2_497_281_664, 1_050_000_000, 3_647_000_000,
                             11_800_000, "baixando", "huggingface.co"))
    mp.bar.set_progress(1_050_000_000, 3_647_000_000)
    shot("modelos-baixando")
    from .download import DownloadError
    mp._on_finished(DownloadError("offline", "x"))
    shot("modelos-sem-internet")
    ctx.root = ROOT
    mp.prog_card.setVisible(False)
    mp._banner("ok", "")
    mp.refresh()
    shot("modelos-prontos")

    # 4 áudio
    win.show_page("audio")
    shot("audio")
    win.pages["audio"].meter.set_level(-26.0)
    shot("audio-nivel")

    # 5 voz
    win.show_page("voice")
    win.pages["voice"].meter.set_level(-20.0)
    win.pages["voice"].status2.setText("Captei sua voz com bom nível.")
    shot("teste-de-voz")

    # 6 VAD
    win.show_page("vad")
    win.pages["vad"].show_result(Calibration(0.55, -52.0, -21.0, 0.08, 0.93, ("Há bastante ruído de fundo. Um fone com microfone melhora muito o reconhecimento.",)))
    shot("calibragem-vad")

    # 7 atalhos
    win.show_page("hotkeys")
    hp = win.pages["hotkeys"]
    hp.status["safety.talk_key"].setText("Livre")
    hp.status["safety.emergency_hotkey"].setText("Livre")
    hp.status["safety.mute_hotkey"].setText("Em uso por outro programa: atalho ctrl+alt+m recusado pelo Windows. Use “Sugerir outra”.")
    hp.status["safety.mute_hotkey"].set_state("warn")
    shot("atalhos")

    # 8 permissões
    win.show_page("permissions")
    shot("permissoes")

    # 9 doctor (REAL)
    win.show_page("doctor")
    from ..doctor import run_doctor
    win.pages["doctor"].show_results(run_doctor(ctx.cfg))
    shot("verificacao-final")

    # 10 pronto
    win.show_page("done")
    shot("tudo-pronto")
    win.closing_ok = True
    win.close()
    return 0
