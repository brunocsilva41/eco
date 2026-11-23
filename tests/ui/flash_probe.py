"""Mede o "piscar" ao abrir uma tela: conta janelas top-level criadas pelo processo (e filhos) e as vezes que ficam visíveis.

Uso:  venv\\Scripts\\python.exe -I tests\\ui\\flash_probe.py [settings|settings-open|island] [--label antes|depois] [--secs 7]

Lança o filho do MESMO jeito que o app (DETACHED_PROCESS | CREATE_NO_WINDOW, sys.executable ou pythonw), amostra EnumWindows a
cada ~15 ms e relata: janelas distintas, classes, tempo até a primeira janela visível, quantas transições visível→oculto,
consoles (ConsoleWindowClass) e a captura final. Usa trava própria (JARVIS_TEST_INSTANCE): nunca toca a janela do usuário.
Só termina o PID que ele mesmo lançou (e os filhos desse PID).
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"F:\Jarvis\..\Shared").resolve() if False else Path(r"C:\Users\<usuário>\capturas/ui-prints\flash")
u32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def snapshot(pids: set[int]) -> dict[int, dict]:
    found: dict[int, dict] = {}

    def cb(hwnd, _lp):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        cls = ctypes.create_unicode_buffer(128)
        u32.GetClassNameW(hwnd, cls, 128)
        if pid.value in pids or cls.value == "ConsoleWindowClass":
            ttl = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, ttl, 256)
            r = wintypes.RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(r))
            found[int(hwnd)] = {"pid": pid.value, "cls": cls.value, "title": ttl.value, "vis": bool(u32.IsWindowVisible(hwnd)),
                                "rect": (r.left, r.top, r.right - r.left, r.bottom - r.top)}
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def family(pid: int) -> set[int]:
    try:
        p = psutil.Process(pid)
        return {pid} | {c.pid for c in p.children(recursive=True)}
    except psutil.Error:
        return {pid}


def main() -> int:
    args = sys.argv[1:]
    what = next((a for a in args if not a.startswith("--")), "settings")
    label = args[args.index("--label") + 1] if "--label" in args else "medicao"
    secs = float(args[args.index("--secs") + 1]) if "--secs" in args else 7.0
    code = ("import sys; sys.path.insert(0, r'%s'); from jarvis.__main__ import main; raise SystemExit(main(sys.argv[1:]))"
            % str(ROOT / "src"))
    cmd_args = {"settings": ["settings", "--open", "geral"], "settings-open": ["settings"], "island": ["island-demo"],
                "setup": ["setup"], "record": ["record"], "memory": ["memory"]}[what]
    env = dict(os.environ, JARVIS_TEST_INSTANCE="-probe-" + str(os.getpid()), PYTHONUTF8="1")
    before = set(snapshot(set()).keys())                       # consoles pré-existentes (de outros)
    t0 = time.perf_counter()
    if "--legacy" in args:                                       # jeito antigo do app: python.exe + DETACHED_PROCESS
        proc = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-c", code, *cmd_args], cwd=str(ROOT), env=env,
                                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | 0x08000000)
    else:                                                        # jeito atual: win.spawn.spawn_gui (pythonw + CREATE_NO_WINDOW)
        sys.path.insert(0, str(ROOT / "src"))
        os.environ.update(env)
        from jarvis.win.spawn import spawn_gui
        proc = spawn_gui(["-I", "-X", "utf8", "-c", code, *cmd_args], cwd=str(ROOT))
    seen: dict[int, dict] = {}
    vis_hist: dict[int, list[bool]] = {}
    first_vis = None
    frames: list[tuple[float, int]] = []                         # (t desde a 1ª visível, contraste da janela principal)
    shot_done = False
    OUT.mkdir(parents=True, exist_ok=True)
    while time.perf_counter() - t0 < secs:
        fam = family(proc.pid)
        snap = snapshot(fam)
        now = time.perf_counter() - t0
        for h, d in snap.items():
            if d["cls"] == "ConsoleWindowClass" and h in before:
                continue
            if h not in seen:
                seen[h] = dict(d, first=round(now, 3))
                vis_hist[h] = []
                if d["vis"] and d["cls"] != "ConsoleWindowClass" and 0 < d["rect"][2] < 700 and sum(1 for k in seen if k != h) < 40:
                    try:                                        # janela pequena e visível: guarda uma foto para identificar
                        from PIL import ImageGrab
                        x, y, w, hh = d["rect"]
                        ImageGrab.grab(bbox=(x, y, x + w, y + hh), all_screens=True).save(OUT / f"{label}-{what}-pequena-{len(seen)}.png")
                    except Exception:                           # noqa: BLE001
                        pass
            h_hist = vis_hist[h]
            if not h_hist or h_hist[-1] != d["vis"]:
                h_hist.append(d["vis"])
            seen[h]["last"] = round(now, 3)
            seen[h].update(vis=d["vis"], rect=d["rect"])
            if d["vis"] and first_vis is None and d["rect"][2] > 200:
                first_vis = now
        if first_vis is not None and now - first_vis < 1.4 and len(frames) < 80:
            try:                                                # a janela principal está visível: ela já tem conteúdo ou está em branco?
                from PIL import ImageGrab
                big = max((d for d in seen.values() if d["vis"] and d["rect"][2] > 600), key=lambda d: d["rect"][2] * d["rect"][3], default=None)
                if big is not None:
                    x, y, w, hh = big["rect"]
                    im = ImageGrab.grab(bbox=(x + 8, y + 40, x + w - 8, y + hh - 8), all_screens=True).convert("L").resize((48, 32))
                    px = list(im.getdata())
                    spread = max(px) - min(px)
                    frames.append((round(now - first_vis, 3), spread))
            except Exception:                                   # noqa: BLE001
                pass
        time.sleep(0.015)
        if not shot_done and first_vis is not None and now - first_vis > 1.5:
            shot_done = True
            try:
                from PIL import ImageGrab
                big = max((d for d in seen.values() if d["vis"]), key=lambda d: d["rect"][2] * d["rect"][3])
                x, y, w, h = big["rect"]
                ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(OUT / f"{label}-{what}.png")
            except Exception as exc:                            # noqa: BLE001
                print("sem captura:", exc)
    # ---- janela em branco: fotografa a janela principal repetidamente logo depois de aparecer? (já passou o tempo): ver blank_probe()
    for pid in family(proc.pid):                                 # só o que EU lancei
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass
    rows = []
    for h, d in sorted(seen.items(), key=lambda kv: kv[1]["first"]):
        toggles = sum(1 for a, b in zip(vis_hist[h], vis_hist[h][1:]) if a and not b)
        rows.append({"hwnd": h, "classe": d["cls"], "titulo": d["title"][:40], "pid": d["pid"], "aparece_s": d["first"],
                     "ficou_visivel_alguma_vez": any(vis_hist[h]), "transicoes_visivel_para_oculto": toggles,
                     "tam": d["rect"][2:], "historico": vis_hist[h][:12]})
    visible_now = [r for r in rows if r["ficou_visivel_alguma_vez"]]
    res = {"rotulo": label, "tela": what, "janelas_distintas": len(rows), "janelas_que_ficaram_visiveis": len(visible_now),
           "consoles": sum(1 for r in rows if r["classe"] == "ConsoleWindowClass"),
           "primeira_visivel_s": None if first_vis is None else round(first_vis, 3),
           "quadros_em_branco": sum(1 for _t, s in frames if s < 12), "quadros_medidos": len(frames),
           "janela_pintada_apos_s": next((t for t, s in frames if s >= 12), None), "janelas": rows}
    (OUT / f"{label}-{what}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "janelas"}, ensure_ascii=False))
    for r in rows:
        print("  ", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
