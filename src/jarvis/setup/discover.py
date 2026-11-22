"""Procura modelos que o usuário JÁ TEM no computador e os traz para a instalação, sem baixar de novo.

Como acha: indexa os arquivos pelo TAMANHO (só os tamanhos que o manifesto pede), prefere o mesmo nome de arquivo e
confere o SHA-256 antes de aceitar (um arquivo de mesmo tamanho que não bate é ignorado). Como traz: link físico
(instantâneo, não ocupa espaço extra; só no mesmo disco NTFS) e, se não der, cópia verificada.
Nada é movido nem apagado na origem.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from .download import CHUNK, DownloadError, Progress, ProgressCb, verify_file
from .manifest import FileEntry
from .state import mark_verified

log = logging.getLogger(__name__)

SKIP_DIRS = {"windows", "$recycle.bin", "system volume information", "node_modules", ".git", "__pycache__", "winsxs",
             "$windows.~bt", "$windows.~ws", "windowsapps", "recovery", "config.msi", "msocache", "installer", "temp", "tmp",
             "site-packages", "venv", ".venv", "uvcache", "npm-cache", ".npm", ".nuget", "pkgs", "conda", "miniconda3", "anaconda3"}
LIKELY = ("jarvis", "model", "whisper", "llama", "gguf", "piper", "silero", "huggingface", "lmstudio", "ollama")
PER_ROOT_SECONDS = 12.0           # nenhuma pasta enorme esgota o orçamento das outras
QUICK_MAX_FILES = 600_000
QUICK_MAX_SECONDS = 90.0
DEEP_MAX_SECONDS = 600.0
ScanCb = Callable[[int, str], None]


def _fixed_drives() -> list[Path]:
    import ctypes
    out: list[Path] = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()                      # type: ignore[attr-defined]
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:         # type: ignore[attr-defined]  DRIVE_FIXED
                out.append(Path(root))
    return out


def _previous_install_dirs() -> list[Path]:
    """Instalações anteriores do Jarvis registradas no Windows (Inno Setup grava InstallLocation em Uninstall)."""
    found: list[Path] = []
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")
            except OSError:
                continue
            with key:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    if "jarvis" not in name.lower():
                        continue
                    try:
                        with winreg.OpenKey(key, name) as sub:
                            loc = winreg.QueryValueEx(sub, "InstallLocation")[0]
                        if loc:
                            found.append(Path(loc))
                    except OSError:
                        continue
    except ImportError:
        pass
    return found


def candidate_roots(extra: Iterable[Path] = ()) -> list[Path]:
    """Pastas onde modelos costumam estar (busca rápida, com profundidade limitada)."""
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    roots: list[Path] = [Path(p) for p in extra]
    env = os.environ.get("JARVIS_MODELS")
    if env:
        roots.append(Path(env))
    roots += _previous_install_dirs()
    roots += [home / "Downloads", home / "Documents", home / "Desktop", home / ".cache" / "huggingface", home / ".lmstudio",
              home / ".ollama", home / "models", local / "Programs" / "Jarvis", local / "Jarvis",
              Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))) / "Jarvis",
              Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Jarvis"]
    for drive in _fixed_drives():
        roots += [drive / "Jarvis", drive / "models", drive / "Models", drive / "Modelos", drive / "IA", drive / "AI",
                  drive / "Jarvis-Modelos", drive / "LLM", drive / "llm"]
        try:                                                                 # primeiro nível: qualquer pasta cujo nome lembra Jarvis/modelos
            for e in os.scandir(drive):
                n = e.name.lower()
                if e.is_dir(follow_symlinks=False) and n not in SKIP_DIRS and any(k in n for k in ("jarvis", "model", "whisper", "llama", "gguf", "piper")):
                    roots.append(Path(e.path))
        except OSError:
            continue
    uniq: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        k = str(r).lower()
        if k not in seen and r.is_dir():
            seen.add(k)
            uniq.append(r)
    uniq.sort(key=lambda p: 0 if any(w in str(p).lower() for w in LIKELY) else 1)      # as mais prováveis primeiro (sort estável)
    return uniq


def _walk(root: Path, wanted_sizes: set[int], hits: dict[int, list[Path]], counter: list[int], deadline: float,
          max_files: int, max_depth: int, cancel: threading.Event, cb: ScanCb | None) -> None:
    stack: list[tuple[str, int]] = [(str(root), 0)]
    while stack:
        if cancel.is_set() or time.monotonic() > deadline or counter[0] > max_files:
            return
        cur, depth = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if depth < max_depth and e.name.lower() not in SKIP_DIRS:
                                stack.append((e.path, depth + 1))
                        elif e.is_file(follow_symlinks=False):
                            counter[0] += 1
                            size = e.stat(follow_symlinks=False).st_size
                            if size in wanted_sizes:
                                hits.setdefault(size, []).append(Path(e.path))
                    except OSError:
                        continue
        except OSError:
            continue
        if cb and counter[0] % 2000 < 50:
            cb(counter[0], cur)


def scan(entries: Iterable[FileEntry], roots: Iterable[Path] | None = None, *, deep: bool = False,
         cancel: threading.Event | None = None, cb: ScanCb | None = None,
         install_root: Path | None = None) -> dict[str, list[Path]]:
    """{caminho do manifesto: [candidatos]} (candidatos de mesmo tamanho, o mais provável primeiro). Não confere hash."""
    cancel = cancel or threading.Event()
    entries = list(entries)
    wanted: dict[int, list[FileEntry]] = {}
    for e in entries:
        wanted.setdefault(e.size, []).append(e)
    sizes = set(wanted)
    hits: dict[int, list[Path]] = {}
    counter = [0]
    inst = str(install_root).lower() if install_root else None
    if deep:
        roots = _fixed_drives()
        deadline, max_files, depth = time.monotonic() + DEEP_MAX_SECONDS, 50_000_000, 40
    else:
        roots = list(roots) if roots is not None else candidate_roots()
        deadline, max_files, depth = time.monotonic() + QUICK_MAX_SECONDS, QUICK_MAX_FILES, 7
    for r in roots:
        if cancel.is_set() or time.monotonic() > deadline:
            break
        per = deadline if deep else min(deadline, time.monotonic() + PER_ROOT_SECONDS)
        _walk(Path(r), sizes, hits, counter, per, max_files, depth, cancel, cb)
    out: dict[str, list[Path]] = {}
    for size, es in wanted.items():
        for e in es:
            name = Path(e.path).name.lower()
            keyparts = {p.lower() for p in Path(e.path).parts[:-1]}
            cands = [p for p in hits.get(size, []) if not (inst and str(p).lower() == str(e.dest(install_root)).lower())]
            cands.sort(key=lambda p: (p.name.lower() != name, -len(keyparts & {x.lower() for x in p.parts}), -p.stat().st_mtime))
            if cands:
                out[e.path] = cands[:6]
    return out


def sha256_of(path: Path, cancel: threading.Event, cb: Callable[[int], None] | None = None) -> str:
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as f:
        while True:
            if cancel.is_set():
                raise DownloadError("cancelled", "Conferência cancelada.")
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
            done += len(b)
            if cb:
                cb(done)
    return h.hexdigest()


def import_found(found: dict[str, list[Path]], entries: Iterable[FileEntry], root: Path, progress: ProgressCb | None = None,
                 cancel: threading.Event | None = None) -> tuple[list[str], list[str], list[str]]:
    """Traz para `root` os arquivos achados. Devolve (ligados/copiados, não encontrados, usaram cópia).

    Só entra arquivo cujo SHA-256 confere. Preferência: link físico (instantâneo, sem espaço extra); senão cópia."""
    cancel = cancel or threading.Event()
    entries = [e for e in entries]
    total = sum(e.size for e in entries)
    done_overall = 0
    imported: list[str] = []
    missing: list[str] = []
    copied: list[str] = []
    for e in entries:
        dest = e.dest(root)
        name = Path(e.path).name
        if dest.is_file() and verify_file(e, root, cancel):
            done_overall += e.size
            continue
        ok = False
        for cand in found.get(e.path, []):
            try:
                if progress:
                    progress(Progress(name, 0, e.size, done_overall, total, 0.0, "conferindo"))
                digest = sha256_of(cand, cancel, lambda n, e=e, base=done_overall: progress and progress(
                    Progress(name, n, e.size, base + n, total, 0.0, "conferindo")))
            except OSError as exc:
                log.warning("não consegui ler %s: %s", cand, exc)
                continue
            if digest != e.sha256:
                log.info("%s tem o tamanho certo mas o hash não confere; ignorado", cand)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest.unlink()
            try:
                os.link(cand, dest)                                           # mesmo volume NTFS: instantâneo e sem espaço extra
            except OSError:
                part = dest.with_name(dest.name + ".part")
                n = 0
                t0 = time.monotonic()
                with open(cand, "rb") as fin, open(part, "wb") as fout:
                    while True:
                        if cancel.is_set():
                            part.unlink(missing_ok=True)
                            raise DownloadError("cancelled", "Importação cancelada.")
                        b = fin.read(CHUNK)
                        if not b:
                            break
                        fout.write(b)
                        n += len(b)
                        if progress:
                            progress(Progress(name, n, e.size, done_overall + n, total, n / max(time.monotonic() - t0, 1e-3), "copiando"))
                os.replace(part, dest)
                copied.append(e.path)
            mark_verified(e.path, e.sha256, dest, root)
            imported.append(e.path)
            ok = True
            break
        done_overall += e.size
        if not ok:
            missing.append(e.path)
    return imported, missing, copied
