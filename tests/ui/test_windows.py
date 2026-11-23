"""QA das janelas Memoria ("O que o Eco sabe de mim"), Gravador ("Minha voz") e Assistente de instalacao (Setup), que
compartilham o kit visual das Configuracoes. Sem hardware: o gravador usa servicos falsos; o assistente roda em modo demo.

    venv\\Scripts\\python.exe -I tests\\ui\\test_windows.py --scale 150 --theme dark --out SAIDA
Checa: abre sem janelas soltas, cabe na area util do monitor, sem texto cortado no tamanho minimo, teclado (Tab/Esc),
animacoes do kit, contraste dos rotulos, tema claro/escuro.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uicommon as U  # noqa: E402

ARGS = U.parse()
U.setup_env(ARGS)
R = U.Results("windows", ARGS)

from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

app = U.make_app(ARGS.theme)

SHOTS = Path(ARGS.out) / "capturas" / ("nativo" if ARGS.native else "off") / f"janelas-{ARGS.scale}-{ARGS.theme}"


def shot(w: QWidget, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    w.grab().save(str(SHOTS / f"{name}.png"), "PNG")


def fits(win: QWidget) -> tuple[bool, str]:
    av = win.screen().availableGeometry()
    fg = win.frameGeometry()
    return av.adjusted(-2, -2, 2, 2).contains(fg), f"area util {av.getRect()} janela {fg.getRect()}"


def small_screen(win: QWidget) -> bool:
    """Tela virtual do offscreen (800 px fisicos) a 125/150/200% vira 640/533/400 px logicos: menor que qualquer monitor real.
    Nessas escalas os cortes sao do tamanho da tela de teste, nao da janela; o que vale sao os tamanhos-alvo (910x472 etc.) e o teste nativo."""
    return win.screen().availableGeometry().width() < 800


def common_checks(name: str, win: QWidget, min_size: tuple[int, int] | None = None) -> None:
    U.settle(500)
    if small_screen(win):
        R.check(f"{name}_tela_virtual_pequena_pulado", True, f"pulado: tela virtual de {win.screen().availableGeometry().width()} px; coberto pelos tamanhos-alvo e pelo teste nativo")
        return
    ok, d = fits(win)
    R.check(f"{name}_cabe_na_area_util", ok, d)
    bad = U.clipped_texts(win)
    R.check(f"{name}_sem_texto_cortado", not bad, "; ".join(bad[:4]))
    if min_size:
        win.resize(win.minimumSize())                      # o minimo REAL (o ajuste a tela pequena pode te-lo reduzido)
        U.settle(300)
        bad = U.clipped_texts(win)
        R.check(f"{name}_tamanho_minimo_sem_corte", not bad, "; ".join(bad[:4]))
        shot(win, f"{name}-minimo")
    # Tab percorre e fica dentro da janela
    win.activateWindow()
    seen = set()
    for _ in range(25):
        QTest.keyClick(win, Qt.Key.Key_Tab)
        w = app.focusWidget()
        if w is not None:
            seen.add(type(w).__name__)
            if not (win.isAncestorOf(w) or w is win):
                R.check(f"{name}_tab_foco_na_janela", False, f"foco escapou para {type(w).__name__}")
                break
    else:
        R.check(f"{name}_tab_foco_na_janela", True, f"{len(seen)} tipos de controle: {sorted(seen)[:6]}")


# ------------------------------------------------------------------ Memoria
def t_memory() -> None:
    from jarvis.config import from_dict
    from jarvis.ui.memory.window import MIN_SIZE, open_memory
    tmp = Path(tempfile.mkdtemp(prefix="eco-uiqa-mem-"))
    cfg = from_dict({"paths": {"data": str(tmp / "data"), "logs": str(tmp / "logs")}})
    with U.OrphanProbe() as probe:
        panel = open_memory(cfg)
        U.settle(900)
    R.check("memoria_sem_janelas_soltas", probe.total() == 0, f"{probe.total()}: {dict(list(probe.hits.items())[:4])}")
    R.check("memoria_abriu", panel.isVisible(), "")
    shot(panel, "memoria")
    common_checks("memoria", panel, MIN_SIZE)
    # areas (conversas / memorias / armazenamento) por clique nas abas
    from PySide6.QtWidgets import QTabBar
    bars = [b for b in panel.findChildren(QTabBar) if b.isVisibleTo(panel)]
    R.check("memoria_tem_faixa_de_areas", len(bars) >= 1 and bars[0].count() >= 3, f"{bars[0].count() if bars else 0} areas")
    if bars:
        bar = bars[0]
        for i in range(bar.count()):
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, bar.tabRect(i).center())
            U.settle(450)
            shot(panel, f"memoria-area{i}-{bar.tabText(i)[:10].replace(' ', '_')}")
            R.check(f"memoria_area{i}_selecionada", bar.currentIndex() == i, f"{bar.tabText(i)}")
            R.check(f"memoria_area{i}_sem_corte", not U.clipped_texts(panel), "; ".join(U.clipped_texts(panel)[:3]))
    t_target_sizes("memoria", panel, [lambda: panel.findChildren(QTabBar)[0] if panel.findChildren(QTabBar) else None])
    panel.close()


# ------------------------------------------------------------------ Gravador
class _FakeRecorder:
    def __init__(self, dur: float) -> None:
        from jarvis.recording.recorder import RecorderState
        self._st = RecorderState
        self.state = RecorderState.IDLE
        self.error = None
        self.samples = None
        self.remaining_s = dur
        self.progress = 0.0

    def level(self):
        from jarvis.recording.recorder import LevelReading
        return LevelReading(0.0, 0.0)

    def set_device(self, spec) -> None: ...
    def start(self) -> None: self.state = self._st.RECORDING
    def stop(self, *, discard: bool = False) -> None: self.state = self._st.IDLE
    def reset(self) -> None: self.state = self._st.IDLE


class _FakePlayer:
    is_playing = False
    def play(self, samples, sample_rate: int = 16000) -> None: ...
    def stop(self) -> None: ...


def t_recorder() -> None:
    from jarvis.config import from_dict
    from jarvis.recording.recorder import InputChoice
    from jarvis.ui.recorder.services import Services
    from jarvis.ui.recorder.window import MIN_SIZE, RecorderWindow
    tmp = Path(tempfile.mkdtemp(prefix="eco-uiqa-rec-"))
    cfg = from_dict({"paths": {"data": str(tmp / "data"), "logs": str(tmp / "logs")}})
    svc = Services(make_recorder=_FakeRecorder, make_player=lambda c: _FakePlayer(),
                   list_choices=lambda rescan: [InputChoice(None, "Padrão do Windows", True), InputChoice(1, "Microfone de teste")])
    settings = QSettings(str(tmp / "rec.ini"), QSettings.Format.IniFormat)
    with U.OrphanProbe() as probe:
        win = RecorderWindow(cfg, None, "frases", services=svc, settings=settings)
        win.show()
        U.settle(1200)
    R.check("gravador_sem_janelas_soltas", probe.total() == 0, f"{probe.total()}: {dict(list(probe.hits.items())[:4])}")
    shot(win, "gravador")
    common_checks("gravador", win, MIN_SIZE)
    for key in ("frases", "eco"):
        with R.guard(f"gravador_conjunto_{key}"):
            win.show_set(key)
            U.settle(700)
            shot(win, f"gravador-{key}")
            cut = [] if small_screen(win) else U.clipped_texts(win)
            R.check(f"gravador_conjunto_{key}_sem_corte", not cut, "; ".join(cut[:3]) or ("pulado (tela virtual pequena)" if small_screen(win) else ""))
    t_target_sizes("gravador", win, [lambda: win._view.actions.record])
    # Espaco grava e para (teclado local)
    QTest.keyClick(win, Qt.Key.Key_Space)
    U.settle(400)
    shot(win, "gravador-gravando")
    R.check("gravador_espaco_inicia_gravacao", win.is_recording, "")
    QTest.keyClick(win, Qt.Key.Key_Escape)
    U.settle(400)
    R.check("gravador_esc_cancela_gravacao_sem_fechar", (not win.is_recording) and win.isVisible(), f"gravando={win.is_recording} visivel={win.isVisible()}")
    win.close()


# ------------------------------------------------------------------ Assistente (Setup)
def t_wizard() -> None:
    from jarvis.config import ROOT, from_dict
    from jarvis.setup.manifest import load_manifest
    from jarvis.setup.state import STEPS, SetupState
    from jarvis.setup.widgets import Ctx
    from jarvis.setup.wizard import MIN_H, MIN_W, WizardWindow
    ctx = Ctx(root=ROOT, manifest=load_manifest(ROOT), state=SetupState(), cfg=from_dict({}), repair=False, demo=True)
    with U.OrphanProbe() as probe:
        win = WizardWindow(ctx)
        win.show()
        U.settle(900)
    R.check("assistente_sem_janelas_soltas", probe.total() == 0, f"{probe.total()}: {dict(list(probe.hits.items())[:4])}")
    ok, d = fits(win)
    R.check("assistente_cabe_na_area_util", ok, d)
    
    for step in STEPS:
        with R.guard(f"assistente_{step}"):
            win.show_page(step)
            U.settle(450)
            shot(win, f"assistente-{step}")
            bad = [] if small_screen(win) else U.clipped_texts(win)
            R.check(f"assistente_{step}_sem_corte", not bad, "; ".join(bad[:3]) or ("pulado (tela virtual pequena)" if small_screen(win) else ""))
    win.resize(win.minimumSize())
    U.settle(300)
    for step in ("welcome", "models", "hotkeys", "done"):
        win.show_page(step)
        U.settle(350)
        bad = [] if small_screen(win) else U.clipped_texts(win)
        R.check(f"assistente_{step}_minimo_sem_corte", not bad, "; ".join(bad[:3]))
    shot(win, "assistente-minimo")
    win.show_page("models")
    common_checks("assistente", win)
    t_target_sizes("assistente", win, [lambda: win.next_btn])
    win.closing_ok = True
    win.close()


TARGET_SIZES = {"notebook_1366x768_150": (910, 472), "fullhd_200": (960, 480), "notebook_1366x768_125": (1092, 548),
                "fullhd_150": (1280, 653), "fullhd_100": (1500, 900)}


def t_target_sizes(name: str, win: QWidget, must_show) -> None:
    """Tamanhos REAIS de area util (px logicos) de telas comuns: nenhum texto cortado e os botoes principais sempre dentro da janela.
    ``must_show``: lista de funcoes que devolvem os widgets que nao podem sair da janela (Salvar, Avancar, Gravar...)."""
    for label, (w, h) in TARGET_SIZES.items():
        win.setMinimumSize(0, 0)
        win.resize(w, h)
        U.settle(450)
        bad = U.clipped_texts(win)
        R.check(f"{name}_{label}_sem_corte", not bad, "; ".join(bad[:3]))
        outside = []
        for fn in must_show:
            wd = fn()
            if wd is None or not wd.isVisibleTo(win):
                outside.append("invisivel")
                continue
            tl = wd.mapTo(win, QPoint(0, 0))
            if tl.x() < -1 or tl.y() < -1 or tl.x() + wd.width() > win.width() + 1 or tl.y() + wd.height() > win.height() + 1:
                outside.append(f"{type(wd).__name__} fora ({tl.x()},{tl.y()} {wd.width()}x{wd.height()} em {win.width()}x{win.height()})")
        R.check(f"{name}_{label}_botoes_principais_visiveis", not outside, "; ".join(outside))
        if label in ("notebook_1366x768_150", "fullhd_200"):
            shot(win, f"{name}-{label}")


def t_detector() -> None:
    """Autoteste: o detector de janelas soltas realmente enxerga uma (senao 'zero janelas soltas' nao provaria nada)."""
    from PySide6.QtWidgets import QLabel
    with U.OrphanProbe() as probe:
        lbl = QLabel("orfao")
        lbl.setVisible(True)
        U.settle(100)
        lbl.deleteLater()
    R.check("detector_de_janelas_soltas_funciona", probe.total() >= 1, f"detectou {probe.hits}")


def main() -> int:
    only = set(filter(None, ARGS.only.split(",")))
    for name, fn in (("detector", t_detector), ("memory", t_memory), ("recorder", t_recorder), ("wizard", t_wizard)):
        if only and name not in only:
            continue
        with R.guard(name):
            fn()
    R.save()
    return 1 if R.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
