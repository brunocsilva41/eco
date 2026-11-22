"""Ponto de entrada do Jarvis instalado: python.exe -I -X utf8 jarvis_boot.py [subcomando ...]. Sem dependência do Python do sistema."""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

from jarvis.__main__ import main  # noqa: E402

raise SystemExit(main(sys.argv[1:]))
