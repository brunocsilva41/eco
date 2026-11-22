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
from ..theme import TYPE, contrast, make_font
from . import glyphs
from . import tokens as T
from .bridge import IslandBridge, LevelFeed
from .conf import IslandConfig
from .dsp import SyntheticSource
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
        win.listen_toggled.connect(lambda mode: bus.publish("listen_mode", mode=mode))   # o "nucleo" falso confirma o clique
        self._steps = (
            (3.0, lambda: bus.publish("state", state="idle")),
            (3.0, lambda: bus.publish("listen_mode", mode="open")),                       # simula a escuta aberta ligando
            (3.0, lambda: bus.publish("state", state="idle")),
            (4.0, self._listen),
            (1.6, lambda: (bus.publish("state", state="transcribing"), bus.publish("transcript", text=_Q, final=True))),
            (2.4, lambda: bus.publish("state", state="thinking")),
            (3.0, lambda: (bus.publish("state", state="acting"),
                           bus.publish("action_step", tool="abrir_app", text="abrir bloco de notas", status="start"))),
            (6.0, lambda: bus.publish("confirm_request", id="c1", text=_CONFIRM, risk=2, timeout_s=6)),
            (5.0, self._speak),
            (3.0, lambda: bus.publish("state", state="idle")),
            (2.0, lambda: bus.publish("listen_mode", mode="push")),                       # e desligando
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
    """Folha de icones: todos os glifos em 16/20/24 px x 100%/200% (pixels reais) + vetor ampliado + estados."""
    pal = T.PALETTE
    names = glyphs.sheet_names()
    states = ("idle", "listening", "muted", "transcribing", "thinking", "acting", "speaking", "confirming", "error")
    cell, top, zoom = 56, 36, 96
    cols = [(s_, sc) for sc in (1, 2) for s_ in (16, 20, 24)]
    rows = [("g", n) for n in names] + [("s", n) for n in states]
    row_h = 60
    width = 150 + len(cols) * cell + zoom + 24
    img = QImage(width, top + len(rows) * row_h + 8, QImage.Format.Format_ARGB32)
    img.fill(QColor(T.BG))
    p = QPainter(img)
    p.setFont(make_font(TYPE.caption))
    p.setPen(QColor(pal.text_muted))
    center = int(Qt.AlignmentFlag.AlignCenter)
    for ci, (s_, sc) in enumerate(cols):
        p.drawText(QRectF(150 + ci * cell, 8, cell, 24), center, f"{s_}px {sc * 100}%")
    p.drawText(QRectF(150 + len(cols) * cell, 8, zoom, 24), center, "vetor 48px")
    for ri, (kind, name) in enumerate(rows):
        y = top + ri * row_h
        color = T.accent() if name in ("listening", "speaking") else (pal.error if name in ("error", "alert") else pal.text)
        p.setPen(QColor(pal.text))
        p.setFont(make_font(TYPE.small, TYPE.semibold))
        p.drawText(QRectF(12, y, 130, row_h), int(Qt.AlignmentFlag.AlignVCenter), ("estado: " if kind == "s" else "") + name)
        def paint(q: QPainter, rect: QRectF) -> None:
            if kind == "g":
                glyphs.draw(q, name, rect, color, fill=name in ("pin", "bolt", "stop"))
            else:
                glyphs.draw_state(q, name, rect, color, 0.45)
        for ci, (s_, sc) in enumerate(cols):
            phys = s_ * sc + 16
            tile = QImage(phys, phys, QImage.Format.Format_ARGB32)
            tile.fill(QColor(T.BG))
            tp = QPainter(tile)
            tp.translate(8, 8)
            tp.scale(sc, sc)
            paint(tp, QRectF(0, 0, s_, s_))
            tp.end()
            p.drawImage(150 + ci * cell + (cell - phys) // 2, y + (row_h - phys) // 2, tile)
        z = QImage(zoom, row_h - 4, QImage.Format.Format_ARGB32)
        z.fill(QColor(T.BG))
        zp = QPainter(z)
        paint(zp, QRectF((zoom - 48) / 2, 4, 48, 48))
        zp.end()
        p.drawImage(150 + len(cols) * cell, y, z)
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
            v = curve.valueForProgress(i / 16)
            win._cur = (T.SIZES[a][0] + (T.SIZES[b][0] - T.SIZES[a][0]) * v, T.SIZES[a][1] + (T.SIZES[b][1] - T.SIZES[a][1]) * v)
            win._apply_geometry()
            win.update()
            _wait(30)
            rgb = _compose(win.grab(), width=T.LW + 48, height=T.LH + 28).convertToFormat(QImage.Format.Format_RGB888)
            frames.append(Image.frombytes("RGB", (rgb.width(), rgb.height()), bytes(rgb.constBits()),
                                          "raw", "RGB", rgb.bytesPerLine(), 1))
        frames.extend([frames[-1]] * 8)                  # pausa no tamanho final
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=40, loop=0)
    return True


def _visible_cfg(**kw) -> IslandConfig:
    c = IslandConfig(autohide=False)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def capture_all(outdir: str) -> list[str]:
    """PNG por modo (acoplada/flutuante) x tamanho x estado, botoes em hover/pressionado/foco, keycaps."""
    os.makedirs(outdir, exist_ok=True)
    app = _make_app()
    scale = round(app.primaryScreen().devicePixelRatio())
    suffix = f"_{scale * 100}pct"
    win = IslandWindow(SyntheticSource(), cfg=_visible_cfg())
    win.start()
    _wait(500)
    made: list[str] = []

    def shoot(name: str, size: IslandSize, state: IslandState, settle_ms: int = 700) -> None:
        win.pin_size(size)
        _fixture(win, state)
        _wait(settle_ms)
        path = os.path.join(outdir, f"ilha_{name}{suffix}.png")
        _compose(win.grab(), pad_x=48, pad_b=48).save(path)
        made.append(path)

    for mode in ("docked", "floating"):
        win.apply_config(_visible_cfg(mode=mode))
        for size in IslandSize:
            for st in IslandState:
                shoot(f"{'acoplada' if mode == 'docked' else 'flutuante'}_{size.value}_{st.name.lower()}", size, st)
    win.apply_config(_visible_cfg(mode="floating"))
    win.set_yolo(24 * 60 + 59)
    win.set_mute(True)
    shoot("flutuante_grande_modos_yolo_mudo", IslandSize.LARGE, IslandState.THINKING)
    win.set_yolo(None)
    win.set_mute(False)
    # botoes: hover / pressionado / foco de teclado
    win.apply_config(_visible_cfg(mode="docked"))
    win.pin_size(IslandSize.LARGE)
    _fixture(win, IslandState.CONFIRMING)
    _wait(700)
    for tag, btn, kind in (("hover_sim", win.b_yes, "hover"), ("pressionado_nao", win.b_no, "press"),
                           ("hover_parar", win.b_stop, "hover"), ("foco_mudo", win.b_mute, "focus")):
        win._hover_btn = btn if kind == "hover" else None
        btn.press = kind == "press"
        win._focus_btn = btn if kind == "focus" else None
        for b in win.btns:
            b.focus = b is win._focus_btn
            b.hover = 1.0 if b is win._hover_btn else 0.0
        win.update()
        _wait(300)
        path = os.path.join(outdir, f"ilha_botao_{tag}{suffix}.png")
        _compose(win.grab(), pad_x=48, pad_b=48).save(path)
        made.append(path)
        btn.press = False
    win._hover_btn = win._focus_btn = None
    set_motion_override(False)                           # versao "reduzir movimento"
    for st in (IslandState.LISTENING, IslandState.THINKING):
        shoot(f"reduzido_grande_{st.name.lower()}", IslandSize.LARGE, st, 600)
    set_motion_override(None)
    if scale == 1:
        icon_sheet(os.path.join(outdir, "ilha_icones_folha.png"))
        made.append("folha de icones")
        if transition_gif(win, os.path.join(outdir, "ilha_transicao_compacta_media_grande.gif")):
            made.append("gif")
    win.close()
    return made


def _backdrop(w: int, h: int, light: bool) -> QImage:
    """Fundo de teste para o vidro: claro (pior caso: branco com texto escuro) ou escuro, com listras de 'conteudo'."""
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("#FFFFFF" if light else "#1B1E24"))
    p = QPainter(img)
    ink = QColor("#222222" if light else "#E0E0E0")
    for y in range(8, h, 18):
        p.fillRect(12, y, max(8, w - 24 - (y * 7) % 90), 6, ink)
    p.end()
    return img


def _compose_on(pm, side: str, light: bool, pad: int = 28) -> QImage:  # type: ignore[no-untyped-def]
    ratio = pm.devicePixelRatio()
    src = pm.toImage()
    src.setDevicePixelRatio(1.0)
    pw = round(pad * ratio)
    if side:
        img = _backdrop(src.width() + 2 * pw, src.height() + 2 * pw, light)
        p = QPainter(img)
        p.drawImage(img.width() - src.width() if side == "right" else 0, pw, src)
    else:
        img = _backdrop(src.width() + 2 * pw, src.height() + pw, light)
        p = QPainter(img)
        p.drawImage((img.width() - src.width()) // 2, 0, src)
    p.end()
    return img


def capture_v3(outdir: str) -> list[str]:
    """Rodada v3: trilho lateral (2 lados x 3 tamanhos x estados), escuta aberta ligada/desligada em cada modo,
    alfinete e transparencia (3 valores sobre fundo claro e escuro). Offscreen: ``win.grab()`` + fundo de teste."""
    os.makedirs(outdir, exist_ok=True)
    app = _make_app()
    suffix = f"_{round(app.primaryScreen().devicePixelRatio()) * 100}pct"
    win = IslandWindow(SyntheticSource(), cfg=_visible_cfg())
    win.start()
    _wait(400)
    made: list[str] = []

    def shoot(name: str, mode: str, size: IslandSize, state: IslandState, *, listen: bool = False, opacity: float = 0.92,
              light: bool = False, pinned: bool = False, yolo: bool = False, settle: int = 650) -> None:
        win.apply_config(_visible_cfg(mode=mode, opacity=opacity, pinned=pinned))
        win.set_listen_mode("open" if listen else "push")
        win.set_yolo(1499 if yolo else None)
        win.pin_size(size)
        _fixture(win, state)
        _wait(settle)
        path = os.path.join(outdir, f"ilha_{name}{suffix}.png")
        _compose_on(win.grab(), win.cfg.side, light).save(path)
        made.append(path)

    for mode in ("dock_right", "dock_left"):
        tag = mode.replace("dock_", "lat_")
        shoot(f"{tag}_recolhido_repouso", mode, IslandSize.COMPACT, IslandState.IDLE)
        shoot(f"{tag}_recolhido_repouso_escuta_aberta", mode, IslandSize.COMPACT, IslandState.IDLE, listen=True)
        shoot(f"{tag}_recolhido_ouvindo_yolo", mode, IslandSize.COMPACT, IslandState.LISTENING, yolo=True)
        shoot(f"{tag}_medio_pensando", mode, IslandSize.MEDIUM, IslandState.THINKING)
        shoot(f"{tag}_medio_ouvindo_escuta_aberta", mode, IslandSize.MEDIUM, IslandState.LISTENING, listen=True)
        shoot(f"{tag}_grande_falando", mode, IslandSize.LARGE, IslandState.SPEAKING)
        shoot(f"{tag}_grande_falando_escuta_aberta_fixada", mode, IslandSize.LARGE, IslandState.SPEAKING, listen=True, pinned=True,
              yolo=True)
        shoot(f"{tag}_grande_confirmacao", mode, IslandSize.LARGE, IslandState.CONFIRMING)
        shoot(f"{tag}_grande_erro", mode, IslandSize.LARGE, IslandState.ERROR)
    for mode in ("docked", "floating"):
        for on in (False, True):
            tag = f"{'acoplada' if mode == 'docked' else 'flutuante'}_escuta_{'ligada' if on else 'desligada'}"
            shoot(f"topo_{tag}_media_repouso", mode, IslandSize.MEDIUM, IslandState.IDLE, listen=on)
            shoot(f"topo_{tag}_grande_repouso", mode, IslandSize.LARGE, IslandState.IDLE, listen=on)
            shoot(f"topo_{tag}_compacta_repouso", mode, IslandSize.COMPACT, IslandState.IDLE, listen=on)
    shoot("topo_fixada_compacta", "docked", IslandSize.COMPACT, IslandState.IDLE, pinned=True)
    shoot("topo_fixada_media", "docked", IslandSize.MEDIUM, IslandState.THINKING, pinned=True)
    shoot("topo_fixada_grande", "docked", IslandSize.LARGE, IslandState.THINKING, pinned=True)
    shoot("topo_nao_fixada_grande", "docked", IslandSize.LARGE, IslandState.THINKING, pinned=False)
    for light in (True, False):
        bgname = "claro" if light else "escuro"
        for op in (0.35, 0.7, 1.0):
            shoot(f"vidro_{int(op * 100)}_{bgname}_topo_media_ouvindo", "docked", IslandSize.MEDIUM, IslandState.LISTENING,
                  opacity=op, light=light, listen=True)
            shoot(f"vidro_{int(op * 100)}_{bgname}_topo_grande_repouso", "docked", IslandSize.LARGE, IslandState.IDLE,
                  opacity=op, light=light)
            shoot(f"vidro_{int(op * 100)}_{bgname}_lateral_grande_falando", "dock_right", IslandSize.LARGE, IslandState.SPEAKING,
                  opacity=op, light=light)
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
    win = IslandWindow(synth, cfg=_visible_cfg())
    win.start()
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
                     reduce_motion: bool = False, floating: bool = False, autohide: bool = False, mode: str = "docked",
                     opacity: float = 0.92, pinned: bool = False, listen: bool = False) -> int:
    if reduce_motion:
        set_motion_override(False)
    if measure_s > 0:
        return measure(measure_s)
    if capture:
        made = capture_all(capture) + capture_v3(os.path.join(capture, "v3"))
        print(f"{len(made)} itens gerados em {capture}")
        print("\n".join(_contrast_report()))
        return 0
    from ...core.events import EventBus

    app = _make_app()
    win = IslandWindow(cfg=_visible_cfg(mode="floating" if floating else mode, autohide=autohide, opacity=opacity,
                                        pinned=pinned or None))
    win.start()
    bus = EventBus()
    bridge = IslandBridge(win, bus, feed=SyntheticSource())  # type: ignore[arg-type]
    bus.publish("mute", muted=False)
    if listen:
        bus.publish("listen_mode", mode="open")
    win.set_permission_mode("balanced")
    DemoCycle(win, bus).start()
    if seconds > 0:
        QTimer.singleShot(int(seconds * 1000), app.quit)
    print(f"Ilha de demonstração no topo da tela (atalho final: {T.HOTKEY}). Clique alterna o tamanho; Ctrl+C encerra.")
    code = app.exec()
    bridge.close()
    bus.close()
    return code
