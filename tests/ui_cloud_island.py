"""Capturas da Ilha quando a nuvem é usada: aviso «Nuvem: <agente>» (início/ok/erro com motivo) e a confirmação com o nome do agente.

    python -I tests\\ui_cloud_island.py SAIDA          (processo filho por escala: 100% e 150%, offscreen)
Usa os eventos REAIS do núcleo (`action_step` com tool="nuvem", `confirm_request`) passados pelo `sanitize` do elo núcleo->Ilha.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    CHECKS.append((name, bool(ok)))
    print(("OK   " if ok else "FALHA"), name, flush=True)


def child(out: Path) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from jarvis.ui.island import demo
    from jarvis.ui.island.demo import IslandWindow, SyntheticSource, _compose, _make_app, _visible_cfg, _wait
    from jarvis.ui.island.link import sanitize
    from jarvis.ui.island.tokens import IslandSize, IslandState

    app = _make_app()
    scale = round(app.primaryScreen().devicePixelRatio() * 100)
    tag = f"{scale}"
    win = IslandWindow(SyntheticSource(), cfg=_visible_cfg(mode="docked"))
    win.start()
    _wait(400)
    win.pin_size(IslandSize.LARGE)
    label = "Google Antigravity"

    def shoot(name: str) -> None:
        _wait(700)
        _compose(win.grab(), pad_x=48, pad_b=48).save(str(out / f"ilha-nuvem-{name}-{tag}pct.png"))

    s = sanitize("action_step", {"tool": "nuvem", "text": label, "status": "start", "risk": 0, "result": ""})
    check(f"[{tag}%] a Ilha recebe o aviso da nuvem (nome do agente passa pelo sanitize)", s is not None and label in s["text"])
    win.set_state(IslandState.THINKING)
    win.set_action(s["tool"], s["text"], s["status"], s["result"])
    shoot("1-consultando")
    win.set_action("nuvem", label, "ok", "")
    shoot("2-respondeu")
    win.set_action("nuvem", "OpenCode", "error", "OpenCode: limite de uso ou créditos da conta esgotados")
    shoot("3-falhou-usando-local")
    text = f"O agente {label}, na nuvem, quer: Abrir o aplicativo bloco de notas"
    c = sanitize("confirm_request", {"id": "c1", "text": text, "risk": 2, "timeout_s": 15})
    check(f"[{tag}%] a confirmação mostra o nome do agente e passa inteira pelo sanitize", c is not None and label in c["text"])
    win.ask_confirmation(c["text"], c["timeout_s"], c["id"])
    shoot("4-confirmacao-com-nome-do-agente")
    check(f"[{tag}%] a Ilha entrou no estado de confirmação", win.state is IslandState.CONFIRMING)
    answers: list[bool] = []
    win.confirm_answered.connect(answers.append)
    win.b_no.clicked.emit() if hasattr(win.b_no, "clicked") else None
    win.close()
    return 0 if all(ok for _, ok in CHECKS) else 1


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        return child(Path(sys.argv[2]))
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for scale in (1.0, 1.5):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=str(scale))
        if fonts.is_dir():
            env["QT_QPA_FONTDIR"] = str(fonts)
        bad += subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--child", str(out)], env=env, timeout=300).returncode != 0
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
