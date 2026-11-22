"""Processo FILHO da Ilha (`Jarvis.cmd island --child`): janela Qt + leitura dos eventos do núcleo por stdin.

Protocolo em `link.py`. Os eventos viram chamadas diretas de um barramento LOCAL minimo (`_DirectBus`: sem threads,
sem importar o EventBus do núcleo) e a `IslandBridge` de sempre os aplica na janela (o mesmo caminho do demo). Os
níveis de áudio (30 Hz) vão direto para o `LevelFeed`. O filho encerra quando o stdin fecha (o Jarvis morreu ou
encerrou) ou quando recebe `quit`. Nada além do protocolo é escrito no stdout (o `print` acidental vai para o stderr).

Leve de propósito: só QtCore/QtGui/QtWidgets, sem numpy, sem ThemeManager.apply (stylesheet), prioridade
BELOW_NORMAL, e a janela fica OCULTA (zero timers) enquanto não há o que mostrar.
"""
from __future__ import annotations

import json
import sys
import threading
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from . import winapi
from .bridge import IslandBridge
from .window import IslandWindow

_EVENTS = frozenset({"state", "transcript", "reply_text", "action_step", "confirm_request", "confirm_done",
                     "context_usage", "yolo", "mute", "emergency", "error", "mode", "config"})


class _Quit(QObject):
    requested = Signal()


class _DirectBus:
    """Barramento minimo: ``publish`` chama os assinantes na thread de quem publica (a thread de leitura do stdin)."""

    def __init__(self) -> None:
        self._subs: list[Any] = []

    def subscribe(self, fn):  # type: ignore[no-untyped-def]
        self._subs.append(fn)
        return lambda: self._subs.remove(fn) if fn in self._subs else None

    def publish(self, kind: str, **data: Any) -> None:
        ev = SimpleNamespace(kind=kind, data=data)
        for fn in list(self._subs):
            fn(ev)

    def close(self) -> None:
        self._subs.clear()


def main_island_child() -> int:
    out = sys.stdout.buffer                       # canal do protocolo
    sys.stdout = sys.stderr                       # qualquer print acidental não corrompe o protocolo
    lock = threading.Lock()
    winapi.lower_priority()

    def send(msg: dict[str, Any]) -> None:
        line = (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with lock:
            try:
                out.write(line)
                out.flush()
            except (OSError, ValueError):
                _quit.requested.emit()            # o pai sumiu

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    _quit = _Quit()
    _quit.requested.connect(app.quit)

    bus = _DirectBus()
    win = IslandWindow()
    bridge = IslandBridge(
        win, bus,
        on_confirm_answer=lambda rid, yes: send({"c": "confirm", "id": rid, "yes": bool(yes)}),
        on_stop=lambda: send({"c": "stop"}),
        on_mute=lambda on: send({"c": "mute", "on": bool(on)}))
    win.settings_requested.connect(lambda section: send({"c": "settings", "section": section}))
    win.start()                                   # escondida: só a zona do topo (se ligada); nada pinta
    send({"c": "ready"})

    def reader() -> None:
        try:
            for raw in sys.stdin.buffer:
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                    kind, d = msg.get("k"), msg.get("d") or {}
                except (ValueError, AttributeError):
                    continue
                try:
                    if kind == "level":
                        bridge.feed.on_level("mic", float(d.get("mic", 0.0)))
                        bridge.feed.on_level("tts", float(d.get("tts", 0.0)))
                    elif kind == "quit":
                        break
                    elif kind in _EVENTS and isinstance(d, dict):
                        bus.publish(kind, **d)
                except (TypeError, ValueError):
                    continue
        except (OSError, ValueError):
            pass
        _quit.requested.emit()                    # EOF: o Jarvis acabou -> a Ilha também

    threading.Thread(target=reader, name="island-stdin", daemon=True).start()
    code = app.exec()
    bridge.close()
    bus.close()
    return int(code)
