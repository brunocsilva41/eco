"""Guarda contra o "piscar": nenhuma janela top-level solta ao abrir as Configurações e o lançador de telas sem console.

    venv\\Scripts\\python.exe -I -W error -m unittest tests.test_no_flash   (ou rodar o arquivo direto)
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["JARVIS_TEST_INSTANCE"] = "-unittest"


class NoFlash(unittest.TestCase):
    def test_gui_python_prefere_pythonw(self):
        from jarvis.win.spawn import gui_python
        exe = Path(gui_python())
        if (Path(sys.executable).with_name("pythonw.exe")).is_file():
            self.assertEqual(exe.name.lower(), "pythonw.exe")

    def test_set_shown_nao_promove_orfao_a_janela(self):
        from PySide6.QtWidgets import QApplication, QLabel, QWidget
        from jarvis.ui.kit.visibility import set_shown
        app = QApplication.instance() or QApplication([])
        lbl = QLabel("x")
        set_shown(lbl, True)
        self.assertFalse(lbl.isVisible(), "órfão não pode virar janela visível")
        host = QWidget()
        child = QLabel("y", host)
        set_shown(child, False)
        self.assertTrue(child.isHidden())
        set_shown(child, True)
        self.assertFalse(child.isHidden())
        del app

    def test_configuracoes_nao_criam_janelas_soltas(self):
        from PySide6.QtCore import QEvent, QObject, Qt, QTimer
        from PySide6.QtWidgets import QApplication, QWidget
        app = QApplication.instance() or QApplication([])
        from jarvis.ui.settings import app as sapp
        from jarvis.ui.settings.prefs import UiPrefs
        from jarvis.ui.theme import ThemeManager
        UiPrefs().apply_saved_theme()
        ThemeManager.instance().apply(app)
        stray: list[str] = []

        class Spy(QObject):
            def eventFilter(self, obj, ev):                                         # noqa: N802
                if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
                    kind = obj.windowFlags() & Qt.WindowType.WindowType_Mask
                    if kind not in (Qt.WindowType.Popup, Qt.WindowType.ToolTip) and type(obj).__name__ != "SettingsWindow":
                        stray.append(f"{type(obj).__name__}:{obj.objectName()}")
                return False

        spy = Spy()
        app.installEventFilter(spy)
        win = sapp.open_settings(open_section="geral")
        from jarvis.ui.settings.categories import CATEGORIES
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.2:
            app.processEvents()
        for cat in CATEGORIES:                     # percorre todas as páginas (montagem sob demanda)
            win.nav.set_current(cat.key)
            t1 = time.monotonic()
            while time.monotonic() - t1 < 0.25:
                app.processEvents()
        win.close()
        app.processEvents()
        app.removeEventFilter(spy)
        self.assertEqual(stray, [], f"janelas soltas mostradas: {stray[:8]} (total {len(stray)})")


if __name__ == "__main__":
    unittest.main()
