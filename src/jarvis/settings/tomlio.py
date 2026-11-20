"""Gravação de TOML (a biblioteca padrão só LÊ) e escrita ATÔMICA de arquivos.

Escreve apenas os tipos que a config usa: texto, número, booleano, lista de textos e tabela texto -> texto.
Nunca escreve segredos (a validação da config já recusa chaves com esses nomes).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

_ESC = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _s(text: str) -> str:
    out = []
    for ch in text:
        if ch in _ESC:
            out.append(_ESC[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _key(k: str) -> str:
    return k if k.replace("_", "").replace("-", "").isalnum() and k.isascii() else _s(k)


def _value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("número inválido para TOML")
        return repr(v)
    if isinstance(v, str):
        return _s(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(i) for i in v) + "]"
    raise TypeError(f"tipo não suportado no TOML: {type(v).__name__}")


def dumps(data: dict[str, Any], header: str = "") -> str:
    """Serializa {secao: {chave: valor | {sub: valor}}} (até 2 níveis de tabela)."""
    lines: list[str] = []
    if header:
        lines += [f"# {ln}" if ln else "#" for ln in header.splitlines()] + [""]
    top = {k: v for k, v in data.items() if not isinstance(v, dict)}
    for k, v in top.items():
        lines.append(f"{_key(k)} = {_value(v)}")
    if top:
        lines.append("")
    for sec, body in data.items():
        if not isinstance(body, dict):
            continue
        scalars = {k: v for k, v in body.items() if not isinstance(v, dict)}
        subs = {k: v for k, v in body.items() if isinstance(v, dict)}
        if scalars or not subs:
            lines.append(f"[{_key(sec)}]")
            for k, v in scalars.items():
                lines.append(f"{_key(k)} = {_value(v)}")
            lines.append("")
        for sub, sbody in subs.items():
            lines.append(f"[{_key(sec)}.{_key(sub)}]")
            for k, v in sbody.items():
                lines.append(f"{_s(k) if not k.isidentifier() else k} = {_value(v)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    """Grava `text` em `path` sem nunca deixar o arquivo pela metade: temporário na mesma pasta + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
