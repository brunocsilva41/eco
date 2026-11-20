"""Linha de comando do Jarvis.

    python -m jarvis run            # roda por voz (segure a tecla de falar)
    python -m jarvis run --text     # também aceita comandos digitados no terminal
    python -m jarvis doctor         # confere o ambiente
    python -m jarvis tools          # lista as ferramentas que o agente pode usar
    python -m jarvis config         # mostra a configuração efetiva
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
import threading

from .config import ConfigError, load


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _console_sink(app) -> None:
    """Mostra no terminal o que o Jarvis ouve, diz e faz (sem expor texto de log)."""
    def on_event(ev) -> None:
        d = ev.data
        if ev.kind == "transcript" and d.get("text"):
            _out(f"  você: {d['text']}")
        elif ev.kind == "reply_text":
            _out(f"  jarvis: {d['text']}")
        elif ev.kind == "action_step" and d.get("status") in ("ok", "error", "denied"):
            _out(f"  [{d['status']}] {d.get('tool')}: {d.get('result', d.get('text', ''))}")
        elif ev.kind == "confirm_request":
            _out(f"  ? CONFIRMAR: {d['text']}  (diga sim/não, Ctrl+Alt+Y / Ctrl+Alt+N, ou digite)")
        elif ev.kind == "emergency":
            _out("  !! PARADA DE EMERGÊNCIA")
        elif ev.kind == "error":
            _out(f"  erro ({d.get('where')}): {d.get('text')}")
    app.bus.subscribe(on_event)


def _stdin_reader(app, stop: threading.Event) -> None:
    for line in sys.stdin:
        if stop.is_set():
            return
        line = line.strip()
        if line.lower() in {"/sair", "/quit", "/exit"}:
            app.request_stop()
            return
        if line:
            app.submit_text(line)


def _cmd_run(args: argparse.Namespace) -> int:
    from .app import JarvisApp, StartupError
    cfg = load()
    app = JarvisApp(cfg)
    try:
        app.start()
    except StartupError as exc:
        _out(str(exc))
        _out("Rode `python -m jarvis doctor` para um diagnóstico completo.")
        return 2
    _console_sink(app)
    stop = threading.Event()
    if args.text:
        threading.Thread(target=_stdin_reader, args=(app, stop), name="stdin", daemon=True).start()
        _out("Modo texto: digite um comando e Enter. /sair encerra.")
    _out(f"Jarvis no ar. Segure {cfg.safety.talk_key.upper()} para falar; {cfg.safety.emergency_hotkey.upper()} para parar tudo; Ctrl+C encerra.")
    try:
        app.run()
    finally:
        stop.set()
        app.shutdown()
    return 0


def _cmd_doctor(_: argparse.Namespace) -> int:
    from .doctor import run_doctor
    cfg = load()
    results = run_doctor(cfg)
    for r in results:
        _out(f"[{'OK ' if r.ok else 'FALHA'}] {r.name}: {r.detail}")
    bad = [r for r in results if not r.ok]
    _out(f"\n{len(results) - len(bad)}/{len(results)} verificações ok." + (" Corrija as FALHAS acima." if bad else ""))
    return 1 if bad else 0


def _cmd_tools(_: argparse.Namespace) -> int:
    from .core.events import EventBus
    from .tools import builtin, notes
    from .tools.registry import ToolRegistry
    cfg = load()
    reg = ToolRegistry(cfg, EventBus())
    builtin.register_all(reg, cfg)
    notes.register(reg, cfg)
    for name in reg.names():
        spec = reg.get(name)
        _out(f"{name:24} risco={spec.risk.name:8} {spec.description}")
    return 0


def _cmd_config(_: argparse.Namespace) -> int:
    cfg = load()
    for sec in dataclasses.fields(cfg):
        val = getattr(cfg, sec.name)
        if dataclasses.is_dataclass(val):
            _out(f"[{sec.name}]")
            for f in dataclasses.fields(val):
                if f.name in {"launch", "hotkeys"}:
                    _out(f"  {f.name} = <{len(getattr(val, f.name))} itens>")
                else:
                    _out(f"  {f.name} = {getattr(val, f.name)}")
        else:
            _out(f"{sec.name} = {val}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis local (assistente de voz em pt-BR).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="roda o assistente")
    run.add_argument("--text", action="store_true", help="aceita também comandos digitados")
    run.set_defaults(fn=_cmd_run)
    sub.add_parser("doctor", help="confere o ambiente").set_defaults(fn=_cmd_doctor)
    sub.add_parser("tools", help="lista as ferramentas").set_defaults(fn=_cmd_tools)
    sub.add_parser("config", help="mostra a configuração efetiva").set_defaults(fn=_cmd_config)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except ConfigError as exc:
        _out(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
