"""Etapa 'schema': schema.uncovered_fields() precisa continuar vazio, e a importacao basica precisa funcionar (offscreen)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from jarvis.settings import schema  # noqa: E402

missing = schema.uncovered_fields()
if missing:
    print("ERRO: campos do config sem cobertura no schema:", ", ".join(map(str, missing)))
    sys.exit(1)
print("OK: schema.uncovered_fields() vazio")
