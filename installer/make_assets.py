"""Gera os recursos visuais do instalador (ícone .ico e imagens do assistente) a partir dos tokens do tema e do ícone 'mic' do kit.
Uso (da raiz do projeto): venv/Scripts/python.exe -I installer/make_assets.py"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent / "src"))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jarvis.ui.kit import icons  # noqa: E402
from jarvis.ui.theme import ThemeManager, make_font, pal  # noqa: E402

mgr = ThemeManager.instance()
mgr.set_mode("dark")
mgr.apply(app)
p = pal()
out = here / "assets"
out.mkdir(exist_ok=True)


def mark(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    g = QPainter(img)
    g.setRenderHint(QPainter.RenderHint.Antialiasing)
    g.setBrush(QColor(p.bg))
    g.setPen(Qt.PenStyle.NoPen)
    g.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    glyph = icons.pixmap("mic", p.accent, int(size * 0.62)).toImage()
    d = size * 0.62 / glyph.devicePixelRatio() if glyph.devicePixelRatio() else size * 0.62
    g.drawImage(QRectF((size - d) / 2, (size - d) / 2, d, d), glyph)
    g.end()
    return img


def side(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    g = QPainter(img)
    g.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(QPointF(0, 0), QPointF(0, h))
    grad.setColorAt(0, QColor(p.surface))
    grad.setColorAt(1, QColor(p.bg))
    g.fillRect(0, 0, w, h, grad)
    d = w * 0.5
    glyph = icons.pixmap("mic", p.accent, int(d)).toImage()
    dd = d / (glyph.devicePixelRatio() or 1)
    g.drawImage(QRectF((w - dd) / 2, h * 0.16, dd, dd), glyph)
    g.setPen(QColor(p.text))
    g.setFont(make_font(w * 0.17, 700))
    g.drawText(QRectF(0, h * 0.16 + dd + h * 0.03, w, h * 0.09), Qt.AlignmentFlag.AlignCenter, "Jarvis")
    g.setPen(QColor(p.text_muted))
    g.setFont(make_font(w * 0.07, 400))
    g.drawText(QRectF(w * 0.08, h * 0.16 + dd + h * 0.13, w * 0.84, h * 0.14), Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap,
               "Assistente de voz\n100% local")
    g.fillRect(0, h - 4, w, 4, QColor(p.accent))
    g.end()
    return img.convertToFormat(QImage.Format.Format_RGB888)


def small(s: int) -> QImage:
    return mark(s).convertToFormat(QImage.Format.Format_RGB888)


for w, h in ((164, 314), (192, 386), (246, 459)):
    side(w, h).save(str(out / f"wizard-{w}x{h}.bmp"), "BMP")
for s in (55, 64, 80):
    # fundo do tema claro do Inno: a marca tem o próprio fundo escuro com cantos arredondados
    img = QImage(s, s, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    g = QPainter(img)
    g.drawImage(0, 0, mark(s))
    g.end()
    img.convertToFormat(QImage.Format.Format_RGB888).save(str(out / f"small-{s}.bmp"), "BMP")

big = mark(256)
big.save(str(out / "jarvis-256.png"), "PNG")
from PIL import Image  # noqa: E402

Image.open(out / "jarvis-256.png").save(out / "jarvis.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("assets em", out)
