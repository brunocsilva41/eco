"""Janela própria do painel (``open_memory``) e programa isolado (``main_memory``, usado por ``python -m jarvis memory``)."""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from ...config import Config, ConfigError
from ..theme import SIZE, SPACE, ThemeManager
from .panel import MemoryPanel
from .texts import tr

log = logging.getLogger(__name__)

# Tamanhos em múltiplos do alvo mínimo (32): mínimo 880x560 (27,5 x 17,5) e abertura 1152x800 (36 x 25).
MIN_SIZE = (round(SIZE.target * 27.5), round(SIZE.target * 17.5))
OPEN_SIZE = (SIZE.target * 36, SIZE.target * 25)
_window: MemoryPanel | None = None


def _load_cfg() -> Config:
    try:
        from ...config import load
        return load()
    except (ConfigError, OSError) as exc:
        log.warning("config.toml ilegível; o painel usa os padrões: %s", exc)
        return Config()


def open_memory(cfg: Config | None = None, parent: QWidget | None = None) -> MemoryPanel:
    """Abre (ou traz à frente) o painel como janela própria. Exige um ``QApplication`` ativo."""
    global _window
    if QApplication.instance() is None:
        raise RuntimeError("open_memory precisa de um QApplication; use main_memory() fora da interface")
    existing = _window
    if existing is not None:
        try:
            if existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return existing
        except RuntimeError:                                  # a janela anterior já foi destruída
            _window = None
    panel = MemoryPanel(cfg if cfg is not None else _load_cfg(), parent)
    panel.setWindowFlag(Qt.WindowType.Window, True)
    panel.setAutoFillBackground(True)                         # janela própria: fundo opaco (embutido, é transparente)
    panel.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
    panel.setWindowTitle(tr().header.window_title)
    panel.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    panel.setMinimumSize(*MIN_SIZE)
    panel.resize(*OPEN_SIZE)
    _window = panel
    panel.show()
    panel.raise_()
    panel.activateWindow()
    panel.focus_search()                                      # janela própria: dá para começar a digitar na hora
    return panel


def main_memory() -> int:
    """Executa o painel como programa próprio. Devolve o código de saída."""
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    if owns_app:
        ThemeManager.instance().apply(app)                    # type: ignore[arg-type]
    try:
        open_memory()
    except Exception:  # noqa: BLE001 - qualquer falha de abertura vira código de saída 1, com o detalhe no log
        log.exception("não consegui abrir o painel de memória")
        return 1
    return int(app.exec()) if owns_app else 0
