"""Preparar o computador: o que o Eco precisa para rodar, o que falta e como resolver com um clique (sem Qt: testável).

Regras (vêm do usuário e do projeto):
* Só LER para checar. Instalar/baixar só quando a pessoa clica e confirma.
* Instalador de terceiros (Visual C++, Ollama): baixado SÓ do site oficial (lista de hosts), só por HTTPS, com retomada, e
  a ASSINATURA DIGITAL (Authenticode) conferida antes de rodar: `Status = Valid` e, quando conhecido, o nome do editor.
  Sem assinatura válida o instalador é apagado e nunca executado. Quem instala é o próprio instalador oficial.
* Modelos do Eco continuam pelo baixador do manifesto (SHA-256 obrigatório). Nada é pago; nada de admin salvo o runtime do
  Visual C++ (o Windows pede a permissão na tela, UAC).
* Ollama e LM Studio são OPCIONAIS: detectamos e sugerimos; o Eco não depende deles e nada é forçado.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from ctypes import wintypes
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable

from ..config import ROOT
from .manifest import Manifest, human_bytes, quick_present
from .state import state_dir

log = logging.getLogger("jarvis.setup.prereqs")
_NOWIN = 0x08000000
UA = "Eco-Setup"                                    # genérico: nada do usuário vai em cabeçalho


# ----------------------------------------------------------------------------- itens
@dataclass(frozen=True)
class Item:
    """Uma linha da tela 'Preparar o computador'. status: ok | warn | fail | info (opcional/informativo)."""
    key: str
    title: str
    status: str
    detail: str = ""
    hint: str = ""
    action: str = ""                 # "" = nada a fazer; senão a chave da ação (ver ACTIONS)
    action_label: str = ""
    optional: bool = False
    tool: str = ""                   # chave em core.toolpaths.CATALOG quando dá para PERSONALIZAR o caminho (botão Personalizar)
    version: str = ""                # versão encontrada
    where: str = ""                  # de onde veio: caminho personalizado, PATH, instalação padrão, pasta do Eco
    path: str = ""                   # onde foi achado
    custom: bool = False             # o caminho vem de configuração do usuário
    url: str = ""                    # site oficial (ação open_url)
    category: str = ""               # Sistema | Eco | Modelos | Agentes | Opcional
    config_key: str = ""             # campo do config que guarda o caminho (ex.: toolpaths.git)


@dataclass(frozen=True)
class Official:
    """Instalador de terceiro permitido (site oficial)."""
    key: str
    name: str
    url: str
    hosts: tuple[str, ...]           # hosts aceitos, inclusive nos redirecionamentos
    filename: str
    signer: str                      # parte do nome do editor que o certificado precisa ter ("" = qualquer assinatura válida, mostrada ao usuário)
    args: tuple[str, ...]
    elevate: bool                    # exige administrador (UAC)
    approx_bytes: int
    note: str = ""


VCREDIST = Official(
    "vcredist", "Microsoft Visual C++ Redistributable (x64)", "https://aka.ms/vs/17/release/vc_redist.x64.exe",
    ("aka.ms", "download.microsoft.com", "go.microsoft.com", "download.visualstudio.microsoft.com"), "vc_redist.x64.exe",
    "Microsoft Corporation", ("/install", "/quiet", "/norestart"), True, 25_000_000,
    "Biblioteca gratuita da Microsoft que o servidor do modelo precisa. O Windows vai pedir permissão de administrador.")
OLLAMA = Official(
    "ollama", "Ollama para Windows", "https://ollama.com/download/OllamaSetup.exe",
    ("ollama.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"), "OllamaSetup.exe",
    "", ("/VERYSILENT", "/NORESTART"), False, 1_000_000_000,
    "Opcional. Instala só para o seu usuário (sem administrador). O arquivo é grande.")
OFFICIAL: dict[str, Official] = {o.key: o for o in (VCREDIST, OLLAMA)}


# ----------------------------------------------------------------------------- checagens (só leitura)
def _sys32() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def check_vcruntime(sys32: Path | None = None) -> Item:
    s = sys32 or _sys32()
    need = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    missing = [n for n in need if not (s / n).is_file()]
    if not missing:
        return Item("vcruntime", "Biblioteca do Visual C++", "ok", "instalada (vcruntime140, msvcp140)")
    return Item("vcruntime", "Biblioteca do Visual C++", "fail", "faltam: " + ", ".join(missing),
                "O servidor do modelo precisa dela. É gratuita e vem do site oficial da Microsoft.",
                "install_vcredist", "Baixar e instalar (Microsoft)")


def vram_from_items(items: list[Item]) -> int:
    """Memória de vídeo (MB) lida do item da GPU ('..., 8.0 GB de memória de vídeo'); 0 se não houver."""
    import re
    for i in items:
        if i.key == "gpu":
            m = re.search(r"([\d.,]+) GB de memória", i.detail)
            if m:
                return int(float(m.group(1).replace(",", ".")) * 1024)
    return 0


def check_vulkan(llama_bin: Path) -> list[Item]:
    from . import hardware
    out: list[Item] = []
    for c in hardware.check_gpu(llama_bin):
        status = "ok" if c.status == "ok" else "warn"
        action = "open_gpu_driver" if c.status != "ok" else ""
        out.append(Item(c.key, c.title, status, c.detail, c.hint, action, "Abrir o site do fabricante" if action else ""))
    return out


def reach_host(host: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Conecta por HTTPS (TCP + TLS) ao host. Não envia nada além do handshake."""
    try:
        with socket.create_connection((host, 443), timeout=timeout) as raw:
            with ssl.create_default_context().wrap_socket(raw, server_hostname=host):
                return True, ""
    except ssl.SSLCertVerificationError as exc:
        return False, f"certificado inválido ({exc.verify_message})"
    except (OSError, ssl.SSLError) as exc:
        return False, str(exc) or exc.__class__.__name__


def manifest_hosts(manifest: Manifest) -> list[str]:
    hosts: list[str] = []
    for pkg in manifest.packages.values():
        for f in pkg.files:
            for u in f.urls:
                h = urllib.parse.urlparse(u).hostname
                if h and h not in hosts:
                    hosts.append(h)
    return hosts


def check_internet(hosts: Iterable[str], reach: Callable[[str], tuple[bool, str]] = reach_host) -> Item:
    hosts = list(hosts)[:4] or ["github.com"]
    bad = []
    for h in hosts:
        ok, why = reach(h)
        if not ok:
            bad.append(f"{h}: {why}")
    if not bad:
        return Item("internet", "Internet e servidores de download", "ok", "alcança " + ", ".join(hosts))
    status = "fail" if len(bad) == len(hosts) else "warn"
    return Item("internet", "Internet e servidores de download", status, "; ".join(bad),
                "Sem internet não dá para baixar modelos. Use o pacote offline (próxima etapa) ou conecte-se e verifique de novo.")


def check_folders(root: Path = ROOT) -> Item:
    problems = []
    for name in ("data", "models", "logs"):
        d = root / name
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / f".w{os.getpid()}"
            probe.write_bytes(b"x")
            probe.unlink()
        except OSError as exc:
            problems.append(f"{name}: {exc.strerror or exc}")
    if len(str(root)) > 120:
        problems.append("o caminho da instalação é muito longo")
    if problems:
        return Item("folders", "Pastas do Eco", "fail", "; ".join(problems),
                    "O Eco precisa gravar na própria pasta. Reinstale em uma pasta sua (ex.: Documentos) ou libere a permissão.")
    return Item("folders", "Pastas do Eco", "ok", f"gravação liberada em {root}")


def decorate(item: Item, tool: str, cfg=None) -> Item:
    """Acrescenta ao item onde a ferramenta está e de onde veio (para a tela mostrar e permitir Personalizar)."""
    from ..core import toolpaths
    d = toolpaths.BY_KEY[tool]
    f = toolpaths.resolve(tool, cfg)
    return replace(item, tool=tool, path=str(f.path) if f.path else "", where=f.source if f.path else "", category=d.category,
                   custom=toolpaths.is_custom(d, cfg), config_key=toolpaths.config_key(d), url=d.url)


def check_llama_server(llama_bin: Path) -> Item:
    from ..core import toolpaths
    found = toolpaths.resolve("llama_server").path
    if found is not None:
        llama_bin = found                                              # caminho personalizado (ou o padrão do config)
    exe = llama_bin / "llama-server.exe"
    if not exe.is_file():
        return Item("llama", "Servidor do modelo (llama.cpp)", "fail", f"ausente: {exe}",
                    "Reinstale o Eco ou use Reparar: o instalador traz este programa.", "repair", "Reparar", tool="llama_server",
                    category="Eco", config_key="paths.llama_bin")
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30, cwd=str(exe.parent), creationflags=_NOWIN)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Item("llama", "Servidor do modelo (llama.cpp)", "fail", f"não consegui executar: {exc}")
    if r.returncode in (3221225781, -1073741515):                                   # 0xC0000135 STATUS_DLL_NOT_FOUND
        return Item("llama", "Servidor do modelo (llama.cpp)", "fail", "o Windows não achou uma biblioteca necessária",
                    "Instale a biblioteca do Visual C++ (item acima).", "install_vcredist", "Baixar e instalar (Microsoft)")
    first = ((r.stdout + r.stderr).strip().splitlines() or ["versão desconhecida"])[-1][:90]
    return decorate(Item("llama", "Servidor do modelo (llama.cpp)", "ok" if r.returncode == 0 else "warn", first), "llama_server")


def check_models(manifest: Manifest, components: list[str], root: Path = ROOT) -> Item:
    files = manifest.files_for(components)
    missing = [f for f in files if not quick_present(f, root)]
    if not missing:
        return Item("models", "Modelos, voz e escuta", "ok", f"{len(files)} arquivo(s) presentes")
    need = sum(f.size for f in missing)
    return Item("models", "Modelos, voz e escuta", "fail", f"faltam {len(missing)} de {len(files)} arquivo(s), {human_bytes(need)}",
                "Cada arquivo é conferido por SHA-256 e o download continua de onde parou.", "download_models",
                f"Baixar o que falta ({human_bytes(need)})")


# ---- Ollama / LM Studio (opcionais)
OLLAMA_API = ("127.0.0.1", 11434)
LMSTUDIO_API = ("127.0.0.1", 1234)


def _local_get(host_port: tuple[str, int], path: str, timeout: float = 1.5):
    """GET em loopback (só 127.0.0.1). Devolve o JSON ou None."""
    import http.client
    try:
        c = http.client.HTTPConnection(host_port[0], host_port[1], timeout=timeout)
        c.request("GET", path, headers={"User-Agent": UA})
        r = c.getresponse()
        data = r.read(2_000_000)
        c.close()
        return json.loads(data) if r.status == 200 else None
    except (OSError, ValueError, http.client.HTTPException):
        return None


def ollama_exe() -> Path | None:
    from ..core import toolpaths                      # caminho personalizado primeiro, depois PATH e instalação padrão
    return toolpaths.resolve("ollama").path


def lmstudio_exe() -> Path | None:
    from ..core import toolpaths
    return toolpaths.resolve("lmstudio").path


@dataclass(frozen=True)
class SuggestedModel:
    tag: str
    approx_gb: float
    why: str


_OLLAMA_POOL = (SuggestedModel("llama3.2:3b", 2.0, "leve e rápido; bom para conversa e comandos"),
                SuggestedModel("gemma3:4b", 3.3, "equilibrado em português; entende imagens"),
                SuggestedModel("qwen2.5:7b", 4.7, "mais capaz em português e ferramentas; pede ~6 GB livres"),
                SuggestedModel("llama3.1:8b", 4.9, "o mais capaz desta lista; precisa de 8 GB de vídeo ou 16 GB de RAM"))


def _ollama_budget_gb(vram_mb: int, ram_gb: float) -> float:
    return (vram_mb / 1024 * 0.85) if vram_mb >= 3500 else max(0.0, ram_gb * 0.35)


def recommended_ollama_model(vram_mb: int, ram_gb: float) -> SuggestedModel:
    """O maior modelo que ocupa até ~60% do orçamento de memória: sobra espaço para o contexto e para o resto do sistema
    (com o modelo do próprio Eco ligado ao mesmo tempo, a memória de vídeo já é bem usada)."""
    budget = _ollama_budget_gb(vram_mb, ram_gb) * 0.6
    fit = [m for m in _OLLAMA_POOL if m.approx_gb <= budget]
    return fit[-1] if fit else _OLLAMA_POOL[0]


def suggest_ollama_models(vram_mb: int, ram_gb: float) -> list[SuggestedModel]:
    """Sugestões prudentes (quantização padrão do Ollama, Q4): cabem na memória de vídeo com folga. Tamanhos aproximados."""
    pool = list(_OLLAMA_POOL)
    budget_gb = _ollama_budget_gb(vram_mb, ram_gb)
    ok = [m for m in pool if m.approx_gb <= budget_gb] or pool[:1]
    return ok


def check_ollama(vram_mb: int = 0, ram_gb: float = 0.0) -> Item:
    return decorate(_check_ollama(vram_mb, ram_gb), "ollama")


def _check_ollama(vram_mb: int = 0, ram_gb: float = 0.0) -> Item:
    exe = ollama_exe()
    ver = _local_get(OLLAMA_API, "/api/version")
    caveat = ("Obs.: o Ollama só usa a GPU em placas NVIDIA ou AMD suportadas; a RX 580 não está na lista oficial e ele pode rodar "
              "na CPU (lento). O Eco já usa a sua GPU por Vulkan com o modelo embutido.")
    if exe is None and ver is None:
        return Item("ollama", "Ollama (opcional)", "info", "não instalado",
                    "Só instale se quiser testar modelos do Ollama. O Eco funciona sem ele. " + caveat,
                    "install_ollama", "Baixar do site oficial (opcional)", True)
    if ver is None:
        return Item("ollama", "Ollama (opcional)", "info", f"instalado em {exe}, serviço parado",
                    "Abra o Ollama pelo menu Iniciar para ele responder. " + caveat, optional=True)
    tags = _local_get(OLLAMA_API, "/api/tags") or {}
    names = [m.get("name", "?") for m in tags.get("models", []) if isinstance(m, dict)]
    sug = suggest_ollama_models(vram_mb, ram_gb)
    sugg = ", ".join(f"{m.tag} (~{m.approx_gb:.1f} GB)" for m in sug)
    detail = f"rodando (versão {ver.get('version', '?')}); " + (f"{len(names)} modelo(s): {', '.join(names[:5])}" if names else "nenhum modelo baixado")
    return Item("ollama", "Ollama (opcional)", "info", detail, f"Sugestões para a sua máquina: {sugg}. {caveat}",
                "ollama_pull", f"Baixar {recommended_ollama_model(vram_mb, ram_gb).tag}", True)


def check_lmstudio() -> Item:
    return decorate(_check_lmstudio(), "lmstudio")


def _check_lmstudio() -> Item:
    exe = lmstudio_exe()
    api = _local_get(LMSTUDIO_API, "/v1/models")
    if api is not None:
        n = len(api.get("data", [])) if isinstance(api, dict) else 0
        return Item("lmstudio", "LM Studio (opcional)", "info", f"servidor local ligado, {n} modelo(s)", optional=True)
    if exe is not None:
        return Item("lmstudio", "LM Studio (opcional)", "info", "instalado; servidor local desligado", optional=True)
    return Item("lmstudio", "LM Studio (opcional)", "info", "não instalado", "Opcional. O Eco não depende dele.", optional=True)


_COVERED = frozenset({"llama_server", "ollama", "lmstudio"})        # já têm checagem própria (com mais detalhe) acima


def _from_scan(s) -> Item:
    """Item da tela a partir de uma linha da varredura de ferramentas (core.toolpaths)."""
    action, label = "", ""
    if s.status in ("fail", "info", "warn"):
        if s.fix == "download_models" and s.status == "fail":
            action, label = "download_models", "Baixar o que falta"
        elif s.fix == "repair":
            action, label = "repair", "Reparar"
        elif s.fix == "open_url" and s.url and s.status in ("fail", "info"):
            action, label = "open_url", "Abrir o site oficial"
    return Item(s.key, s.title, s.status, s.detail, s.hint, action, label, s.optional, tool=s.key, version=s.version, where=s.where,
                path=s.path, custom=s.custom, url=s.url, category=s.category, config_key=s.config_key)


def run_checks(root: Path, manifest: Manifest, components: list[str], llama_bin: Path | None = None, *, vram_mb: int = 0,
               ram_gb: float = 0.0, with_network: bool = True, cfg=None, tools: bool = True) -> list[Item]:
    """Varredura TOTAL do PC para o Eco: pastas, bibliotecas, GPU, internet, modelos e cada programa do catálogo
    (git, PowerShell, Ollama, agentes...), com versão, onde foi achado e o que fazer."""
    from ..config import PathsCfg
    llama_bin = llama_bin or PathsCfg().llama_bin
    items: list[Item] = [check_folders(root), check_vcruntime()]
    items += check_vulkan(llama_bin)
    vram_mb = vram_mb or vram_from_items(items)
    items.append(check_llama_server(llama_bin))
    if with_network:
        items.append(check_internet(manifest_hosts(manifest)))
    items.append(check_models(manifest, components, root))
    items.append(check_ollama(vram_mb, ram_gb))
    items.append(check_lmstudio())
    if tools:
        from ..core import toolpaths
        items += [_from_scan(s) for s in toolpaths.scan_all(cfg) if s.key not in _COVERED]
    return items


def full_scan(root: Path, manifest: Manifest, components: list[str], *, cfg=None, ram_gb: float = 0.0) -> list[Item]:
    return run_checks(root, manifest, components, ram_gb=ram_gb, cfg=cfg)


_ST_TXT = {"ok": "OK", "warn": "AVISO", "fail": "FALTA", "info": "OPCIONAL"}


def full_report_text(items: list[Item]) -> str:
    lines = [f"Relatório do computador (Eco), {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for it in items:
        lines.append(f"[{_ST_TXT.get(it.status, it.status)}] {it.title}")
        if it.version:
            lines.append(f"    versão: {it.version}")
        if it.path:
            lines.append(f"    onde: {it.path}  ({it.where})")
        if it.detail:
            lines.append(f"    {it.detail}")
        if it.status in ("fail", "warn", "info") and it.hint:
            lines.append(f"    o que fazer: {it.hint}")
    lines += ["", f"Resumo: {sum(1 for i in items if i.status == 'ok')} ok, {sum(1 for i in items if i.status == 'warn')} aviso(s), "
                  f"{sum(1 for i in items if i.status == 'fail')} faltando, {sum(1 for i in items if i.status == 'info')} opcional(is)."]
    return "\n".join(lines)


def full_report_json(items: list[Item]) -> str:
    return json.dumps({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": [asdict(i) for i in items]}, ensure_ascii=False, indent=2)


def blocking(items: list[Item]) -> list[Item]:
    return [i for i in items if i.status == "fail"]


# ----------------------------------------------------------------------------- download oficial + assinatura
class PrepError(RuntimeError):
    """`kind`: host | https | net | disk | cancelled | signature | run. `message` é para mostrar (pt-BR)."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind, self.message = kind, message


class _AllowRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts: tuple[str, ...]) -> None:
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):                # type: ignore[no-untyped-def]
        u = urllib.parse.urlparse(newurl)
        if u.scheme != "https":
            raise PrepError("https", "O site tentou desviar o download para um endereço sem HTTPS. Recusado.")
        if not host_allowed(u.hostname or "", self.hosts):
            raise PrepError("host", f"O download foi desviado para {u.hostname}, que não é um site oficial permitido. Recusado.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def host_allowed(host: str, hosts: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in hosts)


def _open(url: str, hosts: tuple[str, ...], headers: dict[str, str], timeout: float = 30.0):
    """Abre a URL (patchável em testes). Só https e só hosts oficiais, inclusive nos redirecionamentos."""
    u = urllib.parse.urlparse(url)
    if u.scheme != "https":
        raise PrepError("https", "Só baixo por HTTPS.")
    if not host_allowed(u.hostname or "", hosts):
        raise PrepError("host", f"{u.hostname} não é um site oficial permitido para este download.")
    opener = urllib.request.build_opener(_AllowRedirect(hosts))
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    return opener.open(req, timeout=timeout)


def download_official(spec: Official, dest_dir: Path, progress: Callable[[int, int], None] | None = None,
                      cancel: threading.Event | None = None, *, opener=_open) -> Path:
    """Baixa o instalador oficial com retomada (`.part` + Range). Devolve o caminho do arquivo completo (ainda NÃO verificado)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / spec.filename
    part = dest_dir / (spec.filename + ".part")
    if dest.is_file():
        dest.unlink()
    for attempt in range(4):
        have = part.stat().st_size if part.is_file() else 0
        try:
            resp = opener(spec.url, spec.hosts, {"Range": f"bytes={have}-"} if have else {})
        except PrepError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and have:                         # já estava completo
                break
            raise PrepError("net", f"O site respondeu {exc.code}.") from exc
        except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
            if attempt == 3:
                raise PrepError("net", "Sem conexão com o site oficial. Verifique a internet e tente de novo; o download continua de onde parou.") from exc
            time.sleep((1, 3, 8)[attempt])
            continue
        status = getattr(resp, "status", 200)
        total = int(resp.headers.get("Content-Length") or 0)
        if status == 206:
            rng = resp.headers.get("Content-Range", "")
            total = int(rng.rsplit("/", 1)[-1]) if "/" in rng and rng.rsplit("/", 1)[-1].isdigit() else have + total
            mode = "ab"
        else:
            have, mode = 0, "wb"                                  # servidor ignorou o Range: recomeça
        free = shutil.disk_usage(dest_dir).free
        if total and total - have + 64 * 1024 * 1024 > free:
            raise PrepError("disk", f"Espaço insuficiente: precisa de {human_bytes(total - have)} e há {human_bytes(free)}.")
        try:
            with open(part, mode) as f:
                done = have
                while True:
                    if cancel is not None and cancel.is_set():
                        raise PrepError("cancelled", "Download pausado. Dá para continuar depois.")
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total or done)
        except (OSError, ssl.SSLError) as exc:
            if attempt == 3:
                raise PrepError("net", "A conexão caiu no meio do download. Tente de novo; ele continua de onde parou.") from exc
            continue
        finally:
            try:
                resp.close()
            except Exception:                                    # noqa: BLE001
                pass
        break
    if not part.is_file() or part.stat().st_size == 0:
        raise PrepError("net", "O download não trouxe dados.")
    os.replace(part, dest)
    return dest


@dataclass(frozen=True)
class Signature:
    valid: bool
    status: str
    subject: str
    thumbprint: str
    detail: str = ""


def verify_authenticode(path: Path, expect_signer: str = "") -> Signature:
    """Confere a assinatura digital (Authenticode) do arquivo. `valid` só é True com Status Valid (arquivo íntegro e cadeia
    confiável) E, se `expect_signer`, com esse nome no certificado do editor."""
    ps = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; $s = Get-AuthenticodeSignature -LiteralPath $env:ECO_VERIFY_PATH; "
          "[pscustomobject]@{Status=[string]$s.Status; Subject=[string]$s.SignerCertificate.Subject; "
          "Thumb=[string]$s.SignerCertificate.Thumbprint; Msg=[string]$s.StatusMessage} | ConvertTo-Json -Compress")
    try:
        # PSModulePath herdado de um PowerShell 7 impede o Windows PowerShell 5.1 de carregar o módulo de segurança: limpa para o padrão
        env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
        env["ECO_VERIFY_PATH"] = str(path)
        exe = _sys32() / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        r = subprocess.run([str(exe) if exe.is_file() else "powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, creationflags=_NOWIN, env=env)
        data = json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
        return Signature(False, "Erro", "", "", f"não consegui conferir a assinatura: {exc}")
    if not data.get("Status"):
        return Signature(False, "Erro", "", "", f"o Windows não devolveu o resultado da assinatura: {(r.stderr or '').strip()[:200]}")
    status, subject = data.get("Status", ""), data.get("Subject", "") or ""
    ok = status == "Valid" and bool(subject)
    if ok and expect_signer and expect_signer.lower() not in subject.lower():
        ok = False
        status = "EditorInesperado"
    return Signature(ok, status, subject, data.get("Thumb", "") or "", data.get("Msg", "") or "")


def signer_name(subject: str) -> str:
    cn = ""
    for part in subject.split(","):
        part = part.strip()
        if part.upper().startswith("O="):
            return part[2:].strip('" ')
        if part.upper().startswith("CN=") and not cn:
            cn = part[3:].strip('" ')
    return cn or subject


def fetch_verified(spec: Official, dest_dir: Path, progress: Callable[[int, int], None] | None = None,
                   cancel: threading.Event | None = None, *, opener=_open) -> tuple[Path, Signature]:
    """Baixa e confere a assinatura. Se não for válida, APAGA o arquivo e levanta PrepError('signature')."""
    path = download_official(spec, dest_dir, progress, cancel, opener=opener)
    sig = verify_authenticode(path, spec.signer)
    if not sig.valid:
        try:
            path.unlink()
        except OSError:
            pass
        raise PrepError("signature", f"A assinatura digital do instalador NÃO é válida ({sig.status}). Ele foi apagado e não será executado.")
    return path, sig


def sha256_of(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------- executar o instalador
def run_installer(path: Path, args: tuple[str, ...], *, elevate: bool, timeout: float = 900.0) -> int:
    """Roda o instalador oficial e devolve o código de saída. Com `elevate` o Windows mostra o pedido de administrador (UAC)."""
    if not sys.platform.startswith("win"):
        raise PrepError("run", "Só no Windows.")
    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040 | 0x00008000                          # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    info.lpVerb = "runas" if elevate else "open"
    info.lpFile = str(path)
    info.lpParameters = " ".join(args)
    info.lpDirectory = str(path.parent)
    info.nShow = 0
    sh = ctypes.windll.shell32
    if not sh.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error() or ctypes.GetLastError()
        if err == 1223:                                           # ERROR_CANCELLED: a pessoa negou o UAC
            raise PrepError("cancelled", "Você não deu a permissão do Windows. Nada foi instalado.")
        raise PrepError("run", f"O Windows não conseguiu abrir o instalador (erro {err}).")
    k32 = ctypes.windll.kernel32
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    r = k32.WaitForSingleObject(info.hProcess, int(timeout * 1000))
    if r != 0:
        k32.CloseHandle(info.hProcess)
        raise PrepError("run", "O instalador demorou demais e não foi encerrado por mim.")
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    k32.CloseHandle(info.hProcess)
    return int(code.value)


INSTALL_OK_CODES = {0: "instalado", 1638: "já havia uma versão igual ou mais nova", 3010: "instalado; reinicie o Windows quando puder"}


# ----------------------------------------------------------------------------- Ollama: baixar modelo (API local)
def ollama_pull(tag: str, progress: Callable[[str, int, int], None] | None = None, cancel: threading.Event | None = None) -> None:
    """Pede ao Ollama (loopback) para baixar o modelo. O próprio Ollama confere os arquivos. Só 127.0.0.1."""
    import http.client
    if not tag or any(c in tag for c in " /\\\"'") or len(tag) > 80:
        raise PrepError("run", "Nome de modelo inválido.")
    try:
        c = http.client.HTTPConnection(*OLLAMA_API, timeout=600)
        c.request("POST", "/api/pull", body=json.dumps({"model": tag, "stream": True}), headers={"Content-Type": "application/json", "User-Agent": UA})
        r = c.getresponse()
        if r.status != 200:
            raise PrepError("net", f"O Ollama respondeu {r.status}: {r.read(300).decode('utf-8', 'replace')}")
        while True:
            if cancel is not None and cancel.is_set():
                c.close()
                raise PrepError("cancelled", "Download do modelo interrompido.")
            line = r.readline()
            if not line:
                break
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("error"):
                raise PrepError("net", f"O Ollama recusou: {d['error']}")
            if progress:
                progress(str(d.get("status", "")), int(d.get("completed") or 0), int(d.get("total") or 0))
        c.close()
    except (OSError, http.client.HTTPException) as exc:
        raise PrepError("net", "Não consegui falar com o Ollama. Abra o Ollama e tente de novo.") from exc


# ----------------------------------------------------------------------------- relatório
def write_report(root: Path, items: list[Item], events: list[str] | None = None) -> Path:
    """Relatório para suporte: o que foi checado e feito. Sem caminhos pessoais além da pasta de instalação, sem segredos."""
    d = state_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "prepare-report.json"
    data = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": [asdict(i) for i in items], "events": events or []}
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix="prepare-report.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    txt = full_report_text(items) + ("\n\nO que foi feito nesta sessão:\n- " + "\n- ".join(events) if events else "") + "\n"
    (d / "prepare-report.txt").write_text(txt, encoding="utf-8")                 # a mesma coisa para ler/enviar sem programa
    return path


def gpu_driver_url(gpu_name: str) -> str:
    n = gpu_name.lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "gtx" in n:
        return "https://www.nvidia.com/Download/index.aspx"
    if "intel" in n or "arc" in n or "uhd" in n or "iris" in n:
        return "https://www.intel.com/content/www/us/en/download-center/home.html"
    return "https://www.amd.com/en/support/download/drivers.html"
