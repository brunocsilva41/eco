"""Descoberta de atualizações: compara a versão instalada com a última release do GitHub e acha o instalador + o SHA-256.

Só LÊ. Acesso, nesta ordem: (1) API pública sem credencial; (2) token SOMENTE-LEITURA guardado no Cofre de Credenciais do
Windows (`core.credstore`); (3) GitHub CLI (`gh`) já logado neste computador. Repositório privado sem nenhuma das três vias
devolve uma mensagem honesta (`UpdateInfo.error` + `UpdateInfo.hint`), nunca um falso "você está atualizado".
Só HTTPS. O download e a instalação ficam em `core.updater`.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import credstore

log = logging.getLogger(__name__)

DEFAULT_REPO = "brunocsilva41/eco"
API = "https://api.github.com"
USER_AGENT = "Eco-Updater"
_ASSET_RE = re.compile(r"^Eco-Setup-.+\.exe$", re.I)
_BODY_HASH = re.compile(r"SHA-?256[^0-9a-fA-F]{0,12}([0-9a-fA-F]{64})", re.I)


@dataclass(frozen=True)
class Asset:
    name: str
    size: int = 0
    api_url: str = ""          # https://api.github.com/repos/.../releases/assets/ID (serve repositório privado)
    browser_url: str = ""      # https://github.com/.../releases/download/... (público)
    digest: str = ""           # "sha256:<hex>" informado pelo GitHub (quando existe)


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str = ""
    available: bool = False
    url: str = ""                                   # página da release
    notes: str = ""
    error: str = ""
    hint: str = ""                                  # o que fazer quando há erro
    tag: str = ""
    prerelease: bool = False
    via: str = ""                                   # "public" | "token" | "gh"
    repo: str = DEFAULT_REPO
    installer: Asset | None = None
    hash_asset: Asset | None = None                 # arquivo .exe.sha256
    body_sha256: str = ""                           # hash achado no corpo da release
    extra: dict = field(default_factory=dict, compare=False)


# ---------------------------------------------------------------- versões
def parse_version(text: str) -> tuple[tuple[int, ...], int, str]:
    """'0.2.0-rc1' -> ((0,2,0), 0, 'rc1'); versão final tem o 2º item 1 (final > pré-lançamento da mesma base)."""
    t = (text or "").strip().lstrip("vV")
    base, _, pre = t.partition("-")
    pre = pre.split("+", 1)[0]
    base = base.split("+", 1)[0]
    nums = tuple(int(x) for x in re.findall(r"\d+", base)[:4]) or (0,)
    if len(nums) < 3:
        nums = nums + (0,) * (3 - len(nums))
    return nums, (0 if pre else 1), pre


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _ver(text: str) -> tuple[int, ...]:          # compatibilidade
    return parse_version(text)[0]


def current_version() -> str:
    try:
        from ..setup.state import app_version
        return str(app_version())
    except Exception:  # noqa: BLE001
        return "0.0.0"


# ---------------------------------------------------------------- HTTP (somente https)
class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Só segue redirecionamento HTTPS e NUNCA leva o Authorization para outro host (o armazenamento do GitHub recusa)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError(f"redirecionamento não-HTTPS recusado: {newurl[:60]}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlparse(newurl).netloc.lower() != urlparse(req.full_url).netloc.lower():
            new.remove_header("Authorization")
        return new


_opener = urllib.request.build_opener(_SafeRedirect)


def open_https(url: str, *, token: str = "", accept: str = "application/vnd.github+json", headers: dict | None = None,
               timeout: float = 15.0):
    if not url.lower().startswith("https://"):
        raise ValueError("somente HTTPS")
    h = {"Accept": accept, "User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    h.update(headers or {})
    return _opener.open(urllib.request.Request(url, headers=h), timeout=timeout)       # noqa: S310 - https verificado


def get_json(path: str, *, token: str = "", timeout: float = 15.0):
    with open_https(f"{API}/{path.lstrip('/')}", token=token, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gh_path() -> str | None:
    return shutil.which("gh")


def gh_json(path: str, timeout: float = 20.0):
    gh = gh_path()
    if not gh:
        return None
    out = subprocess.run([gh, "api", path], capture_output=True, text=True, timeout=timeout, creationflags=0x08000000,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        return None
    return json.loads(out.stdout)


# ---------------------------------------------------------------- consulta
def _pick_release(data, channel: str) -> dict | None:
    if isinstance(data, dict):
        return data
    best: dict | None = None
    for rel in data or []:
        if rel.get("draft"):
            continue
        if channel == "stable" and rel.get("prerelease"):
            continue
        if best is None or is_newer(str(rel.get("tag_name", "")), str(best.get("tag_name", ""))):
            best = rel
    return best


def _fetch(repo: str, channel: str, timeout: float) -> tuple[dict | None, str, str]:
    """-> (release, via, erro). Canal 'stable' usa /releases/latest (o GitHub ignora pré-lançamentos e rascunhos)."""
    path = f"repos/{repo}/releases/latest" if channel == "stable" else f"repos/{repo}/releases?per_page=15"
    err = ""
    for via in ("public", "token", "gh"):
        try:
            if via == "public":
                data = get_json(path, timeout=timeout)
            elif via == "token":
                tok = credstore.get_token()
                if not tok:
                    continue
                data = get_json(path, token=tok, timeout=timeout)
            else:
                data = gh_json(path, timeout)
                if data is None:
                    continue
            rel = _pick_release(data, channel)
            if rel is not None:
                return rel, via, ""
            err = "nenhuma versão publicada ainda"
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 429 or (exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0"):
                err = "limite de consultas do GitHub atingido; tente mais tarde"
            elif exc.code in (401, 403, 404):
                err = err or ("o repositório é privado (ou não existe) e não há acesso com login" if via == "public"
                              else "o token guardado não tem acesso a este repositório")
            else:
                err = f"o GitHub respondeu {exc.code}"
        except (urllib.error.URLError, OSError, TimeoutError):
            return None, "", "sem conexão com a internet"
        except (ValueError, subprocess.SubprocessError):
            err = err or "resposta inválida do GitHub"
    return None, "", err or "não consegui consultar as atualizações"


def _asset(a: dict) -> Asset:
    return Asset(str(a.get("name", "")), int(a.get("size") or 0), str(a.get("url") or ""),
                 str(a.get("browser_download_url") or ""), str(a.get("digest") or ""))


def check(repo: str = DEFAULT_REPO, timeout: float = 12.0, channel: str = "stable", current: str | None = None) -> UpdateInfo:
    """Consulta a release. ``current`` só existe para simular uma versão antiga em testes."""
    cur = current or current_version()
    rel, via, err = _fetch(repo, channel, timeout)
    if rel is None:
        hint = ""
        if "privado" in err or "token" in err:
            hint = ("Guarde um token do GitHub somente-leitura (Configurações > Atualizações) ou entre com `gh auth login` "
                    "neste computador.")
        return UpdateInfo(cur, error=err, hint=hint, repo=repo)
    tag = str(rel.get("tag_name") or rel.get("name") or "")
    latest = tag.lstrip("vV")
    assets = [_asset(a) for a in rel.get("assets", [])]
    exe = next((a for a in assets if _ASSET_RE.match(a.name)), None)
    sha = next((a for a in assets if exe and a.name.lower() == exe.name.lower() + ".sha256"), None)
    body = str(rel.get("body") or "")
    m = _BODY_HASH.search(body)
    return UpdateInfo(cur, latest, is_newer(latest, cur), str(rel.get("html_url") or ""), body[:6000], "", "", tag,
                      bool(rel.get("prerelease")), via, repo, exe, sha, m.group(1).lower() if m else "")
