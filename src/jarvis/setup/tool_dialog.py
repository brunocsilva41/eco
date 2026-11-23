"""Diálogo "Personalizar caminho": escolher onde está uma ferramenta/arquivo do Eco, com validação ao vivo.

Campo + Procurar, "Detectar automaticamente", "Restaurar padrão" e "Salvar". O caminho só é salvo se for válido; executável
fora das pastas confiáveis e sem assinatura digital pede uma confirmação explícita. Caminho de rede é recusado.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget

from ..core import toolpaths
from ..ui.kit.base import Label, set_a11y
from ..ui.kit.buttons import Button
from ..ui.kit.fields import PathField
from ..ui.kit.status import StatusChip
from ..ui.theme import SIZE, SPACE

log = logging.getLogger("jarvis.setup.tooldialog")

_FILTERS = {"exe": "Programas (*.exe *.cmd *.bat *.com);;Todos os arquivos (*.*)", "dir": "", "file": "Todos os arquivos (*.*)"}


class _Bus(QObject):
    validated = Signal(int, object)               # (número do pedido, Validation)
    detected = Signal(object)                     # (caminho|None, origem)


def default_saver(config_key: str, value: str) -> None:
    from .config_io import save_values
    save_values({config_key: value})


class ToolPathDialog(QDialog):
    """`result_value` = o que foi salvo ('' = automático). `saved` diz se houve gravação."""

    def __init__(self, tool_key: str, parent: QWidget | None = None, *, saver: Callable[[str, str], None] | None = None,
                 confirm: Callable[[QWidget, str, str, str], bool] | None = None) -> None:
        super().__init__(parent)
        self.d = toolpaths.BY_KEY[tool_key]
        self._saver = saver or default_saver
        self._confirm = confirm or _ask_confirm
        self.saved = False
        self.result_value = toolpaths.configured_value(self.d)
        self._seq = 0
        self._last: toolpaths.Validation | None = None
        self._bus = _Bus()
        self._bus.validated.connect(self._on_validated)
        self._bus.detected.connect(self._on_detected)
        self.setProperty("kit", "dialog")
        self.setWindowTitle(f"Caminho: {self.d.title}")
        self.setModal(True)
        self.setMinimumWidth(SIZE.target * 15)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
        lay.setSpacing(SPACE.md)
        lay.addWidget(Label(self.d.title, "heading", wrap=True))
        lay.addWidget(Label(self.d.help or "Onde este item está neste computador.", "body", wrap=True))
        self.now = Label("", "help", wrap=True)
        lay.addWidget(self.now)
        lay.addWidget(Label("Caminho (vazio = o Eco procura sozinho)", "label"))
        kind = "dir" if self.d.kind == "dir" else "file"
        cur = self.result_value if toolpaths.is_custom(self.d) else ""
        self.field = PathField(cur, mode=kind, file_filter=_FILTERS.get(self.d.kind, ""), placeholder="automático")
        self.field.setAccessibleName(f"Caminho de {self.d.title}")
        self.field.valueChanged.connect(self._changed)
        lay.addWidget(self.field)
        row = QHBoxLayout()
        row.setSpacing(SPACE.sm)
        self.chip = StatusChip("neutral", "—")
        self.msg = Label("", "body", wrap=True)
        row.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.msg, 1)
        lay.addLayout(row)
        tools = QHBoxLayout()
        tools.setSpacing(SPACE.sm)
        self.btn_detect = Button("Detectar automaticamente", icon_name="search")
        self.btn_detect.clicked.connect(self.detect_auto)
        self.btn_reset = Button("Restaurar padrão", icon_name="refresh")
        self.btn_reset.clicked.connect(self.restore_default)
        tools.addWidget(self.btn_detect)
        tools.addWidget(self.btn_reset)
        tools.addStretch(1)
        lay.addLayout(tools)
        lay.addSpacing(SPACE.sm)
        bottom = QHBoxLayout()
        bottom.setSpacing(SPACE.sm)
        bottom.addStretch(1)
        self.btn_cancel = Button("Cancelar")
        self.btn_save = Button("Salvar", variant="primary", icon_name="check")
        for b in (self.btn_cancel, self.btn_save):
            b.setAutoDefault(False)
            b.setDefault(False)
        self.btn_cancel.setAutoDefault(True)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self.save)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_save)
        lay.addLayout(bottom)
        self.setTabOrder(self.btn_detect, self.btn_reset)
        self.setTabOrder(self.btn_reset, self.btn_cancel)
        self.setTabOrder(self.btn_cancel, self.btn_save)
        set_a11y(self, self.windowTitle(), self.d.help)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._validate_now)
        f = toolpaths.resolve(tool_key)
        self.now.setText(("Agora: " + (f"{f.path}  ({f.source})" if f.path else "não encontrado")) + (f". {f.problem}" if f.problem else ""))
        self._set_state("neutral", "—", "Digite ou escolha o caminho." if not cur else "Conferindo...")
        self.btn_save.setEnabled(False)
        if cur:
            self._validate_now()
        else:
            self._set_state("ok", "Automático", "O Eco procura sozinho (PATH, instalação padrão, pasta do Eco).")
            self.btn_save.setEnabled(bool(toolpaths.is_custom(self.d)) or False)

    # ---------------------------------------------------------------- validação
    def _set_state(self, state: str, chip: str, text: str) -> None:
        self.chip.set_state(state, chip)                     # type: ignore[arg-type]
        self.chip.setFixedWidth(max(self.chip.sizeHint().width(), SIZE.target * 3))
        self.msg.setText(text)

    def _changed(self, _text: str) -> None:
        self.btn_save.setEnabled(False)
        self._set_state("neutral", "...", "Conferindo...")
        self._timer.start(350)

    def _validate_now(self) -> None:
        self._seq += 1
        n, text = self._seq, self.field.value()
        if not text.strip():
            self._on_validated(n, toolpaths.Validation("ok", "Automático: o Eco procura sozinho.", ""))
            return

        def work() -> None:
            try:
                v = toolpaths.validate_path(self.d.key, text)
            except Exception as exc:                          # noqa: BLE001
                log.exception("validação")
                v = toolpaths.Validation("fail", f"Não consegui conferir: {exc}")
            self._bus.validated.emit(n, v)
        threading.Thread(target=work, name="tool-validate", daemon=True).start()

    def _on_validated(self, n: int, v: toolpaths.Validation) -> None:
        if n != self._seq:
            return                                            # resposta velha: a pessoa já mudou o texto
        self._last = v
        state = {"ok": "ok", "warn": "warn", "fail": "error"}[v.status]
        chip = {"ok": "Válido", "warn": "Atenção", "fail": "Inválido"}[v.status]
        if v.status == "ok" and not v.path:
            chip = "Automático"
        self.field.set_invalid(v.status == "fail")
        self._set_state(state, chip, v.message)
        self.btn_save.setEnabled(v.ok)

    # ---------------------------------------------------------------- ações
    def detect_auto(self) -> None:
        self._set_state("neutral", "...", "Procurando...")

        def work() -> None:
            self._bus.detected.emit(toolpaths.detect(self.d.key))
        threading.Thread(target=work, name="tool-detect", daemon=True).start()

    def _on_detected(self, res) -> None:
        path, src = res
        if path is None:
            self._set_state("warn", "Não achei", "Não encontrei este programa nos lugares de sempre. Instale-o ou escolha o caminho com Procurar.")
            return
        self.field.set_value(str(path))                       # dispara a validação
        self.msg.setText(f"Encontrado em {path} ({src}). Conferindo...")

    def restore_default(self) -> None:
        self.field.set_value("")
        self._validate_now()
        self.btn_save.setEnabled(True)                        # restaurar é sempre permitido

    def save(self) -> None:
        text = self.field.value().strip().strip('"')
        v = self._last
        if text and (v is None or not v.ok):
            return
        if text and v is not None and v.confirm:
            if not self._confirm(self, "Confiar neste programa?", v.confirm, "Confio, usar este programa"):
                return
        value = text if text else toolpaths.default_value(self.d)
        try:
            self._saver(toolpaths.config_key(self.d), value if self.d.cfg[0] != "toolpaths" else text)
        except Exception as exc:                              # noqa: BLE001
            self._set_state("error", "Erro", f"Não consegui salvar: {exc}")
            return
        self.result_value = text
        self.saved = True
        self.accept()


def _ask_confirm(parent: QWidget, title: str, body: str, confirm_text: str) -> bool:
    from .widgets import ask_confirm
    return ask_confirm(parent, title, body, confirm_text)
