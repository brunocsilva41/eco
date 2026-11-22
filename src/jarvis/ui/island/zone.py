"""Deteccao do mouse no topo da tela (revelar a Ilha escondida). Duas estrategias, escolhidas por medicao:

* ``HotZone``: janela transparente MINIMA (largura da Ilha x 3 px, alfa 1/255) no topo central. O Windows entrega
  ``enterEvent``/``leaveEvent``: ZERO timers e zero CPU enquanto o mouse nao chega la. Um timer de 160 ms so existe
  enquanto o cursor esta dentro (permanencia, para nao revelar por acidente).
* ``CursorPoller``: ``GetCursorPos`` a 10 Hz (QTimer) so enquanto escondida. Reserva (``Presence.ZONE_MODE``).

Ambos so existem/rodam enquanto a Ilha esta ESCONDIDA e a revelacao por mouse esta ligada.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from . import tokens as T
from . import winapi


def zone_rect(g: QRect, side: str = "", pct: int = 50) -> QRect:
    """Zona ativa em px logicos: no topo (largura da Ilha x 3 px) ou na borda lateral (3 px x 256 px, na altura do trilho)."""
    if not side:
        w = T.CW + 2 * 24
        return QRect(g.x() + (g.width() - w) // 2, g.y(), w, T.ZONE_H)
    h = T.ZONE_SIDE_H
    cy = g.y() + g.height() * max(0, min(100, pct)) / 100.0
    top = max(g.y(), min(round(cy - h / 2), g.y() + g.height() - h))
    return QRect(g.x() + (g.width() - T.ZONE_H if side == "right" else 0), top, T.ZONE_H, h)


class HotZone(QWidget):
    triggered = Signal()
    side = ""
    pct = 50

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.setInterval(T.DWELL_MS)
        self._dwell.timeout.connect(self._fire)

    def place(self) -> None:
        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return
        self.setGeometry(zone_rect(scr.geometry(), self.side, self.pct))

    def arm(self) -> None:
        self.place()
        if not self.isVisible():
            self.show()
            winapi.set_no_activate(int(self.winId()))

    def disarm(self) -> None:
        self._dwell.stop()
        if self.isVisible():
            self.hide()

    def paintEvent(self, _e) -> None:  # type: ignore[no-untyped-def]
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))                  # alfa 1/255: invisivel, mas recebe o mouse
        p.end()

    def enterEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().enterEvent(e)
        self._dwell.start()

    def leaveEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        super().leaveEvent(e)
        self._dwell.stop()

    def _fire(self) -> None:
        self.triggered.emit()


class CursorPoller(QObject):
    """Reserva: GetCursorPos a ``POLL_HZ`` so enquanto armado."""

    triggered = Signal()
    side = ""
    pct = 50

    def __init__(self) -> None:
        super().__init__()
        self._t = QTimer(self)
        self._t.setInterval(round(1000 / T.POLL_HZ))
        self._t.timeout.connect(self._poll)
        self._since = 0
        self._pt = wintypes.POINT()
        self._u32 = ctypes.WinDLL("user32") if sys.platform == "win32" else None

    def arm(self) -> None:
        self._since = 0
        if not self._t.isActive():
            self._t.start()

    def disarm(self) -> None:
        self._t.stop()

    def _poll(self) -> None:
        scr = QGuiApplication.primaryScreen()
        if scr is None or self._u32 is None:
            return
        self._u32.GetCursorPos(ctypes.byref(self._pt))
        g = scr.geometry()
        d = scr.devicePixelRatio()
        x, y = self._pt.x / d, self._pt.y / d
        inside = zone_rect(g, self.side, self.pct).adjusted(0, 0, 1, 1).contains(int(x), int(y))
        self._since = self._since + 1 if inside else 0
        if self._since * self._t.interval() >= T.DWELL_MS:
            self._since = 0
            self.triggered.emit()
