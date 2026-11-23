"""Atualização automática: estado (ignorar/lembrar depois), agenda, download com retomada, SHA-256 e instalação por cima.

Regras de segurança (não negociáveis):
- só HTTPS (o redirecionamento também); o Authorization nunca vai para outro host;
- o instalador SÓ roda depois de o SHA-256 do arquivo baixado bater com o publicado na release (arquivo `.exe.sha256` e/ou
  `digest` da API e/ou corpo da release; se mais de uma fonte existir, TODAS precisam concordar). Sem hash: não instala;
- o hash é conferido de novo pelo script auxiliar imediatamente antes de executar o instalador;
- nunca mata processo: o núcleo é encerrado pelo canal normal (`quit_cb`) e o script espera por PID; sem `quit_cb`, o Inno
  Setup fecha o Eco pelo Restart Manager (`/CLOSEAPPLICATIONS`);
- só instala por cima de uma instalação (pasta com `runtime\\python\\pythonw.exe`); a árvore de desenvolvimento é recusada.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import credstore, updates
from .updates import Asset, UpdateInfo

log = logging.getLogger(__name__)

CHUNK = 1 << 20
_HEX = re.compile(r"[0-9a-fA-F]{64}")
Progress = Callable[[int, int], None]          # (bytes baixados, total)


class UpdateError(RuntimeError):
    """Erro com mensagem pronta para o usuário (pt-BR)."""


# ---------------------------------------------------------------- estado
@dataclass
class UpdateState:
    ignored_version: str = ""
    snooze_until: float = 0.0
    last_check: float = 0.0
    last_seen: str = ""


def updates_dir(data_dir: Path) -> Path:
    d = Path(data_dir) / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_state(data_dir: Path) -> UpdateState:
    try:
        raw = json.loads((updates_dir(data_dir) / "state.json").read_text(encoding="utf-8"))
        return UpdateState(**{k: raw[k] for k in UpdateState.__dataclass_fields__ if k in raw})
    except (OSError, ValueError, TypeError):
        return UpdateState()


def save_state(data_dir: Path, st: UpdateState) -> None:
    p = updates_dir(data_dir) / "state.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(st), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def ignore_version(data_dir: Path, version: str) -> None:
    st = load_state(data_dir)
    st.ignored_version = version
    save_state(data_dir, st)


def snooze(data_dir: Path, hours: float = 24.0, now: float | None = None) -> None:
    st = load_state(data_dir)
    st.snooze_until = (now if now is not None else time.time()) + hours * 3600
    save_state(data_dir, st)


def should_notify(info: UpdateInfo, st: UpdateState, now: float | None = None) -> bool:
    """Pop-up automático só se há versão nova, não foi ignorada e o «Lembrar depois» já venceu."""
    now = time.time() if now is None else now
    return bool(info.available and not info.error and info.latest != st.ignored_version and now >= st.snooze_until)


def should_check_now(cfg, st: UpdateState, *, startup: bool, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    u = cfg.updates
    if not u.enabled:
        return False
    if startup:
        return bool(u.check_on_start)
    return now - st.last_check >= u.interval_hours * 3600


def run_check(cfg, *, current: str | None = None, mark: bool = True) -> UpdateInfo:
    """Consulta e grava `last_check`/`last_seen`. Não decide pop-up (use `should_notify`)."""
    info = updates.check(cfg.updates.repo, channel=cfg.updates.channel, current=current)
    if mark and not info.error:
        try:
            st = load_state(cfg.paths.data)
            st.last_check = time.time()
            st.last_seen = info.latest
            save_state(cfg.paths.data, st)
        except OSError:
            log.warning("não consegui gravar o estado das atualizações", exc_info=True)
    return info


# ---------------------------------------------------------------- hash esperado
def _norm_hash(text: str) -> str:
    m = _HEX.search(text or "")
    return m.group(0).lower() if m else ""


def _fetch_small(asset: Asset, info: UpdateInfo) -> bytes:
    """Baixa um arquivo pequeno (.sha256) pelas mesmas vias do instalador."""
    buf = bytearray()
    for chunk in _stream(asset, info, 0, None):
        buf += chunk
        if len(buf) > 4096:
            raise UpdateError("o arquivo .sha256 é grande demais")
    return bytes(buf)


def expected_sha256(info: UpdateInfo) -> str:
    """SHA-256 publicado. Várias fontes precisam concordar; nenhuma fonte = erro (nunca instala sem hash)."""
    found: dict[str, str] = {}
    if info.hash_asset is not None:
        try:
            h = _norm_hash(_fetch_small(info.hash_asset, info).decode("utf-8", "ignore"))
            if h:
                found["arquivo .sha256"] = h
        except (UpdateError, OSError, urllib.error.URLError):
            log.warning("não consegui ler o .sha256 da release", exc_info=True)
    if info.installer is not None and info.installer.digest.lower().startswith("sha256:"):
        h = _norm_hash(info.installer.digest[7:])
        if h:
            found["digest do GitHub"] = h
    if info.body_sha256:
        found["notas da release"] = info.body_sha256.lower()
    if not found:
        raise UpdateError("a release não traz o SHA-256 do instalador; por segurança não vou instalar")
    if len(set(found.values())) > 1:
        raise UpdateError("os SHA-256 publicados não concordam entre si (" + ", ".join(found) + "); recusado por segurança")
    return next(iter(found.values()))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- download
def _stream(asset: Asset, info: UpdateInfo, start: int, cancel: threading.Event | None):
    """Gera blocos de bytes de `asset` a partir de `start` (retomada por Range). Tenta público -> token -> gh.

    O primeiro bloco gerado depois de `start > 0` é garantido ser a continuação; se o servidor ignorar o Range, levanta
    `_NoResume` e o chamador recomeça do zero.
    """
    last_err: Exception | None = None
    routes: list[str] = []
    if info.via == "public" and asset.browser_url:
        routes.append("public")
    if asset.api_url:
        if credstore.has_token():
            routes.append("token")
        if updates.gh_path():
            routes.append("gh")
    if asset.browser_url and "public" not in routes:
        routes.append("public")
    for route in routes:
        try:
            yield from _route(route, asset, start, cancel)
            return
        except _NoResume:
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError, UpdateError) as exc:
            last_err = exc
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404):
                continue
            if isinstance(exc, (urllib.error.URLError, OSError)) and not isinstance(exc, urllib.error.HTTPError):
                raise UpdateError("sem conexão com a internet (o download pode ser retomado depois)") from exc
            raise UpdateError(f"falha no download: {exc}") from exc
    if isinstance(last_err, urllib.error.HTTPError):
        raise UpdateError("sem acesso ao arquivo da release: repositório privado exige token somente-leitura ou `gh` logado")
    raise UpdateError("nenhuma via de download disponível (sem URL pública, token ou `gh`)")


class _NoResume(Exception):
    pass


def _route(route: str, asset: Asset, start: int, cancel: threading.Event | None):
    rng = {"Range": f"bytes={start}-"} if start else {}
    if route == "gh":
        gh = updates.gh_path()
        cmd = [gh, "api", "-H", "Accept: application/octet-stream"]
        for k, v in rng.items():
            cmd += ["-H", f"{k}: {v}"]
        cmd.append(asset.api_url.replace(updates.API + "/", "", 1))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000)
        got = 0
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("download cancelado")
                b = proc.stdout.read(CHUNK)          # type: ignore[union-attr]
                if not b:
                    break
                got += len(b)
                yield b
            code = proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()                           # nosso próprio filho `gh`, não é processo alheio
            for pipe in (proc.stdout, proc.stderr):
                try:
                    pipe.close()                      # type: ignore[union-attr]
                except OSError:
                    pass
        if code != 0:
            if got > 0:                                   # ja baixou bytes: foi a conexao que caiu, nao falta de acesso
                raise UpdateError("a conexão caiu no meio do download (os bytes já baixados ficam guardados e o download continua de onde parou)")
            raise urllib.error.HTTPError(asset.api_url, 404, "gh falhou", None, None)  # type: ignore[arg-type]
        if start and got == 0:
            return
        return
    token = credstore.get_token() if route == "token" else ""
    url = asset.api_url if route == "token" else asset.browser_url
    accept = "application/octet-stream" if route == "token" else "*/*"
    resp = updates.open_https(url, token=token, accept=accept, headers=rng, timeout=30.0)
    with resp:
        status = getattr(resp, "status", 200)
        if start and status != 206:
            raise _NoResume()
        while True:
            if cancel is not None and cancel.is_set():
                raise UpdateError("download cancelado")
            b = resp.read(CHUNK)
            if not b:
                break
            yield b


def download(info: UpdateInfo, dest_dir: Path, progress: Progress | None = None,
             cancel: threading.Event | None = None) -> Path:
    """Baixa o instalador com retomada (`.part`), confere o SHA-256 e só então o renomeia para `.exe`. Devolve o caminho."""
    a = info.installer
    if a is None:
        raise UpdateError("a release não traz o instalador (Eco-Setup-*.exe)")
    for u in (a.api_url, a.browser_url):
        if u and not u.lower().startswith("https://"):
            raise UpdateError("endereço do instalador não é HTTPS; recusado")
    want = expected_sha256(info)                    # sem hash publicado nem começa a baixar
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / a.name
    if final.exists() and sha256_file(final) == want:
        if progress:
            progress(a.size, a.size)
        return final
    final.unlink(missing_ok=True)
    part = dest_dir / (a.name + ".part")
    for attempt in range(2):
        have = part.stat().st_size if part.exists() else 0
        if a.size and have > a.size:
            part.unlink(missing_ok=True)
            have = 0
        try:
            if not (a.size and have == a.size):
                mode = "ab" if have else "wb"
                with open(part, mode) as f:
                    for b in _stream(a, info, have, cancel):
                        f.write(b)
                        have += len(b)
                        if progress:
                            progress(have, a.size)
            break
        except _NoResume:
            part.unlink(missing_ok=True)             # servidor ignorou o Range: recomeça do zero
            if attempt:
                raise UpdateError("o servidor não aceita retomada; tente de novo") from None
    got = sha256_file(part)
    if got != want:
        part.unlink(missing_ok=True)
        raise UpdateError("o SHA-256 do arquivo baixado NÃO confere com o publicado; arquivo descartado, nada foi instalado")
    if a.size and part.stat().st_size != a.size:
        part.unlink(missing_ok=True)
        raise UpdateError("tamanho do arquivo baixado difere do publicado; descartado")
    os.replace(part, final)
    (dest_dir / (a.name + ".sha256")).write_text(f"{want}  {a.name}\n", encoding="ascii")
    return final


# ---------------------------------------------------------------- instalação por cima
def install_root() -> Path | None:
    """Pasta da instalação em execução (com `runtime\\python\\pythonw.exe`) ou None se for árvore de desenvolvimento."""
    from ..config import ROOT
    return ROOT if (ROOT / "runtime" / "python" / "pythonw.exe").is_file() else None


_PS_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$Exe='@EXE@'; $Sha='@SHA@'; $Dir='@DIR@'; $Log='@LOG@'; $Result='@RESULT@'; $Relaunch='@RELAUNCH@'; $Pids='@PIDS@'; $Ver='@VER@'; $Lnk='@LNK@'
function Out-Result($code,$msg){ @{code=$code;message=$msg;version=$Ver;time=(Get-Date).ToString("s")} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $Result }
$work = $null
try {
  foreach($p in ($Pids -split ",")){ if($p){ $pr = Get-Process -Id ([int]$p) -ErrorAction SilentlyContinue
    if($pr){ if(-not $pr.WaitForExit(90000)){ Out-Result 902 "o Eco não fechou em 90 s; instalação cancelada (nada foi alterado)"; exit 2 } } } }
  if((Get-FileHash -Algorithm SHA256 -LiteralPath $Exe).Hash.ToLower() -ne $Sha.ToLower()){ Out-Result 903 "SHA-256 do instalador mudou; instalação recusada"; exit 3 }
  $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  $run = $Exe
  if($admin){   # elevado: copia para pasta só de administrador e confere o hash da CÓPIA (fecha a janela de troca do arquivo)
    $work = Join-Path $env:windir ("Temp\eco-upd-" + [guid]::NewGuid().ToString("N")); New-Item -ItemType Directory -Path $work | Out-Null
    $run = Join-Path $work (Split-Path $Exe -Leaf); Copy-Item -LiteralPath $Exe -Destination $run
    if((Get-FileHash -Algorithm SHA256 -LiteralPath $run).Hash.ToLower() -ne $Sha.ToLower()){ Out-Result 904 "SHA-256 do instalador mudou depois da elevação; instalação recusada"; exit 4 }
  }
  $a = @("/VERYSILENT","/NORESTART","/SUPPRESSMSGBOXES","/CLOSEAPPLICATIONS","/DIR=`"$Dir`"","/LOG=`"$Log`"")
  $pc = Start-Process -FilePath $run -ArgumentList $a -Wait -PassThru
  if($pc.ExitCode -ne 0){ Out-Result $pc.ExitCode "o instalador terminou com o código $($pc.ExitCode)"; exit 1 }
  Out-Result 0 "ok"
  if($Relaunch){   # relança como usuário NORMAL (não elevado): o explorer.exe abre o atalho com o token do usuário
    $ws = New-Object -ComObject WScript.Shell; $l = $ws.CreateShortcut($Lnk)
    $l.TargetPath = (Join-Path $Dir "runtime\python\pythonw.exe"); $l.Arguments = '-I -X utf8 "' + (Join-Path $Dir "Eco.pyw") + '"'; $l.WorkingDirectory = $Dir; $l.Save()
    Start-Process -FilePath "explorer.exe" -ArgumentList ('"' + $Lnk + '"')
  }
} catch { Out-Result 901 $_.Exception.Message; exit 1 }
finally { if($work){ Remove-Item -Recurse -Force -LiteralPath $work -ErrorAction SilentlyContinue } }
"""


def can_write(path: Path) -> bool:
    import time as _t
    probe = path / ".jarvis_write_probe"
    for attempt in range(4):                       # antivirus/indexador podem travar o arquivo por instantes: nao confundir com falta de permissao
        try:
            probe.write_text("x")
            probe.unlink()
            return True
        except PermissionError:
            if attempt == 3:
                return False
            _t.sleep(0.4)
        except OSError:
            return False
    return False


def needs_elevation(target: Path) -> bool:
    """True quando a pasta da instalação não aceita escrita do usuário (Program Files / «para todos os usuários»)."""
    return not can_write(Path(target))


class UacDeclined(UpdateError):
    """O usuário recusou o pedido do Windows (UAC). O download continua guardado: dá para tentar de novo."""


def _q(text: object) -> str:
    return str(text).replace("'", "''")


def build_script(exe: Path, want: str, target: Path, log_path: Path, result: Path, lnk: Path, relaunch: bool,
                 pids: str, version: str) -> str:
    repl = {"@EXE@": exe, "@SHA@": want, "@DIR@": target, "@LOG@": log_path, "@RESULT@": result,
            "@RELAUNCH@": "1" if relaunch else "", "@PIDS@": pids, "@VER@": version, "@LNK@": lnk}
    out = _PS_SCRIPT
    for k, v in repl.items():
        out = out.replace(k, _q(v))
    return out


def _encoded(script: str) -> str:
    import base64
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def shell_runas(file: str, params: str) -> int:
    """ShellExecuteW com o verbo 'runas' (UAC). >32 = o Windows aceitou lançar; <=32 = recusado/erro."""
    import ctypes
    return int(ctypes.windll.shell32.ShellExecuteW(None, "runas", file, params, None, 0))   # 0 = SW_HIDE


def install(exe: Path, info: UpdateInfo, data_dir: Path, *, quit_cb: Callable[[], object] | None = None,
            target_dir: Path | None = None, relaunch: bool = True, wait_pids: tuple[int, ...] = (),
            dry_run: bool = False, elevate: bool | None = None) -> dict:
    """Confere o hash, monta o script auxiliar EM MEMÓRIA (`-EncodedCommand`: nada em disco que um processo comum possa trocar
    antes de rodar elevado) e o lança desacoplado. Sem permissão de escrita na pasta pede elevação (UAC, `runas`).

    `elevate`: força (True/False) ou detecta (None). Recusa do UAC -> `UacDeclined` e o Eco NÃO é fechado.
    Devolve {'log','result','elevated','cmd','script'}; `dry_run` só valida e monta."""
    want = expected_sha256(info)
    if not exe.is_file() or sha256_file(exe) != want:
        raise UpdateError("o instalador baixado não confere com o SHA-256 publicado; não vou executá-lo")
    target = target_dir or install_root()
    if target is None:
        raise UpdateError("Este Eco está rodando direto da pasta de desenvolvimento (não foi instalado pelo instalador), "
                          "então não há instalação para atualizar. A atualização automática vale para a versão instalada.")
    if not (Path(target) / "runtime" / "python" / "pythonw.exe").is_file():
        raise UpdateError("a pasta de destino não parece uma instalação do Eco")
    elevated = needs_elevation(Path(target)) if elevate is None else bool(elevate)
    d = updates_dir(data_dir)
    log_path, result, lnk = d / "installer.log", d / "last_install.json", d / "relaunch.lnk"
    result.unlink(missing_ok=True)
    pids = ",".join(str(p) for p in dict.fromkeys(wait_pids) if p)
    script = build_script(exe, want, Path(target), log_path, result, lnk, relaunch, pids, info.latest)
    params = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-EncodedCommand", _encoded(script)]
    out = {"log": str(log_path), "result": str(result), "elevated": elevated, "cmd": ["powershell.exe", *params],
           "script": script}
    if dry_run:
        return out
    if elevated:
        rc = shell_runas("powershell.exe", " ".join(params))
        if rc <= 32:
            raise UacDeclined("O Windows pediu permissão de administrador e ela não foi concedida. Nada foi alterado e o "
                              "download continua guardado: clique em «Tentar de novo» quando quiser.")
    else:
        diag = open(d / "apply.out.txt", "wb")
        # Se o Eco foi aberto de um terminal PowerShell 7 (pwsh), o PSModulePath herdado aponta para modulos do 7 e o
        # Windows PowerShell 5.1 do instalador nao acha Get-FileHash ("termo nao reconhecido", codigo 901). Limpa so isso.
        env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
        try:
            base = 0x08000000 | 0x00000200            # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP (DETACHED_PROCESS mata o PowerShell)
            try:                                      # sai do "job" do processo pai
                subprocess.Popen(out["cmd"], creationflags=base | 0x01000000, close_fds=True, stdin=subprocess.DEVNULL,
                                 stdout=diag, stderr=diag, env=env)
            except OSError:
                subprocess.Popen(out["cmd"], creationflags=base, close_fds=True, stdin=subprocess.DEVNULL, stdout=diag,
                                 stderr=diag, env=env)
        finally:
            diag.close()
    if quit_cb is not None:
        try:
            quit_cb()
        except Exception:  # noqa: BLE001
            log.exception("falha ao pedir o fechamento do Eco; o instalador usará o Restart Manager")
    return out


def consume_install_result(data_dir: Path) -> dict | None:
    """Resultado da última instalação automática (lido uma vez ao iniciar). None se não houve."""
    p = updates_dir(data_dir) / "last_install.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
        p.unlink(missing_ok=True)
        return raw
    except (OSError, ValueError):
        return None
