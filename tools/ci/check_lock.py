"""Etapa 'wheels travadas': confere installer/requirements.lock.txt contra requirements.lock.in.txt. So biblioteca padrao.

Falha se: algum pacote do .in nao esta no lock (ou o contrario); a versao difere; falta '--hash=sha256:<64 hex>' em alguma linha;
ha linha sem versao fixa ('=='). Isso garante o 'pip install --require-hashes' do build.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()


def parse(path: Path, need_hash: bool) -> tuple[dict[str, str], list[str]]:
    pkgs, errs = {}, []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9._-]+)==([^\s]+)(.*)$", ln)
        if not m:
            errs.append(f"{path.name}:{n}: linha sem 'pacote==versao': {ln[:60]}")
            continue
        name, ver, rest = m.group(1), m.group(2), m.group(3)
        if need_hash and not re.search(r"--hash=sha256:[0-9a-f]{64}", rest):
            errs.append(f"{path.name}:{n}: {name} sem --hash=sha256:<64 hex>")
        pkgs[norm(name)] = ver
    return pkgs, errs


def main() -> int:
    inst = ROOT / "installer"
    want, e1 = parse(inst / "requirements.lock.in.txt", False)
    have, e2 = parse(inst / "requirements.lock.txt", True)
    errs = e1 + e2
    for k in sorted(set(want) - set(have)):
        errs.append(f"{k}=={want[k]} esta no .in mas nao no lock")
    for k in sorted(set(have) - set(want)):
        errs.append(f"{k}=={have[k]} esta no lock mas nao no .in")
    for k in sorted(set(want) & set(have)):
        if want[k] != have[k]:
            errs.append(f"{k}: versao do .in ({want[k]}) difere do lock ({have[k]})")
    if errs:
        print("\n".join("ERRO: " + e for e in errs))
        return 1
    print(f"OK: {len(have)} pacotes travados por hash e coerentes com o .in")
    return 0


if __name__ == "__main__":
    sys.exit(main())
