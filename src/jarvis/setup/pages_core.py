"""Páginas 1 a 3: boas-vindas, hardware e modelos."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..ui.kit.base import Label, set_a11y
from ..ui.kit.buttons import Button
from ..ui.kit.feedback import InlineBanner
from ..ui.kit.fields import ComboField
from ..ui.kit.layout import Card
from ..ui.kit.meters import ProgressBar
from ..ui.kit.status import StatusChip
from ..ui.kit.tasks import run_async
from ..ui.kit import icons
from ..ui.theme import SIZE, SPACE, pal
from . import hardware, strings as S
from .config_io import apply_stt_choice
from .download import DownloadError, Downloader, Progress, import_offline, default_offline_candidates, verify_file
from .manifest import FileEntry, Package, free_bytes, human_bytes, human_eta, quick_present
from .state import app_version, is_verified
from .widgets import CheckRow, Ctx, Page, ask_confirm

log = logging.getLogger("jarvis.setup.pages")


def clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            clear(it.layout())


# ----------------------------------------------------------------------------- 1. boas-vindas
class WelcomePage(Page):
    key = "welcome"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.col.addWidget(Label(S.W_HEADLINE, "display", wrap=True))
        self.col.addWidget(Label(S.W_LEAD, "body", wrap=True))
        self.banner_host = QVBoxLayout()
        self.col.addLayout(self.banner_host)
        for icon_name, title, body in S.W_POINTS:
            card = Card()
            row = QHBoxLayout()
            row.setSpacing(SPACE.lg)
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, pal().accent_ink, SIZE.icon_lg * 2, self))
            ic.setFixedWidth(SIZE.icon_lg * 2 + SPACE.sm)
            row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(SPACE.xs)
            col.addWidget(Label(title, "heading"))
            col.addWidget(Label(body, "body", wrap=True))
            row.addLayout(col, 1)
            card.body.addLayout(row)
            set_a11y(card, title, body)
            self.col.addWidget(card)
        self.col.addStretch(1)

    def on_enter(self) -> None:
        clear(self.banner_host)
        st = self.ctx.state
        if self.ctx.repair:
            self.banner_host.addWidget(InlineBanner("ok", S.W_REPAIR_TITLE, S.W_REPAIR_BODY))
        elif st.step not in ("welcome",) and not st.completed:
            step = S.STEP_TITLES.get(st.step, st.step)
            b = InlineBanner("ok", S.W_RESUME_TITLE.format(step=step), S.W_RESUME_BODY, action_text=S.W_RESUME_ACTION)
            b.actionTriggered.connect(lambda: self.ctx.go(st.step))
            self.banner_host.addWidget(b)


# ----------------------------------------------------------------------------- 2. hardware
class HardwarePage(Page):
    key = "hardware"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.results: list[hardware.Check] = []
        self.summary_host = QVBoxLayout()
        self.col.addLayout(self.summary_host)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(SPACE.sm)
        card = Card()
        card.body.addLayout(self.rows)
        self.col.addWidget(card)
        self.again = Button(S.H_RECHECK, icon_name="refresh")
        self.again.clicked.connect(self.run)
        self.col.addWidget(self.again, 0, Qt.AlignmentFlag.AlignLeft)
        self.col.addStretch(1)
        self._busy = False

    def on_enter(self) -> None:
        if not self.results and not self.ctx.demo:
            self.run()

    def _need_gb(self) -> float:
        files = self.ctx.manifest.files_for(self.ctx.components)
        return sum(f.size for f in files if not quick_present(f, self.ctx.root)) / 1e9

    def run(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.again.setEnabled(False)
        clear(self.rows)
        self.rows.addWidget(Label(S.H_CHECKING, "body"))
        need = self._need_gb()
        run_async(lambda: hardware.run_all(self.ctx.root, need), self, self._done, self._failed)

    def _failed(self, msg: str) -> None:
        self._busy = False
        self.again.setEnabled(True)
        clear(self.rows)
        self.rows.addWidget(Label(msg, "body", wrap=True))

    def _done(self, res: list[hardware.Check]) -> None:
        self._busy = False
        self.again.setEnabled(True)
        self.show_results(res)

    def show_results(self, res: list[hardware.Check]) -> None:
        self.results = res
        clear(self.rows)
        clear(self.summary_host)
        for r in res:
            self.rows.addWidget(CheckRow(r.status, r.title, r.detail, r.hint))
        worst = "fail" if any(r.status == "fail" for r in res) else "warn" if any(r.status == "warn" for r in res) else "ok"
        text = {"ok": S.H_OK, "warn": S.H_WARN, "fail": S.H_FAIL}[worst]
        self.summary_host.addWidget(InlineBanner({"fail": "error"}.get(worst, worst), text))

    def on_leave(self, forward: bool) -> bool:
        if forward and any(r.status == "fail" for r in self.results):
            return ask_confirm(self, S.H_FAIL_CONFIRM_TITLE, S.H_FAIL_CONFIRM_BODY, S.H_FAIL_CONFIRM)
        return True


# ----------------------------------------------------------------------------- 3. modelos
class _Job(QObject):
    progress = Signal(object)
    finished = Signal(object)          # DownloadError | None | tuple (importação)


class _Scan(QObject):
    done = Signal(object)              # (achados, profundo)


class ModelsPage(Page):
    key = "models"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.cancel = threading.Event()
        self.job: _Job | None = None
        self.thread: threading.Thread | None = None
        self.rows: dict[str, tuple[StatusChip, Label]] = {}

        self.col.addWidget(Label(S.M_PRIVACY, "help", wrap=True))
        stt_row = QHBoxLayout()
        stt_row.addWidget(Label(S.M_SELECT_STT, "label"))
        self.stt = ComboField([(S.M_STT_SMALL, "stt_small"), (S.M_STT_BASE, "stt_base")])
        self.stt.set_value("stt_base" if "stt_base" in ctx.components else "stt_small")
        self.stt.valueChanged.connect(self._stt_changed)
        stt_row.addWidget(self.stt, 1)
        self.col.addLayout(stt_row)

        self.total = Label("", "body", wrap=True)
        self.col.addWidget(self.total)
        self.msg_host = QVBoxLayout()
        self.col.addLayout(self.msg_host)

        self.prog_card = Card()
        self.phase = Label("", "label", wrap=True)
        self.detail = Label("", "help", wrap=True)
        self.bar = ProgressBar()
        self.prog_card.add(self.phase)
        self.prog_card.add(self.bar)
        self.prog_card.add(self.detail)
        self.prog_card.setVisible(False)
        self.col.addWidget(self.prog_card)

        btns = QHBoxLayout()
        self.btn_dl = Button(S.M_DOWNLOAD, variant="primary", icon_name="refresh")
        self.btn_dl.clicked.connect(self.start_download)
        self.btn_pause = Button(S.M_PAUSE, icon_name="stop")
        self.btn_pause.clicked.connect(lambda: self.cancel.set())
        self.btn_pause.setVisible(False)
        self.btn_off = Button(S.M_OFFLINE, icon_name="folder")
        self.btn_off.clicked.connect(self.pick_offline)
        self.btn_ver = Button(S.M_VERIFY, icon_name="check")
        self.btn_ver.clicked.connect(self.verify_all)
        self.btn_use = Button(S.M_FOUND_USE, variant="primary", icon_name="check")
        self.btn_use.clicked.connect(self.use_found)
        self.btn_use.setVisible(False)
        self.btn_deep = Button(S.M_SCAN_DEEP, icon_name="folder")
        self.btn_deep.clicked.connect(lambda: self._start_scan(deep=True))
        self._scan = _Scan()
        self._scan.done.connect(self._on_scan_done)
        self._scanning = False
        self._found: dict[str, list[Path]] = {}
        self._scan_cancel = threading.Event()
        self._scanned_once = False
        for b in (self.btn_use, self.btn_dl, self.btn_pause):
            btns.addWidget(b)
        btns.addStretch(1)
        self.col.addLayout(btns)
        btns2 = QHBoxLayout()                              # ações secundárias em outra linha: nenhum rótulo fica cortado
        for b in (self.btn_off, self.btn_deep, self.btn_ver):
            btns2.addWidget(b)
        btns2.addStretch(1)
        self.col.addLayout(btns2)

        self.sel = QVBoxLayout()
        self.sel.setSpacing(SPACE.md)
        self.col.addLayout(self.sel)
        self.col.addStretch(1)
        self._build_rows()

    # ---- seleção
    def _selected(self) -> list[str]:
        comps = ["vision", "voice", self.stt.value()]
        return comps

    def _stt_changed(self, _v) -> None:
        self.ctx.state.components = self._selected()
        self.refresh()

    def _build_rows(self) -> None:
        clear(self.sel)
        self.rows = {}
        man = self.ctx.manifest
        seen: set[str] = set()
        for key in self._selected():
            comp = man.components[key]
            for pid in comp.packages:
                if pid in seen:
                    continue
                seen.add(pid)
                pkg = man.packages[pid]
                card = Card()
                head = QHBoxLayout()
                col = QVBoxLayout()
                col.setSpacing(SPACE.xs)
                title = comp.title if pid == comp.packages[0] else pkg.name
                first = pid == comp.packages[0]
                sub = pkg.name if first else ""
                col.addWidget(Label(title, "label", wrap=True))
                col.addWidget(Label(f"{sub} · {human_bytes(pkg.size)}" if sub else human_bytes(pkg.size), "body", wrap=True))
                col.addWidget(Label(S.M_LICENSE.format(lic=pkg.license), "help", wrap=True))
                head.addLayout(col, 1)
                chip = StatusChip("neutral", S.M_STATE_MISSING)
                head.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
                card.body.addLayout(head)
                self.sel.addWidget(card)
                self.rows[pid] = (chip, Label(""))
                set_a11y(card, pkg.name, S.M_LICENSE.format(lic=pkg.license))

    def _pkg_state(self, pkg: Package) -> str:
        root = self.ctx.root
        if all(quick_present(f, root) for f in pkg.files):
            return "ok"
        if any(f.dest(root).with_name(f.dest(root).name + ".part").exists() for f in pkg.files):
            return "part"
        return "missing"

    def entries(self) -> list[FileEntry]:
        return self.ctx.manifest.files_for(self._selected())

    def missing(self) -> list[FileEntry]:
        return [f for f in self.entries() if not quick_present(f, self.ctx.root)]

    def refresh(self) -> None:
        self.ctx.state.components = self._selected()
        self._build_rows()
        man = self.ctx.manifest
        for pid, (chip, _l) in self.rows.items():
            st = self._pkg_state(man.packages[pid])
            if st == "ok":
                chip.set_state("ok", S.M_STATE_OK)
            elif st == "part":
                chip.set_state("warn", S.M_STATE_PART)
            else:
                chip.set_state("neutral", S.M_STATE_MISSING)
        miss = self.missing()
        need = sum(f.size for f in miss)
        if miss:
            self.total.setText(S.M_TOTAL.format(need=human_bytes(need), free=human_bytes(free_bytes(self.ctx.root))))
        else:
            self.total.setText(S.M_ALL_OK)
        part = any(f.dest(self.ctx.root).with_name(f.dest(self.ctx.root).name + ".part").exists() for f in miss)
        self.btn_dl.setText(S.M_RESUME if part else S.M_DOWNLOAD)
        self.btn_dl.setVisible(bool(miss) and not self._running())
        self.btn_off.setVisible(bool(miss) and not self._running())
        self.btn_deep.setVisible(bool(miss) and not self._running() and not self._scanning)
        self.btn_use.setVisible(bool(miss) and bool(self._found) and not self._running() and not self._scanning)
        self.changed.emit()

    def on_enter(self) -> None:
        self.ctx.state.components = self._selected()
        self.refresh()
        if self.missing() and not self._scanned_once:
            self._scanned_once = True
            self._start_scan(deep=False)                    # procura sozinho o que o usuário já tem

    # ---- modelos que já existem no PC
    def _start_scan(self, deep: bool) -> None:
        if self._scanning or self._running():
            return
        miss = self.missing()
        if not miss:
            return
        from . import discover
        self._scanning = True
        self._found = {}
        self._scan_cancel = threading.Event()
        self._banner("ok", S.M_SCANNING)
        self.btn_dl.setEnabled(False)
        self.btn_deep.setVisible(False)
        root, cancel = self.ctx.root, self._scan_cancel

        def target() -> None:
            try:
                found = discover.scan(miss, deep=deep, cancel=cancel, install_root=root)
            except Exception:  # noqa: BLE001 - a busca é um extra: nunca derruba o assistente
                log.exception("falha na busca de modelos existentes")
                found = {}
            self._scan.done.emit((found, deep))
        threading.Thread(target=target, name="setup-scan", daemon=True).start()

    def _on_scan_done(self, res) -> None:
        found, deep = res
        self._scanning = False
        self.btn_dl.setEnabled(True)
        self._found = found
        miss = {e.path: e for e in self.missing()}
        if found:
            size = sum(miss[p].size for p in found if p in miss)
            self._banner("ok", S.M_FOUND.format(n=len(found), size=human_bytes(size)))
        else:
            self._banner("warn", S.M_FOUND_NONE, "", S.M_FOUND_NONE_TODO if not deep else "")
        self.refresh()

    def use_found(self) -> None:
        if self._running() or not self._found:
            return
        from . import discover
        entries = self.entries()
        found = dict(self._found)
        self._begin()
        root, cancel = self.ctx.root, self.cancel
        self._run(lambda cb: ("found", *discover.import_found(found, entries, root, cb, cancel)))

    def can_advance(self) -> bool:
        return not self._running()

    def next_label(self) -> str:
        return S.NEXT if not self.missing() else S.SKIP

    def on_leave(self, forward: bool) -> bool:
        if self._running():
            return False
        if forward and self.missing():
            return ask_confirm(self, S.M_SKIP_TITLE, S.M_SKIP_BODY, S.M_SKIP_CONFIRM)
        if forward:
            apply_stt_choice(self._selected(), self.ctx.manifest)
            self.ctx.cfg = self.ctx.reload_cfg()
        return True

    def teardown(self) -> None:
        self.cancel.set()
        self._scan_cancel.set()

    # ---- execução
    def _running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def _banner(self, state: str, what: str, why: str = "", todo: str = "") -> None:
        clear(self.msg_host)
        if what:
            self.msg_host.addWidget(InlineBanner(state, what, why, todo))

    def _begin(self) -> None:
        self._banner("ok", "")
        self.cancel = threading.Event()
        self.prog_card.setVisible(True)
        self.btn_dl.setVisible(False)
        self.btn_off.setVisible(False)
        self.btn_ver.setEnabled(False)
        self.btn_pause.setVisible(True)
        self.bar.set_progress(0, 1)
        self.changed.emit()

    def _end(self) -> None:
        self.btn_pause.setVisible(False)
        self.btn_ver.setEnabled(True)
        self.refresh()

    def _run(self, fn) -> None:
        self.job = _Job()
        self.job.progress.connect(self._on_progress)
        self.job.finished.connect(self._on_finished)

        def target() -> None:
            try:
                res = fn(self.job.progress.emit)
            except DownloadError as exc:
                res = exc
            except Exception as exc:  # noqa: BLE001
                log.exception("falha inesperada no download")
                res = DownloadError("io", f"Falha inesperada: {exc}")
            self.job.finished.emit(res)

        self.thread = threading.Thread(target=target, name="setup-download", daemon=True)
        self.thread.start()

    def start_download(self) -> None:
        if self._running():
            return
        entries = self.entries()
        self._begin()
        root = self.ctx.root
        cancel = self.cancel
        self._run(lambda cb: Downloader(root, cb, cancel).fetch_all(entries))

    def verify_all(self) -> None:
        if self._running():
            return
        entries = [f for f in self.entries() if quick_present(f, self.ctx.root)]
        self._begin()
        root, cancel = self.ctx.root, self.cancel

        def work(cb):
            bad = []
            total = sum(e.size for e in entries)
            done = 0
            for e in entries:
                cb(Progress(Path(e.path).name, 0, e.size, done, total, 0.0, "verificando"))
                ok = verify_file(e, root, cancel, lambda n, e=e, done=done: cb(Progress(Path(e.path).name, n, e.size, done + n, total, 0.0, "verificando")))
                if not ok:
                    bad.append(e)
                    try:
                        e.dest(root).unlink()
                    except OSError:
                        pass
                done += e.size
            return ("verify", bad)
        self._run(work)

    def pick_offline(self) -> None:
        start = next((str(p) for p in default_offline_candidates()), str(Path.home()))
        d = QFileDialog.getExistingDirectory(self, S.M_OFFLINE_PICK, start)
        if not d:
            return
        self.import_offline(Path(d))

    def import_offline(self, src: Path) -> None:
        if self._running():
            return
        entries = self.entries()
        self._begin()
        root, cancel = self.ctx.root, self.cancel
        self._run(lambda cb: ("offline", *import_offline(src, entries, root, cb, cancel)))

    def _on_progress(self, p: Progress) -> None:
        self.phase.setText(S.M_PROGRESS.format(phase=S.M_PHASE.get(p.phase, p.phase), name=p.file))
        self.bar.set_progress(p.overall_done, max(p.overall_total, 1))
        parts = [f"{human_bytes(p.overall_done)} de {human_bytes(p.overall_total)}"]
        if p.speed > 1 and p.phase == "baixando":
            parts += [S.M_SPEED.format(speed=human_bytes(p.speed)), S.M_ETA.format(eta=human_eta(p.eta))]
        if p.source and p.phase == "baixando":
            parts.append(S.M_SOURCE.format(host=p.source))
        self.detail.setText(" · ".join(parts))

    def _on_finished(self, res) -> None:
        self._end()
        if isinstance(res, DownloadError):
            if res.kind == "cancelled":
                self._banner("warn", res.message)
                return
            self.prog_card.setVisible(False)
            if res.kind == "offline":
                self._banner("error", S.M_OFFLINE_ERR, S.M_OFFLINE_WHY, S.M_OFFLINE_TODO)
            else:
                self._banner("error", S.M_ERR, res.message, "")
            return
        if isinstance(res, tuple) and res and res[0] == "offline":
            _tag, imported, missing = res
            if imported:
                self._banner("ok", S.M_OFFLINE_DONE.format(n=len(imported)))
            else:
                self._banner("warn", S.M_OFFLINE_NONE)
            return
        if isinstance(res, tuple) and res and res[0] == "found":
            _tag, imported, missing, copied = res
            self._found = {}
            if imported:
                self._banner("ok", S.M_FOUND_DONE.format(n=len(imported), copied=len(copied)),
                             S.M_FOUND_PARTIAL.format(left=len(missing)) if missing else "", "")
            else:
                self._banner("warn", S.M_FOUND_NONE)
            return
        if isinstance(res, tuple) and res and res[0] == "verify":
            bad = res[1]
            if bad:
                self._banner("warn", f"{len(bad)} arquivo(s) estavam corrompidos e foram removidos.",
                             "Eles serão baixados de novo.", "Clique em Baixar agora.")
            else:
                self._banner("ok", S.M_ALL_OK)
            return
        self._banner("ok", S.M_ALL_OK)
        self.prog_card.setVisible(False)
        self.changed.emit()
