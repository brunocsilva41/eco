"""Pontos de entrada do gravador: abrir dentro de um app ja em execucao ou rodar como programa proprio."""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from ...config import Config
from ..theme import ThemeManager
from .model import check_set_name
from .texts import T
from .window import RecorderWindow

log = logging.getLogger(__name__)

_instance: RecorderWindow | None = None


def _forget(window: RecorderWindow) -> None:
    global _instance
    if _instance is window:
        _instance = None


def open_recorder(cfg: Config, parent: QWidget | None = None, set_name: str = "frases") -> RecorderWindow:
    """Abre (ou traz a frente, se ja aberta) a janela do gravador no conjunto ``set_name``.

    ``set_name``: "frases" (as frases do Bruno) ou "jarvis" (amostras da palavra Jarvis); outro valor levanta
    ``ValueError``. Se a janela ja estiver aberta, troca de conjunto (a menos que esteja gravando). Exige um
    ``QApplication`` ativo; a janela e mantida viva ate ser fechada (nao e preciso guardar o retorno).
    """
    global _instance
    check_set_name(set_name)
    if QApplication.instance() is None:
        raise RuntimeError(T.api.needs_app)
    existing = _instance
    if existing is not None:
        try:
            if existing.isVisible():
                if not existing.show_set(set_name):
                    log.info("gravador ocupado gravando: o conjunto %s nao foi trocado", set_name)
                existing.raise_()
                existing.activateWindow()
                return existing
        except RuntimeError:                  # objeto Qt ja destruido
            _instance = None
    window = RecorderWindow(cfg, parent, set_name)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    window.closed.connect(lambda: _forget(window))
    _instance = window
    window.show()
    window.raise_()
    window.activateWindow()
    return window


def main_recorder(cfg: Config, set_name: str = "frases") -> int:
    """Roda o gravador como programa proprio (cria o ``QApplication`` e o tema se nao existirem). Devolve o codigo de saida."""
    check_set_name(set_name)
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
        ThemeManager.instance().apply(app)  # type: ignore[arg-type]
    open_recorder(cfg, set_name=set_name)
    return int(app.exec()) if owns_app else 0
