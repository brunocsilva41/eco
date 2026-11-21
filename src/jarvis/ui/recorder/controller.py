"""Controlador do gravador: liga modelo, servicos de audio e vista. E o unico lugar com fluxo de gravacao.

Regras que moram aqui (e so aqui):

* nunca substituir um arquivo sem ``ConfirmDialog`` (N-11: "Tentar de novo" so pula a confirmacao para o
  MESMO item cuja confirmacao ja foi dada; trocar de item limpa o aviso e a tentativa);
* so um QTimer, e so enquanto grava ou toca; leitura de disco, escrita e lista de microfones vao para
  ``run_async``; resultados atrasados sao descartados por "ficha" (token) e quando o dono some.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QWidget

from ...config import Config
from ...recording.audio_analysis import to_dbfs
from ...recording.player import PlaybackError
from ...recording.recorder import RecorderError, RecorderState
from ...recording.session import ItemStatus, RecordingSession
from ..kit.tasks import run_async
from . import model, presenter, viewmodel
from .confirmations import confirm_close_recording, confirm_overwrite
from .mics import MicPicker
from .phrase_actions import EditKind, PhraseActions
from .services import PlayerLike, RecorderLike, Services
from .state import Notice
from .texts import T
from .view import RecorderView

log = logging.getLogger(__name__)

TICK_MS = 33


class RecorderController(QObject):
    def __init__(self, cfg: Config, view: RecorderView, host: QWidget, services: Services | None = None) -> None:
        super().__init__(host)
        self._cfg = cfg
        self._view = view
        self._host = host
        svc = services or Services()
        self._player: PlayerLike = svc.make_player(cfg.audio)
        self._make_recorder = svc.make_recorder
        self._mics = MicPicker(view, svc, cfg.audio.input_device, self)
        self._recorder: RecorderLike | None = None
        self._session: RecordingSession | None = None
        self._editor: model.PhraseEditor | None = None
        self._st = viewmodel.ItemState(model.SET_FRASES)
        self._rec_index = 0
        self._rec_overwrite = False
        self._notice: Notice | None = None
        self._notice_action: Callable[[], None] | None = None
        self._shown_notice: Notice | None = None
        self._set_token = self._take_token = 0
        self._actions = PhraseActions(host, self._raise_notice, lambda: (self._session, self._editor), self._idle)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._wire()

    def _wire(self) -> None:
        v, a = self._view, self._view.actions
        v.setChosen.connect(self.load_set)
        v.refreshRequested.connect(lambda: self.refresh_mics(True))
        v.rowChosen.connect(self.select_row)
        v.noticeAction.connect(self._run_notice_action)
        v.retryLoad.connect(lambda: self.load_set(self._st.name))
        v.addRequested.connect(lambda: self._edit("add"))
        v.editRequested.connect(lambda: self._edit("edit"))
        v.removeRequested.connect(lambda: self._edit("remove"))
        v.moveRequested.connect(lambda delta: self._edit("move", delta))
        a.recordClicked.connect(self.toggle_record)
        a.redoClicked.connect(self.start_recording)
        a.listenClicked.connect(self.toggle_listen)
        a.skipClicked.connect(self.skip)
        a.nextClicked.connect(self.next)
        a.prevClicked.connect(self.previous)

    @property
    def is_recording(self) -> bool:
        return self._st.recording

    def _idle(self) -> bool:
        return self._session is not None and not self._st.recording and not self._st.busy

    def start(self, set_name: str) -> None:
        self.refresh_mics(False)
        self.load_set(set_name)

    def load_set(self, name: str) -> bool:
        """Carrega "frases" ou "jarvis" em segundo plano. False se nao der agora (gravando ou salvando)."""
        model.check_set_name(name)
        if self._st.recording or self._st.busy:
            self._view.set_sets(self._st.name)
            return False
        self._stop_audio()
        self._set_token += 1
        self._take_token += 1
        token = self._set_token
        self._session = self._editor = None
        self._st.clear_take()
        self._notice = self._notice_action = None
        self._st.name = name
        self._view.set_sets(name)
        self._view.show_loading(T.states.loading_jarvis if name == model.SET_JARVIS else T.states.loading_frases)
        cfg = self._cfg
        run_async(lambda: model.load_set(cfg, name), self, lambda r: self._on_set_loaded(token, r),
                  lambda msg: self._on_set_failed(token, msg))
        return True

    def _on_set_failed(self, token: int, detail: str) -> None:
        if token == self._set_token:
            n = T.failures.load_set
            log.error("conjunto %s nao carregou: %s", self._st.name, detail)
            self._view.show_error(n.what, n.why, n.todo)

    def _on_set_loaded(self, token: int, loaded: model.LoadedSet) -> None:
        if token != self._set_token:
            return
        self._session = loaded.session
        self._editor = model.PhraseEditor(loaded.session, loaded.book) if loaded.book is not None else None
        if self._recorder is not None:
            self._recorder.stop(discard=True)
        self._recorder = self._make_recorder(loaded.session.recording_set.duration_s)
        if loaded.book_error:                                   # lista ilegivel: tela de erro, edicao bloqueada
            f = T.failures.phrases_file
            log.error("%s: %s", f.what, loaded.book_error)
            self._view.show_error(f.what, f.why, f.todo)
            return
        self._push_rows()
        self._load_current()

    def refresh_mics(self, rescan: bool, then: Callable[[], None] | None = None) -> None:
        if self._st.recording:
            return
        self._stop_audio()
        self._mics.refresh(rescan, then, lambda detail: self._raise_notice(
            presenter.failure(T.failures.mic_list, action=T.failures.retry, detail=detail),
            lambda: self.refresh_mics(True)))

    def _load_current(self) -> None:
        """Mostra o item e, se ja foi gravado, le o arquivo e avalia em segundo plano."""
        session = self._session
        self._st.clear_take()
        self._take_token += 1
        token = self._take_token
        if session is None or not session.count:
            self._view.show_empty(editable=self._editor is not None)
            self._render()
            return
        self._view.show_ready()
        index = session.index
        self._render()
        if session.status(index) is ItemStatus.RECORDED:
            run_async(lambda: model.load_take(session, index), self, lambda t: self._on_take(token, t),
                      lambda msg: self._on_take(token, model.LoadedTake(index, None, None, msg)))

    def _on_take(self, token: int, t: model.LoadedTake) -> None:
        if token != self._take_token or self._st.recording:
            return
        self._st.take, self._st.assessment = t.samples, t.assessment
        if t.error:
            self._notice = presenter.failure(T.failures.unreadable_take, "warn", detail=t.error)
        self._render()

    def select_row(self, row: int) -> None:
        if self._session is not None and 0 <= row != self._session.index:
            self._navigate(lambda s: s.goto(row))

    def _leave_item(self) -> None:
        """Trocar de item limpa o aviso e, com ele, o "Tentar de novo" ligado ao item anterior (N-11)."""
        self._stop_audio()
        self._notice = self._notice_action = None

    def _navigate(self, step: Callable[[RecordingSession], None]) -> None:
        session = self._session
        if session is not None and session.count and self._idle():
            self._leave_item()
            step(session)
            self._load_current()

    def skip(self) -> None:
        self._navigate(self._skip_step)

    def _skip_step(self, session: RecordingSession) -> None:
        session.skip()
        self._advance(session)

    def next(self) -> None:
        self._navigate(self._advance)

    def previous(self) -> None:
        self._navigate(lambda s: s.previous())

    def _advance(self, session: RecordingSession) -> None:
        """Vai ao proximo item; no fim do conjunto, avisa que terminou. Atualiza a lista (o estado pode ter mudado)."""
        if not session.next() and session.next_pending() is None:
            self._notice = presenter.failure(T.levels.finished, "ok")
        self._push_rows()

    def toggle_record(self) -> None:
        if self._st.recording:
            if self._recorder is not None:
                self._recorder.stop()                  # mantem o que ja foi gravado; _tick conclui
            return
        self.start_recording()

    def cancel_recording(self) -> None:
        """Esc durante a gravacao: descarta esta tomada (nada foi salvo ainda)."""
        if self._st.recording and self._recorder is not None:
            self._recorder.stop(discard=True)
            self._finish_recording(self._recorder.state)

    def start_recording(self, *, preconfirmed: int | None = None) -> None:
        """Grava o item atual. ``preconfirmed`` e o item cuja substituicao o usuario ja confirmou numa tentativa
        que falhou; so ele dispensa a pergunta (N-11). Qualquer outro item com arquivo pergunta de novo."""
        session, recorder = self._session, self._recorder
        if session is None or recorder is None or not session.count or not self._idle():
            return
        index = session.index
        self._stop_audio()
        self._notice = self._notice_action = None
        exists = session.would_overwrite(index)
        if exists and preconfirmed != index and not confirm_overwrite(self._host, session, index):
            self._render()
            return
        recorder.set_device(self._view.mic_spec())
        try:
            recorder.start()
        except RecorderError as exc:
            log.warning("erro de gravacao (%s): %s", exc.kind, exc)
            self._raise_notice(presenter.device_notice(exc), lambda: self.retry_recording(index if exists else None))
            return
        self._st.recording = True
        self._rec_index, self._rec_overwrite = index, exists
        self._st.clear_take()
        self._take_token += 1
        self._view.set_capture("recording", session.recording_set.duration_s)
        self._timer.start()
        self._render()

    def retry_recording(self, preconfirmed: int | None) -> None:
        """"Tentar de novo": le os microfones de novo e grava. A confirmacao so e dispensada para o mesmo item."""
        index = self._session.index if self._session else -1

        def go() -> None:           # se o usuario trocou de item enquanto a lista era lida, nao grava nada
            if self._session is not None and self._session.index == index:
                self.start_recording(preconfirmed=preconfirmed)

        self.refresh_mics(True, then=go)

    @Slot()
    def _tick(self) -> None:
        rec, st = self._recorder, self._st
        if st.recording and rec is not None:
            if rec.state is RecorderState.RECORDING:
                self._view.set_live(to_dbfs(rec.level().peak), rec.remaining_s)
            else:
                self._finish_recording(rec.state)
        if st.playing and not self._player.is_playing:
            st.playing = False
            self._render()
        if not st.recording and not st.playing:
            self._timer.stop()

    def _finish_recording(self, state: RecorderState) -> None:
        rec, session = self._recorder, self._session
        if rec is None or session is None or not self._st.recording:
            return
        self._st.recording = False
        self._view.set_capture("idle", session.recording_set.duration_s)
        error, samples = rec.error, rec.samples
        rec.reset()
        if state is RecorderState.ERROR and error is not None:
            log.warning("erro durante a gravacao (%s): %s", error.kind, error)
            kept = self._rec_index if self._rec_overwrite else None
            self._raise_notice(presenter.device_notice(error), lambda: self.retry_recording(kept))
            return
        if state is not RecorderState.FINISHED or samples is None:
            self._render()                                      # descartada
            return
        decision = model.decide_take(samples, session.recording_set.sample_rate)
        self._st.take, self._st.assessment = samples, decision.assessment
        if decision.verdict != "save":
            self._st.unsaved = decision.verdict
            self._render()
            return
        self._save(self._rec_index, samples, self._rec_overwrite)

    def _save(self, index: int, samples: NDArray[np.float32], overwrite: bool) -> None:
        session = self._session
        if session is None:
            return
        self._st.busy = True
        self._render()
        run_async(lambda: model.save_take(session, index, samples, overwrite), self,
                  lambda r: self._on_saved(index, samples, overwrite, r),
                  lambda msg: self._on_saved(index, samples, overwrite, ("failed", msg)))

    def _on_saved(self, index: int, samples: NDArray[np.float32], overwrite: bool, result: tuple[str, str]) -> None:
        self._st.busy = False
        outcome, detail = result
        if outcome == "saved":
            self._push_rows()
            self._render()
        elif outcome == "exists":                             # o arquivo apareceu depois do inicio: pergunta de novo
            if self._session is not None and confirm_overwrite(self._host, self._session, index):
                self._save(index, samples, True)
                return
            self._st.take = self._st.assessment = None
            self._raise_notice(presenter.failure(T.failures.not_saved, "warn"))
        else:
            self._raise_notice(presenter.failure(T.failures.save, action=T.failures.retry, detail=detail),
                               lambda: self._save(index, samples, overwrite))

    def toggle_listen(self) -> None:
        if self._st.playing:
            self._stop_audio()
            self._render()
            return
        session = self._session
        if self._st.take is None or session is None or not self._idle():
            return
        try:
            self._player.play(self._st.take, session.recording_set.sample_rate)
        except PlaybackError as exc:
            log.warning("nao consegui tocar: %s", exc)
            self._raise_notice(presenter.failure(T.failures.playback, action=T.failures.retry, detail=str(exc)),
                               self.toggle_listen)
            return
        self._st.playing = True
        self._timer.start()
        self._render()

    def _stop_audio(self) -> None:
        self._player.stop()
        self._st.playing = False

    def _edit(self, kind: EditKind, delta: int = 0) -> None:
        if self._actions.run(kind, delta) is not None:
            self._leave_item()
            self._push_rows()
            self._load_current()

    def _raise_notice(self, notice: Notice, action: Callable[[], None] | None = None) -> None:
        self._notice, self._notice_action = notice, action
        self._render()

    @Slot()
    def _run_notice_action(self) -> None:
        action = self._notice_action
        self._notice = self._notice_action = None
        self._render()
        if action is not None:
            action()

    def _push_rows(self) -> None:
        s = self._session
        if s is not None:
            title = T.sidebar.title_jarvis if self._st.name == model.SET_JARVIS else T.sidebar.title_frases
            self._view.set_rows(title, presenter.rows(s), s.index)

    def _render(self) -> None:
        s, st = self._session, self._st
        if s is None:
            return
        self._view.set_stage(viewmodel.stage_view(s, st))
        self._view.set_result(viewmodel.result_view(st))
        self._view.set_controls(viewmodel.controls_for(s, st))
        shown = st.assessment if st.take is not None else None
        notice = self._notice or presenter.level_notice(shown, st.unsaved)
        if notice != self._shown_notice:
            self._shown_notice = notice
            self._view.set_notice(notice)
        self._view.sidebar.set_current(s.index)

    def confirm_close(self) -> bool:
        """True se pode fechar. Com gravacao em andamento pede confirmacao (fechar descarta a tomada)."""
        if not self._st.recording:
            return True
        return confirm_close_recording(self._host, self._session.current_phrase if self._session else "")

    def shutdown(self) -> None:
        """Para timer, microfone e som e invalida o que ainda esta em segundo plano. Idempotente."""
        self._timer.stop()
        self._set_token += 1
        self._take_token += 1
        self._mics.invalidate()
        if self._recorder is not None:
            self._recorder.stop(discard=True)
        self._player.stop()
        self._st.recording = self._st.playing = False
        log.info("gravador encerrado")
