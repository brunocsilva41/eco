"""Gera requirements.lock.txt (com --hash=sha256 de cada wheel baixada em installer/wheels). Uso: python -I make_lock.py"""
import hashlib
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
wheels = here / "wheels"


def norm(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


index: dict[str, list[Path]] = {}
for w in wheels.glob("*.whl"):
    name, ver = w.name.split("-")[:2]
    index.setdefault(f"{norm(name)}=={ver}", []).append(w)

lines = []
for raw in (here / "requirements.lock.in.txt").read_text(encoding="utf-8").splitlines():
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        continue
    name, ver = raw.split("==")
    files = index.get(f"{norm(name)}=={ver}")
    if not files:
        sys.exit(f"sem wheel para {raw} em {wheels}")
    hashes = " ".join(f"--hash=sha256:{hashlib.sha256(f.read_bytes()).hexdigest()}" for f in sorted(files))
    lines.append(f"{name}=={ver} {hashes}")
(here / "requirements.lock.txt").write_text("# gerado por make_lock.py a partir de wheels/ (não editar à mão)\n" + "\n".join(lines) + "\n", encoding="utf-8")
print(f"{len(lines)} pacotes travados")
