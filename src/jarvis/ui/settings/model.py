"""Modelo do formulario de Configuracoes: valores originais x atuais, alteracoes e erros por campo.

Sem Qt e sem disco: so estado e regras de comparacao. O ``SettingsStore`` (jarvis.settings) continua dono da
validacao e da gravacao; o controlador conversa com ele e alimenta este modelo.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from jarvis.settings import schema
from jarvis.settings.schema import FieldSpec
from jarvis.settings.store import Problem, SaveResult

from .texts import T

_KEY_IN_TEXT = re.compile(r"\b[a-z_]+\.[a-z_]+(?:\[\d+\])?")
_PREFIX = re.compile(r"^\s*[a-z_]+\.[a-z_]+(?:\[\d+\])?\s*:?\s*")


def normalize(spec: FieldSpec, value: Any) -> Any:
    """Forma comparavel de um valor: None e '' iguais, ferramentas sem ordem, dicionario sem ordem, float sem ruido."""
    if value is None:
        return ""
    if spec.kind == schema.TOOLS:
        return tuple(sorted(str(v) for v in value))
    if isinstance(value, dict):
        return tuple(sorted((str(k), str(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(value)
    if isinstance(value, float):
        return round(value, 9)
    return value


def coerce(spec: FieldSpec, value: Any) -> Any:
    """Valor que um controle entrega -> tipo que o schema espera (numero inteiro, lista de textos, etc.)."""
    kind = spec.kind
    if kind == schema.INT:
        return int(round(float(value)))
    if kind == schema.FLOAT:
        return None if value is None else float(value)
    if kind == schema.BOOL:
        return bool(value)
    if kind in (schema.LIST, schema.TOOLS):
        return [str(v) for v in (value or [])]
    if kind == schema.DICT:
        return {str(k): str(v) for k, v in dict(value or {}).items()}
    if kind in (schema.DEVICE_IN, schema.DEVICE_OUT):
        return None if value in (None, "") else value
    if kind in (schema.TEXT, schema.PATH, schema.HOTKEY):
        return str(value or "").strip()
    return value


def humanize(message: str) -> str:
    """Troca nomes tecnicos 'secao.campo' pelo rotulo do campo dentro da mensagem."""
    def swap(m: re.Match[str]) -> str:
        key = re.sub(r"\[\d+\]$", "", m.group(0))
        return T.label_for(key) if key in schema.BY_KEY else m.group(0)
    return _KEY_IN_TEXT.sub(swap, message)


def field_message(problem: Problem) -> str:
    """Mensagem para mostrar JUNTO do campo: sem o nome tecnico no comeco, com a primeira letra maiuscula."""
    text = _PREFIX.sub("", problem.message, count=1) if problem.key else problem.message
    text = humanize(text).strip()
    return text[:1].upper() + text[1:] if text else humanize(problem.message)


@dataclass(frozen=True)
class SaveOutcome:
    """O que a tela mostra depois de gravar: resultado do store, o que mudou e o estado do Jarvis."""
    result: SaveResult
    reset: bool
    running: bool
    pending_restart: tuple[str, ...]


class FormModel:
    """Valores do formulario. ``original`` e o que esta gravado; ``current`` e o que esta na tela."""

    def __init__(self, values: dict[str, Any]) -> None:
        self.original: dict[str, Any] = {}
        self.current: dict[str, Any] = {}
        self.errors: dict[str, str] = {}
        self.general: list[str] = []
        self.force_dirty = False
        self.load(values)

    # ---- carga
    def load(self, values: dict[str, Any], *, force_dirty: bool = False) -> None:
        self.original = copy.deepcopy(values)
        self.current = copy.deepcopy(values)
        self.errors = {}
        self.general = []
        self.force_dirty = force_dirty

    def revert(self) -> None:
        self.current = copy.deepcopy(self.original)
        self.errors = {}
        self.general = []
        self.force_dirty = False

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.current)

    # ---- edicao
    def set(self, key: str, value: Any) -> bool:
        """Grava um valor. Devolve True se mudou de fato (comparacao normalizada)."""
        spec = schema.BY_KEY[key]
        if normalize(spec, self.current.get(key)) == normalize(spec, value):
            self.current[key] = copy.deepcopy(value)
            return False
        self.current[key] = copy.deepcopy(value)
        return True

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in schema.BY_KEY:
                self.set(key, value)

    # ---- alteracoes
    def changed_keys(self) -> list[str]:
        return [f.key for f in schema.FIELDS
                if normalize(f, self.current.get(f.key)) != normalize(f, self.original.get(f.key))]

    def is_changed(self, key: str) -> bool:
        spec = schema.BY_KEY[key]
        return normalize(spec, self.current.get(key)) != normalize(spec, self.original.get(key))

    def change_count(self) -> int:
        return len(self.changed_keys())

    def has_pending(self) -> bool:
        return self.force_dirty or bool(self.changed_keys())

    # ---- erros
    def set_problems(self, problems: list[Problem]) -> None:
        errors: dict[str, str] = {}
        general: list[str] = []
        for p in problems:
            if p.key in schema.BY_KEY:
                msg = field_message(p)
                errors[p.key] = f"{errors[p.key]} {msg}" if p.key in errors else msg
            else:
                general.append(humanize(p.message))
        self.errors, self.general = errors, general

    def error_count(self) -> int:
        return len(self.errors) + len(self.general)

    def first_error_key(self) -> str:
        return next(iter(self.errors), "")
