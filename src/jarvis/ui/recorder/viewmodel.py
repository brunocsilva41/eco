"""Estado mutavel do item mostrado e funcoes puras que o convertem em dados de tela. Sem Qt."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ...recording.audio_analysis import Assessment
from ...recording.session import ItemStatus, RecordingSession
from . import presenter
from .model import TakeVerdict
from .state import Controls, ResultView, StageView
from .texts import T


@dataclass(slots=True)
class ItemState:
    """O que o controlador sabe do item atual alem do que a sessao guarda."""
    name: str
    take: NDArray[np.float32] | None = None
    assessment: Assessment | None = None
    unsaved: TakeVerdict | None = None
    recording: bool = False
    playing: bool = False
    busy: bool = False                    # salvando em segundo plano

    def clear_take(self) -> None:
        self.take = self.assessment = self.unsaved = None


def item_status(s: RecordingSession) -> ItemStatus:
    return s.status(s.index) if s.count else ItemStatus.PENDING


def stage_view(s: RecordingSession, st: ItemState) -> StageView:
    rset, has, status = s.recording_set, s.count > 0, item_status(s)
    shown = status is ItemStatus.RECORDED and st.take is not None and st.unsaved is None and not st.recording
    hint = (T.stage.complete if s.is_complete else T.stage.saved_next) if shown else ""
    badge = presenter.take_badge(status, st.assessment, recording=st.recording, saving=st.busy, unsaved=st.unsaved)
    return StageView(
        position=T.window.position(st.name, s.index + 1 if has else 0, s.count),
        recorded=T.window.recorded(s.recorded_count, s.count), progress=(s.recorded_count, s.count),
        phrase=s.current_phrase, instruction=rset.instruction, filename=rset.filename(s.index) if has else "",
        badge=badge, countdown_total=rset.duration_s, hint=hint)


def result_view(st: ItemState) -> ResultView:
    a = st.assessment
    return ResultView(st.take, presenter.wave_state(a), presenter.metrics_text(a) if a else "", st.recording)


def controls_for(s: RecordingSession, st: ItemState) -> Controls:
    has, idle = s.count > 0, not st.recording and not st.busy
    recorded = has and item_status(s) is ItemStatus.RECORDED
    return Controls(
        recording=st.recording, busy=st.busy, can_record=st.recording or (has and idle and not recorded),
        can_listen=idle and st.take is not None, can_redo=idle and recorded, can_skip=has and idle,
        can_next=has and idle, can_prev=has and idle and s.index > 0, playing=st.playing, primary_next=recorded,
        has_items=has, set_locked=not s.recording_set.editable)
