"""Estado do assistente (progresso, escolhas) e cache de arquivos já verificados. Fica em `data/setup/`.

Nada aqui é segredo: só a etapa atual, os componentes escolhidos e marcas de verificação.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..config import ROOT

STEPS = ("welcome", "hardware", "prepare", "models", "audio", "voice", "vad", "hotkeys", "permissions", "doctor", "done")
DEFAULT_COMPONENTS = ("vision", "voice", "stt_small")


def state_dir(root: Path = ROOT) -> Path:
    return root / "data" / "setup"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class SetupState:
    step: str = "welcome"
    completed: bool = False
    components: list[str] = field(default_factory=lambda: list(DEFAULT_COMPONENTS))
    choices: dict[str, Any] = field(default_factory=dict)
    updated: float = 0.0

    @classmethod
    def load(cls, root: Path = ROOT) -> "SetupState":
        path = state_dir(root) / "setup.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        st = cls()
        if raw.get("step") in STEPS:
            st.step = raw["step"]
        st.completed = bool(raw.get("completed", False))
        comps = raw.get("components")
        if isinstance(comps, list) and all(isinstance(c, str) for c in comps) and comps:
            st.components = comps
        if isinstance(raw.get("choices"), dict):
            st.choices = raw["choices"]
        st.updated = float(raw.get("updated", 0.0) or 0.0)
        return st

    def save(self, root: Path = ROOT) -> None:
        self.updated = time.time()
        _atomic_write(state_dir(root) / "setup.json", json.dumps(asdict(self), ensure_ascii=False, indent=2))


def read_install_info(root: Path = ROOT) -> dict[str, Any]:
    """`data/setup/install.json`, escrito pelo instalador (versão, componentes escolhidos, modo)."""
    try:
        raw = json.loads((state_dir(root) / "install.json").read_text(encoding="utf-8-sig"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def app_version(root: Path = ROOT) -> str:
    for cand in (root / "VERSION", root / "installer" / "VERSION"):
        try:
            text = cand.read_text(encoding="utf-8-sig").strip()
            if text:
                return text.splitlines()[0].strip()
        except OSError:
            continue
    return "dev"


# ---------------------------------------------------------------- cache de verificação (SHA-256 já conferido)
def _vpath(root: Path) -> Path:
    return state_dir(root) / "verified.json"


def _load_verified(root: Path) -> dict[str, list[int]]:
    try:
        raw = json.loads(_vpath(root).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def is_verified(rel: str, sha256: str, path: Path, root: Path = ROOT) -> bool:
    rec = _load_verified(root).get(rel)
    try:
        st = path.stat()
    except OSError:
        return False
    return bool(rec) and rec[0] == st.st_size and rec[1] == st.st_mtime_ns and len(rec) > 2 and rec[2] == sha256[:16]


def mark_verified(rel: str, sha256: str, path: Path, root: Path = ROOT) -> None:
    data = _load_verified(root)
    st = path.stat()
    data[rel] = [st.st_size, st.st_mtime_ns, sha256[:16]]
    _atomic_write(_vpath(root), json.dumps(data))
