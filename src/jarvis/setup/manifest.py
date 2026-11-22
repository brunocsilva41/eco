"""Leitura do `manifest.json` (nome, URLs, tamanho, SHA-256 e licença de cada modelo) e estado dos arquivos em disco."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ROOT


class ManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileEntry:
    path: str                       # relativo à raiz do Jarvis, com "/" (ex.: models/silero/silero_vad.onnx)
    size: int
    sha256: str
    urls: tuple[str, ...]

    def dest(self, root: Path = ROOT) -> Path:
        return root.joinpath(*self.path.split("/"))


@dataclass(frozen=True)
class Package:
    id: str
    name: str
    license: str
    license_url: str
    homepage: str
    files: tuple[FileEntry, ...]

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)


@dataclass(frozen=True)
class Component:
    key: str
    title: str
    description: str
    packages: tuple[str, ...]
    stt_dir: str = ""


@dataclass(frozen=True)
class Manifest:
    components: dict[str, Component]
    packages: dict[str, Package]
    bundled: tuple[dict, ...] = field(default_factory=tuple)

    def packages_for(self, components: list[str] | tuple[str, ...]) -> list[Package]:
        seen: dict[str, Package] = {}
        for key in components:
            comp = self.components.get(key)
            if comp is None:
                raise ManifestError(f"componente desconhecido: {key}")
            for pid in comp.packages:
                seen.setdefault(pid, self.packages[pid])
        return list(seen.values())

    def files_for(self, components: list[str] | tuple[str, ...]) -> list[FileEntry]:
        return [f for p in self.packages_for(components) for f in p.files]


def find_manifest(root: Path = ROOT) -> Path:
    for cand in (root / "manifest.json", root / "installer" / "manifest.json"):
        if cand.is_file():
            return cand
    raise ManifestError(f"manifest.json não encontrado em {root}")


def load_manifest(root: Path = ROOT) -> Manifest:
    path = find_manifest(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        packages: dict[str, Package] = {}
        for p in raw["packages"]:
            files = tuple(FileEntry(f["path"], int(f["size"]), f["sha256"].lower(), tuple(f["urls"])) for f in p["files"])
            for f in files:
                if not all(u.startswith("https://") for u in f.urls):
                    raise ManifestError(f"{f.path}: só URLs https são aceitas")
                if ".." in f.path.split("/") or f.path.startswith("/") or ":" in f.path:
                    raise ManifestError(f"{f.path}: caminho inseguro")
            packages[p["id"]] = Package(p["id"], p["name"], p.get("license", ""), p.get("license_url", ""),
                                        p.get("homepage", ""), files)
        comps = {k: Component(k, v["title"], v.get("description", ""), tuple(v["packages"]), v.get("stt_dir", ""))
                 for k, v in raw["components"].items()}
        return Manifest(comps, packages, tuple(raw.get("bundled", [])))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ManifestError(f"manifest.json inválido ({path}): {exc}") from exc


def human_bytes(n: float) -> str:
    """1,5 GB / 340 MB / 12 KB (pt-BR: vírgula decimal)."""
    for unit, div in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= div:
            v = n / div
            return (f"{v:.1f}" if v < 100 else f"{v:.0f}").replace(".", ",") + f" {unit}"
    return f"{int(n)} B"


def human_eta(seconds: float) -> str:
    if seconds != seconds or seconds < 0 or seconds > 86400 * 3:
        return "calculando"
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {(s % 3600) // 60:02d} min"


def quick_present(entry: FileEntry, root: Path = ROOT) -> bool:
    """Existe com o tamanho certo (checagem barata; a prova de integridade é o SHA-256 gravado em `verified.json`)."""
    try:
        return entry.dest(root).stat().st_size == entry.size
    except OSError:
        return False


def free_bytes(path: Path) -> int:
    import shutil
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def user_only(path: Path) -> None:
    """Restringe a pasta ao usuário atual e ao SYSTEM (sem herdar). Falha em silêncio: é endurecimento, não requisito."""
    import subprocess
    user = os.environ.get("USERNAME", "")
    if not user:
        return
    try:
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F", "/grant:r",
                        "*S-1-5-18:(OI)(CI)F"], capture_output=True, timeout=30, creationflags=0x08000000)
    except (OSError, subprocess.TimeoutExpired):
        pass
