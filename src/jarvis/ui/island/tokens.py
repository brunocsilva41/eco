"""Tokens da Ilha. Cores vem SEMPRE de ``jarvis.ui.theme`` (paleta escura: a Ilha e preta em
qualquer tema do Windows); aqui ficam so a escolha da cor de destaque, as medidas e o layout dos
tres tamanhos (grade de 4 px).

COR DE DESTAQUE (ainda nao decidida pelo Bruno): troque em UM lugar, ``ACCENT_ATTR`` (outro campo
da paleta, ex. "ok") ou ``ACCENT_OVERRIDE`` (uma cor fixa, ex. ciano). Todo o resto segue.

Tabela de layout (px logicos; x/y a partir do canto superior esquerdo da Ilha):

  COMPACTA 208x36 (repouso)   mic 20 @x12 | rotulo do estado @x40 | [cronometro so em ACTING] | 6 barras | ponto de status
  MEDIA    380x64 (conversa)  mic 24 @x16 | rotulo (13 semibold) + cronometro | ultima frase (12) | 14 barras @x280
  GRANDE   520x200 (expandida) cabecalho y12 (mic 24, estado, chips modo) | espectro 49 barras y44..72 |
                               fala/resposta 3 linhas y78..129 (rolagem) | acao atual y134..150 |
                               contexto + botoes y156..188 (Sim/Nao, Mudo, Parar, Configuracoes)
"""
from __future__ import annotations

from enum import Enum
from typing import Final

from ..theme import DARK, SPACE, Palette, dp

ACCENT_ATTR: Final = "accent_ink"          # campo de Palette usado como destaque (ambar do tema)
ACCENT_OVERRIDE: Final[str | None] = None  # ex.: "#22D3EE" para ciano; None = usar o tema

HOTKEY: Final = "F9"                       # mesmo atalho de falar (decisao do Bruno); registro global = fase I3
HIDE_ON_FULLSCREEN: Final = True           # decisao do Bruno: esconder com jogo/video em tela cheia
FULLSCREEN_POLL_MS: Final = 700
FULLSCREEN_HIDE_HITS: Final = 2            # leituras seguidas em tela cheia para esconder (histerese)
FULLSCREEN_SHOW_MISSES: Final = 3          # leituras seguidas sem tela cheia para voltar

PALETTE: Final[Palette] = DARK


def accent() -> str:
    return ACCENT_OVERRIDE or getattr(PALETTE, ACCENT_ATTR)


class IslandSize(Enum):
    COMPACT = "compacta"
    MEDIUM = "media"
    LARGE = "grande"


class IslandState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    ACTING = "acting"
    SPEAKING = "speaking"
    CONFIRMING = "confirmando"
    ERROR = "error"


SIZES: Final[dict[IslandSize, tuple[int, int]]] = {
    IslandSize.COMPACT: (dp(208), dp(36)),
    IslandSize.MEDIUM: (dp(380), dp(64)),
    IslandSize.LARGE: (dp(520), dp(200)),
}
CW, CH = SIZES[IslandSize.COMPACT]
MW, MH = SIZES[IslandSize.MEDIUM]
LW, LH = SIZES[IslandSize.LARGE]
CORNER_MAX: Final = dp(28)                 # so os cantos de BAIXO sao redondos (colada na borda superior)
TOP_MARGIN: Final = 0                      # colada ao topo do monitor principal
PAD: Final = SPACE.lg                      # 16 (compacta usa SPACE.md = 12)

# compacta
C_PAD: Final = SPACE.md
C_MIC: Final = 20
C_BARS: Final = 6
C_DOT: Final = 6
# media
M_MIC: Final = 24
M_TEXT_X: Final = 52
M_BARS: Final = 14
M_WAVE_W: Final = 84
M_WAVE_H: Final = 36
# grande
L_HEADER_Y: Final = 12
L_WAVE_Y, L_WAVE_H = 44, 28
L_TEXT_Y, L_TEXT_LINES, L_LINE_H = 78, 3, 17
L_ACTION_Y: Final = 134
L_ROW_Y: Final = 156                       # linha dos botoes (32 px de alto)
L_BAR_W: Final = 6
L_BAR_GAP: Final = 4
L_BARS: Final = (LW - 2 * PAD + L_BAR_GAP) // (L_BAR_W + L_BAR_GAP)    # 49

BANDS: Final = 28                          # bandas do analisador

RESIZE_MS: Final = 260                     # crescer/encolher (200 a 350 ms); 0 com "reduzir animacoes"
OVERSHOOT: Final = 0.8                     # mola leve ao crescer
FPS_VOICE: Final = 60                      # ondas ao vivo
FPS: Final = 30                            # demais estados animados
FPS_REDUCED: Final = 12                    # reduzir movimento: so as barras de nivel
CONFIRM_TIMEOUT_S: Final = 15              # sem resposta = NAO

ATTACK_S: Final = 0.015                    # ondas: subida quase imediata
DECAY_S: Final = 0.075                     # queda lenta (60 a 90 ms)

VOICE_STATES: Final = (IslandState.LISTENING, IslandState.SPEAKING)
ANIMATED_STATES: Final = (IslandState.LISTENING, IslandState.TRANSCRIBING, IslandState.THINKING,
                          IslandState.ACTING, IslandState.SPEAKING, IslandState.CONFIRMING)


def state_color(state: IslandState) -> str:
    """Destaque para voz (ouvir/falar); neutro para trabalho interno; atencao/erro com cor propria."""
    if state in VOICE_STATES:
        return accent()
    if state is IslandState.CONFIRMING:
        return PALETTE.warn
    if state is IslandState.ERROR:
        return PALETTE.error
    if state is IslandState.IDLE:
        return PALETTE.text_muted
    return PALETTE.text


def state_label(state: IslandState) -> str:
    from .strings import S
    return {IslandState.IDLE: S.state_idle, IslandState.LISTENING: S.state_listening,
            IslandState.TRANSCRIBING: S.state_transcribing, IslandState.THINKING: S.state_thinking,
            IslandState.ACTING: S.state_acting, IslandState.SPEAKING: S.state_speaking,
            IslandState.CONFIRMING: S.state_confirming, IslandState.ERROR: S.state_error}[state]
