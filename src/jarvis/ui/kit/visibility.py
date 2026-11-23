"""Mostrar/ocultar widgets SEM criar janelas soltas.

Causa do "piscar" das telas: ``widget.setVisible(True)`` num widget que ainda NÃO tem pai (construído antes de entrar num
layout) faz o Qt criar uma janela top-level nativa e mostrá-la por um instante (cerca de 130 janelinhas 'python' ao abrir as
Configurações). Ocultar é seguro; mostrar só vale quando já existe pai. Sem pai, o widget fica como está (não escondido
explicitamente) e aparece junto com o pai quando for adicionado a um layout.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget


def set_shown(widget: QWidget, shown: bool) -> None:
    """Equivale a ``setVisible`` mas nunca promove um widget órfão a janela. Aceita também QAction (sem pai de widget:
    so tem ``setVisible``; antes isto quebrava a busca com AttributeError ao digitar)."""
    if not isinstance(widget, QWidget):
        widget.setVisible(shown)  # type: ignore[attr-defined]
        return
    if shown and widget.parentWidget() is None:
        return
    widget.setVisible(shown)


def show_after_first_paint(window: QWidget, *, timeout_ms: int = 600) -> None:
    """Mostra a janela SEM o instante em branco: ela nasce transparente (opacidade 0), o Qt pinta o conteúdo e só então ela
    vira visível. Um limite de tempo garante que a janela aparece mesmo que a primeira pintura demore. Idempotente."""
    from PySide6.QtCore import QEvent, QObject, QTimer
    import os
    if os.environ.get("JARVIS_NO_PAINT_GATE"):                      # gancho de teste (A/B da janela em branco)
        window.show()
        return
    window.ensurePolished()
    window.setWindowOpacity(0.0)

    class _Once(QObject):
        done = False

        def reveal(self) -> None:
            if self.done:
                return
            self.done = True
            try:
                window.removeEventFilter(self)
                window.setWindowOpacity(1.0)
            except RuntimeError:                                  # janela já destruída
                pass

        def eventFilter(self, obj, ev):                            # noqa: N802
            if obj is window and ev.type() == QEvent.Type.Paint and not self.done:
                QTimer.singleShot(0, self.reveal)                 # depois de terminar a pintura em curso
            return False

    guard = _Once(window)
    window.installEventFilter(guard)
    QTimer.singleShot(timeout_ms, guard.reveal)
    window.show()
