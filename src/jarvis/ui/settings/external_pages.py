"""Paginas que abrem outras telas do Eco: "Minha voz" (gravador) e "O que o Eco sabe de mim" (painel de
memoria). As duas telas sao de outros modulos e entram por importacao PREGUICOSA: se faltarem, a pagina
mostra uma mensagem clara em vez de quebrar.
"""
from __future__ import annotations

import logging

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..kit.base import Label, set_a11y
from ..kit.buttons import Button
from ..kit.feedback import InlineBanner
from ..kit.layout import Section
from ..kit.states import EmptyState
from ..theme import SPACE
from .controller import SettingsController
from .page_base import PageBase
from .searching import matches
from .texts import T

log = logging.getLogger(__name__)


class MyVoicePage(PageBase):
    def __init__(self, controller: SettingsController) -> None:
        super().__init__("my_voice")
        self._ctl = controller
        v = T.my_voice
        self._error_slot = QVBoxLayout()
        self._error_slot.setContentsMargins(0, SPACE.lg, 0, 0)
        self.col.addLayout(self._error_slot)
        self._texts = [v.phrases_title, v.phrases_body, v.wake_title, v.wake_body, v.privacy]
        self._add(v.phrases_title, v.phrases_body, v.phrases_button, "frases", primary=True)
        self._add(v.wake_title, v.wake_body, v.wake_button, "eco", primary=False)
        note = Label(v.privacy, "help", wrap=True)
        self.col.addSpacing(SPACE.xxl)
        self.col.addWidget(note)
        self.finish()

    def _add(self, title: str, body: str, button: str, set_name: str, *, primary: bool) -> None:
        section = Section(title, body, level=1 if primary else 2)
        btn = Button(button, variant="primary" if primary else "secondary", icon_name="mic")
        btn.clicked.connect(lambda: self._open(set_name))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(btn)
        rl.addStretch(1)
        section.add(row)
        self.col.addWidget(section)

    def _open(self, set_name: str) -> None:
        v = T.my_voice
        try:
            from ..recorder_window import open_recorder   # preguicoso: carrega audio so se for usado
            open_recorder(self._ctl.cfg, parent=self.window(), set_name=set_name)  # type: ignore[call-arg]
        except ImportError as exc:
            log.warning("gravador indisponivel: %s", exc)
            self._fail(v.fail_missing)
        except TypeError as exc:
            log.warning("gravador sem suporte a set_name: %s", exc)
            self._fail(v.fail_version)
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem para a pessoa
            log.exception("nao consegui abrir o gravador")
            self._fail(v.fail_other.format(detail=exc))
            return
        else:
            self._clear_error()

    def _clear_error(self) -> None:
        while self._error_slot.count():
            item = self._error_slot.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _fail(self, why: str) -> None:
        self._clear_error()
        self._error_slot.addWidget(InlineBanner.error(T.my_voice.fail_what, why, T.my_voice.fail_todo))

    def search_text(self) -> str:
        return f"{self.title} {self.subtitle} {' '.join(self._texts)}"


class KnowsPage(QWidget):
    """Hospeda o ``MemoryPanel`` (criado so ao abrir a pagina) e chama ``close_memory()`` ao fechar."""

    def __init__(self, controller: SettingsController) -> None:
        super().__init__()
        self.key = "knows"
        self._ctl = controller
        self.title, self.subtitle = T.page(self.key)
        self._panel: QWidget | None = None
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
        self._lay.setSpacing(0)
        self._body: QWidget | None = None
        set_a11y(self, self.title, self.subtitle)

    def filter(self, query: str) -> int:
        return 1 if matches(query, f"{self.title} {self.subtitle}") else 0

    def ensure_loaded(self) -> None:
        if self._body is not None:
            return
        try:
            from ..memory_panel import MemoryPanel
            panel = MemoryPanel(self._ctl.cfg, parent=None)
        except Exception as exc:  # noqa: BLE001 - modulo ausente ou diferente: mostra estado vazio
            log.warning("painel de memoria indisponivel: %s", exc)
            empty = EmptyState(T.knows.missing_title, T.knows.missing_body, action_text=T.knows.retry, icon_name="memory")
            empty.actionTriggered.connect(self._retry)
            self._set_body(empty)
            return
        self._panel = panel
        self._set_body(panel)

    def _retry(self) -> None:
        self._set_body(None)
        self.ensure_loaded()

    def _set_body(self, widget: QWidget | None) -> None:
        if self._body is not None:
            self._lay.removeWidget(self._body)
            if self._body is not self._panel:
                self._body.deleteLater()
            else:
                self._body.setParent(None)
        self._body = widget
        if widget is not None:
            self._lay.addWidget(widget, 1)
            widget.show()

    def shutdown(self) -> None:
        panel = self._panel
        if panel is None:
            return
        closer = getattr(panel, "close_memory", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001 - o fechamento nunca pode travar a janela
                log.exception("close_memory falhou")
        panel.deleteLater()
        self._panel = None

    def scroll_to(self, key: str) -> None:
        return None
