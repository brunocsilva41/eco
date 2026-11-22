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
import os
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
                     "context_usage", "yolo", "mute", "emergency", "error", "mode", "config", "listen_mode", "pin"})


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


class _TraySig(QObject):
    """Cruza os eventos da thread de leitura do stdin para a thread da UI (a bandeja e widget Qt)."""
    event = Signal(str, object)


def _find_action(menu, text: str):  # type: ignore[no-untyped-def]
    for a in menu.actions():
        if a.text() == text:
            return a
        sub = a.menu()
        if sub is not None:
            r = _find_action(sub, text)
            if r is not None:
                return r
    return None


def build_tray(app, send, win):  # type: ignore[no-untyped-def]
    """Liga o icone da bandeja (``ui/tray.py``). ``win`` None = modo so-bandeja (sem janela da Ilha). Devolve (tray, sig)."""
    from ..tray import TrayController
    from ...core import updates
    from dataclasses import replace
    from .bridge import _STATE
    from . import tokens as T

    cbs: dict[str, Any] = {
        "settings": lambda: send({"c": "settings", "section": "general"}),
        "quit": lambda: send({"c": "quit"}),
        "set_listen_mode_toggle": lambda on: send({"c": "listen_mode", "mode": "open" if on else "push"}),
        "set_mute": lambda on: send({"c": "mute", "on": bool(on)}),
    }
    if win is not None:
        def set_position(mode: str) -> None:
            win.apply_config(replace(win.cfg, mode=mode, pinned=win.pinned))
            send({"c": "ui_mode", "mode": mode})
        cbs.update({"reveal": win.reveal, "toggle_visible": win.toggle_visible, "toggle_pin": win.set_pinned,
                    "set_size": win.set_size_name, "set_position": set_position})
    tray = TrayController(app, version=updates.current_version(), callbacks=cbs, check_updates=updates.check)
    sig = _TraySig()
    st = {"muted": False, "yolo": False, "state": "idle"}

    def on_event(kind: str, d: Any) -> None:
        if kind == "state":
            st["state"] = str(d.get("state", "idle"))
        elif kind == "mute":
            st["muted"] = bool(d.get("muted"))
        elif kind == "yolo":
            st["yolo"] = bool(d.get("on"))
        elif kind == "listen_mode":
            tray.set_open_listening(str(d.get("mode")) == "open")
        label = T.state_label(_STATE.get(st["state"], T.IslandState.IDLE)) + (" · YOLO" if st["yolo"] else "")
        tray.set_status(label, muted=st["muted"], listening=st["state"] == "listening")

    sig.event.connect(on_event)
    if win is not None:
        win.pin_toggled.connect(lambda on: _sync_pin(tray, on))
    tray.show()
    return tray, sig


def _sync_pin(tray, on: bool) -> None:  # type: ignore[no-untyped-def]
    a = _find_action(tray._menu, "Fixar na tela")
    if a is not None:
        a.blockSignals(True)
        a.setChecked(bool(on))
        a.blockSignals(False)


def main_island_child(tray_only: bool = False) -> int:
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
    win = None if tray_only else IslandWindow()
    bridge = None
    if win is not None:
        bridge = IslandBridge(
            win, bus,
            on_confirm_answer=lambda rid, yes: send({"c": "confirm", "id": rid, "yes": bool(yes)}),
            on_stop=lambda: send({"c": "stop"}),
            on_mute=lambda on: send({"c": "mute", "on": bool(on)}))
        win.settings_requested.connect(lambda section: send({"c": "settings", "section": section}))
        win.pin_toggled.connect(lambda on: send({"c": "pin", "on": bool(on)}))
        win.listen_toggled.connect(lambda mode: send({"c": "listen_mode", "mode": mode}))
        win.start()                               # escondida: só a zona do topo (se ligada); nada pinta
    tray = tray_sig = None
    if os.environ.get("JARVIS_NO_TRAY") != "1":
        try:
            tray, tray_sig = build_tray(app, send, win)
        except Exception:  # noqa: BLE001 - a bandeja nunca derruba a Ilha
            print("falha ao criar a bandeja", file=sys.stderr)
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
                        if bridge is not None:
                            bridge.feed.on_level("mic", float(d.get("mic", 0.0)))
                            bridge.feed.on_level("tts", float(d.get("tts", 0.0)))
                    elif kind == "quit":
                        break
                    elif kind in _EVENTS and isinstance(d, dict):
                        if tray_sig is not None and kind in ("state", "mute", "yolo", "listen_mode"):
                            tray_sig.event.emit(kind, d)
                        if bridge is not None:
                            bus.publish(kind, **d)
                except (TypeError, ValueError):
                    continue
        except (OSError, ValueError):
            pass
        _quit.requested.emit()                    # EOF: o Jarvis acabou -> a Ilha também

    threading.Thread(target=reader, name="island-stdin", daemon=True).start()
    code = app.exec()
    if tray is not None:
        tray.hide()
    if bridge is not None:
        bridge.close()
    bus.close()
    return int(code)
