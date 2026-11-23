"""Faz uma janela de topo caber na area util do monitor (tela pequena ou escala 150/200%).

Sem isto, uma janela com tamanho minimo fixo (ex.: 900x620) passa da borda de baixo num monitor 1080p a 200% (area util
960x520 em pixels logicos) e a barra de botoes (Salvar, Avancar, Gravar) fica fora da tela. ``install`` liga o ajuste ao
primeiro ``show`` da janela: o tamanho minimo encolhe para caber, a janela nunca passa da area util e volta para dentro dela
se estiver fora (monitor desligado). Nao altera nada quando a janela ja cabe.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QWidget


def fit_to_screen(win: QWidget, min_size: tuple[int, int]) -> None:
    scr = win.screen()
    if scr is None:
        return
    avail = scr.availableGeometry()
    fg = win.frameGeometry()
    frame_w = max(0, fg.width() - win.width())
    frame_h = max(0, fg.height() - win.height())
    max_w, max_h = max(320, avail.width() - frame_w), max(240, avail.height() - frame_h)
    win.setMinimumSize(min(min_size[0], max_w), min(min_size[1], max_h))
    w, h = min(win.width(), max_w), min(win.height(), max_h)
    if (w, h) != (win.width(), win.height()):
        win.resize(w, h)
    fg = win.frameGeometry()
    x = min(max(fg.x(), avail.left()), max(avail.left(), avail.right() - fg.width() + 1))
    y = min(max(fg.y(), avail.top()), max(avail.top(), avail.bottom() - fg.height() + 1))
    if (x, y) != (fg.x(), fg.y()):
        win.move(x, y)


class _FitOnShow(QObject):
    def __init__(self, win: QWidget, min_size: tuple[int, int]) -> None:
        super().__init__(win)
        self._win, self._min, self._done = win, min_size, False
        win.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # type: ignore[no-untyped-def]  # noqa: N802
        if obj is self._win and event.type() == QEvent.Type.Show and not self._done:
            self._done = True
            fit_to_screen(self._win, self._min)
            QTimer.singleShot(0, lambda: fit_to_screen(self._win, self._min))     # de novo com a moldura final do Windows
        return False


def install(win: QWidget, min_size: tuple[int, int]) -> None:
    """Ajusta a janela a area util do monitor no primeiro show."""
    _FitOnShow(win, min_size)
