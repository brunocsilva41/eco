"""Pagina de configuracoes por categoria: monta secoes e linhas a partir de ``categories`` e do schema.

Cada campo vira uma ``FieldRow`` (nunca um cartao por campo). A pagina filtra os campos pela busca, carrega
sob demanda o que e pesado (dispositivos de audio, ferramentas) e rola ate um campo com erro.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from jarvis.settings import schema

from ..kit.base import Label
from ..kit.layout import FieldRow, Section
from .binder import FieldBinder
from .blocks import (Block, config_file_block, details_block, paths_block, reset_block, status_block, theme_block)
from .categories import Category, SectionSpec, sections_for
from .controller import SettingsController
from .controls import DeviceCombo
from .fieldfactory import build_control, is_stacked
from .loaders import load_tools
from .page_base import PageBase
from .prefs import UiPrefs
from .searching import matches
from .texts import T
from .tools_panel import KEY_CONFIRM, KEY_DISABLED, ToolsPanel


@dataclass
class _Item:
    widget: QWidget
    section: Section
    text: str


class SettingsPage(PageBase):
    resetRequested = Signal()

    def __init__(self, cat: Category, controller: SettingsController, binder: FieldBinder, prefs: UiPrefs) -> None:
        super().__init__(cat.key)
        self._ctl, self._binder, self._prefs = controller, binder, prefs
        self._items: list[_Item] = []
        self._sections: list[Section] = []
        self._rows: dict[str, FieldRow] = {}
        self._lazy: list[Callable[[], None]] = []
        for spec in sections_for(cat):
            self._add_section(spec)
        self.finish()

    # ---- montagem
    def _add_section(self, sec: SectionSpec) -> None:
        title, desc = T.section(sec.id)
        section = Section(title, desc, level=sec.level)  # type: ignore[arg-type]
        self._sections.append(section)
        self.col.addWidget(section)
        for block in self._custom(sec):
            section.add(block.widget)
            self._items.append(_Item(block.widget, section, f"{self.title} {title} {block.text}"))
        for key in sec.keys:
            if sec.custom == "tools" and key in (KEY_DISABLED, KEY_CONFIRM):
                continue
            self._add_field(section, title, schema.BY_KEY[key])
        if sec.custom == "tools":
            self._add_tools(section, title)

    def _add_field(self, section: Section, section_title: str, spec: schema.FieldSpec) -> None:
        control = build_control(spec, self._ctl.model.current.get(spec.key))
        row = FieldRow(T.label(spec), control, help=T.help(spec), restart_required=spec.apply == schema.RESTART,
                       locked_reason=T.locked(spec), stacked=is_stacked(spec))
        self._binder.attach(spec, control, row.set_error)
        section.add(row)
        self._rows[spec.key] = row
        if isinstance(control, DeviceCombo):
            self._lazy.append(control.ensure_loaded)
        text = f"{self.title} {section_title} {T.label(spec)} {T.help(spec)} {T.locked(spec)}"
        self._items.append(_Item(row, section, text))

    def _add_tools(self, section: Section, section_title: str) -> None:
        err = Label("", "help", wrap=True)
        err.set_state("error")
        err.hide()
        panel = ToolsPanel(lambda: load_tools(self._ctl.cfg))

        def sink(message: str | None) -> None:
            err.setText(message or "")
            err.setVisible(bool(message))

        self._binder.attach_tools(panel, sink)
        self._lazy.append(panel.ensure_loaded)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(err)
        lay.addWidget(panel)
        section.add(box)
        text = f"{self.title} {section_title} {T.label_for(KEY_DISABLED)} {T.label_for(KEY_CONFIRM)} {T.tools.intro}"
        self._items.append(_Item(box, section, text))

    def _custom(self, sec: SectionSpec) -> list[Block]:
        if sec.custom == "theme":
            return theme_block(self._prefs)
        if sec.custom == "config_file":
            return config_file_block(self._ctl)
        if sec.custom == "reset":
            return reset_block(self.resetRequested.emit)
        if sec.custom == "status":
            return status_block(self._ctl)
        if sec.custom == "paths":
            return paths_block(self._ctl)
        if sec.custom == "details":
            return details_block()
        return []

    # ---- contrato com a janela
    def filter(self, query: str) -> int:
        shown = 0
        visible_sections: set[int] = set()
        for item in self._items:
            ok = matches(query, item.text)
            item.widget.setVisible(ok)
            if ok:
                shown += 1
                visible_sections.add(id(item.section))
        for section in self._sections:
            section.setVisible(id(section) in visible_sections)
        return shown

    def ensure_loaded(self) -> None:
        for load in self._lazy:
            load()

    def scroll_to(self, key: str) -> None:
        row = self._rows.get(key)
        if row is None:
            return
        self.ensureWidgetVisible(row)
        row.control.setFocus(Qt.FocusReason.OtherFocusReason)
