"""Gera site/releases.json a partir da release REAL (JSON do `gh release view --json ...`). So biblioteca padrao.

Uso:
    python -I tools/ci/gen_releases_json.py --repo dono/repo --release-json release.json --sha-file Eco-Setup-0.2.0.exe.sha256 --out site/releases.json
    python -I tools/ci/gen_releases_json.py --repo dono/repo --none --out site/releases.json    # sem release: mantem 'Em breve'

Regras (nada e inventado): versao/data/tamanho vem da release e dos assets; o SHA-256 vem do arquivo .sha256 baixado da propria
release e, se a API trouxer o 'digest' do asset, os dois PRECISAM coincidir (senao falha). A URL de download direto e
https://github.com/<repo>/releases/latest/download/Eco-Setup.exe quando o alias existe entre os assets (release estavel).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

NULLS = {"version": None, "date": None, "size_bytes": None, "sha256": None, "url": None, "versioned_url": None, "notes_url": None, "channel": "stable"}
COMMENT = ("Gerado pelo workflow de Pages (tools/ci/gen_releases_json.py) a partir da release real do GitHub; nunca edite valores a mao. "
           "Enquanto version/url/sha256 forem null o site mostra 'Em breve'.")


def parse_sha(text: str) -> str:
    m = re.search(r"\b([0-9a-fA-F]{64})\b", text)
    if not m:
        raise SystemExit("ERRO: o arquivo .sha256 nao contem um SHA-256 de 64 hex")
    return m.group(1).lower()


def build(repo: str, rel: dict, sha_text: str) -> dict:
    tag = rel.get("tagName") or ""
    m = re.match(r"^v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$", tag)
    if not m:
        raise SystemExit(f"ERRO: tag da release '{tag}' nao e vX.Y.Z")
    version = m.group(1)
    assets = {a["name"]: a for a in rel.get("assets", [])}
    exe_name = f"Eco-Setup-{version}.exe"
    if exe_name not in assets:
        raise SystemExit(f"ERRO: a release {tag} nao tem o asset {exe_name}")
    if f"{exe_name}.sha256" not in assets:
        raise SystemExit(f"ERRO: a release {tag} nao tem o asset {exe_name}.sha256")
    sha = parse_sha(sha_text)
    digest = (assets[exe_name].get("digest") or "").lower()
    if digest.startswith("sha256:") and digest[7:] != sha:
        raise SystemExit(f"ERRO: o SHA-256 do .sha256 ({sha[:12]}...) difere do digest da API ({digest[7:19]}...)")
    size = assets[exe_name].get("size")
    if not isinstance(size, int) or size <= 0:
        raise SystemExit("ERRO: tamanho do asset ausente")
    base = f"https://github.com/{repo}/releases"
    stable = not rel.get("isPrerelease") and "-" not in version
    alias = "Eco-Setup.exe" in assets and stable
    out = dict(NULLS)
    out.update({
        "_comentario": COMMENT,
        "version": version,
        "date": (rel.get("publishedAt") or "")[:10] or None,
        "size_bytes": size,
        "sha256": sha,
        "url": f"{base}/latest/download/Eco-Setup.exe" if alias else f"{base}/download/{tag}/{exe_name}",
        "versioned_url": f"{base}/download/{tag}/{exe_name}",
        "notes_url": f"{base}/tag/{tag}",
        "channel": "stable" if stable else "prerelease",
    })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--release-json")
    ap.add_argument("--sha-file")
    ap.add_argument("--none", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if not re.match(r"^[\w.-]+/[\w.-]+$", a.repo):
        raise SystemExit("ERRO: --repo deve ser dono/repo")
    if a.none:
        data = dict(NULLS, _comentario=COMMENT)
    else:
        if not a.release_json or not a.sha_file:
            raise SystemExit("ERRO: informe --release-json e --sha-file (ou --none)")
        rel = json.loads(Path(a.release_json).read_text(encoding="utf-8"))
        data = build(a.repo, rel, Path(a.sha_file).read_text(encoding="utf-8", errors="replace"))
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: {a.out} -> versao={data['version']} sha256={(data['sha256'] or 'null')[:12]} url={data['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
