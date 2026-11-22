"""Verificação de atualizações: compara a versão instalada com a última release publicada no GitHub.

Só LÊ (uma requisição HTTPS à API pública de releases). Repositório privado não responde sem credencial: nesse caso, se o
GitHub CLI (`gh`) estiver logado neste computador, usa-o; senão explica o motivo. Nada é baixado nem instalado sozinho:
o usuário abre a página da release e roda o instalador novo (atualização por cima mantém dados e configuração).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_REPO = "brunocsilva41/jarvis-local"


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str = ""
    available: bool = False
    url: str = ""
    notes: str = ""
    error: str = ""


def _ver(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:4]) or (0,)


def current_version() -> str:
    try:
        from ..setup.state import app_version
        return str(app_version())
    except Exception:  # noqa: BLE001
        return "0.0.0"


def _fetch_public(repo: str, timeout: float) -> dict | None:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "Jarvis-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:               # noqa: S310 - https fixo
        return json.loads(resp.read().decode("utf-8"))


def _fetch_gh(repo: str, timeout: float) -> dict | None:
    gh = shutil.which("gh")
    if not gh:
        return None
    out = subprocess.run([gh, "api", f"repos/{repo}/releases/latest"], capture_output=True, text=True, timeout=timeout,
                         creationflags=0x08000000)
    if out.returncode != 0:
        return None
    return json.loads(out.stdout)


def check(repo: str = DEFAULT_REPO, timeout: float = 10.0) -> UpdateInfo:
    cur = current_version()
    data: dict | None = None
    err = ""
    try:
        data = _fetch_public(repo, timeout)
    except urllib.error.HTTPError as exc:
        err = "o repositório é privado (sem acesso sem login)" if exc.code in (401, 403, 404) else f"o GitHub respondeu {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        err = "sem conexão com a internet" if isinstance(exc, (urllib.error.URLError, OSError)) else "resposta inválida do GitHub"
    if data is None:
        try:
            data = _fetch_gh(repo, timeout)
        except (OSError, subprocess.SubprocessError, ValueError):
            data = None
    if data is None:
        return UpdateInfo(cur, error=err or "não consegui consultar as atualizações")
    latest = str(data.get("tag_name") or data.get("name") or "").lstrip("vV")
    return UpdateInfo(cur, latest, _ver(latest) > _ver(cur), str(data.get("html_url") or ""), str(data.get("body") or "")[:600])
