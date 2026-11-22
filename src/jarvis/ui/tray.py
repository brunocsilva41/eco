"""Ícone do Jarvis na bandeja do sistema (área de notificação) com menu de contexto.

Vive no MESMO processo da Ilha (que já tem Qt): custo extra ~0. Cada ação é um callback opcional entregue por quem cria o
controlador; o que não tiver callback não aparece no menu. Nomes do menu em pt-BR, no tom de um aplicativo profissional.
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Callable

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

log = logging.getLogger(__name__)

ACCENT = "#F4B63F"


def make_icon(muted: bool = False, listening: bool = False) -> QIcon:
    """Microfone vetorial (cápsula + haste + base) em fundo escuro arredondado, nítido em 16–48 px."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = float(size)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#15171C"))
        p.drawRoundedRect(QRectF(0.5, 0.5, s - 1, s - 1), s * 0.26, s * 0.26)
        ink = QColor("#8A8F99" if muted else ACCENT if listening else "#F2F3F5")
        pen = QPen(ink, max(1.2, s * 0.075))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cw, ch = s * 0.26, s * 0.40
        cap = QRectF(s / 2 - cw / 2, s * 0.17, cw, ch)
        p.drawRoundedRect(cap, cw / 2, cw / 2)
        arc = QPainterPath()
        arc.moveTo(s * 0.28, s * 0.50)
        arc.cubicTo(s * 0.28, s * 0.78, s * 0.72, s * 0.78, s * 0.72, s * 0.50)
        p.drawPath(arc)
        p.drawLine(QPointF(s / 2, s * 0.74), QPointF(s / 2, s * 0.84))
        p.drawLine(QPointF(s * 0.40, s * 0.84), QPointF(s * 0.60, s * 0.84))
        if muted:
            p.setPen(QPen(QColor("#FF6B6B"), max(1.4, s * 0.09)))
            p.drawLine(QPointF(s * 0.22, s * 0.20), QPointF(s * 0.80, s * 0.80))
        p.end()
        icon.addPixmap(pm)
    return icon


class _Bridge(QObject):
    update_result = Signal(object)


class TrayController(QObject):
    """Callbacks aceitos (todos opcionais): settings(), quit(), reveal(), toggle_visible(), set_listen_mode(mode: 'open'|'push'),
    set_mute(on: bool), set_size(size: 'compact'|'medium'|'large'), set_position(mode: str), toggle_pin()."""

    def __init__(self, app: QApplication, *, version: str = "", callbacks: dict[str, Callable] | None = None,
                 check_updates: Callable[[], object] | None = None) -> None:
        super().__init__(app)
        self._cb = callbacks or {}
        self._version = version
        self._check = check_updates
        self._bridge = _Bridge()
        self._bridge.update_result.connect(self._on_update_result)
        self._muted = False
        self._open = False
        self._tray = QSystemTrayIcon(make_icon(), app)
        self._tray.setToolTip("Jarvis")
        self._tray.activated.connect(self._on_activated)
        self._menu = QMenu()
        self._build_menu()
        self._tray.setContextMenu(self._menu)

    # ------------------------------------------------------------------ menu
    def _act(self, menu: QMenu, text: str, key: str, *, checkable: bool = False, checked: bool = False) -> QAction | None:
        if key not in self._cb:
            return None
        a = menu.addAction(text)
        if checkable:
            a.setCheckable(True)
            a.setChecked(checked)
            a.toggled.connect(lambda on, k=key: self._cb[k](on))
        else:
            a.triggered.connect(lambda _=False, k=key: self._cb[k]())
        return a

    def _choice_menu(self, parent: QMenu, title: str, key: str, options: list[tuple[str, str]]) -> None:
        if key not in self._cb:
            return
        sub = parent.addMenu(title)
        group = QActionGroup(sub)
        group.setExclusive(True)
        for value, label in options:
            a = sub.addAction(label)
            a.setCheckable(True)
            group.addAction(a)
            a.triggered.connect(lambda _=False, v=value, k=key: self._cb[k](v))

    def _build_menu(self) -> None:
        m = self._menu
        head = m.addAction(f"Jarvis {self._version}".strip())
        head.setEnabled(False)
        m.addSeparator()
        self._act(m, "Abrir Configurações", "settings")
        self._act(m, "Mostrar a Ilha", "reveal")
        if any(k in self._cb for k in ("set_size", "set_position", "toggle_pin", "toggle_visible")):
            ilha = m.addMenu("Ilha do Jarvis")
            self._act(ilha, "Exibir ou ocultar", "toggle_visible")
            self._act(ilha, "Fixar na tela", "toggle_pin", checkable=True)
            self._choice_menu(ilha, "Tamanho", "set_size", [("compact", "Compacto"), ("medium", "Médio"), ("large", "Expandido")])
            self._choice_menu(ilha, "Posição", "set_position", [
                ("docked", "Topo, acoplada"), ("floating", "Topo, flutuante"),
                ("dock_right", "Lateral direita"), ("dock_left", "Lateral esquerda")])
        m.addSeparator()
        self._open_act = self._act(m, "Escuta contínua", "set_listen_mode_toggle", checkable=True)
        self._mute_act = self._act(m, "Silenciar microfone", "set_mute", checkable=True)
        m.addSeparator()
        if self._check is not None:
            a = m.addAction("Verificar atualizações…")
            a.triggered.connect(self.check_updates)
        about = m.addAction("Sobre o Jarvis")
        about.triggered.connect(self._about)
        m.addSeparator()
        self._act(m, "Encerrar o Jarvis", "quit")

    # ------------------------------------------------------------------ estado
    def show(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()
        else:
            log.warning("a bandeja do sistema não está disponível")

    def hide(self) -> None:
        self._tray.hide()

    def set_status(self, text: str, *, muted: bool | None = None, listening: bool | None = None) -> None:
        self._tray.setToolTip(f"Jarvis · {text}" if text else "Jarvis")
        if muted is not None:
            self._muted = muted
            if self._mute_act is not None:
                self._mute_act.blockSignals(True)
                self._mute_act.setChecked(muted)
                self._mute_act.blockSignals(False)
        self._tray.setIcon(make_icon(self._muted, bool(listening) or self._open))

    def set_open_listening(self, on: bool) -> None:
        self._open = on
        if self._open_act is not None:
            self._open_act.blockSignals(True)
            self._open_act.setChecked(on)
            self._open_act.blockSignals(False)
        self._tray.setIcon(make_icon(self._muted, on))

    def notify(self, title: str, text: str) -> None:
        self._tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 6000)

    # ------------------------------------------------------------------ ações
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            cb = self._cb.get("reveal") or self._cb.get("settings")
            if cb:
                cb()

    def _about(self) -> None:
        self.notify("Jarvis", f"Assistente de voz local. Versão {self._version or 'de desenvolvimento'}.")

    def check_updates(self) -> None:
        if self._check is None:
            return
        self.notify("Jarvis", "Verificando atualizações…")
        threading.Thread(target=lambda: self._bridge.update_result.emit(self._check()), name="jarvis-updates", daemon=True).start()

    def _on_update_result(self, info: object) -> None:
        err = getattr(info, "error", "")
        if err:
            self.notify("Atualizações", f"Não consegui verificar: {err}.")
        elif getattr(info, "available", False):
            self.notify("Atualização disponível", f"Versão {info.latest} (você tem {info.current}). Abrindo a página da versão.")  # type: ignore[attr-defined]
            if getattr(info, "url", "").startswith("https://"):
                webbrowser.open(info.url)  # type: ignore[attr-defined]
        else:
            self.notify("Atualizações", f"Você já está na versão mais recente ({getattr(info, 'current', '')}).")
