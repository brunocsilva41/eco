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
from ..kit.cards import SectionCard
from ..kit.layout import FieldRow
from ..theme import SPACE
from .binder import FieldBinder
from .blocks import (Block, config_file_block, details_block, external_panel, permissions_block, paths_block, reset_block,
                     status_block, theme_block)
from .categories import Category, SectionSpec, sections_for
from .controller import SettingsController
from .controls import DeviceCombo
from .fieldfactory import build_control, is_stacked
from .loaders import load_tools
from .page_base import PageBase
from .prefs import UiPrefs
from .searching import fold, matches
from .texts import T
from .tools_panel import KEY_CONFIRM, KEY_DISABLED, ToolsPanel


@dataclass
class _Item:
    widget: QWidget
    section: SectionCard
    text: str


class SettingsPage(PageBase):
    resetRequested = Signal()

    def __init__(self, cat: Category, controller: SettingsController, binder: FieldBinder, prefs: UiPrefs) -> None:
        super().__init__(cat.key)
        self._ctl, self._binder, self._prefs = controller, binder, prefs
        self._items: list[_Item] = []
        self._sections: list[SectionCard] = []
        self._rows: dict[str, FieldRow] = {}
        self._row_section: dict[str, SectionCard] = {}
        self._section_id: dict[int, str] = {}
        self._searching = False
        self._resting: dict[int, bool] = {}               # estado das secoes antes da busca (voltam ao limpar)
        self._lazy: list[Callable[[], None]] = []
        self._yolo: QWidget | None = None
        self._section_by_id: dict[str, SectionCard] = {}
        for spec in sections_for(cat):
            self._add_section(spec)
        self.finish()

    # ---- montagem
    def _add_section(self, sec: SectionSpec) -> None:
        title, desc = T.section(sec.id)
        collapsible = sec.level == 2 and sec.custom != "reset"
        saved = self._prefs.section_expanded(self.key, sec.id) if collapsible else None
        count = sum(1 for k in sec.keys if k not in (KEY_DISABLED, KEY_CONFIRM) or sec.custom != "tools")
        badge = T.section_badge(count) if collapsible and count else ""
        section = SectionCard(title, desc, collapsible=collapsible, expanded=bool(saved), badge=badge)
        if collapsible:
            section.toggled.connect(lambda v, sid=sec.id: self._remember(sid, v))
        self._sections.append(section)
        self._section_by_id[sec.id] = section
        self._section_id[id(section)] = sec.id
        self.col.addSpacing(SPACE.lg)
        self.col.addWidget(section)
        after = sec.custom == "permissions"            # campos primeiro, depois o cartao do YOLO
        if not after:
            self._add_blocks(sec, section, title)
        for key in sec.keys:
            if sec.custom == "tools" and key in (KEY_DISABLED, KEY_CONFIRM):
                continue
            self._add_field(section, title, schema.BY_KEY[key])
        if after:
            self._add_blocks(sec, section, title)
        if sec.custom == "tools":
            self._add_tools(section, title)
        if not section._rows:                               # painel externo ausente: nada a mostrar, sem cartao vazio
            self.col.removeWidget(section)
            self._sections.remove(section)
            self._section_by_id.pop(sec.id, None)
            section.deleteLater()

    def _remember(self, section_id: str, value: bool) -> None:
        if not self._searching:
            self._prefs.set_section_expanded(self.key, section_id, value)

    def _add_blocks(self, sec: SectionSpec, section: SectionCard, title: str) -> None:
        for block in self._custom(sec):
            section.add(block.widget)
            if callable(getattr(block.widget, "ensure_loaded", None)):
                self._lazy.append(block.widget.ensure_loaded)         # painel externo monta o conteudo ao abrir a pagina
            self._items.append(_Item(block.widget, section, f"{self.title} {title} {block.text}"))

    def _add_field(self, section: SectionCard, section_title: str, spec: schema.FieldSpec) -> None:
        control = build_control(spec, self._ctl.model.current.get(spec.key))
        row = FieldRow(T.label(spec), control, help=T.help(spec), restart_required=spec.apply == schema.RESTART,
                       locked_reason=T.locked(spec), stacked=is_stacked(spec), wrap_help=True)
        def show_error(message: str | None, _row: FieldRow = row, _sec: SectionCard = section) -> None:
            _row.set_error(message)
            if message:
                _sec.set_expanded(True, animated=False)          # erro nunca fica escondido num grupo recolhido

        self._binder.attach(spec, control, show_error)
        section.add(row)
        self._rows[spec.key] = row
        self._row_section[spec.key] = section
        if isinstance(control, DeviceCombo):
            self._lazy.append(control.ensure_loaded)
        text = f"{self.title} {section_title} {T.label(spec)} {T.help(spec)} {T.locked(spec)}"
        self._items.append(_Item(row, section, text))

    def _add_tools(self, section: SectionCard, section_title: str) -> None:
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

    def _permissions(self) -> list[Block]:
        blocks = permissions_block(self._ctl)
        self._yolo = blocks[0].widget
        return blocks

    def _custom(self, sec: SectionSpec) -> list[Block]:
        if sec.custom == "theme":
            return theme_block(self._prefs)
        if sec.custom == "permissions":
            return self._permissions()
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
        if sec.custom == "updates_panel":
            return external_panel("updates_page", self._ctl, f"{self.title} versão atualização verificar instalar")
        if sec.custom == "cloud_panel":
            return external_panel("cloud_brain_page", self._ctl, f"{self.title} nuvem agente opencode claude codex copilot")
        return []

    # ---- contrato com a janela
    def filter(self, query: str) -> int:
        shown = 0
        visible_sections: set[int] = set()
        words = fold(query).split()
        for item in self._items:
            ok = matches(query, item.text)
            item.widget.setVisible(ok)
            setter = getattr(item.widget, "set_highlight", None)
            if callable(setter):
                setter(words if ok else [])
            if ok:
                shown += 1
                visible_sections.add(id(item.section))
        if words and not self._searching:                    # entrou em busca: guarda o estado para devolver depois
            self._searching = True
            self._resting = {id(s): s.expanded() for s in self._sections}
        for section in self._sections:
            section.setVisible(id(section) in visible_sections)
            if self._searching and section.is_collapsible():
                want = bool(words) and id(section) in visible_sections or (not words and self._resting.get(id(section), False))
                section.set_expanded(want, animated=False, emit=False)
        if not words:
            self._searching = False
            self._resting = {}
        return shown

    def ensure_loaded(self) -> None:
        for load in self._lazy:
            load()

    def scroll_to(self, key: str) -> None:
        row = self._rows.get(key)
        if row is None:
            return
        section = self._row_section.get(key)
        if section is not None:
            section.set_expanded(True, animated=False)
        self.ensureWidgetVisible(row)
        row.control.setFocus(Qt.FocusReason.OtherFocusReason)

    def focus_section(self, section_id: str) -> bool:
        """Rola ate a secao e, na de permissoes, poe o foco no botao de ativar o YOLO (sem aciona-lo)."""
        section = self._section_by_id.get(section_id)
        if section is None:
            return False
        section.set_expanded(True, animated=False)
        self.ensureWidgetVisible(section, 0, SPACE.xl)
        if section_id == "permissions" and self._yolo is not None:
            self._yolo.focus_primary()                       # type: ignore[attr-defined]
        return True

