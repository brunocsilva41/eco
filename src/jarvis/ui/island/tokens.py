"""Tokens da Ilha: cores (de ``jarvis.ui.theme``), medidas em grade de 4 px, tempos e o layout dos 3 tamanhos.

COR DE DESTAQUE UNICA: ``ACCENT_ATTR``/``ACCENT_OVERRIDE`` (troque em UM lugar). Estados ok/aviso/erro vem da
paleta escura do tema (contraste AA sobre o preto da Ilha, conferido em ``demo --capture``).

Layout (px logicos; origem = canto superior esquerdo do corpo da Ilha daquele tamanho):

  COMPACTA 208x36   icone de estado 20 @x12 | rotulo 12 semibold @x40 | [chip YOLO] [tempo em ACTING] | 6 barras
  MEDIA    380x64   emblema 40 @x12,y12 (icone 24) | titulo 14 @y13 + linha 12 @y34 | [YOLO] tempo | 14 barras
  GRANDE   600x248  cabecalho y16 (emblema 28, titulo 16, chips, alfinete) | espectro y56..84 (ou pergunta da
                    confirmacao + contagem + Sim/Nao) | fala/resposta 3 linhas y92..146 | acao y154..174 |
                    linha y188 | botoes y200..232 (Mudo, YOLO, Parar, Configuracoes; contexto a esquerda)
"""
from __future__ import annotations

from enum import Enum
from typing import Final

from ..theme import DARK, Palette

ACCENT_ATTR: Final = "accent_ink"          # campo de Palette usado como destaque (ambar do tema)
ACCENT_OVERRIDE: Final[str | None] = None  # ex.: "#22D3EE" para ciano; None = usar o tema

HOTKEY: Final = "F9"                       # so rotulo (o atalho real vem do nucleo na mensagem 'config')
HIDE_ON_FULLSCREEN: Final = True
FULLSCREEN_POLL_MS: Final = 700            # so enquanto a Ilha esta VISIVEL
FULLSCREEN_HIDE_HITS: Final = 2
FULLSCREEN_SHOW_MISSES: Final = 3

PALETTE: Final[Palette] = DARK
BG: Final = "#050608"                      # preto profundo
EDGE: Final = "#FFFFFF"                    # borda sutil = branco a 9% (alpha em EDGE_ALPHA)
EDGE_ALPHA: Final = 24
SHADOW_ALPHA: Final = 150


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
    IslandSize.COMPACT: (208, 36),
    IslandSize.MEDIUM: (380, 64),
    IslandSize.LARGE: (600, 248),
}
CW, CH = SIZES[IslandSize.COMPACT]
MW, MH = SIZES[IslandSize.MEDIUM]
LW, LH = SIZES[IslandSize.LARGE]
CORNER_MAX: Final = 28                     # raio maximo dos cantos
SHADOW_M: Final = 24                       # margem da janela para a sombra no modo flutuante
PAD: Final = 16

# compacta
C_PAD: Final = 12
C_ICON: Final = 20
C_BARS: Final = 6
# media
M_BADGE: Final = 40
M_ICON: Final = 24
M_TEXT_X: Final = 64
M_BARS: Final = 14
M_WAVE_H: Final = 36
# grande
L_HEAD_Y: Final = 16
L_BADGE: Final = 28
L_WAVE_Y, L_WAVE_H = 56, 28
L_TEXT_Y, L_TEXT_LINES, L_LINE_H = 92, 3, 18
L_ACTION_Y: Final = 154
L_RULE_Y: Final = 188
L_ROW_Y: Final = 200                       # linha dos botoes (32 px)
L_BTN_H: Final = 32
L_Q_Y: Final = 56                          # pergunta da confirmacao
L_COUNT_Y: Final = 112                     # barra de contagem
L_CONFIRM_Y: Final = 128                   # botoes Sim/Nao (36 px)
L_CONFIRM_H: Final = 36
L_BAR_W: Final = 6
L_BAR_GAP: Final = 4
L_BARS: Final = (LW - 2 * PAD + L_BAR_GAP) // (L_BAR_W + L_BAR_GAP)    # 52

BANDS: Final = 28

# tempos
RESIZE_MS: Final = 280
OVERSHOOT: Final = 0.7
ENTER_MS: Final = 280                      # deslizar do topo + fade
EXIT_MS: Final = 200
FADE_MS: Final = 150                       # troca de texto/estado (fade + deslocamento de 3 px)
HOVER_MS: Final = 110
DWELL_MS: Final = 160                      # permanencia do mouse na zona do topo
ZONE_H: Final = 3                          # altura da zona de revelacao (px fisicos logicos)
POLL_HZ: Final = 10
FLASH_S: Final = 2.5                       # YOLO / mudo / microfone
ERROR_S: Final = 5.0
BREATH_S: Final = 6.0                      # respiracao no repouso so nos primeiros segundos visiveis
HIDE_DELAY_S: Final = 3.0
FPS_FAST: Final = 60                       # voz, transicoes
FPS: Final = 30                            # pensando/executando/transcrevendo/confirmando
FPS_BREATH: Final = 15
FPS_REDUCED: Final = 12                    # reduzir movimento: so as barras de nivel
CONFIRM_TIMEOUT_S: Final = 15

ATTACK_S: Final = 0.015
DECAY_S: Final = 0.075
PEAK_FALL: Final = 0.9                     # picos caem ~0,9 da escala por segundo

VOICE_STATES: Final = (IslandState.LISTENING, IslandState.SPEAKING)
ACTIVE_STATES: Final = (IslandState.LISTENING, IslandState.TRANSCRIBING, IslandState.THINKING,
                        IslandState.ACTING, IslandState.SPEAKING)
ANIMATED_STATES: Final = ACTIVE_STATES + (IslandState.CONFIRMING,)


def state_color(state: IslandState) -> str:
    """Destaque para voz (ouvir/falar); texto para trabalho interno; aviso/erro com cor propria."""
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
