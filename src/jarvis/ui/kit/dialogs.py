"""ConfirmDialog: confirmacao que mostra o ALVO REAL, com foco inicial em Cancelar."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from ..theme import SIZE, SPACE
from .base import Label, set_a11y, strs
from .buttons import Button
from .fields import TextField


class ConfirmDialog(QDialog):
    """Dialogo modal de confirmacao.

    * ``target``: o texto/nome REAL afetado, mostrado inteiro numa caixa somente leitura.
    * Foco inicial em "Cancelar"; Esc = nao; Enter aciona o botao focado (nunca confirma sozinho).
    * ``destructive=True``: botao de confirmar em vermelho (perigo) e aviso "nao pode ser desfeita".
    * ``require_word``: o botao so habilita quando a pessoa digita a palavra (ex.: "APAGAR").
    Uso: ``ConfirmDialog.ask(parent, title=..., message=..., target=..., confirm_text="Apagar") -> bool``.
    """

    def __init__(self, parent: QWidget | None, *, title: str, message: str = "", target: str = "",
                 confirm_text: str = "", cancel_text: str = "", destructive: bool = False,
                 require_word: str = "") -> None:
        super().__init__(parent)
        c, d = strs().common, strs().dialog
        self._word = require_word.strip()
        self.setProperty("kit", "dialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(SIZE.target * 13)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
        lay.setSpacing(SPACE.md)
        lay.addWidget(Label(title, "heading", wrap=True))
        if message:
            lay.addWidget(Label(message, "body", wrap=True))
        if target:
            lay.addSpacing(SPACE.xs)
            lay.addWidget(Label(d.target_label, "caption"))
            box = QPlainTextEdit(target)
            box.setReadOnly(True)
            lines = min(5, target.count(chr(10)) + 1 + len(target) // 60)
            box.setFixedHeight(box.fontMetrics().lineSpacing() * lines + 2 * SPACE.md)
            box.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            set_a11y(box, d.target_label, target[:200])
            lay.addWidget(box)
        if destructive:
            lay.addWidget(Label(d.cannot_undo, "help", wrap=True))
        self._input: TextField | None = None
        if self._word:
            lay.addSpacing(SPACE.xs)
            lay.addWidget(Label(d.type_to_confirm.format(word=self._word), "label", wrap=True))
            self._input = TextField(accessible_name=d.type_to_confirm.format(word=self._word))
            self._input.valueChanged.connect(self._check)
            lay.addWidget(self._input)
        lay.addSpacing(SPACE.sm)
        row = QHBoxLayout()
        row.setSpacing(SPACE.sm)
        row.addStretch(1)
        self._cancel = Button(cancel_text or c.cancel)
        self._ok = Button(confirm_text or c.confirm, variant="danger" if destructive else "primary")
        for b in (self._cancel, self._ok):
            b.setAutoDefault(False)
            b.setDefault(False)
        self._cancel.setAutoDefault(True)
        self._cancel.clicked.connect(self.reject)
        self._ok.clicked.connect(self.accept)
        row.addWidget(self._cancel)
        row.addWidget(self._ok)
        lay.addLayout(row)
        self.setTabOrder(self._cancel, self._ok)
        self._check()
        set_a11y(self, title, message)

    def _check(self) -> None:
        if self._input is None:
            return
        ok = self._input.text().strip().casefold() == self._word.casefold()
        self._ok.setEnabled(ok)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        QTimer.singleShot(0, self._focus_cancel)

    def _focus_cancel(self) -> None:
        self._cancel.setFocus(Qt.FocusReason.TabFocusReason)

    @classmethod
    def ask(cls, parent: QWidget | None, **kw) -> bool:  # type: ignore[no-untyped-def]
        return cls(parent, **kw).exec() == QDialog.DialogCode.Accepted
