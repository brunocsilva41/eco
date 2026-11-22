"""Tokens da Ilha. Cores vem SEMPRE de ``jarvis.ui.theme`` (paleta escura: a Ilha e preta em
qualquer tema do Windows); aqui ficam so a escolha da cor de destaque e as medidas proprias.

COR DE DESTAQUE (ainda nao decidida pelo Bruno): troque em UM lugar, ``ACCENT_ATTR`` (outro campo
da paleta, ex. "ok") ou ``ACCENT_OVERRIDE`` (uma cor fixa, ex. ciano). Todo o resto segue.
"""
from __future__ import annotations

from enum import Enum
from typing import Final

from ..theme import DARK, SPACE, Palette, dp

ACCENT_ATTR: Final = "accent_ink"          # campo de Palette usado como destaque (ambar do tema)
ACCENT_OVERRIDE: Final[str | None] = None  # ex.: "#22D3EE" para ciano; None = usar o tema

HOTKEY: Final = "F9"                       # mesmo atalho de falar (decisao do Bruno); registro global = fase I3
HIDE_ON_FULLSCREEN: Final = True           # decisao do Bruno: esconder com jogo/video em tela cheia
FULLSCREEN_POLL_MS: Final = 1500

PALETTE: Final[Palette] = DARK


def accent() -> str:
    return ACCENT_OVERRIDE or getattr(PALETTE, ACCENT_ATTR)


class IslandSize(Enum):
    REST = "repouso"
    ACTIVE = "ativo"
    EXPANDED = "expandido"


class IslandState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    ACTING = "acting"
    SPEAKING = "speaking"
    CONFIRMING = "confirmando"


# tamanhos logicos (px); multiplos de 4 (grade do tema)
SIZES: Final[dict[IslandSize, tuple[int, int]]] = {
    IslandSize.REST: (dp(64), dp(8)),
    IslandSize.ACTIVE: (dp(304), dp(48)),
    IslandSize.EXPANDED: (dp(448), dp(200)),
}
CORNER_MAX: Final = dp(28)                 # cantos bem redondos (pedido do Bruno); pilula ate 56 px de altura
TOP_MARGIN: Final = SPACE.sm
PAD: Final = SPACE.md
RING_R: Final = 15                         # raio do anel de pontos
RING_DOTS: Final = 36
BANDS: Final = 28                          # barras do espectro

RESIZE_MS: Final = 220                     # crescer/encolher (~250 ms do spec); 0 com "reduzir animacoes"
FPS: Final = 30
FPS_REDUCED: Final = 12                    # so a barra de nivel, sem animacao decorativa
CONFIRM_TIMEOUT_S: Final = 15              # sem resposta = NAO

VOICE_STATES: Final = (IslandState.LISTENING, IslandState.SPEAKING)
ANIMATED_STATES: Final = (IslandState.LISTENING, IslandState.TRANSCRIBING, IslandState.THINKING,
                          IslandState.ACTING, IslandState.SPEAKING, IslandState.CONFIRMING)

# icone do kit por estado (o nome do estado tambem sempre aparece em texto)
STATE_ICON: Final[dict[IslandState, str]] = {
    IslandState.IDLE: "brain", IslandState.LISTENING: "mic", IslandState.TRANSCRIBING: "edit",
    IslandState.THINKING: "brain", IslandState.ACTING: "keyboard", IslandState.SPEAKING: "listen",
    IslandState.CONFIRMING: "alert",
}


def state_color(state: IslandState) -> str:
    """Destaque para voz (ouvir/falar); neutro para trabalho interno; atencao para confirmar."""
    if state in VOICE_STATES:
        return accent()
    if state is IslandState.CONFIRMING:
        return PALETTE.warn
    if state is IslandState.IDLE:
        return PALETTE.text_muted
    return PALETTE.text


def state_label(state: IslandState) -> str:
    from .strings import S
    return {IslandState.IDLE: S.state_idle, IslandState.LISTENING: S.state_listening,
            IslandState.TRANSCRIBING: S.state_transcribing, IslandState.THINKING: S.state_thinking,
            IslandState.ACTING: S.state_acting, IslandState.SPEAKING: S.state_speaking,
            IslandState.CONFIRMING: S.state_confirming}[state]
