"""Organiza as capturas finais (so as de widget/janela do Qt, sem area de trabalho) em capturas/ui-prints\\qa\\<tela>\\<escala-tema>\\.
Capturas de tela cheia do Windows (pasta nativo-real) NAO entram: mostram o que estiver aberto no PC. Uso:
    venv\\Scripts\\python.exe -I tests\\ui\\collect_prints.py --src work\\ui_qa_final --dst capturas/ui-prints\\qa"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

NOMES = {"": "configuracoes", "ilha": "ilha", "dialogos": "dialogos-e-popups", "janelas": "memoria-gravador-assistente", "bandeja": "bandeja"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    a = ap.parse_args()
    src, dst = Path(a.src) / "capturas" / "off", Path(a.dst)
    n = 0
    for d in sorted(src.glob("*")):
        if not d.is_dir():
            continue
        name = d.name                                   # "100-dark" (configuracoes) ou "ilha-100-dark", "dialogos-150-light"...
        parts = name.split("-")
        if parts[0].isdigit():
            tela, esc, tema = "configuracoes", parts[0], parts[1]
        else:
            tela, esc, tema = NOMES.get(parts[0], parts[0]), parts[1], parts[2]
        if esc not in ("100", "125", "150", "200"):
            continue
        out = dst / tela / f"{esc}-{'escuro' if tema == 'dark' else 'claro'}"
        out.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.png"):
            shutil.copy2(f, out / f.name)
            n += 1
    print(f"{n} capturas copiadas para {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
