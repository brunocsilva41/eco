"""Janela do gravador de voz (PySide6). Toda a lógica vive em ``jarvis.recording``; aqui só há interface.

Fluxo: escolher conjunto e microfone -> Gravar (ou Espaço) -> a gravação para sozinha ao fim da contagem ->
resultado com avaliação -> Próxima (ou Enter). Nada trava a UI: o áudio roda em stream próprio (thread do
PortAudio + vigia) e a janela só lê o medidor/estado por um QTimer de ~30 fps.

Segurança de dados: um arquivo existente nunca é substituído sem confirmação; gravação é atômica.
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..config import Config
from ..recording.audio_analysis import FLOOR_DBFS, Assessment, assess, to_dbfs
from ..recording.phrasebook import PhraseBook, PhraseError
from ..recording.player import PlaybackError, Player
from ..recording.recorder import (InputChoice, MicRecorder, RecorderError, RecorderState, list_input_choices)
from ..recording.session import (ItemStatus, OverwriteError, RecordingSession, RecordingSet, SessionError,
                                 sentences_set, wakeword_set)
from . import theme

log = logging.getLogger(__name__)

TICK_MS = 33
MIN_TAKE_S = 0.5                    # gravação mais curta que isso não é salva
METER_FLOOR_DB = -60.0
METER_WARN_DB = -6.0
METER_CLIP_DB = -1.0                # zona de saturação (vermelha) começa aqui
PEAK_HOLD_S = 1.0
PEAK_FALL_DB_PER_S = 30.0

_STATUS_MARK = {ItemStatus.PENDING: "○", ItemStatus.RECORDED: "✓", ItemStatus.SKIPPED: "↷"}
_STATUS_COLOR = {ItemStatus.PENDING: theme.TEXT_MUTED, ItemStatus.RECORDED: theme.OK, ItemStatus.SKIPPED: theme.WARN}
_SET_CHOICES = (("sentences", "Frases"), ("wakeword", "Palavra de ativação"))


def _fmt_seconds(value: float) -> str:
    return f"{max(0.0, value):.1f}".replace(".", ",") + " s"


def _fmt_db(value: float) -> str:
    return "-∞" if value <= FLOOR_DBFS else f"{value:.1f}".replace(".", ",")


# ====================================================================== widgets de desenho
class LevelMeter(QWidget):
    """Barra horizontal em dBFS (-60..0): RMS preenchido, marca de pico com retenção e zona de saturação."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(theme.SP3)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._rms_db = FLOOR_DBFS
        self._peak_db = FLOOR_DBFS
        self._hold_db = FLOOR_DBFS
        self._hold_age = 0.0

    def set_level(self, peak: float, rms: float, dt: float = TICK_MS / 1000) -> None:
        self._rms_db = to_dbfs(rms)
        self._peak_db = to_dbfs(peak)
        if self._peak_db >= self._hold_db:
            self._hold_db, self._hold_age = self._peak_db, 0.0
        else:
            self._hold_age += dt
            if self._hold_age > PEAK_HOLD_S:
                self._hold_db = max(self._peak_db, self._hold_db - PEAK_FALL_DB_PER_S * dt)
        self.update()

    @property
    def is_idle(self) -> bool:
        return self._rms_db <= FLOOR_DBFS and self._hold_db <= FLOOR_DBFS

    def reset(self) -> None:
        self._rms_db = self._peak_db = self._hold_db = FLOOR_DBFS
        self._hold_age = 0.0
        self.update()

    @staticmethod
    def _frac(db: float) -> float:
        return max(0.0, min(1.0, (db - METER_FLOOR_DB) / -METER_FLOOR_DB))

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.RADIUS_SM
        painter.setPen(QPen(QColor(theme.BORDER)))
        painter.setBrush(QColor(theme.SURFACE_ALT))
        painter.drawRoundedRect(rect, radius, radius)
        width = rect.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setClipRect(rect)
        # zona de saturação (fundo)
        clip_x = rect.left() + width * self._frac(METER_CLIP_DB)
        painter.setBrush(QColor(theme.ERROR).darker(300))
        painter.drawRect(QRectF(clip_x, rect.top(), rect.right() - clip_x, rect.height()))
        # barra RMS por segmentos de cor
        fill = rect.left() + width * self._frac(self._rms_db)
        for lo_db, hi_db, color in ((METER_FLOOR_DB, METER_WARN_DB, theme.OK),
                                    (METER_WARN_DB, METER_CLIP_DB, theme.WARN),
                                    (METER_CLIP_DB, 0.0, theme.ERROR)):
            x0, x1 = rect.left() + width * self._frac(lo_db), min(fill, rect.left() + width * self._frac(hi_db))
            if x1 > x0:
                painter.setBrush(QColor(color))
                painter.drawRect(QRectF(x0, rect.top() + 3, x1 - x0, rect.height() - 6))
        # pico com retenção
        if self._hold_db > FLOOR_DBFS:
            x = rect.left() + width * self._frac(self._hold_db)
            hot = self._hold_db >= METER_CLIP_DB
            painter.setPen(QPen(QColor(theme.ERROR if hot else theme.TEXT), 2))
            painter.drawLine(QPointF(x, rect.top() + 2), QPointF(x, rect.bottom() - 2))
        painter.end()


class WaveformView(QWidget):
    """Miniforma de onda (mín/máx por coluna de pixels) desenhada com QPainter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(theme.SP4 * 2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._samples: NDArray[np.float32] | None = None
        self._color = theme.ACCENT
        self._cache: tuple[int, NDArray[np.float32], NDArray[np.float32]] | None = None

    def set_samples(self, samples: NDArray[np.float32] | None, state: str = "ok") -> None:
        self._samples = samples if samples is not None and samples.size else None
        self._color = theme.state_color(state) if samples is not None else theme.ACCENT
        self._cache = None
        self.update()

    def _columns(self, width: int) -> tuple[NDArray[np.float32], NDArray[np.float32]] | None:
        data = self._samples
        if data is None or width <= 0:
            return None
        if self._cache is not None and self._cache[0] == width:
            return self._cache[1], self._cache[2]
        cols = min(width, data.size)
        edges = np.linspace(0, data.size, cols + 1, dtype=np.int64)[:-1]
        lows = np.minimum.reduceat(data, edges)
        highs = np.maximum.reduceat(data, edges)
        self._cache = (width, lows, highs)
        return lows, highs

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(theme.BORDER)))
        painter.setBrush(QColor(theme.SURFACE_ALT))
        painter.drawRoundedRect(rect, theme.RADIUS_SM, theme.RADIUS_SM)
        mid = rect.center().y()
        painter.setPen(QPen(QColor(theme.BORDER)))
        painter.drawLine(QPointF(rect.left(), mid), QPointF(rect.right(), mid))
        cols = self._columns(int(rect.width()))
        if cols is not None:
            lows, highs = cols
            half = rect.height() / 2 - 3
            painter.setPen(QPen(QColor(self._color), 1))
            n = lows.size
            step = rect.width() / n
            for i in range(n):
                x = rect.left() + (i + 0.5) * step
                painter.drawLine(QPointF(x, mid - float(highs[i]) * half), QPointF(x, mid - float(lows[i]) * half - 0.5))
        painter.end()


class Banner(QFrame):
    """Aviso não bloqueante com botão opcional 'Tentar de novo'."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SP2, theme.SP1, theme.SP1, theme.SP1)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._retry = QPushButton("Tentar de novo")
        self._retry.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._retry.setProperty("variant", "primary")
        self._close = QPushButton("✕")
        self._close.setProperty("variant", "ghost")
        self._close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close.setFixedWidth(theme.SP4)
        row.addWidget(self._label, 1)
        row.addWidget(self._retry)
        row.addWidget(self._close)
        self._action: Callable[[], None] | None = None
        self._retry.clicked.connect(self._on_retry)
        self._close.clicked.connect(self.clear)
        self.hide()

    def show_message(self, text: str, state: str = "warn", retry: Callable[[], None] | None = None) -> None:
        self._action = retry
        self._label.setText(text)
        self.setProperty("state", state)
        self._label.setProperty("state", state)
        self._retry.setVisible(retry is not None)
        theme.repolish(self)
        theme.repolish(self._label)
        self.show()

    def clear(self) -> None:
        self._action = None
        self.hide()

    def _on_retry(self) -> None:
        action, self._action = self._action, None
        self.hide()
        if action is not None:
            action()


# ====================================================================== janela
class RecorderWindow(QWidget):
    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle("Jarvis - Gravador de voz")
        self.setStyleSheet(theme.build_stylesheet())
        self.resize(1080, 720)
        self.setMinimumSize(900, 620)

        self._session: RecordingSession | None = None
        self._book: PhraseBook | None = None
        self._recorder = MicRecorder(1.0)                 # recriado por conjunto (duração própria)
        self._player = Player(cfg.audio)
        self._take: NDArray[np.float32] | None = None
        self._assessment: Assessment | None = None
        self._rec_active = False
        self._rec_index = 0
        self._rec_overwrite = False
        self._syncing = False

        self._build_ui()
        self._build_shortcuts()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._populate_mics(rescan=False)
        self._load_set(0)

    # ------------------------------------------------------------------ construção da UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SP3, theme.SP2, theme.SP3, theme.SP3)
        root.setSpacing(theme.SP2)

        top = QHBoxLayout()
        top.setSpacing(theme.SP2)
        title = QLabel("Minha voz")
        title.setProperty("role", "title")
        self._set_combo = QComboBox()
        for _key, label in _SET_CHOICES:
            self._set_combo.addItem(label)
        self._mic_combo = QComboBox()
        self._mic_combo.setMinimumWidth(280)
        self._refresh_btn = self._button("Atualizar", "ghost")
        self._refresh_btn.setToolTip("Relê a lista de microfones")
        top.addWidget(title)
        top.addSpacing(theme.SP2)
        top.addWidget(QLabel("Conjunto:"))
        top.addWidget(self._set_combo)
        top.addSpacing(theme.SP2)
        top.addWidget(QLabel("Microfone:"))
        top.addWidget(self._mic_combo, 1)
        top.addWidget(self._refresh_btn)
        root.addLayout(top)

        self._banner = Banner()
        root.addWidget(self._banner)

        body = QHBoxLayout()
        body.setSpacing(theme.SP2)
        root.addLayout(body, 1)

        # painel esquerdo: lista + editor
        left = QVBoxLayout()
        left.setSpacing(theme.SP1)
        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setMinimumWidth(300)
        self._list.setMaximumWidth(380)
        left.addWidget(self._list, 1)
        editor = QHBoxLayout()
        editor.setSpacing(theme.SP1)
        self._add_btn = self._button("Adicionar")
        self._edit_btn = self._button("Editar")
        self._remove_btn = self._button("Remover")
        self._up_btn = self._button("↑")
        self._down_btn = self._button("↓")
        for b in (self._up_btn, self._down_btn):
            b.setFixedWidth(theme.SP4 + theme.SP1)
        for b in (self._add_btn, self._edit_btn, self._remove_btn, self._up_btn, self._down_btn):
            editor.addWidget(b)
        self._editor_box = QWidget()
        self._editor_box.setLayout(editor)
        editor.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self._editor_box)
        body.addLayout(left)

        # painel direito
        card = QFrame()
        card.setObjectName("card")
        right = QVBoxLayout(card)
        right.setContentsMargins(theme.SP3, theme.SP3, theme.SP3, theme.SP3)
        right.setSpacing(theme.SP2)
        self._progress_label = QLabel()
        self._progress_label.setProperty("role", "muted")
        self._instruction = QLabel()
        self._instruction.setProperty("role", "muted")
        self._instruction.setWordWrap(True)
        self._phrase = QLabel()
        self._phrase.setProperty("role", "phrase")
        self._phrase.setWordWrap(True)
        self._phrase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._phrase.setMinimumHeight(theme.SP4 * 3)
        right.addWidget(self._progress_label)
        right.addWidget(self._instruction)
        right.addWidget(self._phrase, 1)

        self._countdown = QLabel()
        self._countdown.setProperty("role", "countdown")
        self._countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setTextVisible(False)
        self._meter = LevelMeter()
        meter_caption = QLabel("Nível do microfone (dBFS): zona vermelha = saturação")
        meter_caption.setProperty("role", "muted")
        right.addWidget(self._countdown)
        right.addWidget(self._bar)
        right.addWidget(self._meter)
        right.addWidget(meter_caption)

        self._wave = WaveformView()
        self._verdict = QLabel()
        self._verdict.setWordWrap(True)
        self._verdict.setProperty("role", "title")
        self._metrics = QLabel()
        self._metrics.setProperty("role", "metric")
        self._hint = QLabel()
        self._hint.setProperty("role", "muted")
        self._hint.setWordWrap(True)
        right.addWidget(self._wave)
        right.addWidget(self._verdict)
        right.addWidget(self._metrics)
        right.addWidget(self._hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP1)
        self._prev_btn = self._button("‹ Anterior")
        self._record_btn = self._button("Gravar", "primary")
        self._listen_btn = self._button("Ouvir")
        self._redo_btn = self._button("Regravar")
        self._skip_btn = self._button("Pular")
        self._next_btn = self._button("Próxima ›")
        for b in (self._prev_btn, self._record_btn, self._listen_btn, self._redo_btn, self._skip_btn, self._next_btn):
            buttons.addWidget(b)
        right.addLayout(buttons)
        body.addWidget(card, 1)

        self._set_combo.activated.connect(self._on_set_chosen)
        self._mic_combo.activated.connect(lambda _i: self.setFocus())
        self._refresh_btn.clicked.connect(lambda: self._populate_mics(rescan=True))
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._record_btn.clicked.connect(self._toggle_record)
        self._redo_btn.clicked.connect(lambda: self._start_recording())
        self._listen_btn.clicked.connect(self._toggle_listen)
        self._skip_btn.clicked.connect(self._skip)
        self._next_btn.clicked.connect(self._next)
        self._prev_btn.clicked.connect(self._previous)
        self._add_btn.clicked.connect(self._add_phrase)
        self._edit_btn.clicked.connect(self._edit_phrase)
        self._remove_btn.clicked.connect(self._remove_phrase)
        self._up_btn.clicked.connect(lambda: self._move_phrase(-1))
        self._down_btn.clicked.connect(lambda: self._move_phrase(1))

    @staticmethod
    def _button(text: str, variant: str | None = None) -> QPushButton:
        btn = QPushButton(text)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)       # Espaço/Enter pertencem aos atalhos da janela
        if variant:
            btn.setProperty("variant", variant)
        return btn

    def _build_shortcuts(self) -> None:
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._shortcuts = [
            self._shortcut("Space", self._toggle_record),
            self._shortcut("Return", self._next),
            self._shortcut("Enter", self._next),
        ]

    def _shortcut(self, keys: str, slot: Callable[[], None]) -> QShortcut:
        sc = QShortcut(QKeySequence(keys), self)
        sc.setContext(Qt.ShortcutContext.WindowShortcut)
        sc.activated.connect(slot)
        return sc

    # ------------------------------------------------------------------ microfones
    def _populate_mics(self, rescan: bool) -> None:
        if self._rec_active:
            return
        self._player.stop()
        previous = self._mic_combo.currentData() if self._mic_combo.count() else self._cfg.audio.input_device
        try:
            choices: list[InputChoice] = list_input_choices(rescan=rescan)
        except Exception as exc:  # noqa: BLE001 - DeviceError ou falha do PortAudio
            log.warning("não consegui listar os microfones: %s", exc)
            choices = []
            self._banner.show_message(f"Não consegui listar os microfones: {exc}", "error",
                                      lambda: self._populate_mics(rescan=True))
        self._mic_combo.blockSignals(True)
        self._mic_combo.clear()
        default = next((c for c in choices if c.is_default), None)
        self._mic_combo.addItem("Padrão do Windows" + (f" ({default.label})" if default else ""), None)
        for c in choices:
            self._mic_combo.addItem(c.label + ("  [padrão]" if c.is_default else ""), c.spec)
        pos = self._mic_combo.findData(previous)
        if pos < 0 and previous not in (None, ""):
            if isinstance(previous, str):       # nome configurado: tenta casar por trecho
                needle = previous.casefold()
                pos = next((i for i in range(1, self._mic_combo.count())
                            if needle in self._mic_combo.itemText(i).casefold()), -1)
            if pos < 0:
                self._mic_combo.addItem(f"Configurado: {previous} (indisponível)", previous)
                pos = self._mic_combo.count() - 1
        self._mic_combo.setCurrentIndex(max(pos, 0))
        self._mic_combo.blockSignals(False)

    # ------------------------------------------------------------------ conjuntos
    def _on_set_chosen(self, index: int) -> None:
        self.setFocus()
        if self._rec_active:
            return
        self._load_set(index)

    def _load_set(self, index: int) -> None:
        self._player.stop()
        key = _SET_CHOICES[index][0]
        self._book = None
        try:
            if key == "sentences":
                recording_set = self._load_sentences()
            else:
                recording_set = wakeword_set(self._cfg)
        except (ValueError, OSError) as exc:
            log.exception("não consegui montar o conjunto %s", key)
            self._banner.show_message(f"Não consegui montar este conjunto: {exc}", "error")
            return
        self._session = RecordingSession(recording_set)
        self._recorder.stop(discard=True)
        self._recorder = MicRecorder(recording_set.duration_s)
        self._take, self._assessment = None, None
        self._set_combo.setCurrentIndex(index)
        self._meter.reset()
        self._instruction.setText(recording_set.instruction)
        self._editor_box.setVisible(recording_set.editable)
        self._rebuild_list()
        self._load_current()

    def _load_sentences(self) -> RecordingSet:
        path = self._cfg.paths.root / "tests" / "frases_pt.txt"
        book = PhraseBook(path, autoload=False)
        try:
            book.load()
        except PhraseError as exc:
            self._banner.show_message(f"{exc} A lista foi aberta vazia e não será alterada.", "error")
        self._book = book
        return sentences_set(self._cfg, book)

    # ------------------------------------------------------------------ lista lateral
    def _rebuild_list(self) -> None:
        session = self._session
        if session is None:
            return
        self._syncing = True
        try:
            self._list.clear()
            rset = session.recording_set
            for i, status in enumerate(session.statuses):
                item = QListWidgetItem(f"{_STATUS_MARK[status]}  {i + 1:02d}  {rset.label(i)}")
                item.setForeground(QColor(_STATUS_COLOR[status] if status is not ItemStatus.PENDING else theme.TEXT))
                item.setToolTip(f"{rset.filename(i)} - {status.value}")
                self._list.addItem(item)
            if session.count:
                self._list.setCurrentRow(session.index)
        finally:
            self._syncing = False

    def _on_row_changed(self, row: int) -> None:
        if self._syncing or self._session is None or row < 0 or self._rec_active:
            return
        self._player.stop()
        self._session.goto(row)
        self._load_current()

    # ------------------------------------------------------------------ item atual
    def _load_current(self) -> None:
        """Atualiza o texto e carrega a gravação existente (se houver) para mostrar onda e avaliação."""
        session = self._session
        if session is None:
            return
        self._take, self._assessment = None, None
        if session.count and session.status(session.index) is ItemStatus.RECORDED:
            try:
                self._take = session.load(session.index)
                self._assessment = assess(self._take, session.recording_set.sample_rate)
            except SessionError as exc:
                self._banner.show_message(f"A gravação existente não pôde ser lida: {exc}", "warn")
        self._hint.setText("")
        self._refresh_view()

    def _refresh_view(self) -> None:
        session = self._session
        if session is None:
            return
        rset = session.recording_set
        empty = session.count == 0
        self._progress_label.setText(
            "Nenhuma frase na lista. Use Adicionar." if empty else
            f"Item {session.position_text}  ·  {session.progress_text} gravadas  ·  arquivo {rset.filename(session.index)}")
        self._phrase.setText("" if empty else session.current_phrase)
        if not self._rec_active:
            self._countdown.setText(_fmt_seconds(rset.duration_s))
            self._bar.setValue(0)
        if self._take is not None and self._assessment is not None:
            a = self._assessment
            state = theme.level_state(a.level)
            self._wave.set_samples(self._take, state)
            self._verdict.setText(a.message)
            self._verdict.setProperty("state", state)
            self._metrics.setText(
                f"Pico {_fmt_db(a.peak_dbfs)} dBFS  ·  RMS {_fmt_db(a.rms_dbfs)} dBFS  ·  "
                f"saturação {a.clip_rate * 100:.2f}%".replace(".", ",") + f"  ·  duração {_fmt_seconds(a.duration_s)}")
        else:
            self._wave.set_samples(None)
            self._verdict.setText("" if self._rec_active else ("" if empty else "Pronto para gravar."))
            self._verdict.setProperty("state", "")
            self._metrics.setText("")
        theme.repolish(self._verdict)
        self._update_controls()
        self._sync_list_row()

    def _sync_list_row(self) -> None:
        session = self._session
        if session is None or not session.count:
            return
        self._syncing = True
        try:
            for i, status in enumerate(session.statuses):
                item = self._list.item(i)
                if item is None:
                    continue
                rset = session.recording_set
                item.setText(f"{_STATUS_MARK[status]}  {i + 1:02d}  {rset.label(i)}")
                item.setForeground(QColor(_STATUS_COLOR[status] if status is not ItemStatus.PENDING else theme.TEXT))
            if self._list.currentRow() != session.index:
                self._list.setCurrentRow(session.index)
        finally:
            self._syncing = False

    def _update_controls(self) -> None:
        session = self._session
        recording = self._rec_active
        has_items = session is not None and session.count > 0
        recorded = has_items and session.status(session.index) is ItemStatus.RECORDED     # type: ignore[union-attr]
        playing = self._player.is_playing
        self._record_btn.setText("Parar" if recording else "Gravar")
        self._record_btn.setProperty("variant", "danger" if recording else ("primary" if not recorded else None))
        self._record_btn.setEnabled(recording or (has_items and not recorded))
        self._redo_btn.setEnabled(has_items and not recording and recorded)
        self._listen_btn.setText("Parar áudio" if playing else "Ouvir")
        self._listen_btn.setEnabled(not recording and self._take is not None)
        self._skip_btn.setEnabled(has_items and not recording)
        self._next_btn.setEnabled(has_items and not recording)
        self._next_btn.setProperty("variant", "primary" if recorded and not recording else None)
        self._prev_btn.setEnabled(has_items and not recording and session.index > 0)       # type: ignore[union-attr]
        for w in (self._set_combo, self._mic_combo, self._refresh_btn, self._list):
            w.setEnabled(not recording)
        editable = session is not None and session.recording_set.editable and not recording
        self._add_btn.setEnabled(editable)
        for b in (self._edit_btn, self._remove_btn, self._up_btn, self._down_btn):
            b.setEnabled(editable and has_items)
        for b in (self._record_btn, self._next_btn):
            theme.repolish(b)

    # ------------------------------------------------------------------ gravação
    def _toggle_record(self) -> None:
        if self._rec_active:
            self._recorder.stop()                         # mantém o que já foi gravado; _tick conclui
            return
        if self._session is None or not self._session.count:
            return
        self._start_recording()

    def _confirm_overwrite(self, name: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Substituir gravação?")
        box.setText(f"Já existe a gravação {name}.")
        box.setInformativeText("Gravar de novo vai SUBSTITUIR o arquivo atual. Deseja continuar?")
        replace_btn = box.addButton("Substituir", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.setEscapeButton(cancel_btn)
        box.exec()
        return box.clickedButton() is replace_btn

    def _start_recording(self, confirmed: bool = False) -> None:
        session = self._session
        if session is None or not session.count or self._rec_active:
            return
        self._banner.clear()
        self._player.stop()
        index = session.index
        exists = session.would_overwrite(index)
        if exists and not confirmed and not self._confirm_overwrite(session.recording_set.filename(index)):
            return
        self._recorder.set_device(self._mic_combo.currentData())
        try:
            self._recorder.start()
        except RecorderError as exc:
            self._show_recorder_error(exc)
            return
        self._rec_active = True
        self._rec_index = index
        self._rec_overwrite = exists
        self._take, self._assessment = None, None
        self._meter.reset()
        self._verdict.setText("Gravando... fale agora.")
        self._verdict.setProperty("state", "")
        theme.repolish(self._verdict)
        self._metrics.setText("")
        self._hint.setText("")
        self._wave.set_samples(None)
        self._update_controls()

    def _show_recorder_error(self, exc: RecorderError) -> None:
        log.warning("erro de gravação (%s): %s", exc.kind, exc)
        self._banner.show_message(str(exc), "error", self._retry_recording)

    def _retry_recording(self) -> None:
        self._populate_mics(rescan=True)
        self._start_recording(confirmed=True)

    def _tick(self) -> None:
        rec = self._recorder
        if self._rec_active:
            state = rec.state
            if state is RecorderState.RECORDING:
                reading = rec.level()
                self._meter.set_level(reading.peak, reading.rms)
                self._countdown.setText(_fmt_seconds(rec.remaining_s))
                self._bar.setValue(int(rec.progress * 1000))
            else:
                self._finish_recording(state)
        elif not self._meter.is_idle:
            self._meter.reset()
        if self._listen_btn.text() == "Parar áudio" and not self._player.is_playing:
            self._update_controls()

    def _finish_recording(self, state: RecorderState) -> None:
        rec = self._recorder
        self._rec_active = False
        self._meter.reset()
        index = self._rec_index
        if state is RecorderState.ERROR and rec.error is not None:
            error = rec.error
            rec.reset()
            self._verdict.setText("")
            self._show_recorder_error(error)
            self._refresh_view()
            return
        samples = rec.samples
        rec.reset()
        if state is not RecorderState.FINISHED or samples is None:
            self._refresh_view()                          # descartada
            return
        rate = self._session.recording_set.sample_rate if self._session else 16000
        self._bar.setValue(1000)
        duration = samples.size / rate
        self._countdown.setText(_fmt_seconds(duration))
        self._take = samples
        self._assessment = assess(samples, rate)
        if duration < MIN_TAKE_S:
            self._refresh_view()
            self._verdict.setText(f"Gravação curta demais ({_fmt_seconds(duration)}): não foi salva. Grave de novo.")
            self._verdict.setProperty("state", "warn")
            theme.repolish(self._verdict)
            return
        if self._assessment.level == "silencio":
            self._refresh_view()
            self._hint.setText("Esta gravação NÃO foi salva. Verifique o microfone e use Gravar para tentar de novo.")
            return
        self._save_take(index, samples, overwrite=self._rec_overwrite)

    def _save_take(self, index: int, samples: NDArray[np.float32], overwrite: bool) -> None:
        session = self._session
        if session is None:
            return
        try:
            session.save(index, samples, overwrite=overwrite)
        except OverwriteError:
            name = session.recording_set.filename(index)
            if self._confirm_overwrite(name):
                self._save_take(index, samples, overwrite=True)
                return
            self._hint.setText(f"A gravação não foi salva ({name} já existe).")
            self._refresh_view()
            return
        except SessionError as exc:
            log.error("falha ao salvar a gravação %d: %s", index, exc)
            self._banner.show_message(f"Não consegui salvar a gravação: {exc}", "error",
                                      lambda: self._save_take(index, samples, overwrite))
            self._refresh_view()
            return
        self._refresh_view()
        if session.is_complete:
            self._hint.setText("Conjunto concluído. Use Ouvir/Regravar se quiser revisar alguma.")
        else:
            self._hint.setText("Gravado. Aperte Enter (Próxima) para continuar.")

    # ------------------------------------------------------------------ ouvir
    def _toggle_listen(self) -> None:
        if self._player.is_playing:
            self._player.stop()
            self._update_controls()
            return
        if self._take is None or self._session is None:
            return
        try:
            self._player.play(self._take, self._session.recording_set.sample_rate)
        except PlaybackError as exc:
            self._banner.show_message(str(exc), "error", self._toggle_listen)
        self._update_controls()

    # ------------------------------------------------------------------ navegação
    def _skip(self) -> None:
        session = self._session
        if session is None or not session.count or self._rec_active:
            return
        self._player.stop()
        session.skip()
        self._advance()

    def _next(self) -> None:
        session = self._session
        if session is None or not session.count or self._rec_active:
            return
        self._player.stop()
        self._advance()

    def _advance(self) -> None:
        session = self._session
        if session is None:
            return
        self._banner.clear()
        if not session.next():
            if session.next_pending() is None:
                self._load_current()
                self._banner.show_message(
                    f"Fim do conjunto: {session.progress_text} gravadas. Pode fechar a janela ou revisar os itens.",
                    "ok")
                return
        self._load_current()

    def _previous(self) -> None:
        session = self._session
        if session is None or self._rec_active:
            return
        self._player.stop()
        if session.previous():
            self._load_current()

    # ------------------------------------------------------------------ editor de frases
    def _warn_recorded(self, action: str, index: int) -> bool:
        """Pede confirmação quando a edição afeta um item que já tem gravação."""
        session = self._session
        if session is None or not session.exists(index):
            return True
        ans = QMessageBox.question(
            self, "Item já gravado",
            f"O item {index + 1} já tem a gravação {session.recording_set.filename(index)}. Os arquivos são "
            f"associados às frases pelo número; {action} pode deixar o áudio e a frase fora de par. Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return ans == QMessageBox.StandardButton.Yes

    def _apply_book_change(self, select: int | None) -> None:
        session, book = self._session, self._book
        if session is None or book is None:
            return
        session.set_phrases(book.phrases)
        if select is not None and session.count:
            session.goto(max(0, min(select, session.count - 1)))
        self._rebuild_list()
        self._load_current()

    def _book_or_warn(self) -> PhraseBook | None:
        if self._book is None or self._rec_active:
            return None
        if not self._book.writable:
            self._banner.show_message("O arquivo de frases não pôde ser lido; a edição está bloqueada para "
                                      "proteger seus dados.", "error")
            return None
        return self._book

    def _ask_text(self, title: str, label: str, text: str = "") -> str | None:
        value, ok = QInputDialog.getText(self, title, label, text=text)
        return value if ok else None

    def _add_phrase(self) -> None:
        book = self._book_or_warn()
        if book is None:
            return
        text = self._ask_text("Adicionar frase", "Nova frase (3 a 300 caracteres):")
        if text is None:
            return
        try:
            position = book.add(text)
        except PhraseError as exc:
            self._banner.show_message(str(exc), "warn")
            return
        self._banner.clear()
        self._apply_book_change(position)

    def _edit_phrase(self) -> None:
        book, session = self._book_or_warn(), self._session
        if book is None or session is None or not session.count:
            return
        index = session.index
        if not self._warn_recorded("editar a frase", index):
            return
        text = self._ask_text("Editar frase", "Frase:", book[index])
        if text is None:
            return
        try:
            book.edit(index, text)
        except PhraseError as exc:
            self._banner.show_message(str(exc), "warn")
            return
        self._banner.clear()
        self._apply_book_change(index)

    def _remove_phrase(self) -> None:
        book, session = self._book_or_warn(), self._session
        if book is None or session is None or not session.count:
            return
        index = session.index
        if not self._warn_recorded("remover a frase", index):
            return
        ans = QMessageBox.question(
            self, "Remover frase", f"Remover a frase?\n\n{book[index]}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            book.remove(index)
        except PhraseError as exc:
            self._banner.show_message(str(exc), "warn")
            return
        self._banner.clear()
        self._apply_book_change(index)

    def _move_phrase(self, delta: int) -> None:
        book, session = self._book_or_warn(), self._session
        if book is None or session is None or not session.count:
            return
        index = session.index
        target = index + delta
        if not 0 <= target < session.count:
            return
        if not (self._warn_recorded("mover a frase", index) and self._warn_recorded("mover a frase", target)):
            return
        try:
            final = book.move(index, target)
        except PhraseError as exc:
            self._banner.show_message(str(exc), "warn")
            return
        self._apply_book_change(final)

    # ------------------------------------------------------------------ ciclo de vida
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._rec_active and self._recorder.state is RecorderState.RECORDING:
            ans = QMessageBox.question(
                self, "Gravação em andamento",
                "Há uma gravação em andamento. Fechar agora descarta essa gravação. Fechar mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._timer.stop()
        self._rec_active = False
        self._recorder.stop(discard=True)
        self._player.stop()
        log.info("janela do gravador fechada")
        _forget(self)
        event.accept()


# ====================================================================== pontos de entrada
_instance: RecorderWindow | None = None


def _forget(window: RecorderWindow) -> None:
    global _instance
    if _instance is window:
        _instance = None


def open_recorder(cfg: Config, parent: QWidget | None = None) -> RecorderWindow:
    """Abre (ou traz à frente, se já aberta) a janela do gravador. Exige um ``QApplication`` ativo.

    A janela é mantida viva por esta função até ser fechada (não é preciso guardar o retorno).
    """
    global _instance
    if QApplication.instance() is None:
        raise RuntimeError("open_recorder precisa de um QApplication; use main_recorder(cfg) fora da interface")
    existing = _instance
    if existing is not None:
        try:
            if existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return existing
        except RuntimeError:                  # objeto Qt já destruído
            _instance = None
    window = RecorderWindow(cfg, parent)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    _instance = window
    window.show()
    window.raise_()
    window.activateWindow()
    return window


def main_recorder(cfg: Config) -> int:
    """Executa o gravador como programa próprio (cria o ``QApplication`` se não existir). Devolve o código de saída."""
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    if owns_app:
        theme.apply_theme(app)      # type: ignore[arg-type]
    window = open_recorder(cfg)
    if not owns_app:
        return 0                    # já existe um loop de eventos dono da janela
    return int(app.exec()) if window is not None else 1
