"""Etapa 'validar versao': tag x installer/VERSION x CHANGELOG. So biblioteca padrao.

Uso:
    python -I tools/ci/check_version.py --tag v0.2.0 [--notes saida.md] [--github-output $GITHUB_OUTPUT]

Falha (codigo 1) se: a tag nao e semver 'vX.Y.Z[-pre]'; installer/VERSION difere da tag; o CHANGELOG nao tem a secao
'## [X.Y.Z]' (obrigatoria e nao vazia). Com --notes grava o corpo da secao (notas da release).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
HEAD = re.compile(r"^##\s+\[(?P<v>[^\]]+)\](?:\s*-\s*(?P<d>\d{4}-\d{2}-\d{2}))?\s*$")


def changelog_section(text: str, version: str) -> tuple[str | None, str | None]:
    """(data, corpo) da secao '## [version]' ou (None, None). O corpo vai ate o proximo '## ['."""
    lines = text.splitlines()
    start = None
    date = None
    for i, ln in enumerate(lines):
        m = HEAD.match(ln.strip())
        if m and m.group("v") == version:
            start, date = i + 1, m.group("d")
            break
    if start is None:
        return None, None
    body = []
    for ln in lines[start:]:
        if HEAD.match(ln.strip()):
            break
        body.append(ln)
    return date or "", "\n".join(body).strip("\n").strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--notes")
    ap.add_argument("--github-output")
    a = ap.parse_args(argv)
    root = Path(a.root)
    errs: list[str] = []

    tag = a.tag.removeprefix("refs/tags/")
    if not tag.startswith("v"):
        errs.append(f"a tag '{tag}' deve comecar com 'v' (ex.: v0.2.0)")
    version = tag[1:]
    if not SEMVER.match(version):
        errs.append(f"'{version}' nao e semver (MAJOR.MINOR.PATCH[-pre])")

    vf = root / "installer" / "VERSION"
    file_version = vf.read_text(encoding="utf-8").strip() if vf.exists() else ""
    if not file_version:
        errs.append("installer/VERSION nao existe ou esta vazio")
    elif file_version != version:
        errs.append(f"installer/VERSION ({file_version}) difere da tag ({version})")

    cl = root / "CHANGELOG.md"
    date = body = None
    if not cl.exists():
        errs.append("CHANGELOG.md nao existe")
    else:
        date, body = changelog_section(cl.read_text(encoding="utf-8"), version)
        if body is None:
            errs.append(f"CHANGELOG.md nao tem a secao '## [{version}] - AAAA-MM-DD'")
        elif not body.strip():
            errs.append(f"a secao [{version}] do CHANGELOG.md esta vazia")
        elif not date:
            errs.append(f"a secao [{version}] do CHANGELOG.md precisa de data (## [{version}] - AAAA-MM-DD)")

    if errs:
        for e in errs:
            print(f"ERRO: {e}")
        return 1

    prerelease = "-" in version
    print(f"OK: tag {tag} == installer/VERSION == CHANGELOG [{version}] ({date}); {len(body.splitlines())} linhas de notas; prerelease={prerelease}")
    if a.notes:
        Path(a.notes).write_text(body + "\n", encoding="utf-8")
    if a.github_output:
        with open(a.github_output, "a", encoding="utf-8") as f:
            f.write(f"version={version}\nprerelease={'true' if prerelease else 'false'}\ndate={date}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
