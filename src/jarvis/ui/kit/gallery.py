"""Galeria do kit: todas as pecas e estados nos dois temas, e geracao de capturas offscreen.

* ``main_gallery()`` abre a janela (``python -m jarvis.ui.kit.gallery``).
* ``render_gallery_prints(out_dir)`` gera PNGs em 100%, 150% e 200% nos temas escuro e claro.

Metodo de escala (documentado porque e o ponto delicado): o Qt le ``QT_SCALE_FACTOR`` UMA vez, na
criacao do QGuiApplication, entao cada escala roda num PROCESSO FILHO (``--prints``) com
``QT_QPA_PLATFORM=offscreen`` e ``QT_SCALE_FACTOR=<escala>``. O fator vira devicePixelRatio da tela,
exatamente como um monitor a 150% ou 200% no Windows (layout em pixels logicos, fonte em pontos,
``QWidget.grab()`` devolve o pixmap em pixels fisicos). O PNG sai com o tamanho fisico. A troca
escuro/claro acontece em TEMPO DE EXECUCAO (``set_mode``) dentro do mesmo processo, o que tambem
exercita o sinal ``changed``. As fontes do Windows sao apontadas por ``QT_QPA_FONTDIR`` porque a
plataforma offscreen nao enxerga as fontes do sistema sozinha.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from ..theme import SIZE, SPACE, TYPE, Mode, ThemeManager, make_font, pal, set_motion_override
from .base import Label
from .dialogs import ConfirmDialog
from .feedback import Toast
from .fields import ComboField
from .gallery_pages import Page, build_pages
from .layout import FieldRow
from .navlist import NavList

_WIN_W, _WIN_H = 1360, 860
_THEMES: tuple[tuple[str, Mode], ...] = (("Escuro", "dark"), ("Claro", "light"), ("Sistema (Windows)", "system"))


class GalleryWindow(QWidget):
    """Barra lateral (paginas + tema) e uma pagina rolavel por vez."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Kit de componentes do Eco")
        self.resize(_WIN_W, _WIN_H)
        self.pages: list[Page] = build_pages()
        side = QWidget()
        side.setFixedWidth(SIZE.nav_width)
        side.setProperty("kit", "plain")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, SPACE.xl, 0, SPACE.lg)
        sl.setSpacing(SPACE.sm)
        sl.addWidget(Label("  Kit de componentes", "heading"))
        self.nav = NavList()
        for pg in self.pages:
            self.nav.add_entry(pg.key, pg.title, pg.icon)
        sl.addWidget(self.nav, 1)
        self.theme_combo = ComboField(list(_THEMES))
        self.theme_combo.set_value(ThemeManager.instance().mode)
        self.theme_combo.valueChanged.connect(lambda m: ThemeManager.instance().set_mode(m))
        ThemeManager.instance().modeChanged.connect(self._sync_combo)
        sl.addWidget(FieldRow("Tema", self.theme_combo, help="Troca na hora, sem reiniciar.", stacked=True))
        self.stack = QStackedWidget()
        self.scrolls: list[QScrollArea] = []
        for pg in self.pages:
            sa = QScrollArea()
            sa.setFrameShape(QScrollArea.Shape.NoFrame)
            sa.setWidget(pg.widget)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.scrolls.append(sa)
            self.stack.addWidget(sa)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(side)
        lay.addWidget(self.stack, 1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

    def _sync_combo(self, mode: str) -> None:
        self.theme_combo.blockSignals(True)
        self.theme_combo.set_value(mode)
        self.theme_combo.blockSignals(False)

    def show_page(self, index: int) -> Page:
        self.nav.setCurrentRow(index)
        QApplication.processEvents()
        pg = self.pages[index]
        pg.widget.adjustSize()
        return pg


def main_gallery() -> int:
    """Abre a galeria interativa. Retorna o codigo de saida do app."""
    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)  # type: ignore[arg-type]
    win = GalleryWindow()
    win.show()
    return app.exec()


# ------------------------------------------------------------------ capturas offscreen


def _save(pm: QPixmap, path: Path) -> None:
    if not pm.save(str(path), "PNG"):
        raise OSError(f"nao consegui gravar {path}")


def _stitch(frames: list[tuple[str, QPixmap]]) -> QPixmap:
    """Empilha as capturas de foco/interacao com o nome de cada uma a esquerda."""
    p = pal()
    dpr = frames[0][1].devicePixelRatio()
    label_w, gap = SIZE.target * 5, SPACE.md
    width = label_w + int(max(pm.width() / dpr for _, pm in frames)) + 2 * SPACE.lg
    height = sum(int(pm.height() / dpr) + gap for _, pm in frames) + gap
    out = QPixmap(int(width * dpr), int(height * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(QColor(p.bg))
    g = QPainter(out)
    y = gap
    g.setFont(make_font(TYPE.small))
    for name, pm in frames:
        g.setPen(QColor(p.text_muted))
        g.drawText(QRect(SPACE.lg, y, label_w, int(pm.height() / dpr)), int(Qt.AlignmentFlag.AlignVCenter), name)
        g.drawPixmap(label_w + SPACE.lg, y, pm)
        y += int(pm.height() / dpr) + gap
    g.end()
    return out


def _crop(page: QWidget, target: QWidget) -> QPixmap:
    top_left = target.mapTo(page, QPoint(-SPACE.md, -SPACE.xl))
    return page.grab(QRect(top_left, target.size() + QSize(2 * SPACE.md, SPACE.xl + SPACE.md)))


def _focus_frames(win: GalleryWindow) -> list[tuple[str, QPixmap]]:
    from PySide6.QtTest import QTest
    frames: list[tuple[str, QPixmap]] = []
    for idx, pg in enumerate(win.pages):
        if not pg.focus:
            continue
        win.show_page(idx)
        win.activateWindow()
        for name, widget in pg.focus:
            widget.setFocus(Qt.FocusReason.TabFocusReason)
            QApplication.processEvents()
            if name == "tecla":
                QTest.keyClick(widget, Qt.Key.Key_Return)      # Enter entra em captura
                QApplication.processEvents()
                frames.append(("tecla: capturando", _crop(pg.widget, widget)))
                QTest.keyClick(widget, Qt.Key.Key_Escape)
            else:
                frames.append((f"foco: {name}", _crop(pg.widget, widget)))
            if name.startswith("botao-") and name != "botao-danger":
                QTest.mouseMove(widget, widget.rect().center())
                QApplication.processEvents()
                frames.append((f"hover: {name}", _crop(pg.widget, widget)))
                QTest.mousePress(widget, Qt.MouseButton.LeftButton)
                QApplication.processEvents()
                frames.append((f"pressionado: {name}", _crop(pg.widget, widget)))
                QTest.mouseRelease(widget, Qt.MouseButton.LeftButton)
            QApplication.processEvents()
    return frames


def _render_child(out_dir: Path, themes: list[Mode]) -> None:
    app = QApplication(sys.argv)
    set_motion_override(False)           # captura deterministica: sem animacoes em curso
    mgr = ThemeManager.instance()
    mgr.set_mode(themes[0])
    mgr.apply(app)
    win = GalleryWindow()
    win.show()
    tag_scale = int(round(win.devicePixelRatioF() * 100))
    for mode in themes:
        mgr.set_mode(mode)               # troca em tempo de execucao
        QApplication.processEvents()
        prefix = f"{mode}-{tag_scale}"
        for i, pg in enumerate(win.pages):
            win.show_page(i)
            _save(pg.widget.grab(), out_dir / f"{prefix}-{pg.key}.png")
        win.show_page(0)
        Toast.show_message(win, "ok", "Configurações salvas", "Valem a partir da próxima conversa.")
        QApplication.processEvents()
        _save(win.grab(), out_dir / f"{prefix}-janela.png")
        _save(_stitch(_focus_frames(win)), out_dir / f"{prefix}-foco-e-interacao.png")
        dlg = ConfirmDialog(win, title="Apagar esta memória", message="Ela deixa de existir para o Eco.",
                            target="Lembrar que a reunião de quinta começa às 14h.", destructive=True,
                            confirm_text="Apagar", require_word="APAGAR")
        dlg.show()
        QApplication.processEvents()
        QApplication.processEvents()
        _save(dlg.grab(), out_dir / f"{prefix}-dialogo-confirmacao.png")
        dlg.close()
    win.close()


def render_gallery_prints(out_dir: str | Path, scales: tuple[float, ...] = (1.0, 1.5, 2.0),
                          themes: tuple[Mode, ...] = ("dark", "light")) -> list[Path]:
    """Gera os PNGs em ``out_dir`` (um processo offscreen por escala). Devolve os arquivos gerados."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    src_root = str(Path(__file__).resolve().parents[3])
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for scale in scales:
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=str(scale), PYTHONPATH=src_root)
        if fonts.is_dir():
            env["QT_QPA_FONTDIR"] = str(fonts)
        cmd = [sys.executable, "-m", "jarvis.ui.kit.gallery", "--prints", str(out), "--themes", ",".join(themes)]
        subprocess.run(cmd, env=env, check=True, timeout=300)
    return sorted(out.glob("*.png"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Galeria do kit de UI do Eco")
    ap.add_argument("--prints", metavar="DIR", help="gera capturas offscreen (use QT_SCALE_FACTOR no ambiente)")
    ap.add_argument("--themes", default="dark,light")
    ns = ap.parse_args()
    if ns.prints:
        _render_child(Path(ns.prints), [t for t in ns.themes.split(",")])  # type: ignore[misc]
    else:
        raise SystemExit(main_gallery())
