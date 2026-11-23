"""Gerador da stylesheet Qt a partir dos tokens (sem cor ou tamanho literal: tudo vem de theme.py).

Convencoes: componentes do kit marcam a propriedade dinamica ``kit`` (card, bar, banner, toast,
dialog, nav) e usam ``variant`` (botoes), ``kind`` (rotulos), ``state`` (ok/warn/error),
``invalid`` (campos). Depois de mudar uma propriedade chame ``theme.repolish(widget)``.
O anel de foco dos controles pintados e feito no ``paintEvent``; campos de texto usam borda de 2 px.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

from ..theme import RADIUS, SIZE, SPACE, TYPE, Palette, mix, pt

_PAD_V = SPACE.xs                                   # preenchimento vertical dos controles
_PAD_H = SPACE.sm
_MIN_H = SIZE.target - 2 * SIZE.border - 2 * _PAD_V  # altura de conteudo que fecha 32 px no total


def _font(px: int, weight: int = TYPE.regular) -> str:
    return f"font-size: {pt(px):.2f}pt; font-weight: {weight};"


def _labels(p: Palette) -> str:
    kinds = {"display": (TYPE.display, TYPE.semibold, p.text), "title": (TYPE.title, TYPE.semibold, p.text),
             "heading": (TYPE.heading, TYPE.semibold, p.text), "label": (TYPE.body, TYPE.semibold, p.text),
             "body": (TYPE.body, TYPE.regular, p.text), "help": (TYPE.small, TYPE.regular, p.text_muted),
             "caption": (TYPE.caption, TYPE.regular, p.text_muted), "counter": (TYPE.counter, TYPE.bold, p.text)}
    css = [f'QLabel[kind="{k}"] {{ {_font(px, w)} color: {c}; }}' for k, (px, w, c) in kinds.items()]
    css += [f'QLabel[state="{s}"] {{ color: {p.state(s)}; }}' for s in ("ok", "warn", "error")]
    return "\n".join(css)


def _buttons(p: Palette) -> str:
    err_hover, err_press = mix(p.error, "#FFFFFF", 0.12), mix(p.error, "#000000", 0.14)
    return f"""
QPushButton {{ background: {p.raised}; color: {p.text}; border: {SIZE.border}px solid {p.border_strong};
  border-radius: {RADIUS.sm}px; padding: {_PAD_V}px {SPACE.lg}px; min-height: {_MIN_H}px; {_font(TYPE.body, TYPE.semibold)} }}
QPushButton:hover {{ background: {p.hover}; }}
QPushButton:pressed {{ background: {p.pressed}; }}
QPushButton:disabled {{ background: {p.surface}; color: {p.text_disabled}; border-color: {p.border}; }}
QPushButton[variant="primary"] {{ background: {p.accent}; color: {p.on_accent}; border-color: {p.accent_ink}; }}
QPushButton[variant="primary"]:hover {{ background: {p.accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {p.accent_pressed}; }}
QPushButton[variant="primary"]:disabled {{ background: {p.surface}; color: {p.text_disabled}; border-color: {p.border}; }}
QPushButton[variant="danger"] {{ background: {p.error}; color: {p.on_error}; border-color: {p.error}; }}
QPushButton[variant="danger"]:hover {{ background: {err_hover}; }}
QPushButton[variant="danger"]:pressed {{ background: {err_press}; }}
QPushButton[variant="danger"]:disabled {{ background: {p.surface}; color: {p.text_disabled}; border-color: {p.border}; }}
QPushButton[variant="text"], QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent;
  font-weight: {TYPE.regular}; }}
QPushButton[variant="text"]:hover, QPushButton[variant="ghost"]:hover {{ background: {p.hover}; }}
QPushButton[variant="text"]:pressed, QPushButton[variant="ghost"]:pressed {{ background: {p.pressed}; }}
QPushButton[variant="text"]:disabled, QPushButton[variant="ghost"]:disabled {{ background: transparent; border-color: transparent; }}
QPushButton[iconOnly="true"] {{ padding: 0; min-width: {SIZE.target - 2 * SIZE.border}px; max-width: {SIZE.target}px;
  min-height: {SIZE.target - 2 * SIZE.border}px; }}
QPushButton[kit="keycapture"] {{ text-align: left; padding: {_PAD_V}px {_PAD_H}px; background: {p.surface}; font-weight: {TYPE.regular}; }}
QPushButton[kit="keycapture"][capturing="true"] {{ border: {SIZE.focus_ring}px solid {p.focus_ring}; color: {p.accent_ink}; }}
QPushButton[kit="keycapture"][invalid="true"] {{ border-color: {p.error}; }}
"""


def _inputs(p: Palette) -> str:
    hover_border = mix(p.border_strong, p.text, 0.35)
    pad_f = f"{_PAD_V - 1}px {_PAD_H - 1}px"
    return f"""
QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit, QComboBox {{ background: {p.surface}; color: {p.text};
  border: {SIZE.border}px solid {p.border_strong}; border-radius: {RADIUS.sm}px; padding: {_PAD_V}px {_PAD_H}px;
  min-height: {_MIN_H}px; selection-background-color: {p.accent}; selection-color: {p.on_accent}; }}
QLineEdit:hover, QAbstractSpinBox:hover, QPlainTextEdit:hover, QTextEdit:hover, QComboBox:hover {{ border-color: {hover_border}; }}
QLineEdit:focus, QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
  border: {SIZE.focus_ring}px solid {p.focus_ring}; padding: {pad_f}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QComboBox:disabled {{
  background: {p.bg}; color: {p.text_disabled}; border-color: {p.border}; }}
QComboBox QLineEdit {{ background: transparent; border: none; padding: 0; min-height: 0; }}
QLineEdit[readOnly="true"] {{ color: {p.text_muted}; }}
QLineEdit[invalid="true"], QAbstractSpinBox[invalid="true"], QComboBox[invalid="true"], QPlainTextEdit[invalid="true"] {{
  border-color: {p.error}; }}
QLineEdit[invalid="true"]:focus, QAbstractSpinBox[invalid="true"]:focus, QComboBox[invalid="true"]:focus {{ border-color: {p.error}; }}
QComboBox {{ padding-right: {SPACE.xl + SPACE.xs}px; }}
QComboBox::drop-down {{ border: none; width: {SPACE.xl + SPACE.xs}px; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{ background: {p.raised}; color: {p.text}; border: {SIZE.border}px solid {p.border_strong};
  outline: 0; selection-background-color: {p.pressed}; selection-color: {p.text}; padding: {SPACE.xs}px; }}
QComboBox QAbstractItemView:focus {{ border: {SIZE.border}px solid {p.border_strong}; }}
QComboBox QAbstractItemView::item {{ min-height: {_MIN_H}px; padding: 0 {_PAD_H}px; border-radius: {RADIUS.sm}px; }}
QMenu {{ background: {p.raised}; border: {SIZE.border}px solid {p.border_strong}; padding: {SPACE.xs}px; }}
QMenu::item {{ padding: {_PAD_V + 2}px {SPACE.lg}px; border-radius: {RADIUS.sm}px; }}
QMenu::item:selected {{ background: {p.pressed}; }}
QMenu::item:disabled {{ color: {p.text_disabled}; }}
QMenu::separator {{ height: {SIZE.border}px; background: {p.border}; margin: {SPACE.xs}px {SPACE.sm}px; }}
"""


def _containers(p: Palette) -> str:
    return f"""
QToolTip {{ background: {p.raised}; color: {p.text}; border: {SIZE.border}px solid {p.border_strong};
  padding: {SPACE.xs}px {SPACE.sm}px; {_font(TYPE.small)} }}
QLabel {{ background: transparent; {_font(TYPE.body)} }}
QLabel:disabled {{ color: {p.text_disabled}; }}
QDialog, QMessageBox {{ background: {p.raised}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QFrame[kit="card"] {{ background: {p.raised}; border: {SIZE.border}px solid {p.border}; border-radius: {RADIUS.md}px; }}
QFrame[kit="bar"] {{ background: {p.surface}; border: none; border-top: {SIZE.border}px solid {p.border}; }}
QFrame[kit="nav"] {{ background: {p.surface}; border: none; border-right: {SIZE.border}px solid {p.border}; }}
QFrame[kit="toast"] {{ background: {p.raised}; border: {SIZE.border}px solid {p.border_strong}; border-radius: {RADIUS.md}px; }}
QFrame[kit="banner"] {{ background: {p.raised}; border: {SIZE.border}px solid {p.border_strong}; border-radius: {RADIUS.md}px; }}
{"".join(f'QFrame[kit="banner"][state="{s}"], QFrame[kit="toast"][state="{s}"] {{ background: {p.state_bg(s)}; border-color: {p.state(s)}; }}' for s in ("ok", "warn", "error"))}
QFrame[kit="chip"] {{ background: {p.raised}; border: {SIZE.border}px solid {p.border_strong}; border-radius: {RADIUS.sm}px; }}
QFrame[kit="plain"] {{ background: transparent; border: none; }}
QAbstractItemView {{ background: {p.surface}; color: {p.text}; border: {SIZE.border}px solid {p.border};
  border-radius: {RADIUS.md}px; outline: 0; selection-background-color: {p.pressed}; selection-color: {p.text}; }}
QAbstractItemView:focus {{ border: {SIZE.focus_ring}px solid {p.focus_ring}; }}
QListWidget[kit="nav"] {{ background: transparent; border: none; }}
QListWidget[kit="nav"]:focus {{ border: none; }}
QHeaderView::section {{ background: {p.raised}; color: {p.text}; border: none; border-bottom: {SIZE.border}px solid {p.border};
  padding: {_PAD_V}px {_PAD_H}px; font-weight: {TYPE.semibold}; }}
QProgressBar {{ background: {p.raised}; border: none; border-radius: {SPACE.xs // 2}px; min-height: {SPACE.xs}px; max-height: {SPACE.xs}px; }}
QProgressBar::chunk {{ background: {p.text_muted}; border-radius: {SPACE.xs // 2}px; }}
QScrollBar:vertical {{ background: transparent; width: {SPACE.md}px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: {SPACE.md}px; margin: 0; }}
QScrollBar::handle {{ background: {p.border_strong}; border-radius: {RADIUS.sm}px; min-height: {SPACE.xl}px; min-width: {SPACE.xl}px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {p.text_muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def build_qss(p: Palette) -> str:
    """Stylesheet global do tema ``p`` (instale com ``ThemeManager.apply``)."""
    return _labels(p) + _buttons(p) + _inputs(p) + _containers(p)


def build_qpalette(p: Palette) -> QPalette:
    """QPalette do tema (para widgets nativos, popups e caixas de mensagem)."""
    qp = QPalette()
    roles = {QPalette.ColorRole.Window: p.bg, QPalette.ColorRole.WindowText: p.text,
             QPalette.ColorRole.Base: p.surface, QPalette.ColorRole.AlternateBase: p.raised,
             QPalette.ColorRole.Text: p.text, QPalette.ColorRole.Button: p.raised,
             QPalette.ColorRole.ButtonText: p.text, QPalette.ColorRole.Highlight: p.accent,
             QPalette.ColorRole.HighlightedText: p.on_accent, QPalette.ColorRole.PlaceholderText: p.text_muted,
             QPalette.ColorRole.ToolTipBase: p.raised, QPalette.ColorRole.ToolTipText: p.text,
             QPalette.ColorRole.Link: p.accent_ink, QPalette.ColorRole.BrightText: p.text}
    for role, color in roles.items():
        qp.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        qp.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.text_disabled))
    return qp
