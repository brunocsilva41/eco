"""Coluna central: progresso, frase em destaque, contagem, nivel ao vivo e o resultado da gravacao."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..kit.base import Label
from ..kit.indicator import ListeningIndicator
from ..kit.meters import CountdownRing, LevelMeter, ProgressBar
from ..kit.status import StatusChip
from ..theme import SIZE, SPACE, TYPE, make_font
from .model import METER_FLOOR_DB, METER_HIGH_DB, METER_LOW_DB
from .state import IndicatorKind, ResultView, StageView
from .texts import T
from .waveform import WaveformView


class StageWidget(QWidget):
    """So desenha o que o controlador manda (``apply``, ``set_result``, ``set_live``); nao decide nada."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, SPACE.md, 0)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(SPACE.md)
        self._position = Label("", "heading")
        self._chip = StatusChip("neutral", T.badges.pending)
        head.addWidget(self._position)
        head.addStretch(1)
        head.addWidget(self._chip)
        root.addLayout(head)
        root.addSpacing(SPACE.sm)
        self._progress = ProgressBar()
        root.addWidget(self._progress)
        root.addSpacing(SPACE.sm)
        self._recorded = Label("", "caption")
        root.addWidget(self._recorded)

        root.addSpacing(SPACE.xl)
        self._instruction = Label("", "help", wrap=True)
        root.addWidget(self._instruction)
        root.addSpacing(SPACE.sm)
        self._phrase = Label("", "display", wrap=True)
        self._phrase.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._phrase.setMinimumHeight(QFontMetrics(make_font(TYPE.display, TYPE.semibold)).lineSpacing() * 2)
        root.addWidget(self._phrase)

        root.addSpacing(SPACE.xxl)
        live = QHBoxLayout()
        live.setSpacing(SPACE.xl)
        self._ring = CountdownRing(20.0, diameter=SIZE.target * 4)
        live.addWidget(self._ring, 0, Qt.AlignmentFlag.AlignTop)
        side = QVBoxLayout()
        side.setSpacing(SPACE.xs)
        top = QHBoxLayout()
        top.addWidget(Label(T.stage.meter_caption, "label"))
        top.addStretch(1)
        self._indicator = ListeningIndicator("idle")
        top.addWidget(self._indicator)
        side.addLayout(top)
        self._meter = LevelMeter(floor_db=METER_FLOOR_DB, low_db=METER_LOW_DB, high_db=METER_HIGH_DB)
        side.addWidget(self._meter)
        side.addWidget(Label(T.stage.meter_help, "help", wrap=True))
        side.addStretch(1)
        live.addLayout(side, 1)
        root.addLayout(live)

        root.addSpacing(SPACE.lg)
        self._wave = WaveformView()
        root.addWidget(self._wave)
        root.addSpacing(SPACE.sm)
        self._metrics = Label("", "help", wrap=True)
        root.addWidget(self._metrics)
        root.addSpacing(SPACE.sm)
        self._hint = Label("", "body", wrap=True)
        root.addWidget(self._hint)
        root.addStretch(1)

    # --- estado da frase e do take
    def apply(self, v: StageView) -> None:
        self._position.setText(v.position)
        self._chip.set_state(v.badge.state, v.badge.text)
        done, total = v.progress
        self._progress.set_progress(done, max(total, 1))
        self._recorded.setText(f"{v.recorded}   ·   {T.window.file(v.filename)}" if v.filename else v.recorded)
        self._instruction.setText(v.instruction)
        self._phrase.setText(v.phrase)
        self._hint.setText(v.hint)
        self._ring.set_total(v.countdown_total)

    def set_result(self, r: ResultView) -> None:
        text = T.stage.wave_recording if r.recording else T.stage.wave_empty
        self._wave.set_wave(r.samples, r.level_state, text)
        self._metrics.setText(r.metrics)

    # --- ao vivo (chamado a cada tick de gravacao)
    def set_live(self, level_db: float, remaining_s: float) -> None:
        self._meter.set_level(level_db)
        self._ring.set_remaining(remaining_s)

    def set_capture(self, kind: IndicatorKind, remaining_s: float) -> None:
        """Entra/sai do modo de captura: anel ambar, indicador e medidor zerados."""
        self._indicator.set_state(kind)
        self._ring.set_active(kind == "recording")
        self._ring.set_remaining(remaining_s)
        self._meter.set_level(METER_FLOOR_DB)
        self._meter.reset_peak()
