"""Textos da Ilha (pt-BR) em um lugar so, prontos para i18n. Frases curtas, sem travessao."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IslandStrings:
    window_name: str = "Ilha do Jarvis"
    state_idle: str = "Em repouso"
    state_listening: str = "Ouvindo"
    state_transcribing: str = "Transcrevendo"
    state_thinking: str = "Pensando"
    state_acting: str = "Agindo"
    state_speaking: str = "Falando"
    state_confirming: str = "Confirmar"
    state_error: str = "Erro"
    muted: str = "Mudo"
    unmute: str = "Ligar microfone"
    mute_btn: str = "Silenciar microfone"
    settings: str = "Configurações"
    you: str = "Você"
    jarvis: str = "Jarvis"
    context: str = "Contexto {pct}%"
    acting_prefix: str = "Executando: {what}"
    yolo: str = "YOLO {t}"
    action_running: str = "em andamento"
    action_ok: str = "ok"
    action_error: str = "erro"
    action_denied: str = "negado"
    no_action: str = "Nenhuma ação ainda"
    perm_balanced: str = "Equilíbrio"
    perm_strict: str = "Estrito"
    yes: str = "Sim"
    no: str = "Não"
    stop: str = "Parar"
    waiting_speech: str = "Aguardando sua fala"
    level: str = "Nível"
    confirm_timeout: str = "Sem resposta em {s} s, vale Não"
    confirm_help: str = "Responda Sim ou Não"


S = IslandStrings()
