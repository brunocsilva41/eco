"""Atalho sem janela de console (usado pelos atalhos, pelo Iniciar com o Windows e pelo instalador).

Sem argumentos: abre o assistente de configuração se ele ainda não foi concluído; senão roda o Jarvis (e o sobe de novo se as
Configurações pedirem reinício, código 75). Com argumentos (settings, setup --repair, ...): repassa ao Jarvis.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(ROOT, "runtime", "python", "python.exe")
BOOT = os.path.join(ROOT, "jarvis_boot.py")
NO_WINDOW = 0x08000000


def setup_done() -> bool:
    try:
        with open(os.path.join(ROOT, "data", "setup", "setup.json"), encoding="utf-8") as f:
            return bool(json.load(f).get("completed"))
    except (OSError, ValueError):
        return False


def main() -> int:
    args = sys.argv[1:] or (["run"] if setup_done() else ["setup"])
    env = dict(os.environ, PYTHONUTF8="1")
    while True:
        code = subprocess.call([PY, "-I", "-X", "utf8", BOOT, *args], cwd=ROOT, env=env, creationflags=NO_WINDOW)
        if code == 75 and args[0] == "run":
            continue
        return code


if __name__ == "__main__":
    raise SystemExit(main())
