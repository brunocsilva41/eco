"""Liga controles ao controlador: o que a pessoa edita vai para o modelo; o que o modelo troca volta aos
controles; mensagens de erro chegam ao campo certo. Sem regra de negocio: so cola e converte."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from jarvis.settings import schema
from jarvis.settings.schema import FieldSpec

from .controller import SettingsController
from .fieldfactory import from_control, to_control
from .model import coerce
from .tools_panel import KEY_CONFIRM, KEY_DISABLED, ToolsPanel

ErrorSink = Callable[[str | None], None]


class FieldBinder(QObject):
    def __init__(self, controller: SettingsController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctl = controller
        self._controls: dict[str, tuple[FieldSpec, QWidget]] = {}
        self._sinks: dict[str, ErrorSink] = {}
        self._shown: dict[str, str] = {}
        self._panel: ToolsPanel | None = None
        self._pushing = False
        controller.valuesReplaced.connect(self.push_values)
        controller.stateChanged.connect(self.push_errors)

    # ---- registro
    def attach(self, spec: FieldSpec, control: QWidget, sink: ErrorSink | None = None) -> None:
        self._controls[spec.key] = (spec, control)
        if sink is not None:
            self._sinks[spec.key] = sink
        control.valueChanged.connect(lambda v, s=spec: self._edited(s, v))  # type: ignore[attr-defined]
        self._pushing = True
        try:
            self._set(spec, control)
        finally:
            self._pushing = False

    def attach_tools(self, panel: ToolsPanel, sink: ErrorSink | None = None) -> None:
        self._panel = panel
        for key in (KEY_DISABLED, KEY_CONFIRM):
            if sink is not None:
                self._sinks[key] = sink
            panel.set_value_for(key, self._ctl.model.current.get(key) or [])
        panel.keyChanged.connect(self._tools_edited)

    def control_for(self, key: str) -> QWidget | None:
        entry = self._controls.get(key)
        return entry[1] if entry else (self._panel if key in (KEY_DISABLED, KEY_CONFIRM) else None)

    def controls(self) -> list[QWidget]:
        return [c for _spec, c in self._controls.values()]

    # ---- edicao: controle -> modelo
    def _edited(self, spec: FieldSpec, value: Any) -> None:
        if self._pushing:
            return
        self._ctl.edit(spec.key, coerce(spec, from_control(spec, value)))

    def _tools_edited(self, key: str, names: list[str]) -> None:
        if not self._pushing:
            self._ctl.edit(key, list(names))

    # ---- modelo -> controles
    def push_values(self) -> None:
        self._pushing = True
        try:
            for spec, control in self._controls.values():
                self._set(spec, control)
            if self._panel is not None:
                for key in (KEY_DISABLED, KEY_CONFIRM):
                    self._panel.set_value_for(key, self._ctl.model.current.get(key) or [])
        finally:
            self._pushing = False

    def _set(self, spec: FieldSpec, control: QWidget) -> None:
        value = self._ctl.model.current.get(spec.key)
        control.set_value(to_control(spec, value))  # type: ignore[attr-defined]

    def push_errors(self) -> None:
        errors = self._ctl.model.errors
        for key, sink in self._sinks.items():
            message = errors.get(key, "")
            if self._shown.get(key, "") != message:
                self._shown[key] = message
                sink(message or None)

    def first_error_key(self) -> str:
        return next((k for k in schema.BY_KEY if k in self._ctl.model.errors), "")
