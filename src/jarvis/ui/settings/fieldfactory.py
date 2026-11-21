"""Fabrica de campos: ``FieldSpec.kind`` -> componente do kit, mais a conversao de valores entre o modelo
(tipos do schema) e o controle (tipos do widget). Sem estado e sem regra de negocio.

    BOOL -> ToggleSwitch        INT/FLOAT -> NumberField (FLOAT opcional: OptionalNumber)
    TEXT -> TextField           PATH -> PathField          CHOICE -> ComboField
    LIST -> ChipList (pastas: PathListField)               DICT -> DictEditor
    HOTKEY -> KeyCaptureField   DEVICE_IN/OUT -> DeviceCombo
O painel de ferramentas (TOOLS) tem pagina propria: ver ``tools_panel``.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from jarvis.settings import schema
from jarvis.settings.schema import FieldSpec

from ..kit.chips import ChipList
from ..kit.fields import ComboField, NumberField, PathField, TextField
from ..kit.keycapture import KeyCaptureField
from ..kit.toggle import ToggleSwitch
from .controls import DeviceCombo, OptionalNumber, PathListField
from .dict_editor import DictEditor
from .hotkeys import to_config, to_display
from .texts import T

# controles largos ficam sob o texto do campo, nao ao lado
STACKED_KINDS = frozenset({schema.PATH, schema.LIST, schema.DICT, schema.TOOLS, schema.DEVICE_IN, schema.DEVICE_OUT})
_STACKED_KEYS = frozenset({"tts.length_scale"})
_FOLDER_KEYS = frozenset({"stt.model_dir"})
_FOLDER_LIST_KEYS = frozenset({"files.roots"})
_BIG = 1_000_000.0


def is_stacked(spec: FieldSpec) -> bool:
    return spec.kind in STACKED_KINDS or spec.key in _STACKED_KEYS


def _decimals(spec: FieldSpec) -> int:
    if spec.kind == schema.INT:
        return 0
    text = f"{spec.step or 1.0:.6f}".rstrip("0")
    after = text.split(".")[1] if "." in text else ""
    return max(len(after), 1)


def _number(spec: FieldSpec, value: Any) -> QWidget:
    lo = spec.minimum if spec.minimum is not None else -_BIG
    hi = spec.maximum if spec.maximum is not None else _BIG
    step = spec.step or 1.0
    suffix = T.unit(spec)
    if spec.kind == schema.FLOAT and spec.optional:
        fallback = min(max(1.0, lo), hi)
        return OptionalNumber(None if value in (None, "") else float(value), minimum=lo, maximum=hi, step=step,
                              decimals=_decimals(spec), suffix=suffix, fallback=fallback)
    return NumberField(float(value or 0), minimum=lo, maximum=hi, step=step, decimals=_decimals(spec), suffix=suffix)


def build_control(spec: FieldSpec, value: Any) -> QWidget:
    """Cria o controle do campo, ja com ``value`` (valor do schema) e com o nome acessivel."""
    kind = spec.kind
    control: QWidget
    if kind == schema.BOOL:
        control = ToggleSwitch(bool(value))
    elif kind in (schema.INT, schema.FLOAT):
        control = _number(spec, value)
    elif kind == schema.TEXT:
        control = TextField(str(value or ""))
    elif kind == schema.PATH:
        mode = "dir" if spec.key in _FOLDER_KEYS else "file"
        control = PathField(str(value or ""), mode=mode, file_filter=T.path_filter(spec.key))  # type: ignore[arg-type]
    elif kind == schema.CHOICE:
        control = ComboField([(T.choice_label(spec, v, label), v) for v, label in spec.choices])
        control.set_value(value)  # type: ignore[attr-defined]
    elif kind == schema.LIST:
        control = PathListField(list(value or [])) if spec.key in _FOLDER_LIST_KEYS else ChipList(list(value or []))
    elif kind == schema.DICT:
        control = DictEditor(dict(value or {}))
    elif kind == schema.HOTKEY:
        control = KeyCaptureField(to_display(value))
    elif kind in (schema.DEVICE_IN, schema.DEVICE_OUT):
        control = DeviceCombo("input" if kind == schema.DEVICE_IN else "output")
        control.set_value(value)  # type: ignore[attr-defined]
    else:
        raise ValueError(f"tipo de campo sem componente: {kind!r} ({spec.key})")
    control.setAccessibleName(T.label(spec))
    return control


def to_control(spec: FieldSpec, value: Any) -> Any:
    """Valor do modelo -> valor que o ``set_value`` do controle espera."""
    kind = spec.kind
    if kind == schema.HOTKEY:
        return to_display(value)
    if kind == schema.FLOAT and spec.optional:
        return None if value in (None, "") else float(value)
    if kind in (schema.INT, schema.FLOAT):
        return float(value or 0)
    if kind in (schema.DEVICE_IN, schema.DEVICE_OUT):
        return "" if value in (None, "") else value
    if kind in (schema.TEXT, schema.PATH):
        return str(value or "")
    if kind == schema.LIST:
        return list(value or [])
    if kind == schema.DICT:
        return dict(value or {})
    return value


def from_control(spec: FieldSpec, value: Any) -> Any:
    """Valor que o controle emitiu -> valor do modelo (o ``model.coerce`` acerta o tipo)."""
    return to_config(value) if spec.kind == schema.HOTKEY else value
