"""Nome do usuário do computador (conta do Windows), usado nos textos e prompts no lugar de um nome fixo."""
from __future__ import annotations

import getpass
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def nome_usuario() -> str:
    """Primeiro nome da conta do Windows (ex.: 'maria.silva' -> 'Maria'); 'usuário' se não der para saber."""
    try:
        raw = os.environ.get("USERNAME") or getpass.getuser() or ""
    except Exception:
        raw = ""
    first = raw.replace(".", " ").replace("_", " ").replace("-", " ").strip().split(" ")[0] if raw.strip() else ""
    return first.capitalize() if first and first.lower() not in {"user", "admin", "administrator", "usuario", "usuário"} else "usuário"
