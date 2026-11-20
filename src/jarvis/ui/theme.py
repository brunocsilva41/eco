"""Tokens de design e stylesheet Qt escuro, reutilizável por qualquer janela do projeto.

Uso: ``apply_theme(app)`` no ``QApplication`` (ou ``widget.setStyleSheet(build_stylesheet())`` numa janela).
Variações por propriedade dinâmica (chame ``repolish(widget)`` depois de mudar):

* ``QPushButton[variant="primary"|"danger"|"ghost"]``
* ``QLabel[role="title"|"muted"|"phrase"|"countdown"|"metric"]``
* ``QLabel[state="ok"|"warn"|"error"]`` (cor do texto) e ``QFrame#banner[state=...]``
"""
from __future__ import annotations

from typing import Final, Literal

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

State = Literal["ok", "warn", "error"]

# ------------------------------------------------------------------ cores
BG: Final = "#0F1115"
SURFACE: Final = "#171A21"
SURFACE_ALT: Final = "#1E232C"
BORDER: Final = "#2B313D"
TEXT: Final = "#E6E8EC"
TEXT_MUTED: Final = "#97A0AF"
ACCENT: Final = "#4C8DFF"
ACCENT_HOVER: Final = "#6BA0FF"
ACCENT_PRESSED: Final = "#3A74DB"
ON_ACCENT: Final = "#0B1220"
OK: Final = "#3DDC84"
WARN: Final = "#FFB020"
ERROR: Final = "#FF5C5C"
DISABLED_TEXT: Final = "#5C6472"

STATE_COLORS: Final[dict[str, str]] = {"ok": OK, "warn": WARN, "error": ERROR}

# ------------------------------------------------------------------ grade de 8 px, raios e fontes
SPACE: Final = 8
SP1, SP2, SP3, SP4 = SPACE, 2 * SPACE, 3 * SPACE, 4 * SPACE
RADIUS_SM, RADIUS_MD, RADIUS_LG = 6, 10, 14
FONT_FAMILY: Final = "Segoe UI"
FONT_SIZE_BASE, FONT_SIZE_SMALL, FONT_SIZE_TITLE = 10, 9, 14
FONT_SIZE_PHRASE, FONT_SIZE_COUNTDOWN = 22, 40

_LEVEL_STATE: Final[dict[str, State]] = {"ok": "ok", "baixo": "warn", "saturado": "error", "silencio": "error"}


def level_state(level: str) -> State:
    """Mapeia o veredito de ``audio_analysis.assess`` para a cor de estado."""
    return _LEVEL_STATE.get(level, "warn")


def state_color(state: str) -> str:
    return STATE_COLORS.get(state, TEXT_MUTED)


def repolish(widget: QWidget) -> None:
    """Reaplica o stylesheet depois de mudar uma propriedade dinâmica (variant/state/role)."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def build_stylesheet() -> str:
    return f"""
* {{ font-family: "{FONT_FAMILY}"; font-size: {FONT_SIZE_BASE}pt; color: {TEXT}; }}
QWidget {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {SURFACE_ALT}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}

QLabel[role="title"] {{ font-size: {FONT_SIZE_TITLE}pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {TEXT_MUTED}; font-size: {FONT_SIZE_SMALL}pt; }}
QLabel[role="phrase"] {{ font-size: {FONT_SIZE_PHRASE}pt; font-weight: 500; }}
QLabel[role="countdown"] {{ font-size: {FONT_SIZE_COUNTDOWN}pt; font-weight: 300; }}
QLabel[role="metric"] {{ color: {TEXT_MUTED}; font-size: {FONT_SIZE_SMALL}pt; }}
QLabel[state="ok"] {{ color: {OK}; }}
QLabel[state="warn"] {{ color: {WARN}; }}
QLabel[state="error"] {{ color: {ERROR}; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px; }}
QFrame#card QLabel {{ background: transparent; }}
QFrame#banner {{ background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px; }}
QFrame#banner[state="ok"] {{ border-color: {OK}; }}
QFrame#banner[state="warn"] {{ border-color: {WARN}; }}
QFrame#banner[state="error"] {{ border-color: {ERROR}; }}

QPushButton {{ background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px;
              padding: {SP1 + 2}px {SP2}px; min-height: {SP3}px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {DISABLED_TEXT}; background: {SURFACE}; border-color: {SURFACE_ALT}; }}
QPushButton[variant="primary"] {{ background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[variant="primary"]:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton[variant="primary"]:disabled {{ background: {SURFACE_ALT}; color: {DISABLED_TEXT}; border-color: {SURFACE_ALT}; }}
QPushButton[variant="danger"] {{ background: {ERROR}; color: {ON_ACCENT}; border-color: {ERROR}; font-weight: 600; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; color: {TEXT_MUTED}; }}
QPushButton[variant="ghost"]:hover {{ color: {TEXT}; border-color: {BORDER}; }}

QComboBox {{ background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
            padding: {SP1 - 2}px {SP1 + 2}px; min-height: {SP3 - 2}px; }}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox:disabled {{ color: {DISABLED_TEXT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE_ALT}; border: 1px solid {BORDER};
                               selection-background-color: {ACCENT}; selection-color: {ON_ACCENT}; }}

QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px; padding: {SP1 // 2}px; outline: 0; }}
QListWidget::item {{ padding: {SP1 - 2}px {SP1}px; border-radius: {RADIUS_SM}px; }}
QListWidget::item:hover {{ background: {SURFACE_ALT}; }}
QListWidget::item:selected {{ background: {ACCENT}; color: {ON_ACCENT}; }}

QProgressBar {{ background: {SURFACE_ALT}; border: none; border-radius: {SP1 // 2}px; max-height: {SP1}px; min-height: {SP1}px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: {SP1 // 2}px; }}

QScrollBar:vertical {{ background: transparent; width: {SP1 + 2}px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: {SP1 // 2}px; min-height: {SP3}px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QDialog, QMessageBox, QInputDialog {{ background: {SURFACE}; }}
QLineEdit, QPlainTextEdit {{ background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px; padding: {SP1 - 2}px {SP1}px; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
"""


def build_settings_stylesheet() -> str:
    """Estilos EXTRAS da tela de Configurações (checkbox, spinbox, tabelas, selos, foco visível).

    Acrescente depois de ``build_stylesheet()``; não altera nada do gravador.
    """
    return f"""
QWidget#plain {{ background: transparent; }}
QWidget#page {{ background: {BG}; }}
QScrollArea {{ border: none; background: {BG}; }}
QFrame#nav {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QFrame#footer {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QFrame#card[changed="true"] {{ border-color: {ACCENT}; }}
QFrame#card[invalid="true"] {{ border-color: {ERROR}; }}

QLabel[role="badge"] {{ border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px; padding: 1px {SP1}px; font-size: {FONT_SIZE_SMALL}pt; }}
QLabel[role="badge"][state="ok"] {{ border-color: {OK}; }}
QLabel[role="badge"][state="warn"] {{ border-color: {WARN}; }}
QLabel[role="badge"][state="error"] {{ border-color: {ERROR}; }}
QLabel[role="badge"][state="accent"] {{ border-color: {ACCENT}; color: {ACCENT_HOVER}; }}
QLabel[role="field"] {{ font-weight: 600; }}
QLabel[role="section"] {{ font-size: {FONT_SIZE_TITLE}pt; font-weight: 600; }}

QCheckBox {{ background: transparent; spacing: {SP1}px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid {TEXT_MUTED}; border-radius: 4px; background: {SURFACE_ALT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT_HOVER}; }}
QCheckBox::indicator:disabled {{ border-color: {DISABLED_TEXT}; }}
QCheckBox::indicator:checked:disabled {{ background: {DISABLED_TEXT}; }}
QCheckBox::indicator:focus {{ border-color: {TEXT}; }}

QSpinBox, QDoubleSpinBox {{ background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
                           padding: {SP1 - 2}px {SP1}px; min-height: {SP3 - 2}px; min-width: 120px; }}
QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {DISABLED_TEXT}; }}
QLineEdit[readOnly="true"] {{ color: {TEXT_MUTED}; }}
QLineEdit[invalid="true"], QComboBox[invalid="true"], QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"] {{ border-color: {ERROR}; }}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus,
QListWidget:focus, QTableWidget:focus {{ border: 2px solid {ACCENT_HOVER}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_HOVER}; }}

QPushButton[capture="true"] {{ text-align: left; font-weight: 600; min-width: 200px; }}
QPushButton[capture="true"][capturing="true"] {{ border: 2px solid {WARN}; color: {WARN}; }}

QListWidget#nav {{ background: transparent; border: none; }}
QListWidget#nav::item {{ padding: {SP1 + 2}px {SP2}px; border-radius: {RADIUS_SM}px; }}
QListWidget#nav::item:selected {{ background: {ACCENT}; color: {ON_ACCENT}; }}

QTableWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px; gridline-color: {BORDER};
               selection-background-color: {ACCENT}; selection-color: {ON_ACCENT}; }}
QTableWidget QLineEdit {{ border-radius: 0; }}
QHeaderView::section {{ background: {SURFACE_ALT}; color: {TEXT}; border: none; border-bottom: 1px solid {BORDER}; padding: {SP1 - 2}px {SP1}px; font-weight: 600; }}
QTableCornerButton::section {{ background: {SURFACE_ALT}; border: none; }}
"""


def apply_theme(app: QApplication) -> None:
    """Aplica estilo Fusion, fonte Segoe UI e o stylesheet escuro ao aplicativo inteiro."""
    app.setStyle("Fusion")
    app.setFont(QFont(FONT_FAMILY, FONT_SIZE_BASE))
    app.setStyleSheet(build_stylesheet())
