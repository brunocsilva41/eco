"""BannerSlot: lugar de um aviso fixo na tela (um por vez), montado com o ``InlineBanner`` do kit."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..kit import InlineBanner


class BannerSlot(QWidget):
    """Mostra no máximo um ``InlineBanner``. ``show_banner`` troca o aviso; ``clear`` esconde o espaço."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._banner: InlineBanner | None = None
        self.setVisible(False)

    def banner(self) -> InlineBanner | None:
        return self._banner

    def show_banner(self, state: str, what: str, why: str = "", todo: str = "", *, action_text: str = "",
                    on_action: Callable[[], None] | None = None, dismissible: bool = False) -> InlineBanner:
        self.clear()
        banner = InlineBanner(state, what, why, todo, action_text=action_text if on_action else "",
                              dismissible=dismissible)
        if on_action is not None:
            banner.actionTriggered.connect(lambda: self._act(on_action))
        banner.dismissed.connect(self.clear)
        self._banner = banner
        self._lay.addWidget(banner)
        self.setVisible(True)
        return banner

    def _act(self, callback: Callable[[], None]) -> None:
        self.clear()
        callback()

    def clear(self) -> None:
        banner, self._banner = self._banner, None
        if banner is not None:
            self._lay.removeWidget(banner)
            banner.hide()
            banner.deleteLater()
        self.setVisible(False)
