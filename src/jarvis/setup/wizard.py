"""Janela do assistente: trilho de etapas, cabeçalho, página (com rolagem) e barra Voltar/Avançar.

Teclado: Tab/Shift+Tab, Enter (Avançar), Alt+Seta direita/esquerda. Fechar pergunta antes de sair e guarda o progresso.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from ..config import ROOT, ConfigError, load
from ..ui.kit.base import Label, set_a11y
from ..ui.kit.buttons import Button
from ..ui.settings.prefs import UiPrefs
from ..ui.theme import SIZE, SPACE, ThemeManager
from . import strings as S
from .manifest import load_manifest
from .pages_audio import AudioPage, DoctorPage, DonePage, HotkeysPage, PermissionsPage, VadPage, VoicePage
from .pages_core import HardwarePage, ModelsPage, WelcomePage
from .state import STEPS, SetupState, app_version, read_install_info
from .widgets import Ctx, Page, StepRail, ask_confirm

log = logging.getLogger("jarvis.setup")

MIN_W = SIZE.nav_width + SIZE.reading_width + SPACE.xl * 2 + SIZE.target
MIN_H = SIZE.target * 20
_PAGES = {"welcome": WelcomePage, "hardware": HardwarePage, "models": ModelsPage, "audio": AudioPage, "voice": VoicePage,
          "vad": VadPage, "hotkeys": HotkeysPage, "permissions": PermissionsPage, "doctor": DoctorPage, "done": DonePage}
_NO_HEADER = ("welcome", "done")


class WizardWindow(QWidget):
    def __init__(self, ctx: Ctx, start: str | None = None) -> None:
        super().__init__()
        self.ctx = ctx
        ctx.go = self.go
        ctx.reload_cfg = self.reload_cfg
        self.launch_after = False
        self.closing_ok = False
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle(S.WINDOW_TITLE_REPAIR if ctx.repair else S.WINDOW_TITLE)
        self.setMinimumSize(MIN_W, MIN_H)
        self.resize(MIN_W + SIZE.target * 3, MIN_H + SIZE.target * 3)
        set_a11y(self, self.windowTitle())

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.rail = StepRail(STEPS, S.WINDOW_TITLE_REPAIR if ctx.repair else S.WINDOW_TITLE, app_version(ctx.root))
        outer.addWidget(self.rail)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        outer.addLayout(right, 1)

        self.header = QWidget()
        hl = QVBoxLayout(self.header)
        hl.setContentsMargins(SPACE.xl * 2, SPACE.xl, SPACE.xl, 0)
        hl.setSpacing(SPACE.xs)
        self.title = Label("", "title")
        self.subtitle = Label("", "help", wrap=True)
        hl.addWidget(self.title)
        hl.addWidget(self.subtitle)
        right.addWidget(self.header)

        self.stack = QStackedWidget()
        self.pages: dict[str, Page] = {}
        for key in STEPS:
            page = _PAGES[key](ctx)
            page.changed.connect(self._sync_buttons)
            self.pages[key] = page
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            host = QWidget()
            hl2 = QHBoxLayout(host)
            hl2.setContentsMargins(SPACE.lg, 0, 0, 0)
            hl2.addWidget(page, 1)
            hl2.addStretch(0)
            scroll.setWidget(host)
            self.stack.addWidget(scroll)
        right.addWidget(self.stack, 1)

        bar = QFrame()
        bar.setProperty("kit", "bar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(SPACE.xl, SPACE.md, SPACE.xl, SPACE.md)
        bl.setSpacing(SPACE.sm)
        self.step_label = Label("", "help")
        bl.addWidget(self.step_label)
        bl.addStretch(1)
        self.back_btn = Button(S.BACK, icon_name="prev", shortcut="Alt+Left")
        self.back_btn.clicked.connect(self.back)
        self.next_btn = Button(S.NEXT, variant="primary", icon_name="next", shortcut="Alt+Right")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self.next)
        bl.addWidget(self.back_btn)
        bl.addWidget(self.next_btn)
        right.addWidget(bar)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.next)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.back)

        self.key = ""
        self.show_page(start if start in STEPS else "welcome", first=True)

    # ---------------------------------------------------------------- navegação
    def reload_cfg(self):
        try:
            return load()
        except ConfigError as exc:
            log.warning("config inválida ao recarregar: %s", exc)
            return self.ctx.cfg

    def go(self, key: str) -> None:
        if key in STEPS:
            self.show_page(key)

    def show_page(self, key: str, first: bool = False) -> None:
        page = self.pages[key]
        self.key = key
        self.ctx.state.step = key
        if not self.ctx.demo:
            try:
                self.ctx.state.save(self.ctx.root)
            except OSError as exc:
                log.warning("não salvei o progresso: %s", exc)
        self.stack.setCurrentIndex(STEPS.index(key))
        self.rail.set_current(key)
        self.header.setVisible(key not in _NO_HEADER)
        self.title.setText(S.STEP_TITLES[key])
        self.subtitle.setText(S.STEP_SUBTITLES[key])
        self.subtitle.setVisible(bool(S.STEP_SUBTITLES[key]))
        n = STEPS.index(key) + 1
        self.step_label.setText(S.STEP_OF.format(n=n, total=len(STEPS)))
        page.on_enter()
        self._sync_buttons()
        QTimer.singleShot(0, lambda: page.focusNextChild() if page.isVisible() else None)

    def _sync_buttons(self) -> None:
        page = self.pages[self.key]
        idx = STEPS.index(self.key)
        self.back_btn.setVisible(idx > 0)
        self.next_btn.setText(page.next_label())
        self.next_btn.setEnabled(page.can_advance())
        self.back_btn.setEnabled(True)

    def next(self) -> None:
        page = self.pages[self.key]
        if not page.can_advance() or not page.on_leave(True):
            return
        idx = STEPS.index(self.key)
        if idx + 1 >= len(STEPS):
            self.finish()
            return
        self.show_page(STEPS[idx + 1])

    def back(self) -> None:
        idx = STEPS.index(self.key)
        if idx == 0:
            return
        if not self.pages[self.key].on_leave(False):
            return
        self.show_page(STEPS[idx - 1])

    def finish(self) -> None:
        self.ctx.state.completed = True
        self.ctx.state.step = "done"
        if not self.ctx.demo:
            self.ctx.state.save(self.ctx.root)
        self.closing_ok = True
        self.close()

    def close_and_launch(self) -> None:
        self.launch_after = True
        self.pages["done"].on_leave(True)
        self.finish()

    def closeEvent(self, e: QCloseEvent) -> None:
        if not self.closing_ok and not self.ctx.state.completed and not self.ctx.demo:
            if not ask_confirm(self, S.EXIT_TITLE, S.EXIT_BODY, S.EXIT_CONFIRM):
                e.ignore()
                return
        for p in self.pages.values():
            try:
                p.teardown()
            except Exception:  # noqa: BLE001
                log.debug("teardown", exc_info=True)
        if not self.ctx.demo:
            try:
                self.ctx.state.save(self.ctx.root)
            except OSError:
                pass
        super().closeEvent(e)


def launch_jarvis(root: Path = ROOT) -> None:
    """Abre o Jarvis sem janela de console e desacoplado do assistente."""
    flags = 0x00000008 | 0x00000200 | 0x08000000           # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    pyw = root / "Jarvis.pyw"
    try:
        if pyw.is_file():
            exe = Path(sys.executable).with_name("pythonw.exe")
            subprocess.Popen([str(exe), "-I", "-X", "utf8", str(pyw)], cwd=str(root), creationflags=flags, close_fds=True)
        else:
            subprocess.Popen(["cmd", "/c", str(root / "Jarvis.cmd"), "run"], cwd=str(root), creationflags=flags, close_fds=True)
    except OSError as exc:
        log.warning("não consegui abrir o Jarvis: %s", exc)


def build_ctx(repair: bool, root: Path = ROOT, demo: bool = False) -> Ctx:
    manifest = load_manifest(root)
    state = SetupState.load(root)
    info = read_install_info(root)
    if not state.updated and isinstance(info.get("components"), list) and info["components"]:
        comps = [c for c in info["components"] if c in manifest.components]
        if comps:
            state.components = comps
    if repair:
        state.step, state.completed = "welcome", False
    try:
        cfg = load()
    except ConfigError:
        from ..config import from_dict
        cfg = from_dict({})
    return Ctx(root=root, manifest=manifest, state=state, cfg=cfg, repair=repair, demo=demo)


def main_wizard(repair: bool = False, start: str | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    UiPrefs().apply_saved_theme()
    ThemeManager.instance().apply(app)  # type: ignore[arg-type]
    ctx = build_ctx(repair)
    win = WizardWindow(ctx, start or "welcome")
    win.show()
    code = int(app.exec())
    if win.launch_after:
        launch_jarvis(ctx.root)
    return code
