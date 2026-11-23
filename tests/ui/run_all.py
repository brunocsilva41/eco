"""Roda toda a bateria de UI em processos separados (um por suite x escala x tema), em prioridade baixa, e resume em
SAIDA\\resumo.json. Uso:

    venv\\Scripts\\python.exe -I tests\\ui\\run_all.py --out work\\ui_qa [--scales 100,125,150,200] [--themes dark,light]
        [--suites settings,island,dialogs,...] [--native]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PY = ROOT / "venv" / "Scripts" / "python.exe"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "work" / "ui_qa"))
    ap.add_argument("--scales", default="100,125,150,200")
    ap.add_argument("--themes", default="dark,light")
    ap.add_argument("--suites", default="settings,island,dialogs")
    ap.add_argument("--native", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    t_all = time.time()
    for suite in a.suites.split(","):
        for scale in a.scales.split(","):
            for theme in a.themes.split(","):
                cmd = [str(PY), "-I", "-X", "utf8", str(HERE / f"test_{suite}.py"), "--scale", scale, "--theme", theme, "--out", str(out)]
                if a.native:
                    cmd.append("--native")
                t0 = time.time()
                env = None
                import os
                env = dict(os.environ)
                env.pop("QT_QPA_PLATFORM", None)
                p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                                   creationflags=0x00004000, timeout=1500)      # BELOW_NORMAL_PRIORITY_CLASS
                tag = f"{suite}-{'nativo' if a.native else 'off'}-{scale}-{theme}"
                (out / f"{tag}.log").write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
                res = out / f"{suite}-{'nativo' if a.native else 'off'}-{scale}-{theme}.json"
                ok = bad = 0
                if res.exists():
                    items = json.loads(res.read_text(encoding="utf-8"))["items"]
                    ok = sum(1 for i in items if i["ok"])
                    bad = len(items) - ok
                rows.append({"suite": suite, "scale": int(scale), "theme": theme, "native": a.native, "exit": p.returncode,
                             "ok": ok, "falhas": bad, "segundos": round(time.time() - t0, 1)})
                print(f"{tag}: {ok} ok, {bad} falhas, exit {p.returncode}, {time.time()-t0:.0f}s", flush=True)
    (out / ("resumo-nativo.json" if a.native else "resumo.json")).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total {time.time()-t_all:.0f}s")
    return 1 if any(r["falhas"] or r["exit"] not in (0, 1) for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
