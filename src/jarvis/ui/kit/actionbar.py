"""ActionBar: barra inferior fixa de Salvar / Descartar / Restaurar padrao, com contagem de alteracoes."""
from __future__ import annotations

from PySide6.QtCore import Qt, QVariantAnimation, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from ..theme import MOTION, SIZE, SPACE, pal
from . import icons
from .base import Label, animate, set_a11y, strs, watch_theme
from .visibility import set_shown
from .buttons import Button


_QWIDGETSIZE_MAX = 16777215


class ActionBar(QFrame):
    """Aparece (150 ms) so quando ha alteracoes pendentes e mostra quantas.

    Sinais: ``saveRequested()``, ``discardRequested()``, ``resetRequested()``. Ctrl+S salva
    (atalho do botao Salvar) enquanto a barra esta visivel. ``set_changes(n, errors=0)``: com erros, "Salvar" fica
    desabilitado e a barra diz quantos erros faltam corrigir. ``set_busy(True)`` bloqueia os botoes.
    """

    saveRequested = Signal()
    discardRequested = Signal()
    resetRequested = Signal()

    def __init__(self, parent: QWidget | None = None, *, show_when_clean: bool = False) -> None:
        super().__init__(parent)
        self.setProperty("kit", "bar")
        self._show_when_clean = show_when_clean
        self._changes = 0
        self._errors = 0
        self._busy = False
        self._open = show_when_clean
        self._anim: QVariantAnimation | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE.xl, SPACE.md, SPACE.xl, SPACE.md)
        lay.setSpacing(SPACE.sm)
        self._edit_icon = QLabel()
        self._count = Label("", "label")
        self._err_icon = QLabel()
        self._err_text = Label("", "label")
        self._err_text.set_state("error")
        self._count.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)   # nunca é comprimido abaixo do texto (sem corte)
        lay.addWidget(self._edit_icon)
        lay.addWidget(self._count)
        lay.addSpacing(SPACE.md)
        lay.addWidget(self._err_icon)
        lay.addWidget(self._err_text)
        lay.addStretch(1)
        c = strs().common
        self._reset = Button(c.reset_defaults, variant="text", icon_name="refresh")
        self._discard = Button(c.discard)
        self._save = Button(c.save, variant="primary", icon_name="check", shortcut="Ctrl+S")
        self._reset.clicked.connect(self.resetRequested)
        self._discard.clicked.connect(self.discardRequested)
        self._save.clicked.connect(self.saveRequested)
        for b in (self._reset, self._discard, self._save):
            lay.addWidget(b)
        self.setTabOrder(self._reset, self._discard)
        self.setTabOrder(self._discard, self._save)
        set_a11y(self, strs().common.save)
        watch_theme(self, self._refresh_icons)
        self.set_changes(0)
        set_shown(self, show_when_clean)
    def changes(self) -> int:
        return self._changes

    def set_changes(self, n: int, errors: int = 0) -> None:
        self._changes, self._errors = n, errors
        self._count.setText(strs().bar.pending(n))
        self._err_text.setText(strs().bar.errors(errors) if errors else "")
        set_shown(self._err_icon, errors > 0)
        set_shown(self._err_text, errors > 0)
        clean = n == 0 and errors == 0
        self._save.setEnabled(errors == 0 and not self._busy and not (clean and self._show_when_clean))
        self._discard.setEnabled(not self._busy and not (clean and self._show_when_clean))
        self._save.setToolTip(strs().bar.errors(errors) if errors else f"{strs().common.save} (Ctrl+S)")
        set_a11y(self, strs().bar.pending(n), strs().bar.errors(errors) if errors else "")
        self._refresh_icons()
        self._reveal(n > 0 or errors > 0 or self._show_when_clean)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._reset.setEnabled(not busy)
        self._discard.setEnabled(not busy and not (self._changes == 0 and self._show_when_clean))
        self._save.setEnabled(not busy and self._errors == 0 and not (self._changes == 0 and self._show_when_clean))
        self._save.setText(strs().bar.save_busy if busy else strs().common.save)

    def _refresh_icons(self) -> None:
        p = pal()
        self._edit_icon.setPixmap(icons.pixmap("edit", p.text_muted, SIZE.icon, self))
        set_shown(self._edit_icon, self._changes > 0)
        self._err_icon.setPixmap(icons.pixmap("error", p.error, SIZE.icon, self))

    def _reveal(self, show: bool) -> None:
        if show == self._open:
            return
        self._open = show
        if self._anim is not None:
            self._anim.stop()
        if show:
            self.setMaximumHeight(0)
            set_shown(self, True)
            self._anim = animate(self, 0, self.sizeHint().height(), MOTION.base, lambda v: self.setMaximumHeight(int(v)),
                                 lambda: self.setMaximumHeight(_QWIDGETSIZE_MAX))
        else:
            self._anim = animate(self, self.height(), 0, MOTION.fast, lambda v: self.setMaximumHeight(int(v)), self._finish_hide)

    def _finish_hide(self) -> None:
        set_shown(self, False)
        self.setMaximumHeight(_QWIDGETSIZE_MAX)
