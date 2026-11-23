"""Corredor de testes do CI: roda cada suite do manifesto em processo proprio, com tempo limite, e resume.

Uso:
    python -I tools/ci/run_tests.py --group unit|ui|all [--out saida] [--only id1,id2] [--list]

Falha (codigo 1) se qualquer suite falhar ou estourar o tempo. Escreve saida/<id>.log e saida/resumo.json; se existir
$GITHUB_STEP_SUMMARY, acrescenta uma tabela (relatorio da etapa).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="all", choices=["unit", "ui", "all"])
    ap.add_argument("--out", default=str(ROOT / "work" / "ci_tests"))
    ap.add_argument("--only", default="")
    ap.add_argument("--manifest", default=str(ROOT / "tools" / "ci" / "tests-manifest.json"))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)

    man = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    only = {s for s in a.only.split(",") if s}
    jobs = []
    for s in man["include"]:
        if a.group != "all" and s["group"] != a.group:
            continue
        if only and s["id"] not in only:
            continue
        for i, extra in enumerate(s.get("variants") or [[]]):
            tag = s["id"] + ("" if not extra else "-" + "-".join(x.lstrip("-") for x in extra))
            jobs.append((tag, s, extra))
    if a.list:
        for tag, s, extra in jobs:
            print(tag, s["script"], " ".join(extra))
        return 0

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1", PYTHONIOENCODING="utf-8", NO_COLOR="1")
    rows, failed = [], 0
    for tag, s, extra in jobs:
        cmd = [sys.executable, "-I", "-X", "utf8", str(ROOT / s["script"])]
        if s["group"] == "ui":
            cmd += extra + ["--out", str(out / "ui")]
        t0 = time.time()
        status, tail = "ok", ""
        try:
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=s.get("timeout", 300))
            text = (r.stdout or "") + (r.stderr or "")
            (out / f"{tag}.log").write_text(text, encoding="utf-8")
            tail = " | ".join([ln for ln in text.splitlines() if ln.strip()][-2:])[:200]
            if r.returncode != 0:
                status = f"FALHOU (codigo {r.returncode})"
        except subprocess.TimeoutExpired as e:
            status = f"TEMPO ESGOTADO ({s.get('timeout', 300)} s)"
            txt = (e.stdout or b"")
            (out / f"{tag}.log").write_text(txt.decode("utf-8", "replace") if isinstance(txt, bytes) else str(txt), encoding="utf-8")
        dt = time.time() - t0
        if status != "ok":
            failed += 1
        print(f"[{'OK ' if status == 'ok' else 'ERRO'}] {tag:38s} {dt:6.1f}s  {tail if status == 'ok' else status + ' :: ' + tail}", flush=True)
        rows.append({"suite": tag, "script": s["script"], "status": status, "seconds": round(dt, 1), "tail": tail})

    (out / "resumo.json").write_text(json.dumps({"failed": failed, "total": len(rows), "suites": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write(f"### Testes ({a.group}): {len(rows) - failed}/{len(rows)} ok\n\n| Suite | Resultado | Tempo |\n|---|---|---|\n")
            for r in rows:
                f.write(f"| `{r['suite']}` | {'ok' if r['status'] == 'ok' else '**' + r['status'] + '**'} | {r['seconds']} s |\n")
    print(f"\n{len(rows) - failed}/{len(rows)} suites ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
