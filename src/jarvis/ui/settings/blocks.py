"""Blocos proprios das paginas (tema, arquivo de configuracao, restaurar, sobre). Cada funcao devolve linhas
``FieldRow`` prontas, com o texto usado pela busca. Sem regra de negocio: so leitura de estado e sinais."""
from __future__ import annotations

import importlib
import inspect
import logging
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QWidget

from jarvis.settings.control import Runtime

from ..kit.base import Label
from ..kit.buttons import Button
from ..kit.fields import ComboField
from ..kit.layout import FieldRow
from ..kit.status import StatusChip
from ..theme import SPACE, ThemeManager
from .controller import SettingsController
from .yolo_card import YoloCard
from .prefs import UiPrefs
from .texts import T

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Block:
    widget: QWidget
    text: str                # texto que a busca compara


def open_folder(path: Path) -> bool:
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))


def theme_block(prefs: UiPrefs) -> list[Block]:
    g = T.general
    combo = ComboField([(g.theme_dark, "dark"), (g.theme_light, "light"), (g.theme_system, "system")])
    mgr = ThemeManager.instance()
    combo.set_value(mgr.mode)

    def changed(mode: object) -> None:
        mgr.set_mode(mode)  # type: ignore[arg-type]
        prefs.set_theme_mode(mode)  # type: ignore[arg-type]

    combo.valueChanged.connect(changed)
    row = FieldRow(g.theme_label, combo, help=g.theme_help)
    return [Block(row, f"{g.theme_label} {g.theme_help} {g.theme_dark} {g.theme_light} {g.theme_system}")]


def permissions_block(controller: SettingsController) -> list[Block]:
    y = T.yolo
    return [Block(YoloCard(controller), f"{y.title} {y.badge} {y.on_button} {y.off_button} YOLO confirmações")]


def _folder_row(label: str, path: Path, help_text: str | None = None) -> Block:
    a = T.advanced
    btn = Button(a.open_folder, icon_name="folder")
    row = FieldRow(label, btn, help=help_text if help_text is not None else str(path))

    def go() -> None:
        target = path if path.is_dir() else path.parent
        if open_folder(target):
            row.set_error(None)
        else:
            log.warning("nao consegui abrir a pasta %s", target)
            row.set_error(f"{a.open_failed}: {target}")

    btn.clicked.connect(go)
    return Block(row, f"{label} {path}")


def config_file_block(controller: SettingsController) -> list[Block]:
    return [_folder_row(T.advanced.config_label, controller.store.path)]


def reset_block(on_reset: Callable[[], None]) -> list[Block]:
    a = T.advanced
    btn = Button(a.reset_button, variant="danger", icon_name="refresh")
    btn.clicked.connect(on_reset)
    return [Block(FieldRow(a.reset_label, btn, help=a.reset_help), f"{a.reset_label} {a.reset_help}")]


def status_block(controller: SettingsController) -> list[Block]:
    a = T.about
    chip = StatusChip("neutral", a.unknown)
    detail = Label("", "help")
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(SPACE.sm)
    lay.addWidget(chip)
    lay.addWidget(detail)

    def update(rt: object) -> None:
        if isinstance(rt, Runtime):
            when = datetime.fromtimestamp(rt.started).strftime(a.time_format)
            chip.set_state("ok", a.running)
            detail.setText(f"{a.pid.format(pid=rt.pid)}, {a.since.format(when=when)}")
        else:
            chip.set_state("neutral", a.closed)
            detail.setText("")
        box.setAccessibleName(f"{a.state_label}: {chip.text()} {detail.text()}".strip())

    update(None)
    controller.runtimeChanged.connect(update)
    return [Block(FieldRow(a.state_label, box), f"{a.state_label} {a.running} {a.closed}")]


def paths_block(controller: SettingsController) -> list[Block]:
    a, p = T.about, controller.cfg.paths
    return [_folder_row(a.config_file, controller.store.path), _folder_row(a.data_dir, p.data),
            _folder_row(a.log_dir, p.logs), _folder_row(a.models_dir, p.models)]


def details_block() -> list[Block]:
    a = T.about
    out: list[Block] = []
    for label, value in ((a.python, platform.python_version()), (a.qt, pyside_version)):
        lbl = Label(value, "body")
        lbl.setAccessibleName(f"{label}: {value}")
        out.append(Block(FieldRow(label, lbl), f"{label} {value}"))
    return out


def external_panel(module: str, controller: SettingsController, text: str) -> list[Block]:
    """Painel autocontido de outro modulo (``updates_page``, ``cloud_brain_page``): usa a primeira classe de widget
    definida no modulo cujo nome termina em Panel/Page/Widget e que aceita ``(controller)`` ou nada. Modulo
    ausente ou com erro vira lista vazia (a pagina segue com os campos do schema) e fica no log."""
    try:
        mod = importlib.import_module(f"{__package__}.{module}")
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.endswith(module):
            return []
        log.warning("painel %s nao carregou: %s", module, exc)
        return []
    except Exception as exc:  # noqa: BLE001 (um painel quebrado nao derruba as Configuracoes)
        log.warning("painel %s nao carregou: %s", module, exc)
        return []
    members = sorted(inspect.getmembers(mod, inspect.isclass), key=lambda m: (not m[0].endswith("Panel"), m[0]))
    for name, cls in members:                                # prefere *Panel (sem titulo nem rolagem propria)
        if cls.__module__ != mod.__name__ or not issubclass(cls, QWidget) or not name.endswith(("Panel", "Page", "Widget")):
            continue
        for args in ((controller,), ()):
            try:
                return [Block(cls(*args), text)]
            except TypeError:
                continue
            except Exception as exc:  # noqa: BLE001
                log.warning("painel %s.%s falhou: %s", module, name, exc)
                return []
    return []

