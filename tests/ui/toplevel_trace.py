"""Diagnóstico: quem vira janela top-level 'solta' ao abrir as Configurações (a causa do piscar de janelinhas 'python').

Uso: venv\\Scripts\\python.exe -I tests\\ui\\toplevel_trace.py [segundos]
Instala um filtro de eventos no QApplication; todo widget que recebe Show sendo janela (isWindow) e NÃO sendo a janela
principal, popup nem tooltip legítimo é registrado com classe, texto/objectName, tamanho e a pilha de quem o criou
(capturada no momento da construção via QWidget.__init__ patch)."""
from __future__ import annotations

import collections
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("JARVIS_TEST_INSTANCE", "-trace")

from PySide6.QtCore import QEvent, QObject, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

created: dict[int, str] = {}
_orig = QWidget.__init__


def _init(self, *a, **k):
    _orig(self, *a, **k)
    try:
        st = [f for f in traceback.extract_stack(limit=14)[:-1] if "eco" in f.filename.lower() and "toplevel_trace" not in f.filename]
        created[id(self)] = " < ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in reversed(st[-4:]))
    except Exception:                                                          # noqa: BLE001
        pass


QWidget.__init__ = _init                                                       # type: ignore[method-assign]
hits: collections.Counter = collections.Counter()
detail: dict[tuple, str] = {}


class Spy(QObject):
    def eventFilter(self, obj, ev):                                            # noqa: N802
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            flags = obj.windowFlags()
            kind = flags & Qt.WindowType.WindowType_Mask
            if kind in (Qt.WindowType.Popup, Qt.WindowType.ToolTip):
                key = ("popup/tooltip", type(obj).__name__)
            else:
                txt = getattr(obj, "text", lambda: "")()
                key = (type(obj).__name__, str(txt)[:40] or obj.objectName(), obj.width(), obj.height(), obj.parent() is None)
            hits[key] += 1
            detail.setdefault(key, created.get(id(obj), "?"))
        return False


def main() -> int:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    what = sys.argv[2] if len(sys.argv) > 2 else "settings"          # settings | memory | record | setup
    app = QApplication.instance() or QApplication(sys.argv[:1])
    spy = Spy()
    app.installEventFilter(spy)
    QTimer.singleShot(int(secs * 1000), app.quit)
    if what == "settings":
        from jarvis.ui.settings import app as sapp
        from jarvis.ui.theme import ThemeManager
        from jarvis.ui.settings.prefs import UiPrefs
        UiPrefs().apply_saved_theme()
        ThemeManager.instance().apply(app)
        sapp.open_settings(open_section="geral")
        app.exec()
    else:
        import runpy
        entry = {"memory": ("jarvis.ui.memory_panel", "main_memory"), "record": ("jarvis.ui.recorder_window", "main_recorder"),
                 "setup": ("jarvis.setup.wizard", "main_wizard")}[what]
        import importlib
        mod = importlib.import_module(entry[0])
        fn = getattr(mod, entry[1], None)
        if fn is None:
            print("sem função", entry, [n for n in dir(mod) if n.startswith("main")])
            return 2
        try:
            fn()
        except SystemExit:
            pass
    print("janelas top-level mostradas (exceto a principal):", sum(v for k, v in hits.items() if k[0] != "SettingsWindow"))
    for k, v in hits.most_common(40):
        print(f"{v:4d}  {k}  <- {detail[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
