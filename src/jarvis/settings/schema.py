"""Modelo de formulário das Configurações: descreve CADA opção da config para a interface (rótulo, tipo, limites, ajuda).

A fonte da verdade continua sendo `jarvis.config` (tipos e validação); aqui só há metadados de apresentação
e a classificação "aplica na hora" x "precisa reiniciar". Campos TRAVADOS não podem ser desativados:
- llm.host (sempre loopback) e safety.emergency_hotkey (obrigatória).
Nunca existe campo de senha, token ou PIN.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config

# tipos de campo que a interface sabe desenhar
BOOL, INT, FLOAT, TEXT, PATH, CHOICE, LIST, DICT, HOTKEY, DEVICE_IN, DEVICE_OUT, TOOLS = (
    "bool", "int", "float", "text", "path", "choice", "list", "dict", "hotkey", "device_in", "device_out", "tools")

LIVE, RESTART = "live", "restart"


@dataclass(frozen=True)
class FieldSpec:
    key: str                              # "secao.campo"
    group: str                            # aba/categoria da tela
    label: str
    kind: str
    help: str = ""
    apply: str = RESTART                  # LIVE = vale na hora; RESTART = vale após reiniciar o Jarvis
    choices: tuple[tuple[str, str], ...] = ()      # (valor, rótulo) para CHOICE
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str = ""
    locked: str = ""                      # se não vazio: não pode ser desativado/relaxado (motivo)
    optional: bool = False                # aceita vazio (ex.: dispositivo padrão, visão desligada)
    section: str = field(init=False, default="")
    name: str = field(init=False, default="")

    def __post_init__(self) -> None:
        sec, _, name = self.key.partition(".")
        object.__setattr__(self, "section", sec)
        object.__setattr__(self, "name", name)


G_RUN, G_VOICE, G_STT, G_LLM, G_TOOLS, G_MEM, G_FILES, G_LOGS, G_SEC = (
    "Funcionamento", "Voz (fala)", "Reconhecimento (escuta)", "Modelo de linguagem", "Ferramentas",
    "Memória e contexto", "Arquivos", "Logs", "Segurança")
GROUPS = (G_RUN, G_VOICE, G_STT, G_LLM, G_TOOLS, G_MEM, G_FILES, G_SEC, G_LOGS)

_S = FieldSpec
FIELDS: tuple[FieldSpec, ...] = (
    # ---- funcionamento
    _S("safety.talk_key", G_RUN, "Tecla de falar", HOTKEY, "Tecla simples, sem Ctrl/Alt (ex.: F9).", RESTART),
    _S("safety.talk_mode", G_RUN, "Modo de ativação", CHOICE, "Segurar a tecla enquanto fala, ou apertar uma vez e parar sozinho no silêncio.", LIVE,
       choices=(("hold", "Segurar para falar"), ("toggle", "Apertar e falar"))),
    _S("safety.mute_hotkey", G_RUN, "Atalho do mudo", HOTKEY, "Liga/desliga o microfone.", RESTART),
    _S("safety.confirm_yes_hotkey", G_RUN, "Atalho: confirmar SIM", HOTKEY, "Responde SIM a uma confirmação pendente.", RESTART),
    _S("safety.confirm_no_hotkey", G_RUN, "Atalho: confirmar NÃO", HOTKEY, "Responde NÃO a uma confirmação pendente.", RESTART),
    _S("safety.confirm_timeout_s", G_RUN, "Tempo para confirmar", FLOAT, "Sem resposta nesse tempo, a ação é NEGADA.", LIVE, minimum=3, maximum=120, step=1, unit="s"),
    _S("safety.max_agent_steps", G_RUN, "Passos máximos por pedido", INT, "Limite de ferramentas encadeadas antes de desistir.", LIVE, minimum=1, maximum=20),
    _S("safety.tool_timeout_s", G_RUN, "Tempo máximo por ferramenta", FLOAT, "", LIVE, minimum=1, maximum=120, step=1, unit="s"),
    # ---- voz
    _S("tts.voice_onnx", G_VOICE, "Voz (arquivo .onnx)", PATH, "Modelo de voz Piper."),
    _S("tts.voice_json", G_VOICE, "Voz (arquivo .json)", PATH, "Configuração da voz Piper."),
    _S("tts.length_scale", G_VOICE, "Velocidade da fala", FLOAT, "Menor = mais rápido; maior = mais lento. Vazio = padrão da voz.", RESTART,
       minimum=0.3, maximum=3.0, step=0.05, optional=True),
    _S("tts.volume", G_VOICE, "Volume", FLOAT, "", RESTART, minimum=0.05, maximum=2.0, step=0.05),
    _S("audio.output_device", G_VOICE, "Dispositivo de saída", DEVICE_OUT, "Vazio = padrão do Windows.", RESTART, optional=True),
    # ---- reconhecimento
    _S("audio.input_device", G_STT, "Microfone", DEVICE_IN, "Vazio = padrão do Windows.", RESTART, optional=True),
    _S("stt.model_dir", G_STT, "Modelo de escuta (pasta)", PATH, "Escolha a pasta do modelo: hf_tiny (~0,5 s), hf_base (~1,3 s), hf_small (~3 s, mais preciso) ou hf_medium, em models/whisper (medido em CPU).", RESTART),
    _S("stt.language", G_STT, "Idioma", TEXT, "Código de 2 letras (pt, en, es...).", RESTART),
    _S("stt.compute_type", G_STT, "Precisão de cálculo", CHOICE, "int8 é o mais leve em CPU.", RESTART,
       choices=(("int8", "int8"), ("int8_float32", "int8_float32"), ("float32", "float32"))),
    _S("stt.cpu_threads", G_STT, "Threads de CPU", INT, "", RESTART, minimum=1, maximum=64),
    _S("stt.beam_size", G_STT, "Beam (precisão x velocidade)", INT, "1 = mais rápido; 5 = mais preciso.", RESTART, minimum=1, maximum=10),
    _S("audio.vad_threshold", G_STT, "Sensibilidade da voz (VAD)", FLOAT, "Maior = exige voz mais clara; menor = mais sensível a ruído.", RESTART, minimum=0.05, maximum=0.95, step=0.05),
    _S("audio.end_silence_ms", G_STT, "Silêncio que encerra a frase", INT, "", RESTART, minimum=200, maximum=5000, step=50, unit="ms"),
    _S("audio.min_speech_ms", G_STT, "Fala mínima", INT, "", RESTART, minimum=80, maximum=2000, step=10, unit="ms"),
    _S("audio.max_utterance_s", G_STT, "Duração máxima da fala", FLOAT, "", RESTART, minimum=1, maximum=60, step=1, unit="s"),
    _S("audio.pre_roll_ms", G_STT, "Pré-gravação", INT, "Áudio guardado antes da fala começar.", RESTART, minimum=0, maximum=2000, step=50, unit="ms"),
    # ---- modelo de linguagem
    _S("llm.model", G_LLM, "Modelo (arquivo .gguf)", PATH, "Caminho do modelo de linguagem."),
    _S("llm.mmproj", G_LLM, "Projetor de visão (mmproj)", PATH, "Vazio = sem visão da tela.", RESTART, optional=True),
    _S("llm.ctx", G_LLM, "Contexto", INT, "Tokens de memória de trabalho do modelo (mais = mais VRAM).", RESTART, minimum=512, maximum=32768, step=256, unit="tokens"),
    _S("llm.ngl", G_LLM, "Camadas na GPU", INT, "99 = tudo na GPU; 0 = só CPU.", RESTART, minimum=0, maximum=999),
    _S("llm.temperature", G_LLM, "Temperatura", FLOAT, "Menor = respostas mais previsíveis.", LIVE, minimum=0, maximum=2, step=0.05),
    _S("llm.max_tokens", G_LLM, "Resposta máxima", INT, "", LIVE, minimum=16, maximum=4096, unit="tokens"),
    _S("llm.request_timeout_s", G_LLM, "Tempo limite da resposta", FLOAT, "", LIVE, minimum=5, maximum=900, unit="s"),
    _S("llm.startup_timeout_s", G_LLM, "Tempo limite de inicialização", FLOAT, "", RESTART, minimum=10, maximum=900, unit="s"),
    _S("llm.port", G_LLM, "Porta local", INT, "O servidor só escuta em 127.0.0.1.", RESTART, minimum=1024, maximum=65535),
    _S("llm.host", G_LLM, "Endereço", TEXT, "Fixo em loopback: o modelo nunca fica exposto na rede.", RESTART, locked="o servidor do modelo só pode escutar em loopback"),
    _S("llm.reasoning_off", G_LLM, "Desligar 'pensar' (Qwen3.5/Gemma 4)", BOOL, "Ligue para modelos que gastam tokens pensando.", RESTART),
    _S("vision.max_side_px", G_LLM, "Visão: lado maior da imagem", INT, "", RESTART, minimum=256, maximum=4096, unit="px"),
    _S("vision.jpeg_quality", G_LLM, "Visão: qualidade JPEG", INT, "", RESTART, minimum=30, maximum=95),
    # ---- ferramentas
    _S("tools.disabled", G_TOOLS, "Ferramentas desligadas", TOOLS, "Desligadas não aparecem para o modelo.", LIVE),
    _S("tools.confirm", G_TOOLS, "Ferramentas que sempre pedem confirmação", TOOLS, "Além das arriscadas, que SEMPRE pedem.", LIVE),
    _S("apps.launch", G_TOOLS, "Aplicativos que posso abrir", DICT, "Nome falado -> programa. Só estes abrem.", RESTART),
    _S("apps.hotkeys", G_TOOLS, "Atalhos de teclado permitidos", LIST, "As teclas de segurança do Jarvis não podem entrar aqui.", RESTART),
    _S("apps.hotkeys_confirm", G_TOOLS, "Atalhos que pedem confirmação", LIST, "Precisam estar na lista acima.", RESTART),
    _S("safety.max_typed_chars", G_TOOLS, "Digitação: máximo de caracteres", INT, "", RESTART, minimum=1, maximum=2000),
    _S("safety.typing_allowed_processes", G_TOOLS, "Digitação: programas permitidos", LIST, "Só nestes programas o Jarvis digita.", RESTART),
    _S("safety.typing_denied_extra", G_TOOLS, "Digitação: bloquear também", LIST, "Acrescenta à lista fixa de bloqueio (terminais, Explorer...).", RESTART),
    _S("safety.typing_confirm", G_TOOLS, "Digitação: quando confirmar", CHOICE, "", RESTART,
       choices=(("always", "Sempre"), ("untrusted_or_multiline", "Só com conteúdo de fora ou parecido com comando"))),
    # ---- memória e contexto
    _S("memory.enabled", G_MEM, "Guardar histórico e memória", BOOL, "Desligado = modo sem histórico: nada é gravado em disco.", RESTART),
    _S("memory.idle_minutes", G_MEM, "Nova conversa após inatividade", INT, "0 = nunca.", LIVE, minimum=0, maximum=1440, unit="min"),
    _S("memory.recall_top_k", G_MEM, "Memórias lembradas por pedido", INT, "", LIVE, minimum=0, maximum=20),
    _S("memory.model_can_remember", G_MEM, "O Jarvis pode propor memórias", BOOL, "", LIVE),
    _S("memory.conversation_ttl_days", G_MEM, "Conversas: guardar por", INT, "Passado o prazo, vão para a lixeira.", RESTART, minimum=1, maximum=3650, unit="dias"),
    _S("memory.trash_days", G_MEM, "Lixeira: guardar por", INT, "", RESTART, minimum=1, maximum=365, unit="dias"),
    _S("context.compact_at_pct", G_MEM, "Compactar a conversa em", INT, "Percentual do contexto que dispara o resumo automático.", LIVE, minimum=30, maximum=95, unit="%"),
    _S("context.keep_recent_messages", G_MEM, "Mensagens recentes mantidas", INT, "", LIVE, minimum=2, maximum=40),
    _S("context.tool_result_max_chars", G_MEM, "Resultado de ferramenta: máximo", INT, "", LIVE, minimum=200, maximum=8000, unit="caracteres"),
    _S("context.summary_max_tokens", G_MEM, "Tamanho do resumo", INT, "", LIVE, minimum=100, maximum=1500, unit="tokens"),
    # ---- arquivos
    _S("files.roots", G_FILES, "Pastas permitidas", LIST, "O Jarvis só mexe em arquivos dentro destas pastas (nunca Windows, Program Files nem a pasta do Jarvis).", LIVE),
    _S("files.max_read_kb", G_FILES, "Leitura: tamanho máximo", INT, "", LIVE, minimum=1, maximum=4096, unit="KB"),
    _S("files.max_write_kb", G_FILES, "Escrita: tamanho máximo", INT, "", RESTART, minimum=1, maximum=8192, unit="KB"),
    _S("files.undo_keep", G_FILES, "Desfazer: operações guardadas", INT, "", LIVE, minimum=1, maximum=200),
    _S("files.undo_max_mb", G_FILES, "Desfazer: espaço máximo", INT, "", LIVE, minimum=10, maximum=5000, unit="MB"),
    # ---- segurança
    _S("safety.emergency_hotkey", G_SEC, "Tecla de emergência", HOTKEY, "Para tudo na hora. OBRIGATÓRIA: não pode ser desativada.", RESTART,
       locked="a tecla de emergência é obrigatória"),
    # ---- logs
    _S("logs.level", G_LOGS, "Nível de log", CHOICE, "", LIVE, choices=(("DEBUG", "Detalhado"), ("INFO", "Normal"), ("WARNING", "Só avisos"), ("ERROR", "Só erros"))),
    _S("logs.max_mb", G_LOGS, "Tamanho por arquivo", INT, "", RESTART, minimum=1, maximum=100, unit="MB"),
    _S("logs.keep_files", G_LOGS, "Arquivos guardados", INT, "", RESTART, minimum=1, maximum=50),
)

BY_KEY: dict[str, FieldSpec] = {f.key: f for f in FIELDS}
LIVE_KEYS: frozenset[str] = frozenset(f.key for f in FIELDS if f.apply == LIVE)


def fields_by_group() -> dict[str, list[FieldSpec]]:
    out: dict[str, list[FieldSpec]] = {g: [] for g in GROUPS}
    for f in FIELDS:
        out[f.group].append(f)
    return out


def get_value(cfg: Config, key: str) -> Any:
    sec, _, name = key.partition(".")
    return getattr(getattr(cfg, sec), name)


def to_plain(value: Any) -> Any:
    """Valor da config -> valor simples para a interface/TOML (Path -> texto, tuple -> list)."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def current_values(cfg: Config) -> dict[str, Any]:
    """{'secao.campo': valor} de todos os campos editáveis (o que a tela mostra)."""
    return {f.key: to_plain(get_value(cfg, f.key)) for f in FIELDS}


def uncovered_fields() -> list[str]:
    """Campos da config SEM metadado de tela (para garantir que 'tudo' é configurável). Vazio = cobertura total."""
    covered = set(BY_KEY)
    missing: list[str] = []
    for sec in dataclasses.fields(Config):
        default = getattr(Config(), sec.name)
        if dataclasses.is_dataclass(default):
            for f in dataclasses.fields(default):
                k = f"{sec.name}.{f.name}"
                if k not in covered and k not in {"paths.root", "paths.models", "paths.logs", "paths.data", "paths.llama_bin",
                                                  "audio.sample_rate"}:
                    missing.append(k)
    return missing
