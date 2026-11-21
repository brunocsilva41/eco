"""Controles que o kit nao tem e que as Configuracoes precisam: numero opcional, dispositivo de audio sob
demanda e lista de pastas. Seguem o contrato do kit: ``value()``, ``set_value(v)``, ``valueChanged``,
``set_invalid(bool)``. Sem regra de negocio: a carga de dispositivos vem de ``loaders``."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..kit.base import set_a11y
from ..kit.buttons import Button
from ..kit.chips import ChipList
from ..kit.fields import ComboField, NumberField
from ..kit.tasks import run_async
from ..theme import SIZE, SPACE
from .loaders import DeviceChoice, DeviceKind, load_devices
from .texts import T

log = logging.getLogger(__name__)


class OptionalNumber(QWidget):
    """Numero que pode ficar sem valor (usa o padrao da voz): lista "Padrao"/"Personalizar" + campo numerico.

    ``value()`` devolve ``None`` no padrao. ``valueChanged(object)`` com ``float | None``.
    """

    valueChanged = Signal(object)

    def __init__(self, value: float | None, *, minimum: float, maximum: float, step: float, decimals: int,
                 suffix: str = "", fallback: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        o = T.optional
        self._mode = ComboField([(o.default, False), (o.custom, True)])
        self._number = NumberField(fallback if value is None else value, minimum=minimum, maximum=maximum,
                                   step=step, decimals=decimals, suffix=suffix)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        lay.addWidget(self._mode)
        lay.addWidget(self._number)
        lay.addStretch(1)
        self._mode.set_value(value is not None)
        self._number.setEnabled(value is not None)
        self._mode.valueChanged.connect(self._on_mode)
        self._number.valueChanged.connect(lambda _v: self.valueChanged.emit(self.value()))
        self.setFocusProxy(self._mode)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def value(self) -> float | None:
        return self._number.value() if self._mode.value() else None

    def set_value(self, value: float | None) -> None:
        self._mode.blockSignals(True)
        self._mode.set_value(value is not None)
        self._mode.blockSignals(False)
        self._number.setEnabled(value is not None)
        if value is not None:
            self._number.blockSignals(True)
            self._number.set_value(float(value))
            self._number.blockSignals(False)

    def set_invalid(self, invalid: bool) -> None:
        self._number.set_invalid(invalid)
        self._mode.set_invalid(invalid)

    def is_invalid(self) -> bool:
        return self._number.is_invalid()

    def setAccessibleName(self, name: str) -> None:  # noqa: N802 (API Qt)
        super().setAccessibleName(name)
        self._mode.setAccessibleName(name)
        self._number.setAccessibleName(f"{name}: valor")

    def _on_mode(self, custom: object) -> None:
        self._number.setEnabled(bool(custom))
        self.valueChanged.emit(self.value())


class DeviceCombo(ComboField):
    """Microfone ou saida de som. Comeca so com "Padrao do Windows" (+ o valor atual) e lista os dispositivos
    em segundo plano quando a pagina aparece (``ensure_loaded``). ``loadFailed(str)`` se a listagem falhar."""

    loadFailed = Signal(str)

    def __init__(self, kind: DeviceKind, parent: QWidget | None = None) -> None:
        super().__init__([(T.devices.default, "")], parent=parent)
        self._kind: DeviceKind = kind
        self._wanted: Any = ""
        self._state = "idle"

    def set_value(self, value: Any) -> None:
        self._wanted = "" if value in (None, "") else value
        self._ensure_item(self._wanted)
        super().set_value(self._wanted)

    def ensure_loaded(self) -> None:
        if self._state != "idle":
            return
        self._state = "loading"
        self.setToolTip(T.devices.loading)
        run_async(lambda: load_devices(self._kind), self, self._on_loaded, self._on_failed)

    def _ensure_item(self, value: Any) -> None:
        if value != "" and self.findData(value) < 0:
            self.addItem(T.devices.current.format(name=value), value)

    def _on_loaded(self, choices: object) -> None:
        self._state = "ready"
        self.setToolTip("")
        current = self._wanted
        self.blockSignals(True)
        self.clear()
        self.addItem(T.devices.default, "")
        for ch in choices:  # type: ignore[attr-defined]
            if isinstance(ch, DeviceChoice):
                self.addItem(ch.label, ch.value)
        self._ensure_item(current)
        super().set_value(current)
        self.blockSignals(False)

    def _on_failed(self, message: str) -> None:
        log.warning("nao consegui listar dispositivos de audio: %s", message)
        self._state = "idle"
        self.setToolTip(T.devices.failed_detail.format(detail=message))
        self.loadFailed.emit(message)


class PathListField(QWidget):
    """Lista de pastas: etiquetas removiveis + botao para escolher uma pasta no Windows."""

    valueChanged = Signal(list)

    def __init__(self, items: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chips = ChipList(items or [])
        self._add = Button(T.path_list.add_folder, icon_name="folder")
        self._add.clicked.connect(self._choose)
        self._chips.valueChanged.connect(self.valueChanged)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        lay.addWidget(self._chips)
        lay.addWidget(self._add, 0, Qt.AlignmentFlag.AlignLeft)
        self.setFocusProxy(self._chips)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def value(self) -> list[str]:
        return self._chips.value()

    def set_value(self, items: list[str]) -> None:
        self._chips.set_value(items)

    def set_invalid(self, invalid: bool) -> None:
        self._chips.set_invalid(invalid)

    def is_invalid(self) -> bool:
        return self._chips.is_invalid()

    def setAccessibleName(self, name: str) -> None:  # noqa: N802
        super().setAccessibleName(name)
        set_a11y(self._chips, name)

    def minimumSizeHint(self) -> QSize:
        return QSize(SIZE.target * 6, SIZE.target * 2)

    def _choose(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, T.path_list.choose)
        if chosen and chosen not in self._chips.value():
            self._chips.set_value([*self._chips.value(), chosen.replace("/", "\\")])
            self.valueChanged.emit(self._chips.value())
