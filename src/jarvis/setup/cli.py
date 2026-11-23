"""Subcomando `Eco.cmd setup`: assistente em Qt (padrão) e modos sem janela para o instalador e para scripts.

    Eco.cmd setup                          abre o assistente (continua de onde parou)
    Eco.cmd setup --repair                 abre como "Reparar/Reconfigurar"
    Eco.cmd setup --fetch [--components vision,voice,stt_small]
                                              baixa e confere os modelos, sem janela (usado pelo instalador)
    Eco.cmd setup --offline PASTA_OU_ZIP   importa modelos de um pacote offline (confere o SHA-256)
    Eco.cmd setup --make-pack PASTA        cria um pacote offline a partir dos modelos já instalados
    Eco.cmd setup --scan [--deep] [--use-found]
                                              procura modelos que você JÁ TEM no PC (pastas comuns; --deep = discos inteiros);
                                              --use-found confere o SHA-256 e liga/copia para a instalação
    Eco.cmd setup --status                 mostra o estado dos arquivos de modelo
    Eco.cmd setup --capture PASTA          (desenvolvimento) grava PNG de todas as telas, offscreen
Códigos de saída: 0 ok, 2 uso/arquivo, 3 sem internet, 4 falha de download/integridade, 5 disco cheio, 130 cancelado.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import ROOT
from .download import DownloadError, Downloader, Progress, import_offline, make_offline_pack, verify_file
from .manifest import human_bytes, human_eta, load_manifest, quick_present
from .state import DEFAULT_COMPONENTS, SetupState, read_install_info

_EXIT = {"offline": 3, "http": 4, "hash": 4, "disk": 5, "cancelled": 130, "io": 2}


def _out(text: str = "") -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _components(arg: str | None, root: Path) -> list[str]:
    if arg:
        return [c.strip() for c in arg.split(",") if c.strip()]
    info = read_install_info(root)
    if isinstance(info.get("components"), list) and info["components"]:
        return [c for c in info["components"] if isinstance(c, str)]
    st = SetupState.load(root)
    return st.components or list(DEFAULT_COMPONENTS)


def _progress_printer():
    last = {"t": 0.0, "name": ""}

    def cb(p: Progress) -> None:
        import time
        now = time.monotonic()
        if p.phase == "pronto" and p.file:
            _out(f"  ok: {p.file}")
            return
        if now - last["t"] < 2.0 and p.file == last["name"]:
            return
        last["t"], last["name"] = now, p.file
        pct = 100 * p.overall_done / max(p.overall_total, 1)
        speed = f"{human_bytes(p.speed)}/s, faltam {human_eta(p.eta)}" if p.speed > 1 else p.phase
        _out(f"  {p.file}: {pct:.0f}% ({human_bytes(p.overall_done)}/{human_bytes(p.overall_total)}) {speed}")
    return cb


def _adopt_existing(entries, root: Path, deep: bool = False, use: bool = True) -> int:
    """Procura os modelos que faltam no PC e (se `use`) traz os que conferem. Devolve quantos faltam depois."""
    from . import discover
    missing = [e for e in entries if not quick_present(e, root)]
    if not missing:
        return 0
    _out(f"Procurando {len(missing)} arquivo(s) de modelo que você já possa ter no computador" + (" (discos inteiros, pode demorar)..." if deep else "..."))
    found = discover.scan(missing, deep=deep, install_root=root)
    for e in missing:
        for c in found.get(e.path, [])[:1]:
            _out(f"  achei: {Path(e.path).name} -> {c}")
    if not found:
        _out("  nenhum modelo existente encontrado.")
        return len(missing)
    if not use:
        return len(missing) - len(found)
    imported, still, copied = discover.import_found(found, missing, root, _progress_printer())
    for p in imported:
        _out(f"  usado: {p}" + (" (copiado)" if p in copied else " (ligado, sem espaço extra)"))
    return len(still)


def cmd_scan_folder(components: list[str], root: Path, folder: Path, use: bool) -> int:
    from . import discover
    from .config_io import apply_stt_choice
    man = load_manifest(root)
    entries = man.files_for(components)
    if not folder.is_dir():
        _out(f"ERRO: a pasta não existe: {folder}")
        return 2
    _out(f"Examinando {folder} e conferindo o SHA-256 dos candidatos...")
    report, valid, sigs = discover.inspect_folder(folder, entries, None, _progress_printer(), root)
    ok = 0
    for f in report:
        if f.status == "ok":
            ok += 1
            _out(f"  [UTILIZÁVEL] {f.name} ({human_bytes(f.size)}) -> {f.path}")
        elif f.status == "hash":
            _out(f"  [DIFERENTE ] {f.name}: mesmo tamanho, conteúdo diferente ({f.path}); não serve")
        else:
            _out(f"  [AUSENTE   ] {f.name}")
    _out(f"{ok} de {len(report)} arquivo(s) dessa pasta podem ser usados.")
    if use and valid:
        imported, still, copied = discover.import_found(valid, entries, root, _progress_printer(), None, sigs)
        for p in imported:
            _out(f"  usado: {p}" + (" (copiado)" if p in copied else " (ligado, sem espaço extra)"))
        if not still and root == ROOT:
            apply_stt_choice(components, man)
    return 0 if ok else 4


def cmd_scan(components: list[str], root: Path, deep: bool, use: bool) -> int:
    from .config_io import apply_stt_choice
    man = load_manifest(root)
    entries = man.files_for(components)
    left = _adopt_existing(entries, root, deep, use)
    if use and not left:
        if root == ROOT:                                          # --root é só para teste: não mexe na configuração real
            apply_stt_choice(components, man)
        _out("Todos os modelos já estavam no PC e foram conferidos (SHA-256).")
    elif left:
        _out(f"{left} arquivo(s) ainda faltam (use --fetch para baixar só o que falta).")
    return 0 if not left else 4


def cmd_fetch(components: list[str], root: Path) -> int:
    from .config_io import apply_stt_choice
    man = load_manifest(root)
    entries = man.files_for(components)
    _adopt_existing(entries, root, deep=False, use=True)          # aproveita o que já existe antes de baixar
    _out(f"Baixando/conferindo {len(entries)} arquivo(s), {human_bytes(sum(e.size for e in entries))} no total...")
    try:
        Downloader(root, _progress_printer()).fetch_all(entries)
    except DownloadError as exc:
        _out(f"ERRO ({exc.kind}): {exc.message}")
        return _EXIT.get(exc.kind, 4)
    apply_stt_choice(components, man)
    _out("Modelos prontos e conferidos (SHA-256).")
    return 0


def cmd_offline(src: Path, components: list[str], root: Path) -> int:
    man = load_manifest(root)
    entries = man.files_for(components)
    try:
        done, missing = import_offline(src, entries, root, _progress_printer())
    except DownloadError as exc:
        _out(f"ERRO: {exc.message}")
        return _EXIT.get(exc.kind, 2)
    for p in done:
        _out(f"  importado: {p}")
    for p in missing:
        _out(f"  NÃO encontrado no pacote: {p}")
    from .config_io import apply_stt_choice
    if not missing:
        apply_stt_choice(components, man)
    return 0 if not missing else 4


def cmd_status(components: list[str], root: Path) -> int:
    man = load_manifest(root)
    bad = 0
    for e in man.files_for(components):
        ok = quick_present(e, root)
        bad += 0 if ok else 1
        _out(f"[{'OK ' if ok else 'FALTA'}] {e.path} ({human_bytes(e.size)})")
    return 1 if bad else 0


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--repair", action="store_true", help="abre como Reparar/Reconfigurar")
    ap.add_argument("--fetch", action="store_true", help="baixa e confere os modelos, sem janela")
    ap.add_argument("--components", default=None, help="lista separada por vírgula (vision,voice,stt_small,stt_base)")
    ap.add_argument("--offline", metavar="PASTA_OU_ZIP", help="importa modelos de um pacote offline")
    ap.add_argument("--make-pack", metavar="PASTA", help="cria um pacote offline com os modelos instalados")
    ap.add_argument("--scan", action="store_true", help="procura modelos que você já tem no PC")
    ap.add_argument("--deep", action="store_true", help="com --scan: procura nos discos inteiros")
    ap.add_argument("--folder", metavar="PASTA", help="com --scan: examina só esta pasta e diz o que dá para usar")
    ap.add_argument("--use-found", action="store_true", help="com --scan: confere e traz os modelos achados")
    ap.add_argument("--status", action="store_true", help="mostra o estado dos modelos")
    ap.add_argument("--capture", metavar="PASTA", help="(dev) grava PNG de todas as telas, offscreen")
    ap.add_argument("--theme", default="dark", choices=("dark", "light"))
    ap.add_argument("--root", default=None, help=argparse.SUPPRESS)


def run_setup(ns: argparse.Namespace) -> int:
    root = Path(ns.root) if ns.root else ROOT
    if ns.fetch:
        return cmd_fetch(_components(ns.components, root), root)
    if ns.offline:
        return cmd_offline(Path(ns.offline), _components(ns.components, root), root)
    if ns.make_pack:
        man = load_manifest(root)
        done = make_offline_pack(Path(ns.make_pack), man.files_for(list(man.components)), root)
        _out(f"Pacote offline com {len(done)} arquivo(s) em {ns.make_pack}")
        return 0 if done else 2
    if ns.scan and ns.folder:
        return cmd_scan_folder(_components(ns.components, root), root, Path(ns.folder), ns.use_found)
    if ns.scan:
        return cmd_scan(_components(ns.components, root), root, ns.deep, ns.use_found)
    if ns.status:
        return cmd_status(_components(ns.components, root), root)
    if ns.capture:
        from .capture import run_capture
        return run_capture(Path(ns.capture), ns.theme)
    from .wizard import main_wizard
    return main_wizard(repair=ns.repair)


def main_setup(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="eco setup", description="Assistente de configuração do Eco.")
    add_arguments(ap)
    return run_setup(ap.parse_args(argv))
