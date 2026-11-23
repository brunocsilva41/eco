"""Gera o RELATORIO-QA.md (matriz tela x DPI x tema x resultado) a partir dos JSONs das suites em uma ou mais pastas.

    venv\\Scripts\\python.exe -I tests\\ui\\make_report.py --in work\\ui_qa_final [--in OUTRA] --out capturas/ui-prints\\qa\\RELATORIO-QA.md
Cada JSON e {suite, scale, theme, native, items:[{name, ok, detail}]}. O ultimo arquivo de cada (suite, nativo, escala, tema) vence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

NOMES = {"settings": "Configurações (todas as páginas)", "settings_native": "Configurações, entrada real (SendInput)",
         "island": "Ilha (estados, popups, avisos, alfinete)", "dialogs": "Diálogos, toasts e pop-up de nova versão",
         "windows": "Memória, Gravador e Assistente de instalação", "tray": "Bandeja do sistema"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows: dict[tuple, dict] = {}
    for d in a.inputs:
        for f in sorted(Path(d).glob("*.json"), key=lambda p: p.stat().st_mtime):
            if f.name.startswith("resumo"):
                continue
            j = json.loads(f.read_text(encoding="utf-8"))
            rows[(j["suite"], bool(j["native"]), int(j["scale"]), j["theme"])] = j
    out = ["# Relatório de QA das telas do Eco", "",
           "Gerado por `tests\\ui\\make_report.py` a partir dos resultados das suites em `tests\\ui\\`. "
           "**offscreen** = Qt sem janela real (rápido, 100/125/150/200%); **nativo** = janela real do Windows com entrada real.", ""]
    suites = []
    for (s, n, sc, th) in rows:
        if (s, n) not in suites:
            suites.append((s, n))
    total_ok = total = 0
    out += ["## Matriz (aprovadas/total por escala e tema)", "", "| Tela | Modo | " + " | ".join(f"{sc}% escuro | {sc}% claro" for sc in (100, 125, 150, 200)) + " |",
            "|---|---|" + "---|" * 8]
    for s, n in suites:
        cells = []
        for sc in (100, 125, 150, 200):
            for th in ("dark", "light"):
                j = rows.get((s, n, sc, th))
                if j is None:
                    cells.append("—")
                    continue
                ok = sum(1 for i in j["items"] if i["ok"])
                tot = len(j["items"])
                total_ok += ok
                total += tot
                cells.append(f"{'✓' if ok == tot else '✗'} {ok}/{tot}")
        out.append(f"| {NOMES.get(s, s)} | {'nativo' if n else 'offscreen'} | " + " | ".join(cells) + " |")
    out += ["", f"**Total: {total_ok}/{total} verificações aprovadas.**", ""]
    fails = []
    for (s, n, sc, th), j in sorted(rows.items()):
        for i in j["items"]:
            if not i["ok"]:
                fails.append(f"- `{s}{' (nativo)' if n else ''}` {sc}% {th}: **{i['name']}** — {i['detail'][:240]}")
    out += ["## Falhas em aberto", ""] + (fails or ["Nenhuma."]) + [""]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(out), encoding="utf-8")
    print(f"{a.out}: {total_ok}/{total}, {len(fails)} falhas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
