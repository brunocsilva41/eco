"""Widgets de campo reutilizáveis da tela de Configurações (um editor por tipo de ``FieldSpec``).

Todo editor segue o mesmo contrato (``FieldEditor``): ``value()``, ``set_value()``, ``local_error()``, ``focus_widget()``
e o sinal ``changed`` (só emitido por ações do usuário, nunca por ``set_value``). A lógica de validação de negócio fica em
``SettingsStore``; aqui só há validação local de forma (linha incompleta, nome repetido, campo obrigatório vazio).

Nada aqui bloqueia a thread da interface: listas de dispositivos e de ferramentas são carregadas por ``run_async``.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (QAbstractItemView, QSizePolicy, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..settings import schema
from ..settings.schema import FieldSpec
from ..win.keys import KeyError_, parse_combo
from . import theme

try:  # pragma: no cover - shiboken sempre acompanha o PySide6
    from shiboken6 import isValid as _is_valid
except ImportError:  # pragma: no cover
    def _is_valid(obj: object) -> bool:
        return True

log = logging.getLogger(__name__)

DEFAULT_DEVICE_LABEL: Final = "Padrão do Windows"
RISK_TEXT: Final[dict[int, tuple[str, str]]] = {0: ("Leitura", "ok"), 1: ("Controla o PC", "warn"), 2: ("Arriscado", "error")}


# ============================================================================ trabalho em segundo plano
class _TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            try:
                result = self.fn()
            except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem para o usuário
                log.exception("tarefa em segundo plano falhou")
                self.signals.failed.emit(str(exc) or exc.__class__.__name__)
                return
            self.signals.finished.emit(result)
        except RuntimeError:                      # aplicativo já encerrando: ninguém mais espera o resultado
            log.debug("resultado descartado: a interface já foi destruída")


class _Receiver(QObject):
    """Vive na thread da interface: recebe o resultado (conexão enfileirada) e chama os callbacks se o dono ainda existe."""
    _alive: set[_Receiver] = set()

    def __init__(self, task: _Task, owner: QObject, on_done: Callable[[Any], None], on_fail: Callable[[str], None]) -> None:
        super().__init__()
        self._task, self._owner, self._on_done, self._on_fail = task, owner, on_done, on_fail
        _Receiver._alive.add(self)
        task.signals.finished.connect(self._done)
        task.signals.failed.connect(self._failed)

    def _release(self) -> None:
        _Receiver._alive.discard(self)

    def _done(self, result: object) -> None:
        try:
            if _is_valid(self._owner):
                self._on_done(result)
        finally:
            self._release()

    def _failed(self, message: str) -> None:
        try:
            if _is_valid(self._owner):
                self._on_fail(message)
        finally:
            self._release()


def run_async(fn: Callable[[], Any], owner: QObject, on_done: Callable[[Any], None], on_fail: Callable[[str], None]) -> None:
    """Roda ``fn`` numa thread do pool e entrega o resultado na thread da interface (só se ``owner`` ainda existir)."""
    task = _Task(fn)
    _Receiver(task, owner, on_done, on_fail)
    QThreadPool.globalInstance().start(task)


# ============================================================================ pequenos componentes visuais
class LockIcon(QWidget):
    """Cadeado desenhado (não depende de fonte de emoji). Sempre acompanhado de texto."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plain")
        self.setFixedSize(QSize(16, 18))
        self.setAccessibleName("Campo travado")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.WARN)
        pen = QPen(color, 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(4, 1, 8, 9, 0, 180 * 16)
        p.drawLine(4, 6, 4, 8)
        p.drawLine(12, 6, 12, 8)
        p.setBrush(color)
        p.drawRoundedRect(2, 8, 12, 9, 2, 2)
        p.end()


def make_badge(text: str, state: str, tip: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", "badge")
    lab.setProperty("state", state)
    if tip:
        lab.setToolTip(tip)
        lab.setAccessibleDescription(tip)
    return lab


def _spin_decimals(step: float | None) -> int:
    return 2 if step is None or step < 1 else 1


# ============================================================================ contrato dos editores
class FieldEditor(QWidget):
    """Base dos editores. Subclasses implementam ``value``/``set_value``; ``changed`` só sai de ações do usuário."""

    changed = Signal()

    def __init__(self, spec: FieldSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self._loading = False
        self.setObjectName("plain")

    # --- contrato
    def value(self) -> Any:
        raise NotImplementedError

    def set_value(self, value: Any) -> None:
        self._loading = True
        try:
            self._apply(value)
        finally:
            self._loading = False

    def _apply(self, value: Any) -> None:
        raise NotImplementedError

    def local_error(self) -> str:
        return ""

    def focus_widget(self) -> QWidget:
        return self

    def ensure_loaded(self) -> None:
        """Carrega dados externos sob demanda (dispositivos...). Padrão: nada a fazer."""

    def _notify(self, *_args: object) -> None:
        if not self._loading:
            self.changed.emit()


# ============================================================================ campos simples
class BoolEditor(FieldEditor):
    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        self._box = QCheckBox("Desligado")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._box)
        lay.addStretch(1)
        self._box.toggled.connect(self._on_toggle)

    def _on_toggle(self, checked: bool) -> None:
        self._box.setText("Ligado" if checked else "Desligado")
        self._notify()

    def value(self) -> bool:
        return self._box.isChecked()

    def _apply(self, value: Any) -> None:
        self._box.setChecked(bool(value))
        self._box.setText("Ligado" if self._box.isChecked() else "Desligado")

    def focus_widget(self) -> QWidget:
        return self._box


class _SpinInt(QSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: Any) -> None:  # noqa: N802 - rolar a página não deve mudar o valor
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _SpinFloat(QDoubleSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: Any) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class IntEditor(FieldEditor):
    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        self._spin = _SpinInt()
        self._lo = int(spec.minimum) if spec.minimum is not None else -1_000_000_000
        self._hi = int(spec.maximum) if spec.maximum is not None else 1_000_000_000
        self._spin.setRange(self._lo, self._hi)
        self._spin.setSingleStep(int(spec.step or 1))
        self._spin.setAccelerated(True)
        if spec.unit:
            self._spin.setSuffix(f" {spec.unit}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._spin)
        lay.addStretch(1)
        self._spin.valueChanged.connect(self._notify)

    def value(self) -> int:
        return int(self._spin.value())

    def _apply(self, value: Any) -> None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = self._lo
        self._spin.setRange(min(self._lo, number), max(self._hi, number))      # valor fora do limite continua visível (e a validação acusa)
        self._spin.setValue(number)

    def focus_widget(self) -> QWidget:
        return self._spin


class FloatEditor(FieldEditor):
    """Decimal com limites. Se ``optional``, há a caixa 'Usar o padrão' (valor ``None``). Valor não tocado volta idêntico (sem arredondar)."""

    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        self._spin = _SpinFloat()
        self._lo = float(spec.minimum) if spec.minimum is not None else -1e9
        self._hi = float(spec.maximum) if spec.maximum is not None else 1e9
        self._spin.setDecimals(_spin_decimals(spec.step))
        self._spin.setRange(self._lo, self._hi)
        self._spin.setSingleStep(float(spec.step or 0.1))
        if spec.unit:
            self._spin.setSuffix(f" {spec.unit}")
        self._orig: float | None = None
        self._touched = False
        self._default_box: QCheckBox | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._spin)
        if spec.optional:
            self._default_box = QCheckBox("Usar o padrão (vazio)")
            lay.addWidget(self._default_box)
            self._default_box.toggled.connect(self._on_default)
        lay.addStretch(1)
        self._spin.valueChanged.connect(self._on_spin)

    def _on_default(self, checked: bool) -> None:
        self._spin.setEnabled(not checked)
        self._notify()

    def _on_spin(self, _v: float) -> None:
        if not self._loading:
            self._touched = True
        self._notify()

    def value(self) -> float | None:
        if self._default_box is not None and self._default_box.isChecked():
            return None
        if not self._touched and self._orig is not None:
            return self._orig
        return float(self._spin.value())

    def _apply(self, value: Any) -> None:
        self._touched = False
        empty = value is None or value == ""
        if self._default_box is not None:
            self._default_box.setChecked(empty)
            self._spin.setEnabled(not empty)
        try:
            number = float(value) if not empty else (self._lo if self._lo > -1e8 else 0.0)
        except (TypeError, ValueError):
            number, empty = self._lo, False
        self._orig = None if empty else number
        self._spin.setRange(min(self._lo, number), max(self._hi, number))
        self._spin.setValue(number)

    def focus_widget(self) -> QWidget:
        return self._spin


class TextEditor(FieldEditor):
    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        self._edit = QLineEdit()
        if spec.locked:
            self._edit.setReadOnly(True)
            self._edit.setProperty("readOnly", True)
        if spec.optional:
            self._edit.setPlaceholderText("(vazio)")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._edit, 1)
        self._edit.textChanged.connect(self._notify)

    def value(self) -> str:
        return self._edit.text().strip()

    def _apply(self, value: Any) -> None:
        self._edit.setText("" if value is None else str(value))

    def focus_widget(self) -> QWidget:
        return self._edit


class ChoiceEditor(FieldEditor):
    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        self._combo = QComboBox()
        self._combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._combo.setMinimumContentsLength(24)
        for val, label in spec.choices:
            self._combo.addItem(label, val)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._combo, 1)
        lay.addStretch(1)
        self._combo.currentIndexChanged.connect(self._notify)

    def value(self) -> Any:
        return self._combo.currentData()

    def _apply(self, value: Any) -> None:
        idx = self._combo.findData(value)
        if idx < 0:                                           # valor que a tela não conhece: mostra, sem perder
            self._combo.addItem(f"{value} (valor atual não listado)", value)
            idx = self._combo.count() - 1
        self._combo.setCurrentIndex(idx)

    def focus_widget(self) -> QWidget:
        return self._combo


# ============================================================================ caminhos
_DIR_KEYS: Final = frozenset({"stt.model_dir"})
_FILE_FILTERS: Final[dict[str, str]] = {
    "tts.voice_onnx": "Voz Piper (*.onnx);;Todos os arquivos (*)",
    "tts.voice_json": "Configuração da voz (*.json);;Todos os arquivos (*)",
    "llm.model": "Modelo GGUF (*.gguf);;Todos os arquivos (*)",
    "llm.mmproj": "Projetor GGUF (*.gguf);;Todos os arquivos (*)",
}


def _start_dir(text: str) -> str:
    cur = Path(text) if text.strip() else None
    try:
        if cur is not None:
            if cur.is_dir():
                return str(cur)
            if cur.parent.is_dir():
                return str(cur.parent)
    except OSError:
        pass
    return str(Path.home())


class PathEditor(FieldEditor):
    """Caminho com botão 'Procurar...' e indicação se existe (verificada com pequeno atraso, a cada edição)."""

    def __init__(self, spec: FieldSpec, folder: bool | None = None) -> None:
        super().__init__(spec)
        self._folder = spec.key in _DIR_KEYS if folder is None else folder
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("(vazio)" if spec.optional else "Caminho")
        self._browse = QPushButton("Procurar pasta..." if self._folder else "Procurar arquivo...")
        self._status = QLabel("")
        self._status.setProperty("role", "muted")
        self._status.setAccessibleName("Situação do caminho")
        top = QHBoxLayout()
        top.addWidget(self._edit, 1)
        top.addWidget(self._browse)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP1 // 2)
        lay.addLayout(top)
        lay.addWidget(self._status)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh_status)
        self._edit.textChanged.connect(self._on_text)
        self._browse.clicked.connect(self._choose)

    def _on_text(self, _t: str) -> None:
        self._timer.start()
        self._notify()

    def _refresh_status(self) -> None:
        text = self._edit.text().strip()
        if not text:
            self._set_status("Vazio" if self.spec.optional else "Informe o caminho", "warn" if not self.spec.optional else "")
            return
        try:
            path = Path(os.path.expandvars(text)).expanduser()
            if self._folder:
                ok, kind = path.is_dir(), "Pasta"
            else:
                ok, kind = path.is_file(), "Arquivo"
            exists = ok or path.exists()
        except (OSError, ValueError):
            self._set_status("Caminho inválido", "error")
            return
        if ok:
            self._set_status(f"{kind} encontrado", "ok")
        elif exists:
            self._set_status("Existe, mas não é " + ("uma pasta" if self._folder else "um arquivo"), "error")
        else:
            self._set_status("Não encontrado neste computador", "error")

    def _set_status(self, text: str, state: str) -> None:
        self._status.setText(text)
        self._status.setProperty("state", state)
        theme.repolish(self._status)

    def _choose(self) -> None:
        start = _start_dir(self._edit.text())
        if self._folder:
            chosen = QFileDialog.getExistingDirectory(self, "Escolher pasta", start)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, "Escolher arquivo", start,
                                                    _FILE_FILTERS.get(self.spec.key, "Todos os arquivos (*)"))
        if chosen:
            self._edit.setText(os.path.normpath(chosen))
            self._edit.setFocus()

    def value(self) -> str:
        return self._edit.text().strip()

    def _apply(self, value: Any) -> None:
        self._edit.setText("" if value is None else str(value))
        self._refresh_status()

    def focus_widget(self) -> QWidget:
        return self._edit


# ============================================================================ lista de textos
class ListEditor(FieldEditor):
    """Lista de textos: adicionar, editar no lugar (duplo clique/F2) e remover. Para pastas, oferece 'Escolher pasta...'."""

    def __init__(self, spec: FieldSpec, folders: bool = False) -> None:
        super().__init__(spec)
        self._list = QListWidget()
        self._list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self._list.setMinimumHeight(110)
        self._list.setAccessibleName(f"Lista: {spec.label}")
        self._new = QLineEdit()
        self._new.setPlaceholderText("Novo item e Enter")
        self._new.setAccessibleName(f"Novo item de {spec.label}")
        self._add = QPushButton("Adicionar")
        self._remove = QPushButton("Remover selecionado")
        self._folder_btn = QPushButton("Escolher pasta...") if folders else None
        row = QHBoxLayout()
        row.addWidget(self._new, 1)
        row.addWidget(self._add)
        row2 = QHBoxLayout()
        if self._folder_btn is not None:
            row2.addWidget(self._folder_btn)
        row2.addWidget(self._remove)
        row2.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._list)
        lay.addLayout(row)
        lay.addLayout(row2)
        self._add.clicked.connect(self._add_current)
        self._new.returnPressed.connect(self._add_current)
        self._remove.clicked.connect(self._remove_selected)
        self._list.itemChanged.connect(self._notify)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        if self._folder_btn is not None:
            self._folder_btn.clicked.connect(self._pick_folder)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self._remove.setEnabled(bool(self._list.selectedItems()))

    def _append(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._list.addItem(item)

    def _add_current(self) -> None:
        text = self._new.text().strip()
        if not text:
            return
        self._append(text)
        self._new.clear()
        self._notify()

    def _pick_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Escolher pasta", _start_dir(self._new.text()))
        if chosen:
            self._append(os.path.normpath(chosen))
            self._notify()

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self._notify()

    def value(self) -> list[str]:
        out = [self._list.item(i).text().strip() for i in range(self._list.count())]
        return [t for t in out if t]

    def _apply(self, value: Any) -> None:
        self._list.clear()
        for text in (value or []):
            self._append(str(text))
        self._sync_buttons()

    def focus_widget(self) -> QWidget:
        return self._list


# ============================================================================ tabela nome -> programa
class DictEditor(FieldEditor):
    """Tabela de duas colunas (nome falado -> programa). Linha completamente vazia é ignorada; incompleta ou repetida é erro."""

    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Nome falado", "Programa (caminho ou comando)"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 200)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setMinimumHeight(170)
        self._table.setAccessibleName(f"Tabela: {spec.label}")
        self._add = QPushButton("Adicionar")
        self._remove = QPushButton("Remover")
        self._browse = QPushButton("Programa...")
        row = QHBoxLayout()
        row.addWidget(self._add)
        row.addWidget(self._browse)
        row.addWidget(self._remove)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._table)
        lay.addLayout(row)
        self._add.clicked.connect(self._add_row)
        self._remove.clicked.connect(self._remove_row)
        self._browse.clicked.connect(self._pick_program)
        self._table.itemChanged.connect(self._notify)
        self._table.itemSelectionChanged.connect(self._sync_buttons)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has = self._table.currentRow() >= 0
        self._remove.setEnabled(has)
        self._browse.setEnabled(has)

    def _append(self, name: str = "", program: str = "") -> int:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(name))
        self._table.setItem(row, 1, QTableWidgetItem(program))
        return row

    def _add_row(self) -> None:
        self._table.blockSignals(True)
        row = self._append()
        self._table.blockSignals(False)
        self._table.setCurrentCell(row, 0)
        self._table.editItem(self._table.item(row, 0))
        self._notify()

    def _remove_row(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)
            self._notify()

    def _pick_program(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 1)
        start = _start_dir(item.text() if item else "")
        chosen, _ = QFileDialog.getOpenFileName(self, "Escolher programa", start, "Programas (*.exe *.bat *.cmd *.lnk);;Todos os arquivos (*)")
        if chosen and item is not None:
            item.setText(os.path.normpath(chosen))

    def _rows(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for r in range(self._table.rowCount()):
            a, b = self._table.item(r, 0), self._table.item(r, 1)
            name, prog = (a.text().strip() if a else ""), (b.text().strip() if b else "")
            if name or prog:
                out.append((name, prog))
        return out

    def value(self) -> dict[str, str]:
        return {name: prog for name, prog in self._rows() if name}

    def local_error(self) -> str:
        seen: set[str] = set()
        for name, prog in self._rows():
            if not name:
                return "Há uma linha com programa mas sem nome falado."
            if not prog:
                return f"'{name}' está sem programa."
            low = name.casefold()
            if low in seen:
                return f"O nome '{name}' aparece mais de uma vez."
            seen.add(low)
        return ""

    def _apply(self, value: Any) -> None:
        self._table.setRowCount(0)
        for name, prog in dict(value or {}).items():
            self._append(str(name), str(prog))
        self._sync_buttons()

    def focus_widget(self) -> QWidget:
        return self._table


# ============================================================================ captura de atalho
_VK_NAMES: Final[dict[int, str]] = {
    0x0D: "enter", 0x09: "tab", 0x20: "space", 0x08: "backspace", 0x2E: "delete", 0x2D: "insert", 0x24: "home",
    0x23: "end", 0x21: "pageup", 0x22: "pagedown", 0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x13: "pause", 0x2C: "printscreen",
    **{c: chr(c).lower() for c in range(0x41, 0x5B)},
    **{c: chr(c) for c in range(0x30, 0x3A)},
    **{0x6F + i: f"f{i}" for i in range(1, 25)},
}
_QT_NAMES: Final[dict[int, str]] = {
    Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter", Qt.Key.Key_Tab: "tab", Qt.Key.Key_Backtab: "tab",
    Qt.Key.Key_Space: "space", Qt.Key.Key_Backspace: "backspace", Qt.Key.Key_Delete: "delete", Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end", Qt.Key.Key_PageUp: "pageup", Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Left: "left", Qt.Key.Key_Up: "up", Qt.Key.Key_Right: "right", Qt.Key.Key_Down: "down",
    Qt.Key.Key_Pause: "pause", Qt.Key.Key_Print: "printscreen",
}
_MODIFIER_KEYS: Final = frozenset({Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
                                   Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock, Qt.Key.Key_ScrollLock})


def main_key_name(vk: int, qt_key: int) -> str | None:
    """Nome da tecla principal no vocabulário do Jarvis (``win.keys``), ou None se não for suportada."""
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if qt_key in _QT_NAMES:
        return _QT_NAMES[qt_key]
    if 0x41 <= qt_key <= 0x5A:
        return chr(qt_key).lower()
    if 0x30 <= qt_key <= 0x39:
        return chr(qt_key)
    f1 = int(Qt.Key.Key_F1)
    if f1 <= qt_key <= f1 + 23:
        return f"f{qt_key - f1 + 1}"
    return None


def modifier_names(mods: Qt.KeyboardModifier) -> list[str]:
    out: list[str] = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        out.append("ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        out.append("alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        out.append("shift")
    if mods & Qt.KeyboardModifier.MetaModifier:
        out.append("win")
    return out


class _CaptureButton(QPushButton):
    """Botão que, depois de clicado, captura a próxima combinação digitada (Esc cancela; perder o foco cancela)."""

    captured = Signal(str)
    rejected = Signal(str)

    def __init__(self) -> None:
        self.capturing = False
        self._shown = ""
        super().__init__()
        self.setProperty("capture", True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.begin)

    def show_value(self, text: str) -> None:
        self._shown = text
        if not self.capturing:
            self.setText(text or "(nenhuma)  -  clique para definir")

    def begin(self) -> None:
        self.capturing = True
        self.setProperty("capturing", True)
        theme.repolish(self)
        self.setText("Pressione a combinação...  (Esc cancela)")

    def _end(self) -> None:
        self.capturing = False
        self.setProperty("capturing", False)
        theme.repolish(self)
        self.setText(self._shown or "(nenhuma)  -  clique para definir")

    def focusNextPrevChild(self, next_: bool) -> bool:  # noqa: N802 - permite capturar a tecla Tab
        return False if self.capturing else super().focusNextPrevChild(next_)

    def event(self, ev: QEvent) -> bool:
        if self.capturing and ev.type() == QEvent.Type.ShortcutOverride:
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev: QKeyEvent) -> None:  # noqa: N802
        if not self.capturing:
            super().keyPressEvent(ev)
            return
        key = ev.key()
        if key == Qt.Key.Key_Escape:
            self._end()
            return
        mods = modifier_names(ev.modifiers())
        if key in _MODIFIER_KEYS:
            self.setText(("+".join(mods) + "+...") if mods else "Pressione a combinação...  (Esc cancela)")
            return
        name = main_key_name(int(ev.nativeVirtualKey()), int(key))
        if name is None:
            self._end()
            self.rejected.emit("Essa tecla não é suportada. Use letras, números, F1-F24, setas, Enter, Espaço, Tab etc.")
            return
        combo = "+".join([*mods, name])
        try:
            combo = parse_combo(combo).norm
        except KeyError_ as exc:
            self._end()
            self.rejected.emit(str(exc))
            return
        self._shown = combo
        self._end()
        self.captured.emit(combo)

    def keyReleaseEvent(self, ev: QKeyEvent) -> None:  # noqa: N802
        if self.capturing:
            ev.accept()
            return
        super().keyReleaseEvent(ev)

    def focusOutEvent(self, ev: Any) -> None:  # noqa: N802
        if self.capturing:
            self._end()
        super().focusOutEvent(ev)


class HotkeyEditor(FieldEditor):
    """Captura de atalho: clique, pressione a combinação e o campo mostra 'ctrl+alt+m'. A validação final é do SettingsStore."""

    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        self._btn = _CaptureButton()
        self._note = QLabel("")
        self._note.setProperty("role", "muted")
        self._value = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._btn)
        lay.addWidget(self._note, 1)
        self._btn.captured.connect(self._on_captured)
        self._btn.rejected.connect(self._on_rejected)

    def _on_captured(self, combo: str) -> None:
        self._note.setText("")
        self._value = combo
        self._btn.show_value(combo)
        self._notify()

    def _on_rejected(self, message: str) -> None:
        self._note.setText(message)

    def value(self) -> str:
        return self._value

    def local_error(self) -> str:
        if not self._value and (self.spec.locked or not self.spec.optional):
            return "Esta tecla é obrigatória: clique no botão e pressione a combinação."
        return ""

    def _apply(self, value: Any) -> None:
        self._value = "" if value is None else str(value)
        self._btn.show_value(self._value)
        self._note.setText("")

    def focus_widget(self) -> QWidget:
        return self._btn


# ============================================================================ dispositivos de áudio
def _list_devices_for(kind: str) -> list[tuple[str, str]]:
    """(nome, rótulo) dos dispositivos que servem para entrada/saída, sem repetir o mesmo aparelho em várias APIs do Windows."""
    from ..audio.devices import list_devices          # import tardio: PortAudio só é carregado sob demanda
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for dev in sorted(list_devices(), key=lambda d: (d.api_rank, d.index)):
        if not dev.supports("input" if kind == "in" else "output") or "wdm" in dev.hostapi.lower():
            continue
        key = dev.name.casefold()[:28]
        if key in seen:
            continue
        seen.add(key)
        mark = "  (padrão do sistema)" if dev.is_default("input" if kind == "in" else "output") else ""
        out.append((dev.name, dev.name + mark))
    return out


class DeviceEditor(FieldEditor):
    """Seletor de dispositivo de áudio. Lista carregada sob demanda em segundo plano; vazio = 'Padrão do Windows'."""

    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        self._kind = "in" if spec.kind == schema.DEVICE_IN else "out"
        self._combo = QComboBox()
        self._combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._combo.setMinimumContentsLength(22)
        self._combo.addItem(DEFAULT_DEVICE_LABEL, "")
        self._refresh = QPushButton("Atualizar lista")
        self._status = QLabel("Lista ainda não carregada.")
        self._status.setProperty("role", "muted")
        self._loaded = False
        self._loading_list = False
        self._wanted = ""
        top = QHBoxLayout()
        top.addWidget(self._combo, 1)
        top.addWidget(self._refresh)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self._status)
        self._combo.currentIndexChanged.connect(self._notify)
        self._refresh.clicked.connect(self._load)

    def ensure_loaded(self) -> None:
        if not self._loaded and not self._loading_list:
            self._load()

    def _load(self) -> None:
        if self._loading_list:
            return
        self._loading_list = True
        self._refresh.setEnabled(False)
        self._status.setText("Procurando dispositivos...")
        kind = self._kind
        run_async(lambda: _list_devices_for(kind), self, self._on_devices, self._on_fail)

    def _on_devices(self, devices: object) -> None:
        self._loading_list = False
        self._loaded = True
        self._refresh.setEnabled(True)
        current = self.value()
        self._loading = True
        try:
            self._combo.clear()
            self._combo.addItem(DEFAULT_DEVICE_LABEL, "")
            names = set()
            for name, label in devices:          # type: ignore[attr-defined]
                self._combo.addItem(label, name)
                names.add(name)
            self._select(current)
        finally:
            self._loading = False
        count = self._combo.count() - 1
        self._status.setText(f"{count} dispositivo(s) encontrado(s)." if count else "Nenhum dispositivo encontrado; o padrão do Windows será usado.")

    def _on_fail(self, message: str) -> None:
        self._loading_list = False
        self._refresh.setEnabled(True)
        self._status.setText(f"Não consegui listar os dispositivos: {message}")

    def _select(self, value: str) -> None:
        idx = self._combo.findData(value)
        if idx < 0 and value:                                   # configurado mas ausente agora: mantém, avisando
            self._combo.addItem(f"{value} (não encontrado agora)", value)
            idx = self._combo.count() - 1
        self._combo.setCurrentIndex(max(idx, 0))

    def value(self) -> str:
        data = self._combo.currentData()
        return "" if data is None else str(data)

    def _apply(self, value: Any) -> None:
        self._select("" if value is None else str(value))

    def focus_widget(self) -> QWidget:
        return self._combo


# ============================================================================ ferramentas
class ToolsPanel(FieldEditor):
    """Lista de ferramentas com 'Ligada' e 'Sempre confirmar' (liga as chaves ``tools.disabled`` e ``tools.confirm``).

    O estado vive em listas (fonte da verdade); a grade é só a vista e é montada quando o catálogo chega (sob demanda,
    em segundo plano). Ferramentas ARRISCADAS sempre confirmam: o botão fica marcado e desabilitado.
    """

    def __init__(self, spec: FieldSpec, load_tools: Callable[[], list[Any]]) -> None:
        super().__init__(spec)
        self._load_tools = load_tools
        self._disabled: list[str] = []
        self._confirm: list[str] = []
        self._tools: list[Any] = []
        self._state = "idle"
        self._on_boxes: dict[str, QCheckBox] = {}
        self._conf_boxes: dict[str, QCheckBox] = {}
        self._status = QLabel("As ferramentas serão listadas ao abrir esta página.")
        self._status.setProperty("role", "muted")
        self._status.setWordWrap(True)
        self._list_host = QWidget()
        self._list_host.setObjectName("plain")
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(theme.SP1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._status)
        lay.addWidget(self._list_host)

    # --- valores por chave
    def value_for(self, key: str) -> list[str]:
        return list(self._disabled if key == "tools.disabled" else self._confirm)

    def set_value_for(self, key: str, value: Any) -> None:
        names = [str(v) for v in (value or [])]
        if key == "tools.disabled":
            self._disabled = names
        else:
            self._confirm = names
        self._sync()

    def value(self) -> Any:                                   # contrato genérico: não usado (há duas chaves)
        return {"tools.disabled": self.value_for("tools.disabled"), "tools.confirm": self.value_for("tools.confirm")}

    def _apply(self, value: Any) -> None:
        for key, names in dict(value).items():
            self.set_value_for(key, names)

    # --- carregamento sob demanda
    def ensure_loaded(self) -> None:
        if self._state != "idle":
            return
        self._state = "loading"
        self._status.setText("Carregando a lista de ferramentas...")
        run_async(self._load_tools, self, self._on_tools, self._on_fail)

    def reload(self) -> None:
        self._state = "idle"
        self.ensure_loaded()

    def _on_fail(self, message: str) -> None:
        self._state = "idle"
        self._status.setText(f"Não consegui listar as ferramentas: {message}. Os valores salvos continuam intactos.")

    def _on_tools(self, tools: object) -> None:
        self._state = "ready"
        self._tools = list(tools)                              # type: ignore[call-overload]
        self._status.setText("Ligue ou desligue cada ferramenta. Ferramentas arriscadas SEMPRE pedem confirmação (não dá para desligar isso).")
        self._build()

    def _build(self) -> None:
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._on_boxes.clear()
        self._conf_boxes.clear()
        for tool in self._tools:
            text, state = RISK_TEXT.get(int(tool.risk), RISK_TEXT[1])
            risky = int(tool.risk) >= 2
            block = QFrame()
            block.setObjectName("banner")
            block.setProperty("state", state)
            bl = QVBoxLayout(block)
            bl.setContentsMargins(theme.SP1 + 2, theme.SP1, theme.SP1 + 2, theme.SP1)
            bl.setSpacing(2)
            top = QHBoxLayout()
            top.setSpacing(theme.SP1)
            on = QCheckBox(tool.name)
            on.setAccessibleName(f"Ligar a ferramenta {tool.name}")
            on.toggled.connect(lambda checked, n=tool.name: self._toggle_on(n, checked))
            risk = make_badge(f"Risco: {text}", state, "Nível de risco da ferramenta")
            conf = QCheckBox("Sempre pede confirmação (arriscada)" if risky else "Sempre confirmar")
            conf.setAccessibleName(f"Sempre confirmar a ferramenta {tool.name}")
            if risky:
                conf.setChecked(True)
                conf.setEnabled(False)
                conf.setToolTip("Ferramentas arriscadas sempre pedem confirmação; isso não pode ser desligado.")
            else:
                conf.toggled.connect(lambda checked, n=tool.name: self._toggle_confirm(n, checked))
            top.addWidget(on)
            top.addWidget(risk)
            top.addStretch(1)
            desc = QLabel(tool.description)
            desc.setWordWrap(True)
            desc.setProperty("role", "muted")
            bl.addLayout(top)
            bl.addWidget(desc)
            bl.addWidget(conf)
            self._on_boxes[tool.name] = on
            self._conf_boxes[tool.name] = conf
            self._list_lay.addWidget(block)
        self._sync()

    def _sync(self) -> None:
        for name, box in self._on_boxes.items():
            box.blockSignals(True)
            box.setChecked(name not in self._disabled)
            box.blockSignals(False)
        for tool in self._tools:
            if int(tool.risk) >= 2:
                continue
            box = self._conf_boxes[tool.name]
            box.blockSignals(True)
            box.setChecked(tool.name in self._confirm)
            box.blockSignals(False)

    def _toggle_on(self, name: str, checked: bool) -> None:
        if checked and name in self._disabled:
            self._disabled.remove(name)
        elif not checked and name not in self._disabled:
            self._disabled.append(name)
        self._notify()

    def _toggle_confirm(self, name: str, checked: bool) -> None:
        if checked and name not in self._confirm:
            self._confirm.append(name)
        elif not checked and name in self._confirm:
            self._confirm.remove(name)
        self._notify()

    def focus_widget(self) -> QWidget:
        first = next(iter(self._on_boxes.values()), None)
        return first if first is not None else self


class ToolsFacet:
    """Visão de UMA chave (``tools.disabled`` ou ``tools.confirm``) do painel único de ferramentas."""

    def __init__(self, panel: ToolsPanel, spec: FieldSpec) -> None:
        self.panel, self.spec = panel, spec

    def value(self) -> list[str]:
        return self.panel.value_for(self.spec.key)

    def set_value(self, value: Any) -> None:
        self.panel.set_value_for(self.spec.key, value)

    def local_error(self) -> str:
        return ""


# ============================================================================ fábrica
def make_editor(spec: FieldSpec) -> FieldEditor:
    """Editor adequado ao tipo do campo (TOOLS é tratado pela janela, que injeta o carregador do catálogo)."""
    kind = spec.kind
    if kind == schema.BOOL:
        return BoolEditor(spec)
    if kind == schema.INT:
        return IntEditor(spec)
    if kind == schema.FLOAT:
        return FloatEditor(spec)
    if kind == schema.TEXT:
        return TextEditor(spec)
    if kind == schema.PATH:
        return PathEditor(spec)
    if kind == schema.CHOICE:
        return ChoiceEditor(spec)
    if kind == schema.LIST:
        return ListEditor(spec, folders=spec.key == "files.roots")
    if kind == schema.DICT:
        return DictEditor(spec)
    if kind == schema.HOTKEY:
        return HotkeyEditor(spec)
    if kind in (schema.DEVICE_IN, schema.DEVICE_OUT):
        return DeviceEditor(spec)
    raise ValueError(f"tipo de campo sem editor: {kind}")


def limits_hint(spec: FieldSpec) -> str:
    """'de 3 a 120 s' a partir dos limites do campo (vazio se não houver)."""
    if spec.kind not in (schema.INT, schema.FLOAT) or (spec.minimum is None and spec.maximum is None):
        return ""
    def fmt(v: float) -> str:
        return f"{v:g}"
    unit = f" {spec.unit}" if spec.unit else ""
    if spec.minimum is not None and spec.maximum is not None:
        return f"De {fmt(spec.minimum)} a {fmt(spec.maximum)}{unit}."
    if spec.minimum is not None:
        return f"Mínimo: {fmt(spec.minimum)}{unit}."
    return f"Máximo: {fmt(spec.maximum or 0)}{unit}."


# ============================================================================ cartão de um campo
class FieldRow(QFrame):
    """Cartão de um campo: rótulo, selos (Aplica na hora / Requer reiniciar), cadeado, ajuda, editor, marca de alterado e erro."""

    def __init__(self, title: str, help_text: str, apply: str, editor: QWidget, label_target: QWidget,
                 locked: str = "", keys: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.setObjectName("card")
        self.keys = keys
        self._base_help = help_text
        self._label = QLabel(title)
        self._label.setProperty("role", "field")
        self._label.setWordWrap(True)
        self._label.setBuddy(label_target)
        self._changed_tag = make_badge("Alterado", "accent", "Este campo foi modificado e ainda não foi salvo.")
        self._changed_tag.setVisible(False)
        live = apply == schema.LIVE
        badge = make_badge("Aplica na hora" if live else "Requer reiniciar", "ok" if live else "warn",
                           "Vale assim que o Jarvis recarregar a configuração." if live else
                           "Só vale depois de reiniciar o Jarvis.")
        head = QHBoxLayout()
        head.setSpacing(theme.SP1)
        head.addWidget(self._label)
        head.addWidget(self._changed_tag)
        head.addStretch(1)
        head.addWidget(badge)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP2, theme.SP2, theme.SP2, theme.SP2)
        lay.setSpacing(theme.SP1)
        lay.addLayout(head)
        if help_text:
            self._help = QLabel(help_text)
            self._help.setProperty("role", "muted")
            self._help.setWordWrap(True)
            lay.addWidget(self._help)
        lay.addWidget(editor)
        if locked:
            lock = QHBoxLayout()
            lock.setSpacing(theme.SP1)
            lock.addWidget(LockIcon())
            reason = QLabel(f"Travado: {locked}.")
            reason.setProperty("state", "warn")
            reason.setWordWrap(True)
            lock.addWidget(reason, 1)
            lay.addLayout(lock)
        self._error = QLabel("")
        self._error.setProperty("state", "error")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        self._error.setAccessibleName("Erro do campo")
        lay.addWidget(self._error)
        self._target = label_target
        label_target.setAccessibleName(title)
        if help_text:
            label_target.setAccessibleDescription(help_text)

    def set_changed(self, changed: bool) -> None:
        self._changed_tag.setVisible(changed)
        self.setProperty("changed", changed)
        theme.repolish(self)

    def set_errors(self, messages: Iterable[str]) -> None:
        msgs = [m for m in messages if m]
        self._error.setText("Erro: " + " ".join(msgs) if msgs else "")
        self._error.setVisible(bool(msgs))
        self.setProperty("invalid", bool(msgs))
        theme.repolish(self)
        self._target.setAccessibleDescription((self._base_help + " " + self._error.text()).strip())
