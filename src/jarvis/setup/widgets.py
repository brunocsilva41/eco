"""Peças visuais do assistente (usam só o kit e os tokens): base de página, linha de checagem, trilho de etapas."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..config import ROOT, Config
from ..ui.kit.base import Label, set_a11y, watch_theme
from ..ui.kit.status import StatusChip
from ..ui.theme import RADIUS, SIZE, SPACE, TYPE, make_font, pal
from . import strings as S
from .manifest import Manifest
from .state import SetupState


@dataclass
class Ctx:
    """Estado compartilhado entre as páginas."""
    root: Path
    manifest: Manifest
    state: SetupState
    cfg: Config
    repair: bool = False
    demo: bool = False                      # captura offscreen: não toca em áudio nem em hotkeys reais
    go: Callable[[str], None] = field(default=lambda key: None)
    reload_cfg: Callable[[], Config] = field(default=lambda: None)   # type: ignore[assignment,return-value]
    extra: dict = field(default_factory=dict)

    @property
    def components(self) -> list[str]:
        return self.state.components


class Page(QWidget):
    """Uma etapa. `key` identifica a página; o assistente chama `on_enter` ao mostrar e `on_leave` ao sair."""

    key = ""
    changed = Signal()                      # a página mudou algo que afeta o botão Avançar

    def __init__(self, ctx: Ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(SPACE.xl, SPACE.lg, SPACE.xl, SPACE.xl)
        self.col.setSpacing(SPACE.lg)
        self.setMaximumWidth(SIZE.reading_width + 2 * SPACE.xl)

    # ---- ciclo de vida
    def on_enter(self) -> None:
        pass

    def on_leave(self, forward: bool) -> bool:
        """False cancela a navegação (a página deve explicar o motivo)."""
        return True

    def next_label(self) -> str:
        return S.NEXT

    def can_advance(self) -> bool:
        return True

    def teardown(self) -> None:
        """Libera recursos (streams de áudio, threads)."""


class CheckRow(QWidget):
    """Linha: selo de estado + título + detalhe + dica. Estado nunca é só cor (o selo tem ícone e palavra)."""

    def __init__(self, status: str, title: str, detail: str = "", hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, SPACE.xs, 0, SPACE.xs)
        lay.setSpacing(SPACE.md)
        chip_state = {"fail": "error"}.get(status, status)
        self.chip = StatusChip(chip_state, S.STATUS_TEXT.get(status, status))      # type: ignore[arg-type]
        self.chip.setFixedWidth(max(self.chip.sizeHint().width(), SIZE.target * 3))
        lay.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(Label(title, "label", wrap=True))
        if detail:
            col.addWidget(Label(detail, "body", wrap=True))
        if hint:
            col.addWidget(Label(hint, "help", wrap=True))
        lay.addLayout(col, 1)
        set_a11y(self, f"{S.STATUS_TEXT.get(status, status)}: {title}", " ".join(x for x in (detail, hint) if x))


class _RailRow(QWidget):
    def __init__(self, n: int, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.n, self.title = n, title
        self.state = "todo"                  # todo | now | done
        self.setFixedHeight(SIZE.target + SPACE.xs)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        watch_theme(self)

    def set_state(self, state: str) -> None:
        self.state = state
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(SIZE.nav_width, SIZE.target + SPACE.xs)

    def paintEvent(self, _e) -> None:  # type: ignore[no-untyped-def]
        p, g = pal(), QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = SPACE.xl
        cx, cy = SPACE.lg + d / 2, self.height() / 2
        circle = QRectF(cx - d / 2, cy - d / 2, d, d)
        if self.state == "now":
            g.setBrush(QColor(p.accent))
            g.setPen(Qt.PenStyle.NoPen)
            g.drawEllipse(circle)
            g.setPen(QColor(p.on_accent))
        elif self.state == "done":
            g.setBrush(QColor(p.ok_bg))
            g.setPen(QColor(p.ok))
            g.drawEllipse(circle)
            g.setPen(QColor(p.ok))
        else:
            g.setBrush(Qt.BrushStyle.NoBrush)
            g.setPen(QColor(p.border_strong))
            g.drawEllipse(circle)
            g.setPen(QColor(p.text_muted))
        g.setFont(make_font(TYPE.small, TYPE.semibold))
        mark = "✓" if self.state == "done" else str(self.n)
        g.drawText(circle, Qt.AlignmentFlag.AlignCenter, mark)
        g.setPen(QColor(p.text if self.state != "todo" else p.text_muted))
        g.setFont(make_font(TYPE.body, TYPE.semibold if self.state == "now" else TYPE.regular))
        g.drawText(QRectF(SPACE.lg * 2 + d, 0, self.width() - SPACE.lg * 3 - d, self.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.title)
        g.end()


class StepRail(QFrame):
    """Trilho lateral com as etapas (só leitura: a navegação é por Voltar/Avançar)."""

    def __init__(self, keys: tuple[str, ...], title: str, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("kit", "nav")
        self.setFixedWidth(SIZE.nav_width)
        self.keys = keys
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, SPACE.xl, 0, SPACE.lg)
        lay.setSpacing(0)
        head = QVBoxLayout()
        head.setContentsMargins(SPACE.lg, 0, SPACE.lg, SPACE.lg)
        head.setSpacing(0)
        brand = Label("Eco", "title")
        head.addWidget(brand)
        head.addWidget(Label(S.W_VERSION.format(v=version), "caption"))
        lay.addLayout(head)
        self.rows: dict[str, _RailRow] = {}
        for i, k in enumerate(keys, 1):
            row = _RailRow(i, S.STEP_TITLES[k])
            self.rows[k] = row
            lay.addWidget(row)
        lay.addStretch(1)

    def set_current(self, key: str) -> None:
        idx = self.keys.index(key)
        total = len(self.keys)
        for i, k in enumerate(self.keys):
            row = self.rows[k]
            row.set_state("done" if i < idx else "now" if i == idx else "todo")
            suffix = S.RAIL_DONE if i < idx else S.RAIL_NOW if i == idx else ""
            row.setAccessibleName(S.RAIL_A11Y.format(n=i + 1, total=total, title=S.STEP_TITLES[k], state=suffix))


def ask_confirm(parent: QWidget, title: str, body: str, confirm_text: str) -> bool:
    """Diálogo de confirmação do kit (o padrão é cancelar)."""
    from ..ui.kit.dialogs import ConfirmDialog
    if parent.property("autoconfirm") is not None or parent.window().property("autoconfirm") is not None:
        return bool(parent.window().property("autoconfirm"))        # captura/teste sem diálogo modal
    return ConfirmDialog.ask(parent, title=title, message=body, confirm_text=confirm_text, cancel_text="Voltar")


def _safe_toggle_cls():
    from shiboken6 import isValid
    from ..ui.kit.toggle import ToggleSwitch

    class SafeToggle(ToggleSwitch):
        """ToggleSwitch do kit que não quebra ao esconder depois de uma animação já concluída (o kit guarda uma
        referência a um QVariantAnimation que se apagou sozinho)."""

        def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
            if self._anim is not None and not isValid(self._anim):
                self._anim = None
            super().hideEvent(event)

    return SafeToggle


SafeToggle = None


def make_toggle(checked: bool = False, *, accessible_name: str = "", show_text: bool = False):
    global SafeToggle
    if SafeToggle is None:
        SafeToggle = _safe_toggle_cls()
    return SafeToggle(checked, show_text=show_text, accessible_name=accessible_name)
