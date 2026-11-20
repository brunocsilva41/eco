"""Leitura, validação, comparação e gravação das Configurações (config.toml).

Regras (as mesmas da config tipada, que é a fonte da verdade):
- cada campo é validado por `jarvis.config` (tipos + regras de negócio) e os erros voltam POR CAMPO, em português;
- `llm.host` fica em loopback e `safety.emergency_hotkey` é obrigatória: valores que as desativem são recusados;
- gravação ATÔMICA, com cópia de segurança (`config.toml.bak`) antes de substituir;
- só é gravado o que difere do padrão (mudanças futuras de padrão valem para o usuário);
- nenhum segredo, token ou PIN é aceito nem gravado.
"""
from __future__ import annotations

import copy
import dataclasses
import logging
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config as cfgmod
from ..config import Config, ConfigError
from ..win.keys import KeyError_, parse_combo
from . import schema, tomlio

log = logging.getLogger(__name__)

HEADER = ("Configuração do Jarvis (gerada pela tela de Configurações; pode editar à mão).\n"
          "Só aparece o que difere do padrão. NUNCA coloque senhas, PINs ou tokens aqui.")


@dataclass(frozen=True)
class Problem:
    key: str                  # "secao.campo" ou "" para erro geral
    message: str


@dataclass(frozen=True)
class Changes:
    live: tuple[str, ...]
    restart: tuple[str, ...]

    @property
    def any(self) -> bool:
        return bool(self.live or self.restart)


@dataclass(frozen=True)
class SaveResult:
    config: Config
    changes: Changes


class SettingsError(ValueError):
    def __init__(self, problems: list[Problem]) -> None:
        super().__init__("; ".join(f"{p.key or 'geral'}: {p.message}" for p in problems))
        self.problems = problems


_PREFIX = re.compile(r"^\s*([a-z_]+(?:\.[a-z_]+)+)(?:\[\d+\])?\s*:?\s*(.*)$")


def _split_errors(msg: str) -> list[Problem]:
    """Converte a mensagem agregada do ConfigError em problemas por campo (quando o texto cita 'secao.campo')."""
    out: list[Problem] = []
    for line in msg.splitlines():
        line = line.strip().lstrip("-").strip()
        if not line or line.startswith("configuração inválida"):
            continue
        m = _PREFIX.match(line)
        key = ""
        if m:
            cand = m.group(1)
            parts = cand.split(".")
            for n in range(len(parts), 1, -1):                       # 'apps.hotkeys[3]' -> 'apps.hotkeys'
                if ".".join(parts[:n]) in schema.BY_KEY:
                    key = ".".join(parts[:n])
                    break
        out.append(Problem(key, line))
    return out or [Problem("", msg)]


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or cfgmod.CONFIG_FILE

    # ------------------------------------------------------------- leitura
    def load(self) -> Config:
        return cfgmod.load(self.path)

    def defaults(self) -> Config:
        return cfgmod.from_dict({})

    def values(self, cfg: Config | None = None) -> dict[str, Any]:
        return schema.current_values(cfg or self.load())

    # ------------------------------------------------------------- validação
    def to_config(self, values: dict[str, Any]) -> Config:
        """Constrói a Config candidata a partir de {'secao.campo': valor}. Levanta SettingsError com os problemas por campo."""
        problems = self._pre_check(values)
        if problems:
            raise SettingsError(problems)
        raw = self._to_raw(values)
        try:
            return cfgmod.from_dict(raw)
        except ConfigError as exc:
            raise SettingsError(_split_errors(str(exc))) from exc

    def validate(self, values: dict[str, Any]) -> list[Problem]:
        """Lista de problemas (vazia = válido). Para o feedback ao vivo da tela."""
        try:
            self.to_config(values)
        except SettingsError as exc:
            return exc.problems
        return []

    def _pre_check(self, values: dict[str, Any]) -> list[Problem]:
        out: list[Problem] = []
        for key in values:
            if key not in schema.BY_KEY:
                out.append(Problem(key, "opção desconhecida (a tela não guarda senhas, tokens nem PINs)"))
        emergency = values.get("safety.emergency_hotkey")
        if emergency is not None:
            try:
                parse_combo(str(emergency))
            except KeyError_:
                out.append(Problem("safety.emergency_hotkey", "a tecla de emergência é obrigatória e precisa ser uma combinação válida"))
        host = values.get("llm.host")
        if host is not None:
            try:
                cfgmod.assert_loopback(str(host))
            except ConfigError:
                out.append(Problem("llm.host", "o servidor do modelo só pode escutar em loopback (127.0.0.1)"))
        return out

    @staticmethod
    def _to_raw(values: dict[str, Any]) -> dict[str, Any]:
        """{'a.b': v} -> {'a': {'b': v}} no formato do TOML; vazio opcional vira o padrão (omitido) ou desliga (mmproj)."""
        raw: dict[str, Any] = {}
        for key, val in values.items():
            sec, name = key.split(".", 1)
            spec = schema.BY_KEY.get(key)
            if spec and spec.optional and (val is None or val == ""):
                if key == "llm.mmproj":
                    raw.setdefault(sec, {})[name] = ""             # "" desliga a visão
                continue                                           # demais opcionais vazios = padrão
            if isinstance(val, tuple):
                val = list(val)
            raw.setdefault(sec, {})[name] = val
        return raw

    # ------------------------------------------------------------- comparação
    def diff(self, old: Config, new: Config) -> Changes:
        live: list[str] = []
        restart: list[str] = []
        for f in schema.FIELDS:
            if schema.get_value(old, f.key) != schema.get_value(new, f.key):
                (live if f.apply == schema.LIVE else restart).append(f.key)
        return Changes(tuple(live), tuple(restart))

    # ------------------------------------------------------------- gravação
    def save(self, values: dict[str, Any]) -> SaveResult:
        """Valida e grava (atômico, com .bak). Devolve a nova Config e o que aplica na hora x precisa reiniciar."""
        new = self.to_config(values)
        try:
            old = self.load()
        except ConfigError:
            old = self.defaults()                      # config atual quebrada: a nova a substitui
        self._write(new)
        changes = self.diff(old, new)
        log.info("configurações salvas (%d aplicadas na hora, %d exigem reiniciar)", len(changes.live), len(changes.restart))
        return SaveResult(new, changes)

    def reset_defaults(self) -> SaveResult:
        """Restaura os padrões: apaga o arquivo (com .bak) e devolve a configuração padrão."""
        try:
            old = self.load()
        except ConfigError:
            old = self.defaults()
        new = self.defaults()
        self._backup()
        if self.path.exists():
            self.path.unlink()
        log.info("configurações restauradas para o padrão")
        return SaveResult(new, self.diff(old, new))

    def _write(self, cfg: Config) -> None:
        defaults = self.defaults()
        data: dict[str, Any] = {}
        for f in schema.FIELDS:
            val, dflt = schema.get_value(cfg, f.key), schema.get_value(defaults, f.key)
            if val == dflt:
                continue
            if val is None:
                if f.key == "llm.mmproj":
                    data.setdefault(f.section, {})[f.name] = ""
                continue
            data.setdefault(f.section, {})[f.name] = self._toml_value(val)
        text = tomlio.dumps(data, HEADER)
        tomllib.loads(text)                                          # a saída DEVE ser TOML válido
        self._backup()
        tomlio.atomic_write_text(self.path, text)

    @staticmethod
    def _toml_value(val: Any) -> Any:
        if isinstance(val, Path):
            return str(val)
        if isinstance(val, tuple):
            return list(val)
        if isinstance(val, dict) and not val:
            return {}
        return val

    def _backup(self) -> None:
        if self.path.exists():
            try:
                shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
            except OSError:
                log.warning("não consegui fazer a cópia de segurança de %s", self.path)


def clone_values(values: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(values)


__all__ = ["SettingsStore", "SettingsError", "Problem", "Changes", "SaveResult", "clone_values", "dataclasses"]
