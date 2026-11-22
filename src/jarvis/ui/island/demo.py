"""Demonstracao da Ilha (fase I0): ciclo de estados com eventos FALSOS pelo EventBus real + bridge,
audio SINTETICO, capturas por tamanho e estado, folha de icones do microfone, GIF e medicao.

    Jarvis.cmd island-demo                    # abre a Ilha e cicla os estados (Ctrl+C ou --seconds)
    Jarvis.cmd island-demo --capture PASTA    # PNG por tamanho x estado, folha de icones e GIF (offscreen)
    Jarvis.cmd island-demo --measure 8        # mede CPU/RAM por fase (8 s cada)
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QEasingCurve, QEventLoop, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from ..kit.platform import motion_enabled, set_motion_override
from ..theme import TYPE, ThemeManager, contrast, make_font
from . import tokens as T
from .bridge import IslandBridge, LevelFeed
from .dsp import SyntheticSource
from .micicon import MicKind, draw_mic
from .tokens import IslandSize, IslandState
from .window import IslandWindow

_Q = "abre o bloco de notas e escreve a lista de compras de hoje"
_REPLY = ("Pronto, abri o bloco de notas e escrevi a lista: leite, pão, ovos e café. "
          "Quer que eu salve o arquivo na pasta Documentos?")
_CONFIRM = "Apagar 3 arquivos da pasta Downloads?"
_WALL = "#7C8696"                                    # "papel de parede" neutro so para as capturas


class DemoCycle(QObject):
    """Publica eventos falsos no EventBus real (mesmo contrato do nucleo); a bridge os aplica na Ilha."""

    def __init__(self, win: IslandWindow, bus) -> None:  # type: ignore[no-untyped-def]
        super().__init__(win)
        self._bus = bus
        self._i = -1
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.next)
        win.confirm_answered.connect(self._answered)
        self._steps = (
            (3.0, lambda: bus.publish("state", state="idle")),
            (4.0, self._listen),
            (1.6, lambda: (bus.publish("state", state="transcribing"), bus.publish("transcript", text=_Q, final=True))),
            (2.4, lambda: bus.publish("state", state="thinking")),
            (3.0, lambda: (bus.publish("state", state="acting"),
                           bus.publish("action_step", tool="abrir_app", text="abrir bloco de notas", status="start"))),
            (6.0, lambda: bus.publish("confirm_request", id="c1", text=_CONFIRM, risk=2, timeout_s=6)),
            (5.0, self._speak),
        )

    def _listen(self) -> None:
        self._bus.publish("state", state="listening")
        self._bus.publish("context_usage", used=4200, limit=12288, n_ctx=12288, pct=34)

    def _speak(self) -> None:
        self._bus.publish("action_step", tool="abrir_app", text="abrir bloco de notas", status="ok",
                          result="Bloco de notas aberto")
        self._bus.publish("state", state="speaking")
        self._bus.publish("reply_text", text=_REPLY)

    def _answered(self, _yes: bool) -> None:
        self._bus.publish("confirm_done", id="c1")
        self.next()

    def start(self) -> None:
        self.next()

    def next(self) -> None:
        self._timer.stop()
        self._i = (self._i + 1) % len(self._steps)
        secs, fn = self._steps[self._i]
        fn()
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
    pairs = (("texto", p.text), ("texto secundario", p.text_muted), ("destaque", T.accent()),
             ("atencao", p.warn), ("erro", p.error), ("ok", p.ok))
    return [f"  contraste {n} sobre o preto da Ilha: {contrast(c, p.bg):.1f}:1" for n, c in pairs]


# ------------------------------------------------------------------ capturas
def _compose(pm, *, pad_x: int = 32, pad_b: int = 32, width: int = 0, height: int = 0) -> QImage:  # type: ignore[no-untyped-def]
    """Ilha colada ao topo sobre um fundo neutro (como na tela), com margens so nas laterais e embaixo."""
    ratio = pm.devicePixelRatio()
    src = pm.toImage()
    src.setDevicePixelRatio(1.0)
    px, pb = round(pad_x * ratio), round(pad_b * ratio)
    w = round(width * ratio) if width else src.width() + 2 * px
    img = QImage(w, round(height * ratio) if height else src.height() + pb, QImage.Format.Format_ARGB32)
    img.fill(QColor(_WALL))
    p = QPainter(img)
    p.drawImage((w - src.width()) // 2, 0, src)
    p.end()
    return img


def _fixture(win: IslandWindow, state: IslandState) -> None:
    win.set_preview_clock(12.0)
    win.set_permission_mode("balanced")
    win.set_context_pct(34)
    win.set_transcript(_Q if state is not IslandState.IDLE else "")
    win.set_reply(_REPLY if state in (IslandState.SPEAKING, IslandState.IDLE) else "")
    if state is IslandState.ACTING:
        win.set_action("abrir_app", "abrir bloco de notas", "start")
    else:
        win.set_action("abrir_app", "abrir bloco de notas", "ok", "Bloco de notas aberto")
    if state is IslandState.ERROR:
        win.set_error("O modelo não respondeu. Reinicie o Jarvis.")
    elif state is IslandState.CONFIRMING:
        win.ask_confirmation(_CONFIRM, 15)
    else:
        win.set_state(state)


def icon_sheet(path: str) -> None:
    """Folha de contato do icone do microfone: 4 estados x 16/20/24 px x 100%/200% (pixels reais) + zoom."""
    pal = T.PALETTE
    kinds = ((MicKind.REST, "Repouso", 0.0), (MicKind.LISTENING, "Ouvindo", 0.45),
             (MicKind.MUTED, "Mudo", 0.0), (MicKind.ERROR, "Erro", 0.0))
    cols = [(s, sc) for sc in (1, 2) for s in (16, 20, 24)]
    cell, label_w, top, zoom = 64, 96, 36, 96
    row_h = zoom + 16
    width = label_w + len(cols) * cell + zoom + 32
    height = top + len(kinds) * row_h + 8
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(pal.bg))
    p = QPainter(img)
    center = int(Qt.AlignmentFlag.AlignCenter)
    p.setFont(make_font(TYPE.caption))
    p.setPen(QColor(pal.text_muted))
    for ci, (s, sc) in enumerate(cols):
        p.drawText(QRectF(label_w + ci * cell, 8, cell, 24), center, f"{s}px {sc * 100}%")
    p.drawText(QRectF(label_w + len(cols) * cell, 8, zoom, 24), center, "vetor 96px")
    for ri, (kind, name, phase) in enumerate(kinds):
        y = top + ri * row_h
        color = pal.error if kind is MicKind.ERROR else (T.accent() if kind is MicKind.LISTENING else pal.text)
        p.setPen(QColor(pal.text))
        p.setFont(make_font(TYPE.small, TYPE.semibold))
        p.drawText(QRectF(12, y, label_w - 12, row_h), int(Qt.AlignmentFlag.AlignVCenter), name)
        for ci, (s, sc) in enumerate(cols):
            phys = s * sc + 24
            tile = QImage(phys, phys, QImage.Format.Format_ARGB32)
            tile.fill(QColor(pal.bg))
            tp = QPainter(tile)
            tp.translate(12, 12)
            tp.scale(sc, sc)
            draw_mic(tp, QRectF(0, 0, s, s), kind, color, bg=pal.bg, phase=phase)
            tp.end()
            p.drawImage(label_w + ci * cell + (cell - phys) // 2, y + (row_h - phys) // 2, tile)
        z = QImage(zoom, zoom, QImage.Format.Format_ARGB32)
        z.fill(QColor(pal.bg))
        zp = QPainter(z)
        draw_mic(zp, QRectF(10, 10, zoom - 20, zoom - 20), kind, color, bg=pal.bg, phase=phase)
        zp.end()
        p.drawImage(label_w + len(cols) * cell, y, z)
    p.end()
    img.save(path)


def transition_gif(win: IslandWindow, path: str) -> bool:
    """GIF compacta -> media -> grande -> compacta, com a mesma curva do app (mola ao crescer)."""
    try:
        from PIL import Image
    except ImportError:
        return False
    _fixture(win, IslandState.LISTENING)
    win.pin_size(IslandSize.COMPACT)
    _wait(200)
    frames = []
    seq = ((IslandSize.COMPACT, IslandSize.MEDIUM), (IslandSize.MEDIUM, IslandSize.LARGE),
           (IslandSize.LARGE, IslandSize.COMPACT))
    for a, b in seq:
        grow = T.SIZES[b][0] * T.SIZES[b][1] > T.SIZES[a][0] * T.SIZES[a][1]
        curve = QEasingCurve(QEasingCurve.Type.OutBack if grow else QEasingCurve.Type.OutCubic)
        if grow:
            curve.setOvershoot(T.OVERSHOOT)
        for i in range(17):
            win._morph(T.SIZES[a], T.SIZES[b], curve.valueForProgress(i / 16))
            _wait(30)
            rgb = _compose(win.grab(), width=T.LW + 48, height=T.LH + 28).convertToFormat(QImage.Format.Format_RGB888)
            frames.append(Image.frombytes("RGB", (rgb.width(), rgb.height()), bytes(rgb.constBits()),
                                          "raw", "RGB", rgb.bytesPerLine(), 1))
        frames.extend([frames[-1]] * 8)                  # pausa no tamanho final
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=40, loop=0)
    return True


def capture_all(outdir: str) -> list[str]:
    os.makedirs(outdir, exist_ok=True)
    app = _make_app()
    scale = round(app.primaryScreen().devicePixelRatio())
    suffix = f"_{scale * 100}pct"
    win = IslandWindow(SyntheticSource())
    win.show()
    made: list[str] = []

    def shoot(name: str, size: IslandSize, state: IslandState, settle_ms: int = 900) -> None:
        win.pin_size(size)
        _fixture(win, state)
        _wait(settle_ms)
        path = os.path.join(outdir, f"ilha_{name}{suffix}.png")
        _compose(win.grab()).save(path)
        made.append(path)

    for size in IslandSize:
        for st in IslandState:
            shoot(f"{size.value}_{st.name.lower()}", size, st)
    win.set_yolo(24 * 60 + 59)                           # modos no cabecalho grande: YOLO + mudo
    win.set_mute(True)
    shoot("grande_modos_yolo_mudo", IslandSize.LARGE, IslandState.THINKING)
    win.set_yolo(None)
    win.set_mute(False)
    set_motion_override(False)                           # versao "reduzir movimento"
    for st in (IslandState.LISTENING, IslandState.THINKING):
        shoot(f"reduzido_grande_{st.name.lower()}", IslandSize.LARGE, st, 600)
    set_motion_override(None)
    if scale == 1:
        icon_sheet(os.path.join(outdir, "ilha_icone_microfone_folha.png"))
        made.append("folha de icones")
        if transition_gif(win, os.path.join(outdir, "ilha_transicao_compacta_media_grande.gif")):
            made.append("gif")
    win.close()
    return made


# ------------------------------------------------------------------ medicao
def measure(seconds: float) -> int:
    import psutil

    app = _make_app()
    proc = psutil.Process()
    cores = psutil.cpu_count() or 1
    synth = SyntheticSource()
    feed = LevelFeed()
    feed.on_level("mic", 0.5)
    feed.on_level("tts", 0.5)
    win = IslandWindow(synth)
    win.show()
    phases = (("compacta, em repouso", IslandSize.COMPACT, IslandState.IDLE, synth),
              ("media, pensando", IslandSize.MEDIUM, IslandState.THINKING, synth),
              ("media, ouvindo (sintetico)", IslandSize.MEDIUM, IslandState.LISTENING, synth),
              ("media, ouvindo (nivel real)", IslandSize.MEDIUM, IslandState.LISTENING, feed),
              ("grande, falando (sintetico)", IslandSize.LARGE, IslandState.SPEAKING, synth),
              ("grande, falando (nivel real)", IslandSize.LARGE, IslandState.SPEAKING, feed))
    print(f"plataforma Qt: {app.platformName()}  nucleos logicos: {cores}  reduzir movimento: {not motion_enabled()}")
    idx = {"i": 0}

    def begin() -> None:
        _name, size, st, src = phases[idx["i"]]
        win.set_levels_source(src)
        win.pin_size(size)
        _fixture(win, st)
        QTimer.singleShot(1500, lambda: (proc.cpu_percent(None), QTimer.singleShot(int(seconds * 1000), end)))

    def end() -> None:
        name = phases[idx["i"]][0]
        cpu = proc.cpu_percent(None)
        rss = proc.memory_info().rss / 1e6
        print(f"{name:30s} CPU {cpu:5.1f}% de 1 nucleo ({cpu / cores:4.1f}% da maquina)  RAM {rss:6.1f} MB")
        idx["i"] += 1
        if idx["i"] < len(phases):
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
        print(f"{len(made)} itens gerados em {capture}")
        print("\n".join(_contrast_report()))
        return 0
    from ...core.events import EventBus

    app = _make_app()
    win = IslandWindow()
    win.show()
    bus = EventBus()
    bridge = IslandBridge(win, bus, feed=SyntheticSource())  # type: ignore[arg-type]
    bus.publish("mute", muted=False)
    win.set_permission_mode("balanced")
    DemoCycle(win, bus).start()
    if seconds > 0:
        QTimer.singleShot(int(seconds * 1000), app.quit)
    print(f"Ilha de demonstração no topo da tela (atalho final: {T.HOTKEY}). Clique alterna o tamanho; Ctrl+C encerra.")
    code = app.exec()
    bridge.close()
    bus.close()
    return code
