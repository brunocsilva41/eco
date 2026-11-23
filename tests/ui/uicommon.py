"""Base dos testes de UI do Eco: ambiente ISOLADO (config.toml, QSettings e dados temporarios; nunca os reais),
resultados em JSON (um objeto por verificacao), contraste WCAG, deteccao de texto cortado/sobreposto.

Cada script de teste roda em UM processo por (escala, tema):

    venv\\Scripts\\python.exe -I tests\\ui\\test_settings.py --scale 150 --theme dark --out SAIDA [--native]

--native = plataforma Windows real (janela de verdade, SendInput); sem ele = offscreen (QT_QPA_PLATFORM=offscreen).
A escala vem de QT_SCALE_FACTOR (offscreen) e, no modo nativo, do fator Qt tambem (o DPI do monitor nao e alterado).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=100)
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--out", default=str(ROOT / "work" / "ui_qa"))
    ap.add_argument("--native", action="store_true")
    ap.add_argument("--only", default="")
    return ap.parse_args(argv)


def setup_env(args: argparse.Namespace) -> None:
    """Chamar ANTES de importar PySide6."""
    os.environ["QT_SCALE_FACTOR"] = str(args.scale / 100)
    if not args.native:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["JARVIS_QA"] = "1"
    if not args.native:
        os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")   # offscreen sem fontes = texto em quadrados
    os.environ["PYTHONUTF8"] = "1"


class Results:
    def __init__(self, suite: str, args: argparse.Namespace) -> None:
        self.suite, self.args = suite, args
        self.items: list[dict] = []
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.exceptions: list[str] = []
        _prev = sys.excepthook

        def hook(et, ev, tb) -> None:                       # excecao dentro de slot/evento do Qt: so imprime; aqui vira FALHA
            self.exceptions.append("".join(traceback.format_exception(et, ev, tb, limit=-4)).strip().replace(chr(10), " / ")[-420:])
            _prev(et, ev, tb)
        sys.excepthook = hook

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"[{'OK ' if ok else 'FALHA'}] {self.suite}:{name} {detail}", flush=True)
        return bool(ok)

    def guard(self, name: str):
        """Context manager: uma excecao vira FALHA (com traceback) e o teste continua."""
        res = self

        class _G:
            def __enter__(self_):
                return self_

            def __exit__(self_, et, ev, tb):
                if et is not None:
                    res.check(name, False, "EXCECAO " + "".join(traceback.format_exception_only(et, ev)).strip()
                              + " | " + traceback.format_exc(limit=-3).replace("\n", " / ")[-400:])
                    return True
                return False
        return _G()

    def save(self) -> Path:
        uniq = list(dict.fromkeys(self.exceptions))
        self.check("sem_excecoes_nos_slots_do_qt", not uniq, f"{len(self.exceptions)} excecao(oes): {' || '.join(uniq[:3])}")
        a = self.args
        tag = f"{self.suite}-{'nativo' if a.native else 'off'}-{a.scale}-{a.theme}"
        p = self.out / f"{tag}.json"
        p.write_text(json.dumps({"suite": self.suite, "scale": a.scale, "theme": a.theme, "native": a.native,
                                 "items": self.items}, ensure_ascii=False, indent=1), encoding="utf-8")
        bad = [i for i in self.items if not i["ok"]]
        print(f"== {tag}: {len(self.items) - len(bad)}/{len(self.items)} OK", flush=True)
        return p

    def failed(self) -> int:
        return sum(1 for i in self.items if not i["ok"])


# ------------------------------------------------------------------ contraste WCAG
def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def settle(ms: int = 250) -> None:
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.008)


# ------------------------------------------------------------------ app e janela isolada
def make_app(theme: str, motion: bool = True):
    from PySide6.QtWidgets import QApplication
    from jarvis.ui.theme import ThemeManager, set_motion_override
    app = QApplication.instance() or QApplication(sys.argv[:1])
    set_motion_override(motion)
    mgr = ThemeManager.instance()
    mgr.set_mode(theme)
    mgr.apply(app)
    return app


def tmp_env():
    from PySide6.QtCore import QSettings
    from jarvis.settings.store import SettingsStore
    from jarvis.ui.settings.prefs import UiPrefs
    tmp = Path(tempfile.mkdtemp(prefix="eco-uiqa-"))
    store = SettingsStore(tmp / "config.toml")
    cfg = store.defaults()
    cfg = dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, data=tmp / "data", logs=tmp / "logs"))
    prefs = UiPrefs(QSettings(str(tmp / "ui.ini"), QSettings.Format.IniFormat))
    return tmp, store, cfg, prefs


def grab(widget, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    widget.grab().save(str(path), "PNG")


# ------------------------------------------------------------------ texto cortado / sobreposto
def clipped_texts(root) -> list[str]:
    """Widgets visiveis cujo texto nao cabe na largura/altura (rotulos sem quebra, botoes, campos). Heuristica por
    QFontMetrics: so conta quando o texto real excede a area util em mais de 1 px."""
    from PySide6.QtWidgets import QAbstractButton, QLabel
    bad: list[str] = []
    for w in root.findChildren(QLabel) + root.findChildren(QAbstractButton):
        if not w.isVisibleTo(root) or w.width() <= 0:
            continue
        text = w.text() if hasattr(w, "text") else ""
        if not text or "<" in text:
            continue
        fm = w.fontMetrics()
        wrap = getattr(w, "wordWrap", lambda: False)()
        if wrap:
            avail = w.width()
            need = fm.boundingRect(0, 0, avail, 10000, 0x1000 | 0x0004, text).height()   # TextWordWrap | AlignLeft
            if need > w.height() + 2 and w.height() > 0 and w.maximumHeight() < 16777215:
                bad.append(f"{type(w).__name__}[{text[:40]!r}] altura {w.height()} < {need}")
        else:
            adv = fm.horizontalAdvance(text)
            if isinstance(w, QAbstractButton):
                adv += 8
            if adv > w.width() + 1 and w.width() < w.sizeHint().width() - 1 and w.minimumWidth() <= w.width():
                bad.append(f"{type(w).__name__}[{text[:40]!r}] largura {w.width()} < {adv}")
    return bad



# ------------------------------------------------------------------ entrada REAL com trava de seguranca
def hit_info(x: int, y: int) -> tuple[int, str]:
    """(pid, classe) da janela de nivel superior sob o pixel fisico (x, y)."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.WindowFromPoint.argtypes = (wintypes.POINT,)
    u.WindowFromPoint.restype = wintypes.HWND
    u.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    u.GetAncestor.restype = wintypes.HWND
    hwnd = u.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hwnd:
        return 0, ""
    root = u.GetAncestor(hwnd, 2) or hwnd
    pid = wintypes.DWORD(0)
    u.GetWindowThreadProcessId(root, ctypes.byref(pid))
    buf = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(root, buf, 128)
    return int(pid.value), buf.value


TRAY_CLASSES = ("Shell_TrayWnd", "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland", "#32768", "Shell_SecondaryTrayWnd")


_TARGET = None          # janela de teste a trazer de volta para cima quando outra janela a cobre


def set_target(win) -> None:
    global _TARGET
    _TARGET = win


def _reraise() -> None:
    if _TARGET is None:
        return
    try:
        import ctypes
        from ctypes import wintypes
        from jarvis.win import windows
        u = ctypes.windll.user32
        hwnd = wintypes.HWND(int(_TARGET.winId()))
        u.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
        u.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)     # HWND_TOPMOST, sem mover/redimensionar/ativar
        u.BringWindowToTop(hwnd)
        windows.focus_window(int(_TARGET.winId()))
        settle(200)
    except Exception:  # noqa: BLE001
        pass


def safe_click(x: int, y: int, button: str = "left", allow_classes: tuple[str, ...] = ()) -> None:
    """Clique REAL (SendInput) so se a janela sob o ponto for do PROPRIO processo de teste (ou de uma classe permitida,
    ex.: a bandeja). Se outra janela cobrir o ponto, traz a de teste de volta (ate 4 vezes); se nao der, recusa o clique."""
    from jarvis.win import input as winput
    for _ in range(4):
        pid, cls = hit_info(x, y)
        if pid == os.getpid() or cls in allow_classes:
            winput.click(x, y, button)
            return
        _reraise()
    raise RuntimeError(f"clique cancelado em ({x},{y}): ali esta outra janela (pid {pid}, classe {cls!r}), nao a de teste")


def safe_move(x: int, y: int) -> None:
    from jarvis.win import input as winput
    winput.move_to(x, y)


def raise_test_window(win) -> bool:
    """Deixa a janela de teste por cima de tudo e em foco (so a do teste)."""
    from PySide6.QtCore import Qt
    from jarvis.win import windows
    win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    win.show()
    win.raise_()
    settle(200)
    return bool(windows.focus_window(int(win.winId())))


def require_foreground() -> None:
    """Teclado real so e enviado se a janela em primeiro plano for deste processo de teste."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = wintypes.HWND
    hwnd = u.GetForegroundWindow()
    pid = wintypes.DWORD(0)
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if int(pid.value) != os.getpid():
        _reraise()
        hwnd = u.GetForegroundWindow()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if int(pid.value) != os.getpid():
        raise RuntimeError(f"teclado cancelado: o primeiro plano e de outro processo (pid {pid.value}), nao da janela de teste")


class OrphanProbe:
    """Detecta janelas SOLTAS: widget de nivel superior simples (tipo Qt.Window, sem titulo) que aparece (evento Show) durante um
    bloco. E o que acontece com ``setVisible(True)`` num widget sem pai: o Qt cria uma janela nativa que pisca na tela e custa
    ~14 ms no Windows (era a causa de abrir as Configuracoes em 3 s). Usa um filtro de eventos do aplicativo (nada de
    monkeypatch em QWidget, que derrubava o Qt)."""

    def __init__(self) -> None:
        self.hits: dict[str, int] = {}

    def __enter__(self):
        from PySide6.QtCore import QEvent, QObject, Qt
        from PySide6.QtWidgets import QApplication, QWidget
        probe = self

        class _F(QObject):
            def eventFilter(self, obj, ev):  # noqa: N802
                if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
                    if obj.windowType() == Qt.WindowType.Window and not obj.windowTitle():
                        text = getattr(obj, "text", lambda: "")() if hasattr(obj, "text") else ""
                        key = f"{type(obj).__name__}[{str(text)[:30]!r}]"
                        probe.hits[key] = probe.hits.get(key, 0) + 1
                return False
        self._filter = _F()
        QApplication.instance().installEventFilter(self._filter)
        return self

    def __exit__(self, *a):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().removeEventFilter(self._filter)
        return False

    def total(self) -> int:
        return sum(self.hits.values())


def wait_until(cond, timeout_s: float = 4.0, step_ms: int = 40) -> bool:
    """Roda o laco de eventos ate ``cond()`` ficar verdadeira (ou estourar o tempo). Evita esperas fixas que falham sob carga."""
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if cond():
            return True
        settle(step_ms)
    return bool(cond())
