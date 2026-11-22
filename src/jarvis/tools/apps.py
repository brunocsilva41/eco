"""Ferramentas de aplicativos: abrir apps da allowlist e listar quais podem ser abertos."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any, Final

from ..config import Config
from ..core.textutil import fold
from ._matching import best_matches
from .registry import Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec

log = logging.getLogger(__name__)

_FUZZY_CUTOFF = 0.72
ALLOWED_URI_SCHEMES: Final = frozenset({"ms-settings"})
_URI: Final = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]+):")     # 2+ caracteres: uma letra só é unidade (C:)


def _system_dirs() -> tuple[Path, ...]:
    """Únicas pastas onde se procura executável sem caminho: System32 e a raiz do Windows (%SystemRoot%)."""
    root = Path(os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows")
    return (root / "System32", root)


def _find_system_exe(name: str, dirs: tuple[Path, ...]) -> Path | None:
    """Procura `name` (sem caminho) só nas pastas dadas, nunca no diretório atual nem no PATH."""
    suffixes = ("",) if Path(name).suffix else (".exe", ".com")
    for directory in dirs:
        for suffix in suffixes:
            candidate = directory / (name + suffix)
            if candidate.is_file():
                return candidate
    return None


def _default_browser_exe() -> str | None:
    """Executável do navegador padrão do Windows (HKCU UrlAssociations https -> ProgId -> comando). Só aceita .exe existente
    dentro de Program Files, Program Files (x86) ou %LocalAppData%; qualquer outra coisa vira None (fora da allowlist)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
            prog_id = str(winreg.QueryValueEx(k, "ProgId")[0])
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command") as k:
            command = str(winreg.QueryValueEx(k, "")[0])
    except OSError:
        return None
    m = re.match(r'\s*"([^"]+)"', command) or re.match(r"\s*(\S+\.exe)", command, re.I)
    if not m:
        return None
    exe = Path(m.group(1))
    roots = [os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData")]
    allowed = [Path(r).resolve() for r in roots if r]
    try:
        resolved = exe.resolve()
    except OSError:
        return None
    if resolved.suffix.lower() != ".exe" or not resolved.is_file() or not any(a in resolved.parents for a in allowed):
        return None
    return str(resolved)


def _resolve_target(name: str, target: str, dirs: tuple[Path, ...]) -> str | None:
    """Alvo da configuração -> caminho absoluto (ou URI de esquema permitido). None = fora da allowlist."""
    if target.strip().lower() == "default-browser":
        found_browser = _default_browser_exe()
        if found_browser is None:
            log.warning("apps.launch: %r -> não achei o navegador padrão em Program Files/LocalAppData; ignorado", name)
        return found_browser
    scheme = _URI.match(target)
    if scheme:
        if scheme.group(1).lower() not in ALLOWED_URI_SCHEMES:
            log.warning("apps.launch: %r usa o esquema %r, não permitido (%s); ignorado",
                        name, scheme.group(1), ", ".join(sorted(ALLOWED_URI_SCHEMES)))
            return None
        return target
    path = PureWindowsPath(target)
    if target.startswith(("\\\\", "//")):
        log.warning("apps.launch: %r aponta para caminho de rede; ignorado", name)
        return None
    if path.is_absolute():
        if not Path(target).is_file():
            log.warning("apps.launch: %r -> %s não existe; ignorado", name, target)
            return None
        return str(Path(target))
    if path.drive or len(path.parts) != 1:                  # relativo com pasta/unidade: não há como resolver com segurança
        log.warning("apps.launch: %r -> %r é caminho relativo; use caminho absoluto. Ignorado", name, target)
        return None
    found = _find_system_exe(target, dirs)
    if found is None:
        log.warning("apps.launch: %r -> %r não foi achado em %s; ignorado",
                    name, target, ", ".join(str(d) for d in dirs))
        return None
    return str(found)


def _allowlist(cfg: Config) -> dict[str, str]:
    """Nome falado -> alvo ABSOLUTO resolvido agora. Nomes repetidos após a normalização: vale o primeiro."""
    dirs = _system_dirs()
    index: dict[str, tuple[str, str]] = {}
    for name, target in cfg.apps.launch.items():
        key = fold(name)
        if not key or not target.strip():
            log.warning("apps.launch: entrada inválida ignorada: %r", name)
            continue
        if key in index:
            log.warning("apps.launch: %r repete %r após normalizar; ignorado", name, index[key][0])
            continue
        resolved = _resolve_target(name, target.strip(), dirs)
        if resolved is None:
            continue
        log.info("apps.launch: %r -> %s", name, resolved)
        index[key] = (name, resolved)
    return {name: target for name, target in index.values()}


def register(registry: ToolRegistry, cfg: Config) -> None:
    apps = _allowlist(cfg)
    names = list(apps)

    def abrir_app(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = str(args["nome"])
        matches = best_matches(query, names, key=lambda n: n, query_contains_item=True,
                               fuzzy_cutoff=_FUZZY_CUTOFF)
        if not matches:
            return ToolResult(False, f"Não tenho permissão para abrir '{query.strip()[:40]}'. "
                                     f"Posso abrir: {', '.join(names) or 'nenhum app'}.",
                              data={"apps": names})
        if len(matches) > 1:
            return ToolResult(False, "Qual deles? " + ", ".join(matches) + ".", data={"opcoes": matches})
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        name = matches[0]
        try:
            # Alvo = caminho absoluto resolvido na partida; nenhum argumento do modelo é repassado ao programa.
            os.startfile(apps[name])  # noqa: S606 - allowlist, sem shell
        except OSError as exc:
            log.warning("falha ao abrir %r: %s", name, exc)
            return ToolResult(False, f"Não consegui abrir {name}.")
        return ToolResult(True, f"Abri {name}.")

    def listar_apps_permitidos(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if not names:
            return ToolResult(True, "Nenhum aplicativo está liberado para abrir.", data={"apps": []})
        return ToolResult(True, "Posso abrir: " + ", ".join(names) + ".", data={"apps": names})

    registry.register(ToolSpec(
        name="abrir_app",
        description=("Abre um aplicativo do computador pelo nome, por exemplo 'bloco de notas' ou "
                     "'calculadora'. Só funciona com os apps da lista permitida "
                     "(veja listar_apps_permitidos)."),
        parameters={
            "type": "object",
            "properties": {"nome": {"type": "string", "minLength": 1, "maxLength": 60,
                                    "description": "Nome falado do aplicativo."}},
            "required": ["nome"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=abrir_app,
        confirm_text=lambda a: f"Abrir o aplicativo {str(a.get('nome', ''))[:60]}",
    ))
    registry.register(ToolSpec(
        name="listar_apps_permitidos",
        description="Diz quais aplicativos o Jarvis pode abrir. Use quando perguntarem o que ele consegue abrir.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        risk=Risk.READ,
        handler=listar_apps_permitidos,
    ))
