"""Demonstracao da Ilha (fase I0): ciclo automatico de estados com audio SINTETICO, capturas e medicao.

    Jarvis.cmd island-demo                    # abre a Ilha e cicla os estados (Ctrl+C ou --seconds)
    Jarvis.cmd island-demo --capture PASTA    # grava PNG por tamanho e estado (use QT_QPA_PLATFORM=offscreen)
    Jarvis.cmd island-demo --measure 8        # mede CPU/RAM em repouso, ativa e expandida (8 s cada)
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QEventLoop, QObject, QRectF, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from ..kit.platform import motion_enabled, set_motion_override
from ..theme import LIGHT, ThemeManager, contrast
from . import tokens as T
from .dsp import SyntheticSource
from .tokens import IslandSize, IslandState
from .window import IslandWindow

_Q = "abre o Chrome e pesquisa o preço do dólar hoje"
# (estado, segundos, transcricao, passo)
_CYCLE: tuple[tuple[IslandState, float, str, str], ...] = (
    (IslandState.IDLE, 3.0, "", ""),
    (IslandState.LISTENING, 4.0, "abre o Chrome e pesquisa", ""),
    (IslandState.TRANSCRIBING, 1.8, _Q, ""),
    (IslandState.THINKING, 2.6, _Q, "Escolhendo as ferramentas"),
    (IslandState.ACTING, 2.8, _Q, "Abrindo o Chrome..."),
    (IslandState.CONFIRMING, 6.0, _Q, ""),
    (IslandState.SPEAKING, 4.0, _Q, "Pronto, abri o Chrome e pesquisei o dólar."),
)
_CONFIRM = "Apagar 3 arquivos da pasta Downloads?"


class DemoCycle(QObject):
    """Percorre os estados com dados falsos; Sim/Nao respondidos na Ilha avancam o ciclo."""

    def __init__(self, win: IslandWindow) -> None:
        super().__init__(win)
        self._win = win
        self._i = -1
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.next)
        win.confirm_answered.connect(lambda _yes: self.next())

    def start(self) -> None:
        self.next()

    def next(self) -> None:
        self._timer.stop()
        self._i = (self._i + 1) % len(_CYCLE)
        state, secs, transcript, detail = _CYCLE[self._i]
        w = self._win
        w.set_transcript(transcript)
        w.set_detail(detail)
        if state is IslandState.CONFIRMING:
            w.ask_confirmation(_CONFIRM, int(secs))
        else:
            w.set_state(state)
        self._timer.start(int(secs * 1000))


def _make_app() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    mgr = ThemeManager.instance()
    mgr.set_mode("dark")          # a Ilha e sempre escura (botoes do kit seguem o tema do app)
    mgr.apply(app)
    return app  # type: ignore[return-value]


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _contrast_report() -> list[str]:
    p = T.PALETTE
    pairs = (("texto", p.text), ("texto secundario", p.text_muted), ("destaque", T.accent()), ("atencao", p.warn))
    return [f"  contraste {n} sobre fundo da Ilha: {contrast(c, p.bg):.1f}:1" for n, c in pairs]


# ------------------------------------------------------------------ capturas
def _grab(win: IslandWindow, path: str) -> None:
    pm = win.grab()
    ratio = pm.devicePixelRatio()
    pad = round(32 * ratio)
    img = QImage(pm.width() + 2 * pad, pm.height() + 2 * pad, QImage.Format.Format_ARGB32)
    img.fill(QColor(LIGHT.bg))                      # fundo claro so para o contorno da Ilha preta aparecer
    p = QPainter(img)
    src = pm.toImage()
    src.setDevicePixelRatio(1.0)
    p.drawImage(pad, pad, src)
    p.end()
    img.save(path)


def capture_all(outdir: str) -> list[str]:
    os.makedirs(outdir, exist_ok=True)
    app = _make_app()
    scale = round(app.primaryScreen().devicePixelRatio())
    suffix = f"_{scale * 100}pct"
    win = IslandWindow(SyntheticSource())
    win.show()
    made: list[str] = []
    detail = {IslandState.ACTING: "Abrindo o Chrome...", IslandState.THINKING: "Escolhendo as ferramentas",
              IslandState.SPEAKING: "Pronto, abri o Chrome e pesquisei o dólar."}

    def shoot(name: str, size: IslandSize, state: IslandState, settle_ms: int = 900) -> None:
        win.pin_size(None if size is IslandSize.REST else size)
        win.set_transcript(_Q if state is not IslandState.IDLE else "")
        win.set_detail(detail.get(state, ""))
        if state is IslandState.CONFIRMING:
            win.ask_confirmation(_CONFIRM, 15)
        else:
            win.set_state(state)
        _wait(settle_ms)
        path = os.path.join(outdir, f"ilha_{name}{suffix}.png")
        _grab(win, path)
        made.append(path)

    shoot("repouso_idle", IslandSize.REST, IslandState.IDLE, 400)
    for size in (IslandSize.ACTIVE, IslandSize.EXPANDED):
        for st in IslandState:
            shoot(f"{size.value}_{st.name.lower()}", size, st)
    # versao "reduzir movimento"
    set_motion_override(False)
    for st in (IslandState.LISTENING, IslandState.THINKING):
        shoot(f"reduzido_expandido_{st.name.lower()}", IslandSize.EXPANDED, st, 600)
    set_motion_override(None)
    win.close()
    return made


# ------------------------------------------------------------------ medicao
def measure(seconds: float) -> int:
    import psutil

    app = _make_app()
    proc = psutil.Process()
    cores = psutil.cpu_count() or 1
    win = IslandWindow(SyntheticSource())
    win.show()
    phases = (("repouso", IslandSize.REST, IslandState.IDLE), ("ativa (ouvindo)", IslandSize.ACTIVE, IslandState.LISTENING),
              ("ativa (pensando)", IslandSize.ACTIVE, IslandState.THINKING),
              ("expandida (falando)", IslandSize.EXPANDED, IslandState.SPEAKING))
    print(f"plataforma Qt: {app.platformName()}  nucleos logicos: {cores}  reduzir movimento: {not motion_enabled()}")
    state = {"i": 0}

    def begin() -> None:
        name, size, st = phases[state["i"]]
        win.pin_size(None if size is IslandSize.REST else size)
        win.set_state(st)
        QTimer.singleShot(1500, lambda: (proc.cpu_percent(None), QTimer.singleShot(int(seconds * 1000), end)))

    def end() -> None:
        name = phases[state["i"]][0]
        cpu = proc.cpu_percent(None)
        rss = proc.memory_info().rss / 1e6
        print(f"{name:22s} CPU {cpu:5.1f}% de 1 nucleo ({cpu / cores:4.1f}% da maquina)  RAM {rss:6.1f} MB")
        state["i"] += 1
        if state["i"] < len(phases):
            begin()
        else:
            win.close()
            app.quit()

    QTimer.singleShot(0, begin)
    app.exec()
    return 0


# ------------------------------------------------------------------ demo ao vivo
def main_island_demo(capture: str | None = None, seconds: float = 0.0, measure_s: float = 0.0,
                     reduce_motion: bool = False) -> int:
    if reduce_motion:
        set_motion_override(False)
    if measure_s > 0:
        return measure(measure_s)
    if capture:
        made = capture_all(capture)
        print(f"{len(made)} capturas em {capture}")
        print("\n".join(_contrast_report()))
        return 0
    app = _make_app()
    win = IslandWindow(SyntheticSource())
    win.show()
    DemoCycle(win).start()
    if seconds > 0:
        QTimer.singleShot(int(seconds * 1000), app.quit)
    print(f"Ilha de demonstração no topo da tela (atalho final: {T.HOTKEY}). Clique alterna o tamanho; Ctrl+C encerra.")
    return app.exec()
