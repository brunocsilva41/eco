"""Pop-up de nova versão (processo da Ilha/bandeja). Só Qt puro, sem o kit: o processo da Ilha é leve de propósito.

Opções: Baixar, Instalar automaticamente, Lembrar depois (24 h), Ignorar esta versão. Mostra notas, progresso e erros em pt-BR.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from ..core.updates import UpdateInfo
from .update_flow import UpdateSession

log = logging.getLogger(__name__)


def _mb(n: int) -> str:
    return f"{n / (1 << 20):.0f} MB"


class UpdateDialog(QDialog):
    def __init__(self, session: UpdateSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._s = session
        self.setWindowTitle("Eco · Nova versão")
        self.setMinimumWidth(680)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        self._title = QLabel()
        f = self._title.font()
        f.setPointSizeF(f.pointSizeF() * 1.25)
        f.setBold(True)
        self._title.setFont(f)
        self._sub = QLabel()
        self._sub.setWordWrap(True)
        self._notes = QTextBrowser()
        self._notes.setOpenExternalLinks(False)
        self._notes.setMinimumHeight(160)
        self._notes.setAccessibleName("Notas da versão")
        self._bar = QProgressBar()
        self._bar.setTextVisible(True)
        self._bar.setVisible(False)
        self._msg = QLabel()
        self._msg.setWordWrap(True)
        self._msg.setVisible(False)
        for w in (self._title, self._sub, self._notes, self._bar, self._msg):
            lay.addWidget(w)
        row = QHBoxLayout()
        row.setSpacing(8)
        self._b_ignore = QPushButton("Ignorar esta versão")
        self._b_later = QPushButton("Lembrar depois")
        self._b_dl = QPushButton("Baixar")
        self._b_auto = QPushButton("Instalar automaticamente")
        self._b_auto.setDefault(True)
        for b in (self._b_ignore, self._b_later):
            row.addWidget(b)
        row.addStretch(1)
        for b in (self._b_dl, self._b_auto):
            row.addWidget(b)
        for b in (self._b_ignore, self._b_later, self._b_dl, self._b_auto):
            b.setMinimumWidth(b.fontMetrics().horizontalAdvance(b.text()) + 48)
        lay.addLayout(row)
        self._b_ignore.clicked.connect(self._ignore)
        self._b_later.clicked.connect(self._later)
        self._b_dl.clicked.connect(lambda: self._s.download(then_install=False))
        self._b_auto.clicked.connect(self._auto)
        s = session
        s.progress.connect(self._on_progress)
        s.ready.connect(self._on_ready)
        s.failed.connect(self._on_failed)
        s.installing.connect(self._on_installing)
        s.state_changed.connect(lambda _st: self._refresh())

    # ------------------------------------------------------------ dados
    def show_info(self, info: UpdateInfo) -> None:
        self._title.setText(f"Eco {info.latest} disponível")
        pre = " (pré-lançamento)" if info.prerelease else ""
        size = f" · instalador de {_mb(info.installer.size)}" if info.installer and info.installer.size else ""
        self._sub.setText(f"Você está na versão {info.current}{pre}{size}. Instalar por cima mantém seus dados, "
                          "configuração e modelos.")
        self._notes.setMarkdown(info.notes or "Sem notas para esta versão.")
        self._msg.setVisible(False)
        self._bar.setVisible(False)
        self._refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def _refresh(self) -> None:
        st = self._s.state
        busy = st in ("downloading", "installing", "checking")
        ok, why = self._s.can_install()
        ready = st == "ready"
        self._b_dl.setEnabled(not busy and not ready)
        self._b_dl.setText("Baixado" if ready else "Baixar")
        self._b_auto.setEnabled(not busy and ok)
        self._b_auto.setText(("Tentar de novo" if self._s.retry else "Instalar agora") if ready else "Instalar automaticamente")
        self._b_auto.setToolTip(why)
        self._b_later.setEnabled(not busy)
        self._b_ignore.setEnabled(not busy)
        if not ok and not busy:
            self._note(why)

    def _note(self, text: str, error: bool = False) -> None:
        self._msg.setText(("⚠ " if error else "ℹ ") + text)
        self._msg.setVisible(True)

    # ------------------------------------------------------------ ações
    def _auto(self) -> None:
        if self._s.state == "ready":
            self._s.install()
        else:
            self._s.download(then_install=True)

    def _ignore(self) -> None:
        self._s.ignore()
        self.close()

    def _later(self) -> None:
        self._s.remind_later(24.0)
        self.close()

    # ------------------------------------------------------------ retornos
    def _on_progress(self, got: int, total: int) -> None:
        self._bar.setVisible(True)
        self._bar.setMaximum(max(total, 1))
        self._bar.setValue(min(got, max(total, 1)))
        self._bar.setFormat(f"{_mb(got)} de {_mb(total)}" if total else _mb(got))

    def _on_ready(self, _path: str) -> None:
        self._bar.setVisible(False)
        self._note("Download concluído e SHA-256 conferido. Pronto para instalar.")
        self._refresh()

    def _on_installing(self) -> None:
        self._note("Instalando: o Eco vai fechar, atualizar e abrir de novo sozinho.")

    def _on_failed(self, msg: str) -> None:
        self._bar.setVisible(False)
        self._note(msg, error=True)
        self._refresh()
