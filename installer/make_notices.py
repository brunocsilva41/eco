"""Gera THIRD-PARTY.txt (pacote, versão, licença) lendo os metadados do que foi instalado no runtime.
Uso: python -I make_notices.py <site-packages> <saida.txt>"""
import sys
from importlib import metadata
from pathlib import Path

site, out = Path(sys.argv[1]), Path(sys.argv[2])
rows = []
for dist in metadata.distributions(path=[str(site)]):
    md = dist.metadata
    lic = (md.get("License-Expression") or "").strip()
    if not lic:
        lic = (md.get("License") or "").strip().splitlines()[0][:80] if (md.get("License") or "").strip() else ""
    if not lic or len(lic) > 70:
        cls = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
        lic = "; ".join(cls) or lic or "ver metadados do pacote"
    rows.append((md["Name"], md["Version"], lic, md.get("Home-page") or ""))
rows.sort(key=lambda r: r[0].lower())
text = ["JARVIS - COMPONENTES DE TERCEIROS (pacotes Python embutidos)", "",
        "Cada pacote mantém sua própria licença (arquivos LICENSE dentro de runtime/python/Lib/site-packages/<pacote>-<versão>.dist-info).",
        "Aviso: o pacote piper-tts (GPL-3.0) e o PySide6 (LGPL-3.0) exigem que o texto da licença e o acesso ao código-fonte acompanhem a distribuição;",
        "o código-fonte de cada versão está no PyPI e nos repositórios acima indicados.", ""]
text += [f"{n} {v}  -  {l}" for n, v, l, _h in rows]
out.write_text("\n".join(text) + "\n", encoding="utf-8")
print(f"{len(rows)} pacotes em {out}")
