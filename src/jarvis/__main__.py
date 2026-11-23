"""Linha de comando do Eco.

    python -m jarvis run            # roda por voz (segure a tecla de falar)
    python -m jarvis run --text     # também aceita comandos digitados no terminal
    python -m jarvis settings       # tela de Configurações
    python -m jarvis record         # gravador de voz ("Minha voz")
    python -m jarvis memory         # o que o Eco sabe de mim (memórias e conversas)
    python -m jarvis island-demo    # Ilha do Eco (prototipo visual, estados automaticos)
    python -m jarvis doctor         # confere o ambiente
    python -m jarvis tools          # lista as ferramentas que o agente pode usar
    python -m jarvis config         # mostra a configuração efetiva
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
import threading

from .win import dpi

dpi.ensure_per_monitor_v2()          # PRIMEIRO: antes de qualquer import que use janelas/captura/coordenadas

from .config import ConfigError, load  # noqa: E402


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _console_sink(app) -> None:
    """Mostra no terminal o que o Eco ouve, diz e faz (sem expor texto de log)."""
    def on_event(ev) -> None:
        d = ev.data
        if ev.kind == "transcript" and d.get("text"):
            _out(f"  você: {d['text']}")
        elif ev.kind == "reply_text":
            _out(f"  eco: {d['text']}")
        elif ev.kind == "action_step" and d.get("status") in ("ok", "error", "denied"):
            detail = d.get("result") or d.get("text", "")
            _out(f"  [{d['status']}] {d.get('tool')}: {detail}")
        elif ev.kind == "confirm_request":
            _out(f"  ? CONFIRMAR: {d['text']}  (diga sim/não, Ctrl+Alt+Y / Ctrl+Alt+N, ou digite)")
        elif ev.kind == "yolo":
            _out(f"  !! {d.get('text')} (confirmações {'DESLIGADAS' if d.get('on') else 'de volta'})")
        elif ev.kind == "emergency":
            _out("  !! PARADA DE EMERGÊNCIA")
        elif ev.kind == "notice":
            _out(f"  ! {d.get('text')}")
        elif ev.kind == "config_applied":
            _out(f"  configuração aplicada; aguardam reinício: {', '.join(d.get('restart', [])) or 'nenhuma'}")
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
    if not stop.is_set():                    # fim da entrada (terminal fechado / processo pai morreu): não deixa o Eco órfão segurando GPU e RAM
        app.request_stop()


def _cmd_run(args: argparse.Namespace) -> int:
    from .app import JarvisApp, StartupError
    cfg = load()
    app = JarvisApp(cfg)
    try:
        app.start()
    except StartupError as exc:
        _out(str(exc))
        _out("Rode `Eco.cmd doctor` para um diagnóstico completo.")
        return 2
    except KeyboardInterrupt:
        _out("Interrompido durante a partida.")
        return 130
    _console_sink(app)
    stop = threading.Event()
    if args.text:
        threading.Thread(target=_stdin_reader, args=(app, stop), name="stdin", daemon=True).start()
        _out("Modo texto: digite um comando e Enter. /sair encerra.")
    _out(f"Eco no ar. {cfg.safety.talk_key.upper()} para falar; {cfg.safety.emergency_hotkey.upper()} para parar tudo; Ctrl+C encerra.")
    code = 0
    try:
        code = app.run()
    finally:
        stop.set()
        app.shutdown()
    return code


def _cmd_settings(ns: argparse.Namespace) -> int:
    from .ui.settings_window import main_settings
    if ns.open_section:
        return main_settings(open_section=ns.open_section)
    return main_settings()


def _cmd_memory(_: argparse.Namespace) -> int:
    from .ui.memory_panel import main_memory
    return main_memory()


def _cmd_terminal(_: argparse.Namespace) -> int:
    from .ui.terminal import main_terminal
    return main_terminal()


def _cmd_record(_: argparse.Namespace) -> int:
    from .ui.recorder_window import main_recorder
    return main_recorder(load())


def _cmd_island_demo(args: argparse.Namespace) -> int:
    from .ui.island.demo import main_island_demo
    return main_island_demo(capture=args.capture, seconds=args.seconds, measure_s=args.measure,
                            reduce_motion=args.reduce_motion, mode=args.mode, opacity=args.opacity,
                            pinned=args.pinned, listen=args.listen, autohide=args.autohide)


def _cmd_island(args: argparse.Namespace) -> int:
    """Subcomando INTERNO: o Eco lança `island --child` como processo filho (pipes JSON; ver ui/island/link.py)."""
    if not args.child:
        _out("A Ilha roda sozinha junto com `Eco.cmd run`. Para ver a demonstração: `Eco.cmd island-demo`.")
        return 2
    from .ui.island.child import main_island_child
    return main_island_child(tray_only=bool(getattr(args, 'tray_only', False)))


def _cmd_doctor(ns: argparse.Namespace) -> int:
    from .doctor import run_doctor
    cfg = load()
    if getattr(ns, "full", False) and (getattr(ns, "json", False) or getattr(ns, "out", "")):
        from .setup import prereqs
        from .setup.manifest import load_manifest
        from .setup.state import SetupState
        items = prereqs.full_scan(cfg.paths.root, load_manifest(cfg.paths.root), list(SetupState.load(cfg.paths.root).components), cfg=cfg)
        text = prereqs.full_report_json(items) if ns.json else prereqs.full_report_text(items)
        if ns.out:
            from pathlib import Path
            Path(ns.out).write_text(text, encoding="utf-8")
            _out(f"Relatório salvo em {ns.out}")
        else:
            _out(text)
        return 1 if prereqs.blocking(items) else 0
    results = run_doctor(cfg, full=getattr(ns, "full", False))
    for r in results:
        _out(f"[{'OK ' if r.ok else 'FALHA'}] {r.name}: {r.detail}")
    bad = [r for r in results if not r.ok]
    _out(f"\n{len(results) - len(bad)}/{len(results)} verificações ok." + (" Corrija as FALHAS acima." if bad else ""))
    return 1 if bad else 0


_RISK = {0: "leitura", 1: "controla", 2: "ARRISCADA"}


def _cmd_setup(ns: argparse.Namespace) -> int:
    from .setup.cli import run_setup
    return run_setup(ns)


def _cmd_tools(_: argparse.Namespace) -> int:
    from .tools.catalog import describe_tools
    for t in describe_tools(load()):
        state = "" if t.enabled else " (desligada)"
        _out(f"{t.name:24} {_RISK[t.risk]:9}{state} {t.description}")
    return 0


def _cmd_config(_: argparse.Namespace) -> int:
    cfg = load()
    for sec in dataclasses.fields(cfg):
        val = getattr(cfg, sec.name)
        if dataclasses.is_dataclass(val):
            _out(f"[{sec.name}]")
            for f in dataclasses.fields(val):
                v = getattr(val, f.name)
                _out(f"  {f.name} = " + (f"<{len(v)} itens>" if isinstance(v, (dict, tuple)) and len(v) > 6 else str(v)))
        else:
            _out(f"{sec.name} = {val}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eco", description="Eco local (assistente de voz em pt-BR).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="roda o assistente")
    run.add_argument("--text", action="store_true", help="aceita também comandos digitados")
    run.set_defaults(fn=_cmd_run)
    sp = sub.add_parser("settings", help="tela de Configurações")
    sp.add_argument("--open", dest="open_section", default=None, help="abre já numa seção (ex.: permissions)")
    sp.set_defaults(fn=_cmd_settings)
    sub.add_parser("record", help="gravador de voz (Minha voz)").set_defaults(fn=_cmd_record)
    sub.add_parser("memory", help="o que o Eco sabe de mim (memórias e conversas)").set_defaults(fn=_cmd_memory)
    sub.add_parser("terminal", help="painel do terminal integrado (comandos, saída, parar, copiar)").set_defaults(fn=_cmd_terminal)
    isl = sub.add_parser("island-demo", help="Ilha do Eco: demonstração visual com áudio de teste")
    isl.add_argument("--seconds", type=float, default=0.0, help="fecha sozinha depois de N segundos")
    isl.add_argument("--capture", metavar="PASTA", help="grava PNG por tamanho e estado (offscreen)")
    isl.add_argument("--measure", type=float, default=0.0, metavar="S", help="mede CPU/RAM, S segundos por fase")
    isl.add_argument("--reduce-motion", action="store_true", help="simula 'reduzir animações'")
    isl.add_argument("--mode", default="docked", choices=("docked", "floating", "dock_right", "dock_left"), help="posição da Ilha")
    isl.add_argument("--opacity", type=float, default=0.92, help="opacidade do fundo 0.35..1.0")
    isl.add_argument("--pinned", action="store_true", help="começa fixada (alfinete)")
    isl.add_argument("--listen", action="store_true", help="começa com a escuta aberta ligada")
    isl.add_argument("--autohide", action="store_true", help="esconde sozinha (como no app)")
    isl.set_defaults(fn=_cmd_island_demo)
    ic = sub.add_parser("island", help="interno: processo filho da Ilha (lançado pelo Eco)")
    ic.add_argument("--child", action="store_true", help="modo filho (protocolo JSON em stdin/stdout)")
    ic.add_argument("--tray-only", action="store_true", help="so o icone da bandeja (sem janela da Ilha)")
    ic.set_defaults(fn=_cmd_island)
    dp = sub.add_parser("doctor", help="confere o ambiente (--full: varredura total das ferramentas e do PC)")
    dp.add_argument("--full", action="store_true", help="varredura total: versão, onde foi achado e o que fazer em cada ferramenta")
    dp.add_argument("--json", action="store_true", help="com --full: relatório em JSON")
    dp.add_argument("--out", default="", help="com --full: grava o relatório neste arquivo (texto, ou JSON com --json)")
    dp.set_defaults(fn=_cmd_doctor)
    su = sub.add_parser("setup", help="assistente de configuração (--repair, --fetch, --offline, --status)")
    from .setup.cli import add_arguments as _setup_args
    _setup_args(su)
    su.set_defaults(fn=_cmd_setup)
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
