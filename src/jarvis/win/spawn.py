"""Lançar telas (Configurações, Terminal...) em outro processo SEM janela de console piscando.

O ``python.exe`` do venv é um lançador que cria o Python real como filho: se o pai está sem console (``DETACHED_PROCESS``), o
Windows dá ao filho um console NOVO e visível por um instante (a "janela do python piscando"). Para telas gráficas usamos o
``pythonw.exe`` (subsistema GUI: nunca abre console) e ``CREATE_NO_WINDOW`` para o caso de só existir o ``python.exe``.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


def gui_python() -> str:
    """Caminho do pythonw.exe ao lado do interpretador atual (ou o próprio interpretador, se não existir)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        return str(exe)
    w = exe.with_name("pythonw.exe")
    return str(w) if w.is_file() else str(exe)


def spawn_gui(args: list[str], *, cwd: str) -> subprocess.Popen:
    """Abre ``python -I -X utf8 -c <código> ...`` como programa gráfico independente, sem console visível."""
    py = gui_python()
    # sem DETACHED_PROCESS: com ele o lançador do venv ganharia um console novo e visível
    return subprocess.Popen([py, *args], cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, close_fds=True)
