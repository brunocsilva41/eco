"""Diário de operações reversíveis em `data\\files_undo\\` (JSON atômico + backups de arquivos editados).

Grava só metadados: caminho, operação, tamanho e sha256, NUNCA o conteúdo (a única cópia de conteúdo são os
backups binários da pasta `backups`, usados para reverter edições). `undo_last()` só reverte se o estado atual ainda
bate com o "depois" registrado; se o arquivo mudou desde então, recusa e explica. Apagar vai para a Lixeira e NÃO é
revertido automaticamente (marcado como manual, sem fingir que foi desfeito).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import stat
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import Config
from ..core.cancel import CancelToken
from .recycle import RecycleError, send_to_recycle_bin
from .sandbox import Sandbox, SandboxError

log = logging.getLogger(__name__)

HASH_LIMIT = 64 * 1024 * 1024            # acima disso não calculamos sha256 (comparação só por tamanho)
MAX_SCAN_ITEMS = 100_000
_CHUNK = 1024 * 1024
_OPS = frozenset({"criar", "editar", "copiar", "mover", "apagar"})


class JournalError(Exception):
    """Falha no diário/backup. A mensagem pode ser falada."""


@dataclass(frozen=True)
class FileState:
    kind: str                            # "absent" | "file" | "dir" | "other"
    size: int = 0
    sha256: str | None = None
    items: int | None = None             # só para pastas

    @staticmethod
    def from_dict(d: Any) -> "FileState":
        if not isinstance(d, dict):
            return FileState("absent")
        sha = d.get("sha256")
        items = d.get("items")
        return FileState(str(d.get("kind", "absent")), int(d.get("size", 0)),
                         sha if isinstance(sha, str) else None, items if isinstance(items, int) else None)


@dataclass(frozen=True)
class Backup:
    name: str                            # nome do arquivo em backups\
    size: int
    sha256: str


@dataclass(frozen=True)
class UndoResult:
    ok: bool
    message: str
    op: str | None = None
    manual: bool = False                 # True = precisa ser desfeito à mão (ex.: restaurar da Lixeira)
    entry_id: str | None = None


def _check(cancel: CancelToken | None) -> None:
    if cancel is not None:
        cancel.raise_if_cancelled()


def sha256_file(path: str | os.PathLike[str], cancel: CancelToken | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            _check(cancel)
            h.update(chunk)
    return h.hexdigest()


def snapshot(path: str | os.PathLike[str], cancel: CancelToken | None = None) -> FileState:
    """Estado observável de `path` sem seguir links (sha256 só para arquivos até HASH_LIMIT)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return FileState("absent")
    if stat.S_ISREG(st.st_mode):
        sha = sha256_file(path, cancel) if st.st_size <= HASH_LIMIT else None
        return FileState("file", st.st_size, sha)
    if stat.S_ISDIR(st.st_mode):
        items, total, stack = 0, 0, [os.fspath(path)]
        while stack:
            _check(cancel)
            with os.scandir(stack.pop()) as it:
                for e in it:
                    items += 1
                    if items > MAX_SCAN_ITEMS:
                        raise JournalError("A pasta tem itens demais para eu conferir.")
                    est = e.stat(follow_symlinks=False)
                    if stat.S_ISDIR(est.st_mode) and not getattr(est, "st_file_attributes", 0) & 0x400:
                        stack.append(e.path)
                    else:
                        total += est.st_size
        return FileState("dir", total, None, items)
    return FileState("other", st.st_size)


def same_state(a: FileState, b: FileState) -> bool:
    if a.kind != b.kind or a.size != b.size:
        return False
    if a.sha256 is not None and b.sha256 is not None and a.sha256 != b.sha256:
        return False
    return a.items is None or b.items is None or a.items == b.items


def atomic_write_json(path: Path, obj: Any) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


class UndoJournal:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._dir = cfg.paths.data / "files_undo"
        self._backups = self._dir / "backups"
        self._keep = max(1, cfg.files.undo_keep)
        self._max_bytes = max(1, cfg.files.undo_max_mb) * 1024 * 1024
        self._lock = threading.RLock()
        self._sandbox = Sandbox(cfg)

    # ------------------------------------------------------------ armazenamento
    def _ensure_dirs(self) -> None:
        try:
            self._backups.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise JournalError(f"Não consegui preparar a pasta de desfazer: {exc.strerror or type(exc).__name__}.") from exc

    def _entries(self) -> list[tuple[Path, dict[str, Any]]]:
        """Entradas válidas, da mais antiga para a mais nova."""
        out: list[tuple[Path, dict[str, Any]]] = []
        try:
            files = sorted(p for p in self._dir.glob("*.json") if not p.name.startswith("."))
        except OSError:
            return out
        for p in files:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("diário: entrada ilegível ignorada: %s", p.name)
                continue
            if isinstance(data, dict) and data.get("op") in _OPS and isinstance(data.get("id"), str):
                out.append((p, data))
        return out

    def _backup_path(self, name: str) -> Path:
        if not name or name != Path(name).name or not name.endswith(".bak"):
            raise JournalError("Referência de backup inválida.")
        return self._backups / name

    def _drop(self, path: Path, entry: dict[str, Any]) -> None:
        bk = entry.get("backup")
        if isinstance(bk, str):
            try:
                self._backup_path(bk).unlink(missing_ok=True)
            except (OSError, JournalError):
                log.warning("diário: não consegui remover backup %s", bk)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("diário: não consegui remover entrada %s", path.name)

    def _backup_bytes(self) -> int:
        total = 0
        try:
            for p in self._backups.iterdir():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
        return total

    def _rotate(self, extra_needed: int = 0) -> None:
        """Mantém no máximo `undo_keep` entradas e `undo_max_mb` de backups, descartando as mais antigas."""
        entries = self._entries()
        while len(entries) > self._keep:
            p, e = entries.pop(0)
            log.info("diário: descartando operação antiga %s", e.get("id"))
            self._drop(p, e)
        while entries and self._backup_bytes() + extra_needed > self._max_bytes:
            p, e = entries.pop(0)
            log.info("diário: descartando %s para liberar espaço de backup", e.get("id"))
            self._drop(p, e)

    # ------------------------------------------------------------ backup / registro
    def make_backup(self, path: str | os.PathLike[str], cancel: CancelToken | None = None) -> Backup:
        """Copia o arquivo para a área de backup ANTES de editar/sobrescrever. Recusa se não couber no orçamento."""
        with self._lock:
            self._ensure_dirs()
            try:
                st = os.lstat(path)
            except OSError as exc:
                raise JournalError("Não consegui ler o arquivo para guardar o backup.") from exc
            if not stat.S_ISREG(st.st_mode):
                raise JournalError("Só faço backup de arquivos comuns.")
            if st.st_size > self._max_bytes:
                raise JournalError("O arquivo é maior que o espaço reservado para desfazer; não edito sem backup.")
            self._rotate(extra_needed=st.st_size)
            name = f"{time.time_ns():020d}-{secrets.token_hex(4)}.bak"
            dest = self._backups / name
            h = hashlib.sha256()
            size = 0
            try:
                with open(path, "rb") as src, open(dest, "xb") as out:
                    while chunk := src.read(_CHUNK):
                        _check(cancel)
                        h.update(chunk)
                        size += len(chunk)
                        if size > self._max_bytes:
                            raise JournalError("O arquivo cresceu além do espaço de backup.")
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
            except BaseException as exc:
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
                if isinstance(exc, OSError):
                    raise JournalError(f"Não consegui guardar o backup: {exc.strerror or type(exc).__name__}.") from exc
                raise
            return Backup(name, size, h.hexdigest())

    def discard_backup(self, backup: Backup | None) -> None:
        if backup is None:
            return
        with self._lock:
            try:
                self._backup_path(backup.name).unlink(missing_ok=True)
            except (OSError, JournalError):
                log.warning("diário: não consegui descartar backup %s", backup.name)

    def record(self, op: str, *, src: Path | str | None = None, dst: Path | str | None = None,
               before: FileState | None = None, after: FileState | None = None, backup: Backup | None = None,
               reversible: bool = True) -> str:
        """Registra a operação (já executada) de forma atômica. Devolve o id."""
        if op not in _OPS:
            raise JournalError(f"Operação desconhecida: {op}")
        with self._lock:
            self._ensure_dirs()
            entry_id = f"{time.time_ns():020d}-{secrets.token_hex(3)}"
            entry: dict[str, Any] = {
                "id": entry_id, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "op": op,
                "src": str(src) if src is not None else None, "dst": str(dst) if dst is not None else None,
                "before": asdict(before or FileState("absent")), "after": asdict(after or FileState("absent")),
                "backup": backup.name if backup else None, "backup_sha256": backup.sha256 if backup else None,
                "reversible": bool(reversible), "status": "ativa",
            }
            atomic_write_json(self._dir / f"{entry_id}.json", entry)
            self._rotate()
            main = Path(str(dst or src)).name
            log.info("diário: %s %s (antes=%s/%d, depois=%s/%d, sha=%s)", op, main, entry["before"]["kind"],
                     entry["before"]["size"], entry["after"]["kind"], entry["after"]["size"],
                     (entry["after"]["sha256"] or "-")[:12])
            return entry_id

    def last(self) -> dict[str, Any] | None:
        with self._lock:
            active = [e for _, e in self._entries() if e.get("status") == "ativa"]
            return active[-1] if active else None

    # ------------------------------------------------------------ desfazer
    def undo_last(self, cancel: CancelToken | None = None) -> UndoResult:
        with self._lock:
            active = [(p, e) for p, e in self._entries() if e.get("status") == "ativa"]
            if not active:
                return UndoResult(False, "Não há nenhuma operação de arquivo para desfazer.")
            path, entry = active[-1]
            op = str(entry["op"])
            eid = str(entry["id"])
            try:
                result = self._undo_entry(entry, cancel)
            except SandboxError as exc:
                return UndoResult(False, f"Não posso desfazer: {exc}", op, entry_id=eid)
            except RecycleError as exc:
                return UndoResult(False, f"Não consegui desfazer: {exc}", op, entry_id=eid)
            except JournalError as exc:
                return UndoResult(False, str(exc), op, entry_id=eid)
            except OSError as exc:
                log.warning("diário: desfazer falhou em %s: %s", op, exc)
                return UndoResult(False, "Não consegui desfazer: o arquivo está em uso ou sem permissão.", op, entry_id=eid)
            if result.ok or result.manual:
                entry["status"] = "desfeita" if result.ok else "manual"
                try:
                    atomic_write_json(path, entry)
                except OSError:
                    log.exception("diário: não consegui atualizar o estado de %s", eid)
            return UndoResult(result.ok, result.message, op, result.manual, eid)

    def _p(self, text: Any) -> Path:
        if not isinstance(text, str) or not text:
            raise JournalError("A entrada do diário está incompleta.")
        return self._sandbox.resolve(text)

    def _undo_entry(self, e: dict[str, Any], cancel: CancelToken | None) -> UndoResult:
        op = e["op"]
        before, after = FileState.from_dict(e.get("before")), FileState.from_dict(e.get("after"))
        if op == "apagar" or not e.get("reversible", True):
            where = e.get("src") or e.get("dst") or "?"
            return UndoResult(False, f"O último passo foi apagar {Path(str(where)).name}. Não consigo restaurar sozinho: "
                              "abra a Lixeira do Windows e restaure por lá.", op, manual=True)
        changed = "O arquivo foi alterado depois dessa operação; não desfaço para não perder suas mudanças."

        if op in ("criar", "copiar"):
            dst = self._p(e.get("dst"))
            if not same_state(snapshot(dst, cancel), after):
                return UndoResult(False, changed, op)
            send_to_recycle_bin(dst, size_hint=after.size)
            return UndoResult(True, f"Desfeito: {dst.name} foi para a Lixeira.", op)

        if op == "editar":
            dst = self._p(e.get("dst"))
            bk_name, bk_sha = e.get("backup"), e.get("backup_sha256")
            if not isinstance(bk_name, str) or not isinstance(bk_sha, str):
                return UndoResult(False, "Não há backup dessa edição.", op)
            bk = self._backup_path(bk_name)
            if not bk.is_file() or sha256_file(bk, cancel) != bk_sha:
                return UndoResult(False, "O backup dessa edição sumiu ou está corrompido.", op)
            if not same_state(snapshot(dst, cancel), after):
                return UndoResult(False, changed, op)
            tmp = dst.with_name(f".jv{secrets.token_hex(4)}.t")
            try:
                with open(bk, "rb") as s, open(tmp, "xb") as out:
                    while chunk := s.read(_CHUNK):
                        _check(cancel)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(tmp, dst)
            except BaseException:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            try:
                bk.unlink(missing_ok=True)
            except OSError:
                pass
            return UndoResult(True, f"Desfeito: {dst.name} voltou à versão anterior.", op)

        if op == "mover":
            src, dst = self._p(e.get("src")), self._p(e.get("dst"))
            if snapshot(src).kind != "absent":
                return UndoResult(False, "O lugar original já está ocupado; não desfaço para não sobrescrever.", op)
            if not same_state(snapshot(dst, cancel), after):
                return UndoResult(False, changed, op)
            if not src.parent.is_dir():
                return UndoResult(False, "A pasta original não existe mais; não consigo devolver.", op)
            os.rename(dst, src)
            return UndoResult(True, f"Desfeito: {src.name} voltou ao lugar original.", op)
        return UndoResult(False, "Tipo de operação desconhecido.", op)
