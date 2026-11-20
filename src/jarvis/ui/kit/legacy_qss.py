"""DEPRECATED. Estilos para as telas ANTIGAS (settings_window, recorder_window, memory_panel).

Mantem as propriedades antigas (``role``, ``variant``, ``state``, objectName ``card``/``banner``/
``nav``/``footer``/``page``) funcionando em cima dos tokens novos. Apague este arquivo quando as
telas forem reescritas com o kit. Nao use em codigo novo.
"""
from __future__ import annotations

from ..theme import RADIUS, SIZE, SPACE, TYPE, Palette, pt


def _base(p: Palette) -> str:
    small, title, phrase, countdown = (f"{pt(x):.2f}pt" for x in (TYPE.small, TYPE.title, TYPE.display, TYPE.counter))
    return f"""
QLabel[role="title"] {{ font-size: {title}; font-weight: {TYPE.semibold}; }}
QLabel[role="muted"] {{ color: {p.text_muted}; font-size: {small}; }}
QLabel[role="phrase"] {{ font-size: {phrase}; font-weight: {TYPE.semibold}; }}
QLabel[role="countdown"] {{ font-size: {countdown}; font-weight: {TYPE.regular}; }}
QLabel[role="metric"] {{ color: {p.text_muted}; font-size: {small}; }}
QLabel[role="field"] {{ font-weight: {TYPE.semibold}; }}
QLabel[role="section"] {{ font-size: {title}; font-weight: {TYPE.semibold}; }}
QLabel[role="badge"] {{ border: {SIZE.border}px solid {p.border_strong}; border-radius: {RADIUS.sm}px; padding: 1px {SPACE.sm}px; font-size: {small}; }}
QLabel[role="badge"][state="ok"] {{ border-color: {p.ok}; }}
QLabel[role="badge"][state="warn"] {{ border-color: {p.warn}; }}
QLabel[role="badge"][state="error"] {{ border-color: {p.error}; }}
QLabel[role="badge"][state="accent"] {{ border-color: {p.accent_ink}; color: {p.accent_ink}; }}
QFrame#card {{ background: {p.surface}; border: {SIZE.border}px solid {p.border}; border-radius: {RADIUS.lg}px; }}
QFrame#card[changed="true"] {{ border-color: {p.accent_ink}; }}
QFrame#card[invalid="true"] {{ border-color: {p.error}; }}
QFrame#banner {{ background: {p.raised}; border: {SIZE.border}px solid {p.border}; border-radius: {RADIUS.md}px; }}
QFrame#banner[state="ok"] {{ border-color: {p.ok}; }}
QFrame#banner[state="warn"] {{ border-color: {p.warn}; }}
QFrame#banner[state="error"] {{ border-color: {p.error}; }}
QPushButton:focus {{ border: {SIZE.focus_ring}px solid {p.focus_ring}; }}
QListWidget {{ background: {p.surface}; border: {SIZE.border}px solid {p.border}; border-radius: {RADIUS.md}px; padding: {SPACE.xs}px; outline: 0; }}
QListWidget::item {{ padding: {SPACE.xs}px {SPACE.sm}px; border-radius: {RADIUS.sm}px; }}
QListWidget::item:hover {{ background: {p.hover}; }}
QListWidget::item:selected {{ background: {p.accent}; color: {p.on_accent}; }}
"""


def _extras(p: Palette) -> str:
    return f"""
QWidget#plain {{ background: transparent; }}
QWidget#page {{ background: {p.bg}; }}
QFrame#nav {{ background: {p.surface}; border-right: {SIZE.border}px solid {p.border}; }}
QFrame#footer {{ background: {p.surface}; border-top: {SIZE.border}px solid {p.border}; }}
QCheckBox {{ background: transparent; spacing: {SPACE.sm}px; }}
QCheckBox::indicator {{ width: {SPACE.lg + 2}px; height: {SPACE.lg + 2}px; border: {SIZE.focus_ring}px solid {p.border_strong};
  border-radius: {RADIUS.sm}px; background: {p.raised}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent_ink}; }}
QCheckBox::indicator:disabled {{ border-color: {p.text_disabled}; }}
QCheckBox::indicator:focus {{ border-color: {p.focus_ring}; }}
QPushButton[capture="true"] {{ text-align: left; font-weight: {TYPE.semibold}; min-width: {SPACE.huge * 4}px; }}
QPushButton[capture="true"][capturing="true"] {{ border: {SIZE.focus_ring}px solid {p.warn}; color: {p.warn}; }}
QListWidget#nav {{ background: transparent; border: none; }}
QListWidget#nav::item {{ padding: {SPACE.sm + 2}px {SPACE.lg}px; border-radius: {RADIUS.sm}px; }}
QListWidget#nav::item:selected {{ background: {p.accent}; color: {p.on_accent}; }}
QTableWidget {{ background: {p.surface}; border: {SIZE.border}px solid {p.border}; border-radius: {RADIUS.md}px; gridline-color: {p.border};
  selection-background-color: {p.accent}; selection-color: {p.on_accent}; }}
QTableWidget QLineEdit {{ border-radius: 0; }}
QTableCornerButton::section {{ background: {p.raised}; border: none; }}
"""


def build_legacy_qss(p: Palette, *, base: bool = True, extras: bool = True) -> str:
    return (_base(p) if base else "") + (_extras(p) if extras else "")
