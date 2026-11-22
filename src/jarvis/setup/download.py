"""Baixador de modelos: só HTTPS, retomada por Range, SHA-256 obrigatório, espelhos e pacote offline.

Regras
* O arquivo só vira definitivo (`os.replace` do `.part`) se o SHA-256 conferir com o manifesto.
* Retomada: `.part` + cabeçalho `Range: bytes=N-`. Servidor que ignora o Range (200) recomeça do zero.
* Redirecionamento para outro esquema que não seja https é recusado.
* Falha de rede: tenta de novo (com espera crescente) e depois o próximo espelho; sem rede, mensagem clara.
* Nenhum segredo, cookie nem identificação do usuário vai na requisição (User-Agent genérico).
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..config import ROOT
from .manifest import FileEntry, free_bytes, human_bytes
from .state import app_version, is_verified, mark_verified

log = logging.getLogger("jarvis.setup.download")

CHUNK = 1 << 20
MARGIN_BYTES = 256 * 1024 * 1024
RETRIES_PER_URL = 3
_BACKOFF_S = (1.0, 3.0, 8.0)


class DownloadError(RuntimeError):
    """`kind`: offline | http | hash | disk | cancelled | io. `message` é para mostrar ao usuário (pt-BR)."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class Progress:
    file: str                  # nome curto do arquivo
    done: int                  # bytes do arquivo
    total: int
    overall_done: int          # bytes de todos os arquivos pedidos
    overall_total: int
    speed: float               # bytes/s (suavizado)
    phase: str = "baixando"    # baixando | verificando | copiando | pronto
    source: str = ""           # host de onde vem

    @property
    def eta(self) -> float:
        rest = self.overall_total - self.overall_done
        return rest / self.speed if self.speed > 1 else float("nan")


ProgressCb = Callable[[Progress], None]


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):   # type: ignore[no-untyped-def]
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError(f"redirecionamento recusado (não é https): {newurl[:80]}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_HttpsOnly(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def sha256_file(path: Path, cancel: threading.Event | None = None,
                on_bytes: Callable[[int], None] | None = None) -> str:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise DownloadError("cancelled", "Cancelado.")
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
            n += len(b)
            if on_bytes:
                on_bytes(n)
    return h.hexdigest()


def verify_file(entry: FileEntry, root: Path = ROOT, cancel: threading.Event | None = None,
                on_bytes: Callable[[int], None] | None = None) -> bool:
    """True se o arquivo existe e o SHA-256 confere (usa o cache `verified.json` enquanto tamanho e data não mudam)."""
    path = entry.dest(root)
    try:
        if path.stat().st_size != entry.size:
            return False
    except OSError:
        return False
    if is_verified(entry.path, entry.sha256, path, root):
        return True
    if sha256_file(path, cancel, on_bytes) != entry.sha256:
        return False
    mark_verified(entry.path, entry.sha256, path, root)
    return True


def _explain(exc: BaseException) -> tuple[str, str]:
    """(kind, mensagem pt-BR) para uma falha de rede."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return "http", f"o servidor recusou o acesso (HTTP {exc.code})"
        if exc.code == 404:
            return "http", "o arquivo não existe mais nesse endereço (HTTP 404)"
        if exc.code == 429 or exc.code >= 500:
            return "http", f"o servidor está sobrecarregado ou fora do ar (HTTP {exc.code})"
        return "http", f"erro HTTP {exc.code}"
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "http", "o certificado do servidor não é confiável (a conexão foi recusada por segurança)"
    if isinstance(reason, (socket.gaierror, ConnectionRefusedError, OSError)) and not isinstance(reason, TimeoutError):
        return "offline", "sem conexão com a internet (ou o endereço está bloqueado)"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "offline", "a conexão demorou demais para responder"
    return "http", f"falha de rede: {reason}"


class Downloader:
    def __init__(self, root: Path = ROOT, progress: ProgressCb | None = None,
                 cancel: threading.Event | None = None, timeout_s: float = 30.0) -> None:
        self.root = root
        self.cb = progress
        self.cancel = cancel or threading.Event()
        self.timeout = timeout_s
        self._opener = _opener()
        self._ua = f"JarvisSetup/{app_version(root)}"
        self._overall_total = 0
        self._overall_done = 0
        self._speed = 0.0
        self._last_t = 0.0
        self._last_b = 0
        self._last_emit = 0.0

    # ------------------------------------------------------------------ API
    def fetch_all(self, entries: Iterable[FileEntry]) -> list[Path]:
        """Garante que todos os arquivos existam e estejam íntegros. Levanta DownloadError no primeiro que falhar."""
        entries = list(entries)
        self._overall_total = sum(e.size for e in entries)
        self._overall_done = 0
        out: list[Path] = []
        todo: list[FileEntry] = []
        for e in entries:                                   # o que já está certo não conta no espaço necessário
            if self._already_ok(e):
                self._overall_done += e.size
                out.append(e.dest(self.root))
            else:
                todo.append(e)
        need = sum(e.size - self._part_size(e) for e in todo)
        if todo:
            free = free_bytes(self.root)
            if free < need + MARGIN_BYTES:
                raise DownloadError("disk", f"Falta espaço em disco: preciso de {human_bytes(need + MARGIN_BYTES)} "
                                            f"e há {human_bytes(free)} livres em {self.root.anchor}. "
                                            "Libere espaço ou escolha outro disco para instalar.")
        for e in todo:
            self._check_cancel()
            out.append(self.fetch(e))
        self._emit("", 0, 0, "pronto", force=True)
        return out

    def fetch(self, entry: FileEntry) -> Path:
        dest = entry.dest(self.root)
        if self._already_ok(entry):
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        last: DownloadError | None = None
        for url in entry.urls:
            for attempt in range(RETRIES_PER_URL):
                self._check_cancel()
                try:
                    self._download(entry, url, dest)
                    return dest
                except DownloadError as exc:
                    last = exc
                    if exc.kind in ("cancelled", "disk", "io"):
                        raise
                    log.warning("falha em %s (%s, tentativa %d): %s", url.split("/")[2], entry.path, attempt + 1, exc.message)
                    if exc.kind == "hash" or (exc.kind == "http" and "HTTP 404" in exc.message):
                        break                               # tentar de novo na mesma URL não adianta
                    time.sleep(_BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)])
        assert last is not None
        if last.kind == "offline":
            raise DownloadError("offline", f"Não consegui baixar {Path(entry.path).name}: {last.message}. "
                                           "Conecte-se à internet e tente de novo, ou use o pacote offline.")
        raise DownloadError(last.kind, f"Não consegui baixar {Path(entry.path).name} de nenhuma fonte: {last.message}. "
                                       "Tente de novo mais tarde ou use o pacote offline.")

    # ------------------------------------------------------------------ interno
    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise DownloadError("cancelled", "Download pausado. O que já foi baixado fica guardado para retomar.")

    def _part(self, e: FileEntry) -> Path:
        d = e.dest(self.root)
        return d.with_name(d.name + ".part")

    def _part_size(self, e: FileEntry) -> int:
        try:
            return self._part(e).stat().st_size
        except OSError:
            return 0

    def _already_ok(self, e: FileEntry) -> bool:
        try:
            if e.dest(self.root).stat().st_size != e.size:
                return False
        except OSError:
            return False
        self._emit(Path(e.path).name, 0, e.size, "verificando", force=True)
        base = self._overall_done
        ok = verify_file(e, self.root, self.cancel,
                         lambda n: self._emit(Path(e.path).name, n, e.size, "verificando", overall=base + n))
        if not ok:
            log.warning("%s existe mas o SHA-256 não confere; vai ser baixado de novo", e.path)
            try:
                e.dest(self.root).unlink()
            except OSError:
                pass
        return ok

    def _emit(self, name: str, done: int, total: int, phase: str, force: bool = False, overall: int | None = None,
              source: str = "") -> None:
        now = time.monotonic()
        if not force and now - self._last_emit < 0.1:
            return
        self._last_emit = now
        if self.cb:
            od = self._overall_done if overall is None else overall
            self.cb(Progress(name, done, total, od, self._overall_total, self._speed, phase, source))

    def _tick_speed(self, nbytes: int) -> None:
        now = time.monotonic()
        if self._last_t == 0.0:
            self._last_t, self._last_b = now, nbytes
            return
        if now - self._last_t >= 0.5:
            inst = (nbytes - self._last_b) / (now - self._last_t)
            self._speed = inst if self._speed == 0 else 0.7 * self._speed + 0.3 * inst
            self._last_t, self._last_b = now, nbytes

    def _download(self, e: FileEntry, url: str, dest: Path) -> None:
        if not url.lower().startswith("https://"):
            raise DownloadError("io", "endereço sem https recusado")
        host = url.split("/")[2]
        part = self._part(e)
        name = Path(e.path).name
        have = part.stat().st_size if part.exists() else 0
        if have > e.size:                                   # lixo: recomeça
            part.unlink()
            have = 0
        h = hashlib.sha256()
        if have:                                            # recalcula o hash do que já foi baixado (retomada)
            with open(part, "rb") as f:
                while True:
                    b = f.read(CHUNK)
                    if not b:
                        break
                    h.update(b)
        headers = {"User-Agent": self._ua, "Accept": "*/*", "Accept-Encoding": "identity"}
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            resp = self._opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and have == e.size:          # já estava completo, faltava só conferir
                resp = None
            else:
                kind, msg = _explain(exc)
                raise DownloadError(kind, msg) from exc
        except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
            kind, msg = _explain(exc)
            raise DownloadError(kind, msg) from exc
        written = have
        if resp is not None:
            with resp:
                status = resp.status
                if have and status != 206:                  # servidor ignorou o Range: recomeça
                    part.unlink(missing_ok=True)
                    have = written = 0
                    h = hashlib.sha256()
                length = resp.headers.get("Content-Length")
                if length and status == 200 and int(length) != e.size:
                    raise DownloadError("http", f"tamanho anunciado ({human_bytes(int(length))}) difere do esperado "
                                                f"({human_bytes(e.size)}); fonte descartada")
                crange = resp.headers.get("Content-Range", "")
                if status == 206 and crange and f"/{e.size}" not in crange:
                    raise DownloadError("http", "o servidor devolveu um arquivo de outro tamanho; fonte descartada")
                base_overall = self._overall_done
                self._last_t = 0.0
                try:
                    with open(part, "ab" if have else "wb") as out:
                        while True:
                            self._check_cancel()
                            chunk = resp.read(CHUNK)
                            if not chunk:
                                break
                            out.write(chunk)
                            h.update(chunk)
                            written += len(chunk)
                            self._tick_speed(written - have)
                            self._emit(name, written, e.size, "baixando", overall=base_overall + written - 0, source=host)
                except (urllib.error.URLError, OSError, ssl.SSLError, http_incomplete()) as exc:
                    if isinstance(exc, OSError) and exc.errno == 28:
                        raise DownloadError("disk", "O disco ficou sem espaço durante o download.") from exc
                    kind, msg = _explain(exc)
                    raise DownloadError(kind, msg) from exc
        if written != e.size:
            raise DownloadError("http", f"download incompleto ({human_bytes(written)} de {human_bytes(e.size)})")
        self._emit(name, written, e.size, "verificando", force=True, source=host)
        if h.hexdigest() != e.sha256:
            part.unlink(missing_ok=True)
            raise DownloadError("hash", "o arquivo baixado não confere com o SHA-256 esperado (corrompido ou adulterado); descartei")
        os.replace(part, dest)
        mark_verified(e.path, e.sha256, dest, self.root)
        self._overall_done += e.size
        self._emit(name, e.size, e.size, "pronto", force=True, source=host)


def http_incomplete() -> type[BaseException]:
    import http.client
    return http.client.HTTPException


# ----------------------------------------------------------------------------- pacote offline
OFFLINE_NAMES = ("Jarvis-Modelos", "Jarvis-Models", "jarvis-modelos")


def default_offline_candidates(extra: Iterable[Path] = ()) -> list[Path]:
    """Pastas/zips onde um pacote offline costuma estar (ao lado do instalador, Downloads, raiz de discos)."""
    cands: list[Path] = [Path(p) for p in extra]
    bases = [Path(os.environ.get("USERPROFILE", "")) / "Downloads", Path.cwd(), Path(os.environ.get("INSTALLER_DIR", "."))]
    for b in bases:
        for n in OFFLINE_NAMES:
            cands += [b / n, b / (n + ".zip")]
    return [c for c in dict.fromkeys(cands) if str(c) not in ("", ".") and c.exists()]


class _Source:
    """Pasta ou zip que pode conter os arquivos do manifesto (por caminho relativo ou por tamanho+hash)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.zip: zipfile.ZipFile | None = None
        self.by_size: dict[int, list[tuple[str, object]]] = {}
        if path.is_file() and path.suffix.lower() == ".zip":
            self.zip = zipfile.ZipFile(path)
            for zi in self.zip.infolist():
                if not zi.is_dir():
                    self.by_size.setdefault(zi.file_size, []).append((zi.filename, zi))
        elif path.is_dir():
            scan = path / "models" if (path / "models").is_dir() else path
            for dirpath, _dirs, files in os.walk(scan, followlinks=True):
                for fn in files:
                    p = Path(dirpath) / fn
                    try:
                        self.by_size.setdefault(p.stat().st_size, []).append((str(p), p))
                    except OSError:
                        continue
        else:
            raise DownloadError("io", f"Pacote offline não encontrado: {path}")

    def candidates(self, e: FileEntry) -> list[tuple[str, object]]:
        c = self.by_size.get(e.size, [])
        pref = [x for x in c if x[0].replace("\\", "/").lower().endswith(e.path.lower().split("models/", 1)[-1])]
        pref += [x for x in c if x not in pref]
        return pref

    def close(self) -> None:
        if self.zip:
            self.zip.close()


def import_offline(source: Path, entries: Iterable[FileEntry], root: Path = ROOT, progress: ProgressCb | None = None,
                   cancel: threading.Event | None = None) -> tuple[list[str], list[str]]:
    """Copia para `root` os arquivos do manifesto encontrados em `source` (pasta ou .zip), conferindo o SHA-256.

    Devolve (importados, não encontrados). Só entra o que o hash aprova; o resto do pacote é ignorado."""
    cancel = cancel or threading.Event()
    entries = list(entries)
    total = sum(e.size for e in entries)
    src = _Source(Path(source))
    done_overall = 0
    imported: list[str] = []
    missing: list[str] = []
    try:
        for e in entries:
            dest = e.dest(root)
            if dest.is_file() and verify_file(e, root, cancel):
                done_overall += e.size
                continue
            name = Path(e.path).name
            found = False
            for label, obj in src.candidates(e):
                part = dest.with_name(dest.name + ".part")
                dest.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                copied = 0
                if progress:
                    progress(Progress(name, 0, e.size, done_overall, total, 0.0, "copiando"))
                t0 = time.monotonic()
                with (src.zip.open(obj) if src.zip else open(obj, "rb")) as fin, open(part, "wb") as fout:   # type: ignore[arg-type]
                    while True:
                        if cancel.is_set():
                            raise DownloadError("cancelled", "Importação cancelada.")
                        b = fin.read(CHUNK)
                        if not b:
                            break
                        fout.write(b)
                        h.update(b)
                        copied += len(b)
                        if progress:
                            progress(Progress(name, copied, e.size, done_overall + copied, total,
                                              copied / max(time.monotonic() - t0, 1e-3), "copiando"))
                if h.hexdigest() == e.sha256:
                    os.replace(part, dest)
                    mark_verified(e.path, e.sha256, dest, root)
                    imported.append(e.path)
                    done_overall += e.size
                    found = True
                    break
                part.unlink(missing_ok=True)
            if not found:
                missing.append(e.path)
    finally:
        src.close()
    return imported, missing


def make_offline_pack(dest: Path, entries: Iterable[FileEntry], root: Path = ROOT) -> list[str]:
    """Cria uma pasta de pacote offline (mesma estrutura models/...) a partir de arquivos JÁ verificados na instalação."""
    out: list[str] = []
    for e in entries:
        src = e.dest(root)
        if not src.is_file() or not verify_file(e, root):
            continue
        target = dest.joinpath(*e.path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        out.append(e.path)
    return out
