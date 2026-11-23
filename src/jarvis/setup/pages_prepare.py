"""Etapa "Preparar o computador": checa o que falta, baixa/instala com um clique (com confirmação), repara e gera relatório."""
from __future__ import annotations

import logging
import os
import threading
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..ui.kit.base import Label, set_a11y
from ..ui.kit.buttons import Button
from ..ui.kit.feedback import InlineBanner
from ..ui.kit.layout import Card
from ..ui.kit.meters import ProgressBar
from ..ui.kit.status import StatusChip
from ..ui.kit.tasks import run_async
from ..ui.theme import SIZE, SPACE
from . import prereqs, strings as S
from .download import DownloadError, Downloader, Progress, verify_file
from .manifest import human_bytes, human_eta, quick_present
from .widgets import Ctx, Page, ask_confirm

log = logging.getLogger("jarvis.setup.prepare")


class _Job(QObject):
    progress = Signal(str, int, int, float)       # texto, feito, total, bytes/s
    finished = Signal(object)                     # resultado ou PrepError/DownloadError


def _clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())


class PrepRow(QWidget):
    """Selo + título + detalhe + dica + botão de ação (quando há o que fazer)."""

    def __init__(self, item: prereqs.Item, on_action, on_customize=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, SPACE.xs, 0, SPACE.xs)
        lay.setSpacing(SPACE.md)
        shown = {"fail": "error", "info": "neutral"}.get(item.status, item.status)
        text = {"ok": S.STATUS_TEXT["ok"], "warn": S.STATUS_TEXT["warn"], "fail": S.STATUS_TEXT["fail"], "info": S.P_OPTIONAL}[item.status]
        self.chip = StatusChip(shown, text)                                   # type: ignore[arg-type]
        self.chip.setFixedWidth(SIZE.target * 3 + SPACE.md)                 # mesma largura em todas as linhas: texto alinhado
        lay.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(Label(item.title, "label", wrap=True))
        if item.detail:
            col.addWidget(Label(item.detail, "body", wrap=True))
        where = " · ".join(x for x in (f"versão {item.version}" if item.version else "",
                                       f"achado em: {item.where}" if item.where else "") if x)
        if where or item.path:
            self.where_label = Label((where + "\n" if where else "") + item.path, "help", wrap=True)
            col.addWidget(self.where_label)
        if item.hint:
            col.addWidget(Label(item.hint, "help", wrap=True))
        self.button: Button | None = None
        self.custom_button: Button | None = None
        if item.action or (item.tool and on_customize is not None):
            btns = QHBoxLayout()
            btns.setSpacing(SPACE.sm)
            if item.action:
                self.button = Button(item.action_label or S.P_DO, variant="secondary" if item.optional else "primary")
                self.button.clicked.connect(lambda: on_action(item))
                btns.addWidget(self.button)
            if item.tool and on_customize is not None:
                self.custom_button = Button(S.P_CUSTOMIZE + (" ✎" if item.custom else ""), icon_name="edit")
                self.custom_button.setToolTip(S.P_CUSTOMIZE_TIP)
                self.custom_button.clicked.connect(lambda: on_customize(item))
                btns.addWidget(self.custom_button)
            btns.addStretch(1)
            col.addSpacing(SPACE.xs)
            col.addLayout(btns)
        lay.addLayout(col, 1)
        set_a11y(self, f"{text}: {item.title}", " ".join(x for x in (item.detail, item.hint, item.version, item.where) if x))


class PreparePage(Page):
    key = "prepare"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.items: list[prereqs.Item] = []
        self.events: list[str] = []
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self.job: _Job | None = None
        self._busy = False
        self._vram_mb = 0
        self._ram_gb = 0.0

        self.msg_host = QVBoxLayout()
        self.col.addLayout(self.msg_host)

        # o progresso fica NO TOPO (logo abaixo do aviso): visível mesmo com a lista rolada
        self.prog_card = Card()
        self.prog_title = Label("", "label", wrap=True)
        self.bar = ProgressBar()
        self.prog_detail = Label("", "help", wrap=True)
        self.btn_pause = Button(S.P_PAUSE, icon_name="stop")
        self.btn_pause.clicked.connect(self._pause)
        self.prog_card.body.addWidget(self.prog_title)
        self.prog_card.body.addWidget(self.bar)
        self.prog_card.body.addWidget(self.prog_detail)
        self.prog_card.body.addWidget(self.btn_pause, 0, Qt.AlignmentFlag.AlignLeft)
        self.prog_card.setVisible(False)
        self.col.addWidget(self.prog_card)

        # ações no TOPO: sempre à vista, sem rolar a lista até o fim
        self.btn_all = Button(S.P_ALL, variant="primary", icon_name="refresh")
        self.btn_all.clicked.connect(self.prepare_all)
        self.btn_again = Button(S.H_RECHECK, icon_name="refresh")
        self.btn_again.clicked.connect(self.recheck)
        self.btn_repair = Button(S.P_REPAIR, icon_name="settings")
        self.btn_repair.clicked.connect(self.repair)
        self.btn_report = Button(S.P_REPORT, icon_name="log")
        self.btn_report.clicked.connect(self.save_report)
        for pair in ((self.btn_all, self.btn_again), (self.btn_repair, self.btn_report)):     # duas linhas: cabem em qualquer largura
            bar = QHBoxLayout()
            bar.setSpacing(SPACE.sm)
            for b in pair:
                bar.addWidget(b)
            bar.addStretch(1)
            self.col.addLayout(bar)
        self.summary = Label("", "help", wrap=True)
        self.col.addWidget(self.summary)

        self.card = Card()
        self.rows = QVBoxLayout()
        self.rows.setSpacing(SPACE.sm)
        self.card.body.addLayout(self.rows)
        self.col.addWidget(self.card)
        self.col.addStretch(1)

    # ------------------------------------------------------------------ ciclo de vida
    def on_enter(self) -> None:
        if not self.items and not self.ctx.demo:
            self.recheck()

    def teardown(self) -> None:
        self.cancel.set()

    def can_advance(self) -> bool:
        return not self._busy

    def on_leave(self, forward: bool) -> bool:
        if not forward:
            return True
        bad = [i for i in prereqs.blocking(self.items) if i.key != "models"]       # modelos têm a própria etapa logo depois
        if bad:
            return ask_confirm(self, S.P_LEAVE_TITLE, S.P_LEAVE_BODY.format(items=", ".join(i.title for i in bad)), S.H_FAIL_CONFIRM)
        return True

    # ------------------------------------------------------------------ checagem
    def recheck(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        _clear(self.rows)
        self.rows.addWidget(Label(S.H_CHECKING, "body"))
        root, man, comps = self.ctx.root, self.ctx.manifest, list(self.ctx.components)

        def work():
            vram, ram = 0, 0.0
            try:
                import psutil
                ram = psutil.virtual_memory().total / 1024 ** 3
            except Exception:                                                      # noqa: BLE001
                pass
            return prereqs.run_checks(root, man, comps, ram_gb=ram), ram

        run_async(work, self, lambda r: self._checked(r[0], r[1]), self._check_failed)

    def _check_failed(self, msg: str) -> None:
        self._set_busy(False)
        _clear(self.rows)
        self.rows.addWidget(Label(msg, "body", wrap=True))

    def _checked(self, items: list[prereqs.Item], ram_gb: float = 0.0) -> None:
        self._vram_mb, self._ram_gb = prereqs.vram_from_items(items), ram_gb
        self._set_busy(False)
        self.show_items(items)

    _GROUPS = (("", S.P_GRP_PC), ("Eco", S.P_GRP_ECO), ("Modelos", S.P_GRP_MODELS), ("Sistema", S.P_GRP_SYSTEM),
               ("Agentes", S.P_GRP_AGENTS), ("Opcional", S.P_GRP_OPTIONAL))

    def show_items(self, items: list[prereqs.Item]) -> None:
        self.items = items
        _clear(self.rows)
        for cat, title in self._GROUPS:
            group = [i for i in items if (i.category or "") == cat]
            if not group:
                continue
            self.rows.addWidget(Label(title, "caption"))
            for it in group:
                self.rows.addWidget(PrepRow(it, self._on_action, self._customize))
        _clear(self.msg_host)
        fails = prereqs.blocking(items)
        if not fails:
            self.msg_host.addWidget(InlineBanner("ok", S.P_ALL_OK))
        else:
            self.msg_host.addWidget(InlineBanner("warn", S.P_MISSING.format(n=len(fails))))
        n = lambda s: sum(1 for i in items if i.status == s)                      # noqa: E731
        self.summary.setText(S.P_SUMMARY.format(ok=n("ok"), warn=n("warn"), fail=n("fail"), opt=n("info")))
        self.btn_all.setEnabled(bool(fails))
        self.changed.emit()

    def _customize(self, item: prereqs.Item) -> None:
        """Abre o diálogo de caminho da ferramenta; se salvou, confere tudo de novo (o app já passa a usar o novo caminho)."""
        if self._busy or not item.tool:
            return
        factory = self.ctx.extra.get("tool_dialog_factory")
        if factory is not None:
            dlg = factory(item.tool, self)
        else:
            from .tool_dialog import ToolPathDialog
            dlg = ToolPathDialog(item.tool, self)
        dlg.exec()
        if getattr(dlg, "saved", False):
            self._log(f"caminho de {item.tool} personalizado")
            self.recheck()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for b in (self.btn_all, self.btn_again, self.btn_repair, self.btn_report):
            b.setEnabled(not busy)
        self.changed.emit()

    # ------------------------------------------------------------------ ações
    def _on_action(self, item: prereqs.Item) -> None:
        if self._busy:
            return
        a = item.action
        if a == "download_models":
            self._download_models()
        elif a == "install_vcredist":
            self._install_official(prereqs.VCREDIST)
        elif a == "install_ollama":
            self._install_official(prereqs.OLLAMA)
        elif a == "ollama_pull":
            self._pull_ollama()
        elif a == "open_gpu_driver":
            name = next((i.detail for i in self.items if i.key == "gpu"), "")
            self._open_url(prereqs.gpu_driver_url(name))
        elif a == "open_url":
            self._open_url(item.url)
        elif a == "repair":
            self.repair()

    def _open_url(self, url: str) -> None:
        """Abre o SITE OFICIAL no navegador (só https; o Eco não baixa nem instala nada por aqui)."""
        if not url.startswith("https://"):
            return
        opener = self.ctx.extra.get("open_url", webbrowser.open)
        opener(url)
        self._log(f"site oficial aberto: {url}")

    def prepare_all(self) -> None:
        """Faz o que é seguro sem instalar nada de terceiros: baixa o que falta dos modelos do Eco. O resto pede clique próprio."""
        if self._busy:
            return
        if any(i.action == "download_models" for i in self.items):
            self._download_models()
        else:
            self._banner("ok", S.P_NOTHING_SAFE)

    def _begin(self, title: str) -> None:
        self.cancel = threading.Event()
        self._set_busy(True)
        self.prog_card.setVisible(True)
        self.prog_title.setText(title)
        self.bar.set_progress(0, 1)
        self.prog_detail.setText("")
        self.btn_pause.setVisible(True)
        self.btn_pause.setEnabled(True)
        self._banner("ok", "")
        self._to_top()

    def _end(self) -> None:
        self._set_busy(False)
        self.btn_pause.setVisible(False)

    def _pause(self) -> None:
        self.cancel.set()
        self.btn_pause.setEnabled(False)

    def _to_top(self) -> None:
        """Rola a página para o topo: o aviso e o progresso ficam sempre à vista quando algo começa ou termina."""
        from PySide6.QtWidgets import QScrollArea
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if w is not None:
            w.verticalScrollBar().setValue(0)

    def _banner(self, state: str, what: str, why: str = "", todo: str = "") -> None:
        _clear(self.msg_host)
        if what:
            self.msg_host.addWidget(InlineBanner(state, what, why, todo))
            self._to_top()

    def _run(self, fn, on_done) -> None:
        self.job = _Job()
        self.job.progress.connect(self._on_progress)
        self.job.finished.connect(on_done)

        def target() -> None:
            try:
                res = fn(self.job.progress.emit)
            except (prereqs.PrepError, DownloadError) as exc:
                res = exc
            except Exception as exc:                                              # noqa: BLE001
                log.exception("falha inesperada na preparação")
                res = prereqs.PrepError("run", f"Falha inesperada: {exc}")
            self.job.finished.emit(res)

        self.thread = threading.Thread(target=target, name="setup-prepare", daemon=True)
        self.thread.start()

    def _on_progress(self, text: str, done: int, total: int, speed: float) -> None:
        if text:
            self.prog_title.setText(text)
        self.bar.set_progress(done, max(total, 1))
        parts = [f"{human_bytes(done)} de {human_bytes(total)}" if total else human_bytes(done)]
        if speed > 1 and total > done:
            parts += [S.M_SPEED.format(speed=human_bytes(speed)), S.M_ETA.format(eta=human_eta((total - done) / speed))]
        self.prog_detail.setText(" · ".join(parts))

    def _log(self, text: str) -> None:
        self.events.append(text)
        log.info(text)

    # ---- modelos do Eco (SHA-256 obrigatório; só dentro da pasta do Eco)
    def _download_models(self) -> None:
        entries = [f for f in self.ctx.manifest.files_for(list(self.ctx.components)) if not quick_present(f, self.ctx.root)]
        if not entries:
            self.recheck()
            return
        self._begin(S.P_DL_MODELS)
        root, cancel = self.ctx.root, self.cancel

        def work(emit):
            def cb(p: Progress) -> None:
                emit(f"{S.M_PHASE.get(p.phase, p.phase)}: {Path(p.file).name}", p.overall_done, p.overall_total, p.speed)
            Downloader(root, cb, cancel).fetch_all(entries)
            return ("models", len(entries))
        self._run(work, self._models_done)

    def _models_done(self, res) -> None:
        self._end()
        if isinstance(res, DownloadError):
            self.prog_card.setVisible(res.kind == "cancelled")
            self._log(f"modelos: {res.kind}")
            self._banner("warn" if res.kind == "cancelled" else "error", res.message)
            return
        self.prog_card.setVisible(False)
        self._log(f"modelos: {res[1]} arquivo(s) baixados e conferidos")
        self.recheck()

    # ---- instaladores de terceiros (site oficial + assinatura + confirmação)
    def _install_official(self, spec: prereqs.Official) -> None:
        site = spec.hosts[0]
        if not ask_confirm(self, S.P_OFF_TITLE.format(name=spec.name),
                           S.P_OFF_BODY.format(name=spec.name, site=site, size=human_bytes(spec.approx_bytes), note=spec.note),
                           S.P_OFF_YES):
            return
        self._begin(S.P_DL_OFFICIAL.format(name=spec.name))
        cancel = self.cancel
        dest = self.ctx.root / "data" / "setup" / "downloads"

        def work(emit):
            last = [0.0, 0]
            import time

            def prog(done, total):
                now = time.monotonic()
                spd = (done - last[1]) / (now - last[0]) if last[0] and now > last[0] else 0.0
                if now - last[0] > 0.4 or done >= total:
                    emit("", done, total, spd)
                    last[0], last[1] = now, done
            path, sig = prereqs.fetch_verified(spec, dest, prog, cancel)
            return ("downloaded", spec, path, sig)
        self._run(work, self._official_downloaded)

    def _official_downloaded(self, res) -> None:
        self._end()
        if isinstance(res, prereqs.PrepError):
            self.prog_card.setVisible(res.kind == "cancelled")
            self._log(f"instalador oficial: {res.kind}")
            self._banner("warn" if res.kind == "cancelled" else "error", res.message)
            return
        _tag, spec, path, sig = res
        self.prog_card.setVisible(False)
        digest = prereqs.sha256_of(path)
        who = prereqs.signer_name(sig.subject)
        self._log(f"{spec.key}: assinatura válida de {who}; sha256 {digest[:16]}…")
        body = S.P_RUN_BODY.format(name=spec.name, who=who, sha=digest[:16], admin=S.P_RUN_ADMIN if spec.elevate else "")
        if not ask_confirm(self, S.P_RUN_TITLE.format(name=spec.name), body, S.P_RUN_YES):
            self._banner("warn", S.P_RUN_DECLINED)
            return
        self._begin(S.P_INSTALLING.format(name=spec.name))
        self.btn_pause.setVisible(False)
        runner = self.ctx.extra.get("prep_run_installer", prereqs.run_installer)

        def work(emit):
            emit("", 0, 0, 0.0)
            return ("installed", spec, runner(path, spec.args, elevate=spec.elevate))
        self._run(work, self._installed)

    def _installed(self, res) -> None:
        self._end()
        self.prog_card.setVisible(False)
        if isinstance(res, prereqs.PrepError):
            self._log(f"instalação: {res.kind}")
            self._banner("warn" if res.kind == "cancelled" else "error", res.message)
            return
        _tag, spec, code = res
        meaning = prereqs.INSTALL_OK_CODES.get(code)
        self._log(f"{spec.key}: instalador terminou com código {code}")
        if meaning:
            self._banner("ok", S.P_INSTALLED.format(name=spec.name, what=meaning))
        else:
            self._banner("error", S.P_INSTALL_FAIL.format(name=spec.name, code=code), "", S.P_INSTALL_FAIL_TODO)
        self.recheck()

    # ---- Ollama (opcional)
    def _pull_ollama(self) -> None:
        rec = prereqs.recommended_ollama_model(self._vram_mb, self._ram_gb or 16.0)
        tag = rec.tag
        if not ask_confirm(self, S.P_PULL_TITLE.format(tag=tag), S.P_PULL_BODY.format(tag=tag, gb=f"{rec.approx_gb:.1f}", why=rec.why), S.P_PULL_YES):
            return
        self._begin(S.P_PULLING.format(tag=tag))
        cancel = self.cancel

        def work(emit):
            prereqs.ollama_pull(tag, lambda st, done, total: emit(f"{tag}: {st}", done, total, 0.0), cancel)
            return ("pulled", tag)
        self._run(work, self._pulled)

    def _pulled(self, res) -> None:
        self._end()
        if isinstance(res, prereqs.PrepError):
            self.prog_card.setVisible(res.kind == "cancelled")
            self._banner("warn" if res.kind == "cancelled" else "error", res.message)
            return
        self.prog_card.setVisible(False)
        self._log(f"ollama: modelo {res[1]} baixado")
        self._banner("ok", S.P_PULLED.format(tag=res[1]))
        self.recheck()

    # ---- reparar e relatório
    def repair(self) -> None:
        """Confere o SHA-256 de cada arquivo do Eco presente, apaga o corrompido e baixa de novo; depois checa tudo."""
        if self._busy:
            return
        entries = self.ctx.manifest.files_for(list(self.ctx.components))
        present = [e for e in entries if quick_present(e, self.ctx.root)]
        self._begin(S.P_REPAIRING)
        root, cancel = self.ctx.root, self.cancel

        def work(emit):
            total = sum(e.size for e in present) or 1
            done, bad = 0, []
            for e in present:
                name = Path(e.path).name
                ok = verify_file(e, root, cancel, lambda n, e=e, d=done: emit(f"Conferindo {name}", d + n, total, 0.0))
                if not ok:
                    bad.append(name)
                    try:
                        e.dest(root).unlink()
                    except OSError:
                        pass
                done += e.size
            missing = [e for e in entries if not quick_present(e, root)]
            if missing:
                def cb(p: Progress) -> None:
                    emit(f"{S.M_PHASE.get(p.phase, p.phase)}: {Path(p.file).name}", p.overall_done, p.overall_total, p.speed)
                Downloader(root, cb, cancel).fetch_all(missing)
            return ("repaired", bad, len(missing))
        self._run(work, self._repaired)

    def _repaired(self, res) -> None:
        self._end()
        if isinstance(res, (prereqs.PrepError, DownloadError)):
            self.prog_card.setVisible(getattr(res, "kind", "") == "cancelled")
            self._banner("warn" if getattr(res, "kind", "") == "cancelled" else "error", res.message)
            return
        self.prog_card.setVisible(False)
        _tag, bad, refetched = res
        self._log(f"reparo: {len(bad)} corrompido(s), {refetched} baixado(s) de novo")
        self.recheck()
        self._banner("ok", S.P_REPAIRED.format(bad=len(bad), n=refetched))

    def save_report(self) -> None:
        try:
            path = prereqs.write_report(self.ctx.root, self.items, self.events)
        except OSError as exc:
            self._banner("error", S.P_REPORT_FAIL, str(exc))
            return
        self._banner("ok", S.P_REPORT_OK.format(path=path))
