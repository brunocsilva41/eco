"""Páginas 4 a 10: áudio, teste de voz, calibragem do VAD, atalhos, permissões, verificação final e conclusão."""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..ui.kit.base import Label, set_a11y
from ..ui.kit.buttons import Button
from ..ui.kit.feedback import InlineBanner
from ..ui.kit.fields import ComboField
from ..ui.kit.keycapture import KeyCaptureField
from ..ui.kit.layout import Card, FieldRow
from ..ui.kit.meters import LevelMeter, ProgressBar
from ..ui.kit.tasks import run_async
from ..ui.settings.hotkeys import to_config, to_display
from ..ui.theme import SPACE
from . import audio_tools, config_io, strings as S
from .manifest import quick_present
from .pages_core import clear
from .widgets import CheckRow, Ctx, Page, make_toggle

log = logging.getLogger("jarvis.setup.pages")
NOWIN = 0x08000000


def _file_missing(ctx: Ctx, pkg_id: str) -> bool:
    pkg = ctx.manifest.packages.get(pkg_id)
    return pkg is None or not all(quick_present(f, ctx.root) for f in pkg.files)


# ----------------------------------------------------------------------------- 4. microfone e som
class AudioPage(Page):
    key = "audio"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.rec: audio_tools.Recorder | None = None
        self._quiet = 0
        self.mic = ComboField()
        self.out = ComboField()
        self.col.addWidget(FieldRow(S.A_MIC, self.mic, help=S.A_MIC_HELP, stacked=True))
        self.meter = LevelMeter()
        set_a11y(self.meter, "Nível do microfone ao vivo", S.A_LIVE)
        self.live = Label(S.A_LIVE, "help")
        self.col.addWidget(self.live)
        self.col.addWidget(self.meter)
        self.banner_host = QVBoxLayout()
        self.col.addLayout(self.banner_host)
        self.col.addWidget(FieldRow(S.A_OUT, self.out, help=S.A_OUT_HELP, stacked=True))
        self.refresh_btn = Button(S.A_REFRESH, icon_name="refresh")
        self.refresh_btn.clicked.connect(self.reload_devices)
        self.col.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.col.addStretch(1)
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick)
        self.mic.valueChanged.connect(lambda _v: self._restart())

    def reload_devices(self) -> None:
        cfg = self.ctx.cfg
        for combo, kind, cur in ((self.mic, "input", cfg.audio.input_device), (self.out, "output", cfg.audio.output_device)):
            combo.blockSignals(True)
            combo.clear()
            items = audio_tools.device_choices(kind)
            for label, val in items:
                combo.addItem(label, val)
            want = cur if isinstance(cur, str) else None
            idx = combo.findData(want)
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)
        self._restart()

    def on_enter(self) -> None:
        self.reload_devices()
        if not self.ctx.demo:
            self.timer.start()

    def _restart(self) -> None:
        self._stop()
        self._quiet = 0
        clear(self.banner_host)
        if self.ctx.demo or not self.isVisible() and not self.timer.isActive():
            return
        try:
            self.rec = audio_tools.Recorder(self.mic.value())
            self.rec.start()
        except Exception as exc:  # noqa: BLE001
            self.rec = None
            log.warning("microfone não abriu: %s", exc)
            self.banner_host.addWidget(InlineBanner("error", S.A_LIVE_FAIL, str(exc), S.A_LIVE_FAIL_TODO))

    def _stop(self) -> None:
        if self.rec is not None:
            self.rec.stop()
            self.rec = None
        self.meter.set_level(-60.0)

    def _tick(self) -> None:
        if self.rec is not None:
            db = self.rec.level_db
            self.meter.set_level(db)
            self._quiet = self._quiet + 1 if db <= -85.0 else 0
            if self._quiet == 60 * 3:                       # ~3,6 s de silêncio digital: microfone mudo ou sem permissão
                self.banner_host.addWidget(InlineBanner("warn", S.A_SILENT, S.A_SILENT_WHY, S.A_SILENT_TODO))
            elif db > -85.0:
                self._quiet = 0

    def on_leave(self, forward: bool) -> bool:
        self.timer.stop()
        self._stop()
        if forward:
            try:
                self.ctx.cfg = config_io.save_values({"audio.input_device": self.mic.value(),
                                                     "audio.output_device": self.out.value()})
            except Exception as exc:  # noqa: BLE001
                log.warning("não salvei os dispositivos: %s", exc)
        self.ctx.state.choices["mic"] = self.mic.currentText()
        self.ctx.state.choices["out"] = self.out.currentText()
        return True

    def teardown(self) -> None:
        self.timer.stop()
        self._stop()


# ----------------------------------------------------------------------------- 5. teste de voz
class VoicePage(Page):
    key = "voice"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.stop_evt = threading.Event()
        self.busy = False
        self.banner_host = QVBoxLayout()
        self.col.addLayout(self.banner_host)
        c1 = Card(S.V_SPEAK)
        self.btn_speak = Button(S.V_SPEAK, variant="primary", icon_name="listen")
        self.btn_speak.clicked.connect(self.speak)
        self.btn_stop = Button(S.V_STOP, icon_name="stop")
        self.btn_stop.clicked.connect(lambda: self.stop_evt.set())
        self.btn_stop.setVisible(False)
        row = QHBoxLayout()
        row.addWidget(self.btn_speak)
        row.addWidget(self.btn_stop)
        row.addStretch(1)
        c1.body.addLayout(row)
        self.status1 = Label("", "help", wrap=True)
        c1.add(self.status1)
        self.col.addWidget(c1)

        c2 = Card(S.V_ECHO)
        c2.add(Label(S.V_ECHO_HELP, "help", wrap=True))
        self.meter = LevelMeter()
        set_a11y(self.meter, "Nível do microfone", "")
        self.btn_echo = Button(S.V_ECHO, icon_name="record")
        self.btn_echo.clicked.connect(self.echo)
        c2.add(self.btn_echo)
        c2.add(self.meter)
        self.status2 = Label("", "body", wrap=True)
        c2.add(self.status2)
        c2.add(Label(S.V_ECHO_TIP, "help", wrap=True))
        self.col.addWidget(c2)
        self.col.addStretch(1)
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick)
        self.rec: audio_tools.Recorder | None = None
        self.left = 0.0

    def on_enter(self) -> None:
        clear(self.banner_host)
        if _file_missing(self.ctx, "piper-faber"):
            self.banner_host.addWidget(InlineBanner("warn", S.V_NO_MODEL, "", S.V_NO_MODEL_TODO))
            self.btn_speak.setEnabled(False)
        else:
            self.btn_speak.setEnabled(True)

    def _out(self) -> str | None:
        v = self.ctx.cfg.audio.output_device
        return v if isinstance(v, str) else None

    def _in(self) -> str | None:
        v = self.ctx.cfg.audio.input_device
        return v if isinstance(v, str) else None

    def speak(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.stop_evt = threading.Event()
        self.btn_speak.setVisible(False)
        self.btn_stop.setVisible(True)
        self.status1.setText(S.V_SPEAKING)
        cfg, out, ev = self.ctx.cfg, self._out(), self.stop_evt

        def done(_r) -> None:
            self.busy = False
            self.btn_speak.setVisible(True)
            self.btn_stop.setVisible(False)
            self.status1.setText("")

        def fail(msg: str) -> None:
            done(None)
            self.banner_host.addWidget(InlineBanner("error", "Não consegui tocar a voz", msg, "Confira a saída de som na etapa anterior."))

        run_async(lambda: audio_tools.speak_sample(cfg, out, S.V_SPEAK_TEXT, ev), self, done, fail)

    def echo(self) -> None:
        if self.busy:
            return
        self.busy = True
        clear(self.banner_host)
        self.btn_echo.setEnabled(False)
        try:
            self.rec = audio_tools.Recorder(self._in())
            self.rec.start()
        except Exception as exc:  # noqa: BLE001
            self.busy = False
            self.btn_echo.setEnabled(True)
            self.banner_host.addWidget(InlineBanner("error", S.A_LIVE_FAIL, str(exc), S.A_LIVE_FAIL_TODO))
            return
        self.left = 4.0
        self.peak = -90.0
        self.timer.start()

    def _tick(self) -> None:
        if self.rec is None:
            return
        self.left -= self.timer.interval() / 1000
        db = self.rec.level_db
        self.peak = max(self.peak, db)
        self.meter.set_level(db)
        self.status2.setText(S.V_ECHO_REC.format(s=max(0, int(self.left + 0.99))))
        if self.left <= 0:
            self.timer.stop()
            data = self.rec.stop()
            self.rec = None
            self.meter.set_level(-60.0)
            self.status2.setText(S.V_ECHO_PLAY)
            cfg, out = self.ctx.cfg, self._out()
            peak = self.peak

            def done(_r) -> None:
                self.busy = False
                self.btn_echo.setEnabled(True)
                self.status2.setText(S.V_HEARD_LOW if peak < -42 else S.V_HEARD_HOT if peak > -3 else S.V_HEARD_OK)
                self.status2.set_state("warn" if peak < -42 or peak > -3 else "ok")

            def fail(msg: str) -> None:
                done(None)
                self.banner_host.addWidget(InlineBanner("error", "Não consegui tocar a gravação", msg, ""))

            run_async(lambda: audio_tools.play_pcm(cfg, out, data), self, done, fail)

    def teardown(self) -> None:
        self.stop_evt.set()
        self.timer.stop()
        if self.rec is not None:
            self.rec.stop()
            self.rec = None

    def on_leave(self, forward: bool) -> bool:
        if self.busy:
            return False
        self.teardown()
        return True

    def can_advance(self) -> bool:
        return not self.busy


# ----------------------------------------------------------------------------- 6. calibragem do VAD
class VadPage(Page):
    key = "vad"
    NOISE_S, SPEECH_S = 3.0, 4.0

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.threshold: float | None = None
        self.use = True
        self.stage = "idle"
        self.col.addWidget(Label(S.D_INTRO, "body", wrap=True))
        self.banner_host = QVBoxLayout()
        self.col.addLayout(self.banner_host)
        card = Card()
        self.status = Label("", "label", wrap=True)
        self.bar = ProgressBar()
        self.meter = LevelMeter()
        set_a11y(self.meter, "Nível do microfone", "")
        self.btn = Button(S.D_START, variant="primary", icon_name="record")
        self.btn.clicked.connect(self.begin)
        card.add(self.btn)
        card.add(self.status)
        card.add(self.bar)
        card.add(self.meter)
        self.col.addWidget(card)
        self.result_host = QVBoxLayout()
        self.col.addLayout(self.result_host)
        self.col.addStretch(1)
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick)
        self.rec: audio_tools.Recorder | None = None
        self.noise = np.zeros(0, dtype=np.float32)
        self.left = 0.0

    def on_enter(self) -> None:
        clear(self.banner_host)
        self.btn.setEnabled(True)
        if _file_missing(self.ctx, "silero-vad"):
            self.banner_host.addWidget(InlineBanner("warn", S.D_NO_MODEL, "", S.D_NO_MODEL_TODO))
            self.btn.setEnabled(False)

    def begin(self) -> None:
        clear(self.banner_host)
        clear(self.result_host)
        v = self.ctx.cfg.audio.input_device
        try:
            self.rec = audio_tools.Recorder(v if isinstance(v, str) else None)
            self.rec.start()
        except Exception as exc:  # noqa: BLE001
            self.banner_host.addWidget(InlineBanner("error", S.A_LIVE_FAIL, str(exc), S.A_LIVE_FAIL_TODO))
            return
        self.btn.setEnabled(False)
        self.stage, self.left, self.total = "noise", self.NOISE_S, self.NOISE_S
        self.timer.start()

    def _tick(self) -> None:
        if self.rec is None:
            return
        self.left -= self.timer.interval() / 1000
        self.meter.set_level(self.rec.level_db)
        txt = S.D_STEP1 if self.stage == "noise" else S.D_STEP2
        self.status.setText(txt.format(s=max(0, int(self.left + 0.99))))
        self.bar.set_progress(self.total - max(self.left, 0), self.total)
        if self.left > 0:
            return
        data = self.rec.stop()
        if self.stage == "noise":
            self.noise = data
            v = self.ctx.cfg.audio.input_device
            self.rec = audio_tools.Recorder(v if isinstance(v, str) else None)
            self.rec.start()
            self.stage, self.left, self.total = "speech", self.SPEECH_S, self.SPEECH_S
            return
        self.timer.stop()
        self.rec = None
        self.meter.set_level(-60.0)
        self.stage = "calc"
        self.status.setText("Calculando...")
        noise, speech, vad_path = self.noise, data, self.ctx.root / "models" / "silero" / "silero_vad.onnx"
        run_async(lambda: audio_tools.calibrate_vad(noise, speech, vad_path), self, self._done, self._fail)

    def _fail(self, msg: str) -> None:
        self.stage = "idle"
        self.btn.setEnabled(True)
        self.status.setText("")
        self.banner_host.addWidget(InlineBanner("error", "Não consegui calibrar", msg, "Tente de novo falando mais perto do microfone."))

    def _done(self, cal: audio_tools.Calibration) -> None:
        self.show_result(cal)

    def show_result(self, cal: audio_tools.Calibration) -> None:
        self.stage = "idle"
        self.btn.setEnabled(True)
        self.btn.setText(S.D_AGAIN)
        self.status.setText("")
        self.bar.set_progress(0, 1)
        clear(self.result_host)
        self.threshold = cal.threshold
        card = Card(S.D_RESULT.format(thr=f"{cal.threshold:.2f}".replace(".", ",")))
        card.add(Label(S.D_RESULT_HELP.format(noise=f"{cal.noise_db:.0f}", speech=f"{cal.speech_db:.0f}"), "body", wrap=True))
        for n in cal.notes:
            card.add(Label(n, "help", wrap=True))
        row = QHBoxLayout()
        self.t_use = make_toggle(True, accessible_name=S.D_USE)
        self.t_use.valueChanged.connect(lambda v: setattr(self, "use", v))
        self.use = True
        row.addWidget(self.t_use)
        row.addWidget(Label(S.D_USE, "label"))
        row.addStretch(1)
        card.body.addLayout(row)
        self.result_host.addWidget(card)

    def on_leave(self, forward: bool) -> bool:
        self.timer.stop()
        if self.rec is not None:
            self.rec.stop()
            self.rec = None
        if forward and self.threshold is not None and self.use:
            try:
                self.ctx.cfg = config_io.save_values({"audio.vad_threshold": float(self.threshold)})
                self.ctx.state.choices["vad"] = self.threshold
            except Exception as exc:  # noqa: BLE001
                log.warning("não salvei o limiar do VAD: %s", exc)
        return True

    def teardown(self) -> None:
        self.timer.stop()
        if self.rec is not None:
            self.rec.stop()
            self.rec = None

    def next_label(self) -> str:
        return S.NEXT if self.threshold is not None else S.SKIP

    def can_advance(self) -> bool:
        return self.stage in ("idle",)


# ----------------------------------------------------------------------------- 7. atalhos
class HotkeysPage(Page):
    key = "hotkeys"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.fields: dict[str, KeyCaptureField] = {}
        self.status: dict[str, Label] = {}
        self.rows: dict[str, FieldRow] = {}
        spec = (("safety.talk_key", S.K_TALK, S.K_TALK_HELP, S.K_ALTS_TALK),
                ("safety.emergency_hotkey", S.K_EMERGENCY, S.K_EMERGENCY_HELP, S.K_ALTS),
                ("safety.mute_hotkey", S.K_MUTE, S.K_MUTE_HELP, S.K_ALTS))
        self.alts = {k: alts for k, _t, _h, alts in spec}
        for key, title, help_, _alts in spec:
            f = KeyCaptureField("", accessible_name=title)
            f.valueChanged.connect(lambda _v, k=key: self._check(k))
            self.fields[key] = f
            st = Label("", "help", wrap=True)
            self.status[key] = st
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(SPACE.xs)
            line = QHBoxLayout()
            line.addWidget(f, 1)
            sug = Button(S.K_SUGGEST)
            sug.clicked.connect(lambda _c=False, k=key: self._suggest(k))
            line.addWidget(sug)
            lay.addLayout(line)
            lay.addWidget(st)
            row = FieldRow(title, box, help=help_, stacked=True)
            self.rows[key] = row
            self.col.addWidget(row)
        self.col.addWidget(Label(S.K_NOTE, "help", wrap=True))
        self.col.addStretch(1)

    def on_enter(self) -> None:
        s = self.ctx.cfg.safety
        for key, val in (("safety.talk_key", s.talk_key), ("safety.emergency_hotkey", s.emergency_hotkey),
                         ("safety.mute_hotkey", s.mute_hotkey)):
            f = self.fields[key]
            f.blockSignals(True)
            f.set_value(to_display(val))
            f.blockSignals(False)
        for key in self.fields:
            self._check(key)

    def _running(self) -> bool:
        from ..settings.control import read_runtime
        try:
            return read_runtime(self.ctx.cfg.paths.data) is not None
        except Exception:  # noqa: BLE001
            return False

    def _probe(self, combo: str) -> str | None:
        """None = livre; texto = motivo. Registra e solta o atalho de verdade (RegisterHotKey)."""
        from ..win.hotkeys import HotkeyError, HotkeyListener
        lst = HotkeyListener()
        try:
            lst.start()
            lst.add(combo, lambda: None)
            return None
        except HotkeyError as exc:
            return str(exc)
        finally:
            lst.stop()

    def _check(self, key: str) -> None:
        f, lab, row = self.fields[key], self.status[key], self.rows[key]
        combo = to_config(f.value())
        problem = self._validate()
        row.set_error(problem.get(key))
        f.set_invalid(key in problem)
        if key in problem:
            lab.setText("")
            return
        if self.ctx.demo:
            lab.setText(S.K_FREE if key != "safety.talk_key" else S.K_FREE)
            return
        if self._running():
            lab.setText(S.K_RUNNING)
            return
        lab.setText(S.K_TESTING)
        why = self._probe(combo)
        lab.setText(S.K_FREE if why is None else f"{S.K_BUSY}: {why}")
        lab.set_state("" if why is None else "warn")

    def _values(self) -> dict[str, str]:
        return {k: to_config(f.value()) for k, f in self.fields.items()}

    def _validate(self) -> dict[str, str]:
        vals = self._values()
        probs = config_io.store().validate(vals)
        mapped = {p.key: p.message for p in probs if p.key in vals}
        if probs and not mapped:                       # erro geral (ex.: duas teclas iguais): marca as três
            return {k: S.K_INVALID for k in vals}
        return mapped

    def _suggest(self, key: str) -> None:
        used = set(self._values().values())
        for alt in self.alts[key]:
            if alt not in used:
                self.fields[key].set_value(to_display(alt))
                return

    def on_leave(self, forward: bool) -> bool:
        if not forward:
            return True
        probs = self._validate()
        if probs:
            for k in probs:
                self.fields[k].setFocus()
            return False
        vals = self._values()
        try:
            self.ctx.cfg = config_io.save_values(vals)
        except Exception as exc:  # noqa: BLE001
            self.rows["safety.talk_key"].set_error(str(exc))
            return False
        self.ctx.state.choices["talk"] = vals["safety.talk_key"]
        self.ctx.state.choices["emergency"] = vals["safety.emergency_hotkey"]
        return True


# ----------------------------------------------------------------------------- 8. permissões
class PermissionsPage(Page):
    key = "permissions"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.mode = "balanced"
        self.cards: dict[str, Card] = {}
        self.buttons: dict[str, Button] = {}
        for mode, title, body in (("balanced", S.P_BALANCED, S.P_BALANCED_BODY), ("strict", S.P_STRICT, S.P_STRICT_BODY)):
            card = Card()
            card.add(Label(title, "heading"))
            card.add(Label(body, "body", wrap=True))
            btn = Button("", variant="secondary")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _c=False, m=mode: self.select(m))
            card.add(btn)
            self.cards[mode], self.buttons[mode] = card, btn
            self.col.addWidget(card)
        y = Card()
        y.add(Label(S.P_YOLO_TITLE, "heading"))
        y.add(Label(S.P_YOLO_BODY, "body", wrap=True))
        set_a11y(y, S.P_YOLO_TITLE, S.P_YOLO_BODY)
        self.col.addWidget(y)
        self.col.addStretch(1)

    def select(self, mode: str) -> None:
        self.mode = mode
        for m, b in self.buttons.items():
            on = m == mode
            b.setChecked(on)
            b.setText("Escolhido" if on else "Escolher este")
            b.set_variant("primary" if on else "secondary")
            b.setAccessibleName(f"{'Escolhido' if on else 'Escolher'}: {S.P_BALANCED if m == 'balanced' else S.P_STRICT}")
        self.ctx.state.choices["profile"] = mode

    def on_enter(self) -> None:
        self.select(self.ctx.cfg.safety.permission_mode if self.ctx.cfg.safety.permission_mode in self.buttons else "balanced")

    def on_leave(self, forward: bool) -> bool:
        if forward:
            try:
                self.ctx.cfg = config_io.save_values({"safety.permission_mode": self.mode})
            except Exception as exc:  # noqa: BLE001
                log.warning("não salvei o perfil: %s", exc)
        return True


# ----------------------------------------------------------------------------- 9. doctor
class DoctorPage(Page):
    key = "doctor"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.results = []
        self.busy = False
        self.sum_host = QVBoxLayout()
        self.col.addLayout(self.sum_host)
        self.card = Card()
        self.rows = QVBoxLayout()
        self.rows.setSpacing(SPACE.sm)
        self.card.body.addLayout(self.rows)
        self.col.addWidget(self.card)
        self.again = Button(S.X_RUN, icon_name="refresh")
        self.again.clicked.connect(self.run)
        self.col.addWidget(self.again, 0, Qt.AlignmentFlag.AlignLeft)
        self.col.addStretch(1)

    def on_enter(self) -> None:
        if not self.ctx.demo:
            self.run()

    def run(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.again.setEnabled(False)
        clear(self.rows)
        clear(self.sum_host)
        self.rows.addWidget(Label(S.X_RUNNING, "body"))
        self.changed.emit()
        cfg = self.ctx.reload_cfg()
        self.ctx.cfg = cfg

        def work():
            from ..doctor import run_doctor
            return run_doctor(cfg)

        run_async(work, self, self._done, self._fail)

    def _fail(self, msg: str) -> None:
        self.busy = False
        self.again.setEnabled(True)
        clear(self.rows)
        self.sum_host.addWidget(InlineBanner("error", "A verificação falhou", msg, "Tente de novo."))
        self.changed.emit()

    def _done(self, results) -> None:
        self.busy = False
        self.again.setEnabled(True)
        self.show_results(results)
        self.changed.emit()

    def show_results(self, results) -> None:
        self.results = results
        clear(self.rows)
        clear(self.sum_host)
        bad = [r for r in results if not r.ok]
        for r in results:
            hint = "" if r.ok else S.X_FAIL_HINTS.get(r.name, S.X_DEFAULT_HINT)
            self.rows.addWidget(CheckRow("ok" if r.ok else "fail", r.name, r.detail, hint))
        self.sum_host.addWidget(InlineBanner("ok" if not bad else "warn",
                                             S.X_ALL_OK if not bad else S.X_SOME_FAIL,
                                             f"{len(results) - len(bad)} de {len(results)} verificações ok."))

    def can_advance(self) -> bool:
        return not self.busy

    def teardown(self) -> None:
        pass


# ----------------------------------------------------------------------------- 10. tudo pronto
class DonePage(Page):
    key = "done"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx)
        self.col.addWidget(Label(S.F_HEADLINE, "display"))
        self.lead = Label("", "body", wrap=True)
        self.col.addWidget(self.lead)
        self.warn_host = QVBoxLayout()
        self.col.addLayout(self.warn_host)
        self.summary = Card(S.F_SUMMARY)
        self.col.addWidget(self.summary)
        self.autostart = make_toggle(False, accessible_name=S.F_AUTOSTART)
        self.auto_row = QHBoxLayout()
        self.auto_row.addWidget(self.autostart)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(Label(S.F_AUTOSTART, "label"))
        col.addWidget(Label(S.F_AUTOSTART_HELP, "help", wrap=True))
        self.auto_row.addLayout(col, 1)
        self.auto_box = QWidget()
        self.auto_box.setLayout(self.auto_row)
        self.col.addWidget(self.auto_box)
        self.open_btn = Button(S.F_OPEN, variant="primary", icon_name="listen")
        self.open_btn.clicked.connect(self.open_jarvis)
        self.col.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.col.addStretch(1)
        self.launch = True

    def next_label(self) -> str:
        return S.FINISH

    def on_enter(self) -> None:
        cfg = self.ctx.reload_cfg()
        self.ctx.cfg = cfg
        clear(self.warn_host)
        self.lead.setText(S.F_LEAD.format(talk=to_display(cfg.safety.talk_key)))
        ctx = self.ctx
        missing = [f for f in ctx.manifest.files_for(ctx.components) if not quick_present(f, ctx.root)]
        if missing:
            self.warn_host.addWidget(InlineBanner("warn", S.F_INCOMPLETE))
        for i in range(self.summary.body.count() - 1, 0, -1):
            it = self.summary.body.takeAt(i)
            if it.widget():
                it.widget().hide()
                it.widget().setParent(None)
                it.widget().deleteLater()
        mic = cfg.audio.input_device or S.F_DEFAULT_DEV
        out = cfg.audio.output_device or S.F_DEFAULT_DEV
        profile = {"balanced": "Equilibrado", "strict": "Estrito"}.get(cfg.safety.permission_mode, cfg.safety.permission_mode)
        for k, v in ((S.F_SUM_MODELS, "completos" if not missing else f"faltam {len(missing)} arquivo(s)"),
                     (S.F_SUM_MIC, str(mic)), (S.F_SUM_OUT, str(out)),
                     (S.F_SUM_TALK, to_display(cfg.safety.talk_key)), (S.F_SUM_EMERG, to_display(cfg.safety.emergency_hotkey)),
                     (S.F_SUM_PROFILE, profile), (S.F_SUM_VAD, f"{cfg.audio.vad_threshold:.2f}".replace(".", ","))):
            row = QHBoxLayout()
            a = Label(k, "help")
            a.setFixedWidth(SPACE.xxl * 4)
            row.addWidget(a)
            row.addWidget(Label(v, "body", wrap=True), 1)
            w = QWidget()
            w.setLayout(row)
            self.summary.add(w)
        avail = config_io.autostart_available(ctx.root)
        self.auto_box.setVisible(avail)
        if avail:
            self.autostart.setChecked(config_io.autostart_enabled())

    def on_leave(self, forward: bool) -> bool:
        if forward and self.auto_box.isVisible():
            try:
                config_io.set_autostart(self.autostart.isChecked(), self.ctx.root)
            except Exception as exc:  # noqa: BLE001
                log.warning("Iniciar com o Windows: %s", exc)
        return True

    def open_jarvis(self) -> None:
        self.launch = True
        self.window().close_and_launch()          # type: ignore[attr-defined]
