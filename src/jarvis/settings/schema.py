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
    apply: str = RESTART                  # LIVE = vale na hora; RESTART = vale após reiniciar o Eco
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


G_CLOUD = "Cérebro em nuvem"
G_RUN, G_VOICE, G_STT, G_LLM, G_TOOLS, G_MEM, G_FILES, G_LOGS, G_SEC, G_UPD = (
    "Funcionamento", "Voz (fala)", "Reconhecimento (escuta)", "Modelo de linguagem", "Ferramentas",
    "Memória e contexto", "Arquivos", "Logs", "Segurança", "Atualizações")
G_TERM = "Terminal"
G_PATHS = "Caminhos dos programas"
GROUPS = (G_RUN, G_VOICE, G_STT, G_LLM, G_CLOUD, G_TOOLS, G_TERM, G_PATHS, G_MEM, G_FILES, G_SEC, G_LOGS, G_UPD)

_S = FieldSpec
FIELDS: tuple[FieldSpec, ...] = (
    # ---- funcionamento
    _S("safety.talk_key", G_RUN, "Tecla de falar", HOTKEY, "Tecla simples, sem Ctrl/Alt (ex.: F9).", RESTART),
    _S("safety.listen_mode", G_RUN, "Como o Eco escuta", CHOICE,
       "Pela tecla: só ouve enquanto você aperta. Escuta aberta: ouve sozinho, sem apertar nada (mais prático, mas reage a qualquer fala perto do microfone). Também dá para alternar pela Ilha, pela bandeja ou pelo atalho.", LIVE,
       choices=(("push", "Pela tecla de falar"), ("open", "Escuta aberta"))),
    _S("safety.open_listen_hotkey", G_RUN, "Atalho da escuta aberta", HOTKEY, "Liga/desliga a escuta aberta.", RESTART, optional=True),
    _S("safety.talk_mode", G_RUN, "Modo de ativação", CHOICE, "Segurar a tecla enquanto fala, ou apertar uma vez e parar sozinho no silêncio.", LIVE,
       choices=(("hold", "Segurar para falar"), ("toggle", "Apertar e falar"))),
    _S("safety.mute_hotkey", G_RUN, "Atalho do mudo", HOTKEY, "Liga/desliga o microfone.", RESTART),
    _S("safety.confirm_yes_hotkey", G_RUN, "Atalho: confirmar SIM", HOTKEY, "Responde SIM a uma confirmação pendente.", RESTART),
    _S("safety.confirm_no_hotkey", G_RUN, "Atalho: confirmar NÃO", HOTKEY, "Responde NÃO a uma confirmação pendente.", RESTART),
    _S("safety.confirm_timeout_s", G_RUN, "Tempo para confirmar", FLOAT, "Sem resposta nesse tempo, a ação é NEGADA.", LIVE, minimum=3, maximum=120, step=1, unit="s"),
    _S("ui.tray_enabled", G_RUN, "Ícone na bandeja do sistema", BOOL, "Ícone perto do relógio com menu de botão direito (configurações, Ilha, escuta, mudo, atualizações, encerrar).", RESTART),
    _S("ui.island_enabled", G_RUN, "Mostrar a Ilha", BOOL, "Janela no topo da tela com o estado do Eco (some com app em tela cheia).", RESTART),
    _S("ui.island_mode", G_RUN, "Posição da Ilha", CHOICE, "Topo da tela (colada ou flutuante) ou trilho vertical na borda direita ou esquerda.", LIVE,
       choices=(("docked", "Colada ao topo"), ("floating", "Flutuante no topo"), ("dock_right", "Trilho na borda direita"),
                ("dock_left", "Trilho na borda esquerda"))),
    _S("ui.island_pinned", G_RUN, "Fixar a Ilha na tela", BOOL, "Fixada, a Ilha nunca se esconde sozinha (só some com app em tela cheia). Também liga pelo alfinete.", LIVE),
    _S("ui.island_opacity", G_RUN, "Transparência do fundo", FLOAT, "1 = fundo sólido; menor = vidro. O texto continua legível (a Ilha limita o mínimo).", LIVE,
       minimum=0.35, maximum=1.0, step=0.05),
    _S("ui.island_side_y_pct", G_RUN, "Altura do trilho lateral", INT, "Só nos modos de trilho lateral: 0 = topo da tela, 50 = meio, 100 = base.", LIVE,
       minimum=0, maximum=100, step=5, unit="%"),
    _S("ui.island_float_gap_px", G_RUN, "Afastamento do topo", INT, "Só no modo flutuante.", LIVE, minimum=0, maximum=64, step=2, unit="px"),
    _S("ui.island_autohide", G_RUN, "Esconder a Ilha sozinha", BOOL, "Fica invisível e só aparece quando importa (mouse no topo, F9, confirmação, erro).", LIVE),
    _S("ui.island_hide_delay_s", G_RUN, "Esconder depois de", FLOAT, "Tempo em repouso antes de sumir.", LIVE, minimum=0.5, maximum=60, step=0.5, unit="s"),
    _S("ui.island_hover_reveal", G_RUN, "Mostrar com o mouse no topo", BOOL, "Encostar o mouse no centro da borda superior revela a Ilha.", LIVE),
    _S("safety.max_agent_steps", G_RUN, "Passos máximos por pedido", INT, "Limite de ferramentas encadeadas antes de desistir.", LIVE, minimum=1, maximum=20),
    _S("safety.tool_timeout_s", G_RUN, "Tempo máximo por ferramenta", FLOAT, "", LIVE, minimum=1, maximum=120, step=1, unit="s"),
    # ---- voz
    _S("tts.voice_onnx", G_VOICE, "Voz (arquivo .onnx)", PATH, "Modelo de voz Piper."),
    _S("tts.voice_json", G_VOICE, "Voz (arquivo .json)", PATH, "Configuração da voz Piper."),
    _S("tts.device", G_VOICE, "Onde roda a voz", CHOICE,
       "Medido: o processador é mais rápido que a placa de vídeo para esta voz; 'placa de vídeo' cai para o processador com aviso.", RESTART,
       choices=(("cpu", "Processador (medido mais rápido)"), ("auto", "Automático"), ("gpu", "Placa de vídeo"))),
    _S("tts.length_scale", G_VOICE, "Velocidade da fala", FLOAT, "Menor = mais rápido; maior = mais lento. Vazio = padrão da voz.", RESTART,
       minimum=0.3, maximum=3.0, step=0.05, optional=True),
    _S("tts.volume", G_VOICE, "Volume", FLOAT, "", RESTART, minimum=0.05, maximum=2.0, step=0.05),
    _S("audio.output_device", G_VOICE, "Dispositivo de saída", DEVICE_OUT, "Vazio = padrão do Windows.", RESTART, optional=True),
    # ---- reconhecimento
    _S("audio.input_device", G_STT, "Microfone", DEVICE_IN, "Vazio = padrão do Windows.", RESTART, optional=True),
    _S("stt.device", G_STT, "Onde roda a escuta", CHOICE,
       "Automático usa a placa de vídeo (whisper.cpp Vulkan, modelo small) e cai para o processador (faster-whisper) se não der.", RESTART,
       choices=(("auto", "Automático (placa de vídeo)"), ("gpu", "Placa de vídeo"), ("cpu", "Processador"))),
    _S("stt.gpu_model", G_STT, "Modelo da escuta na placa de vídeo (ggml)", PATH, "Arquivo ggml-*.bin do whisper.cpp.", RESTART),
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
    _S("llm.device", G_LLM, "Onde roda o modelo de linguagem", CHOICE,
       "Automático usa a placa de vídeo e, se ela falhar, cai para o processador com aviso. Só processador é ~3x mais lento e gasta muito mais CPU.", RESTART,
       choices=(("auto", "Automático (placa de vídeo)"), ("gpu", "Placa de vídeo"), ("cpu", "Processador"))),
    _S("llm.mmproj_device", G_LLM, "Onde roda a visão (ver a tela)", CHOICE,
       "Na placa de vídeo cada imagem leva ~8 s; no processador ~40 s e muito CPU, mas poupa ~0,8 GB de VRAM.", RESTART,
       choices=(("auto", "Automático (placa de vídeo)"), ("gpu", "Placa de vídeo"), ("cpu", "Processador"))),
    _S("llm.sleep_idle_s", G_LLM, "Descarregar o modelo quando ocioso", INT,
       "Depois deste tempo sem uso o modelo sai da placa de vídeo e da memória (libera ~5 GB de VRAM para renderizar). Volta em ~6 s no próximo pedido. 0 = nunca.",
       RESTART, minimum=0, maximum=86400, step=30, unit="s"),
    _S("llm.mmap", G_LLM, "Carregar com mmap", BOOL,
       "Desligado (recomendado): usa ~2,3 GB a menos de memória RAM com o modelo todo na placa de vídeo.", RESTART),
    _S("llm.temperature", G_LLM, "Temperatura", FLOAT, "Menor = respostas mais previsíveis.", LIVE, minimum=0, maximum=2, step=0.05),
    _S("llm.max_tokens", G_LLM, "Resposta máxima", INT, "", LIVE, minimum=16, maximum=4096, unit="tokens"),
    _S("llm.request_timeout_s", G_LLM, "Tempo limite da resposta", FLOAT, "", LIVE, minimum=5, maximum=900, unit="s"),
    _S("llm.startup_timeout_s", G_LLM, "Tempo limite de inicialização", FLOAT, "", RESTART, minimum=10, maximum=900, unit="s"),
    _S("llm.port", G_LLM, "Porta local", INT, "O servidor só escuta em 127.0.0.1.", RESTART, minimum=1024, maximum=65535),
    _S("llm.host", G_LLM, "Endereço", TEXT, "Fixo em loopback: o modelo nunca fica exposto na rede.", RESTART, locked="o servidor do modelo só pode escutar em loopback"),
    _S("llm.reasoning_off", G_LLM, "Desligar 'pensar' (Qwen3.5/Gemma 4)", BOOL, "Ligue para modelos que gastam tokens pensando.", RESTART),
    _S("vision.max_side_px", G_LLM, "Visão: lado maior da imagem", INT, "", RESTART, minimum=256, maximum=4096, unit="px"),
    _S("vision.jpeg_quality", G_LLM, "Visão: qualidade JPEG", INT, "", RESTART, minimum=30, maximum=95),
    # ---- cérebro em nuvem (ACP): opt-in; o modelo local continua sendo o padrão e o plano B
    _S("brain.kind", G_CLOUD, "Cérebro", CHOICE,
       "Local: o modelo no seu PC (padrão, nada sai daqui). Nuvem: um agente (OpenCode, Claude Code...) responde pelo protocolo ACP, usando o login dele; o que você pede é enviado como TEXTO e a Ilha avisa a cada uso.", LIVE,
       choices=(("local", "Local (modelo no PC)"), ("cloud", "Nuvem via ACP (opcional)"))),
    _S("brain.agent", G_CLOUD, "Agente na nuvem", CHOICE, "Precisa estar instalado e com login feito no próprio agente. O Eco nunca vê sua senha ou token.", LIVE,
       choices=(("opencode", "OpenCode"), ("antigravity", "Google Antigravity"), ("claude", "Claude Code"),
                ("codex", "OpenAI Codex CLI"), ("copilot", "GitHub Copilot CLI"))),
    _S("brain.fallback_local", G_CLOUD, "Se a nuvem falhar, usar o modelo local", BOOL, "Sem internet, sem login ou erro: o Eco responde com o cérebro local e avisa.", LIVE),
    _S("brain.use_tools", G_CLOUD, "O agente pode usar as ferramentas do Eco", BOOL,
       "As ferramentas passam pelas MESMAS travas e confirmações locais; ações no PC sempre pedem sua confirmação com o nome do agente.", LIVE),
    _S("brain.builtin_tools", G_CLOUD, "Ferramentas próprias do agente (shell, editar arquivos)", CHOICE,
       "Negar (recomendado): o agente só usa as ferramentas do Eco. Perguntar: cada pedido dele aparece na Ilha para você aprovar.", LIVE,
       choices=(("deny", "Negar"), ("ask", "Perguntar a cada uso"))),
    _S("brain.consent_screen", G_CLOUD, "Agentes que podem ver a tela e as janelas", LIST, "Lista de agentes (opencode, claude...). Vazio = nenhum: capturas de tela e títulos de janelas nunca vão para a nuvem.", LIVE),
    _S("brain.consent_memory", G_CLOUD, "Agentes que podem usar a memória e as conversas", LIST, "Vazio = nenhum.", LIVE),
    _S("brain.consent_files", G_CLOUD, "Agentes que podem usar as ferramentas de arquivos", LIST, "Vazio = nenhum. Mesmo autorizado, só as pastas permitidas em Arquivos valem.", LIVE),
    _S("brain.action_modes", G_CLOUD, "Ações no PC pedidas pelo agente (por agente)", DICT,
       "Agente -> modo. deny: ele não recebe nenhuma ferramenta que aja no PC (só consultas). confirm (padrão): cada ação pede a sua confirmação, com o nome do agente. normal: vale a regra do Modo de permissões (ações nocivas ainda confirmam). Agente que não está na lista usa confirm.", LIVE),
    _S("brain.models", G_CLOUD, "Modelo por agente", DICT,
       "Agente -> modelo (ex.: opencode = opencode/big-pickle). Vazio = o modelo do próprio agente; se ele falhar por conta/modelo, o Eco tenta outro disponível e lembra.", LIVE),
    _S("brain.request_timeout_s", G_CLOUD, "Tempo máximo por resposta da nuvem", FLOAT, "Passado esse tempo o pedido é cancelado e o cérebro local assume.", LIVE, minimum=10, maximum=600, step=5, unit="s"),
    _S("brain.startup_timeout_s", G_CLOUD, "Tempo máximo para iniciar o agente", FLOAT, "", LIVE, minimum=5, maximum=300, step=5, unit="s"),
    # ---- ferramentas
    _S("tools.disabled", G_TOOLS, "Ferramentas desligadas", TOOLS, "Desligadas não aparecem para o modelo.", LIVE),
    _S("tools.confirm", G_TOOLS, "Ferramentas que sempre pedem confirmação", TOOLS, "Além das arriscadas, que SEMPRE pedem.", LIVE),
    _S("apps.launch", G_TOOLS, "Aplicativos que posso abrir", DICT, "Nome falado -> programa. Só estes abrem.", RESTART),
    _S("apps.hotkeys", G_TOOLS, "Atalhos de teclado permitidos", LIST, "As teclas de segurança do Eco não podem entrar aqui.", RESTART),
    _S("apps.hotkeys_confirm", G_TOOLS, "Atalhos que pedem confirmação", LIST, "Precisam estar na lista acima.", RESTART),
    _S("safety.max_typed_chars", G_TOOLS, "Digitação: máximo de caracteres", INT, "", RESTART, minimum=1, maximum=2000),
    _S("safety.typing_allowed_processes", G_TOOLS, "Digitação: programas permitidos", LIST, "Só nestes programas o Eco digita.", RESTART),
    _S("safety.typing_allowed_titles", G_TOOLS, "Digitação: apps da Microsoft Store permitidos", LIST,
       "Calculadora e similares rodam dentro do ApplicationFrameHost; o Eco só digita se o título da janela tiver uma destas palavras.", RESTART),
    _S("safety.typing_denied_extra", G_TOOLS, "Digitação: bloquear também", LIST, "Acrescenta à lista fixa de bloqueio (terminais, Explorer...).", RESTART),
    _S("safety.typing_confirm", G_TOOLS, "Digitação: quando confirmar", CHOICE, "", RESTART,
       choices=(("always", "Sempre"), ("untrusted_or_multiline", "Só com conteúdo de fora ou parecido com comando"))),
    # ---- memória e contexto
    _S("memory.enabled", G_MEM, "Guardar histórico e memória", BOOL, "Desligado = modo sem histórico: nada é gravado em disco.", RESTART),
    _S("memory.idle_minutes", G_MEM, "Nova conversa após inatividade", INT, "0 = nunca.", LIVE, minimum=0, maximum=1440, unit="min"),
    _S("memory.recall_top_k", G_MEM, "Memórias lembradas por pedido", INT, "", LIVE, minimum=0, maximum=20),
    _S("memory.model_can_remember", G_MEM, "O Eco pode propor memórias", BOOL, "", LIVE),
    _S("memory.conversation_ttl_days", G_MEM, "Conversas: guardar por", INT, "Passado o prazo, vão para a lixeira.", RESTART, minimum=1, maximum=3650, unit="dias"),
    _S("memory.trash_days", G_MEM, "Lixeira: guardar por", INT, "", RESTART, minimum=1, maximum=365, unit="dias"),
    _S("context.compact_at_pct", G_MEM, "Compactar a conversa em", INT, "Percentual do contexto que dispara o resumo automático.", LIVE, minimum=30, maximum=95, unit="%"),
    _S("context.keep_recent_messages", G_MEM, "Mensagens recentes mantidas", INT, "", LIVE, minimum=2, maximum=40),
    _S("context.tool_result_max_chars", G_MEM, "Resultado de ferramenta: máximo", INT, "", LIVE, minimum=200, maximum=8000, unit="caracteres"),
    _S("context.summary_max_tokens", G_MEM, "Tamanho do resumo", INT, "", LIVE, minimum=100, maximum=1500, unit="tokens"),
    # ---- arquivos
    _S("files.roots", G_FILES, "Pastas permitidas", LIST, "O Eco só mexe em arquivos dentro destas pastas (nunca Windows, Program Files nem a pasta do Eco).", LIVE),
    _S("files.max_read_kb", G_FILES, "Leitura: tamanho máximo", INT, "", LIVE, minimum=1, maximum=4096, unit="KB"),
    _S("files.max_write_kb", G_FILES, "Escrita: tamanho máximo", INT, "", RESTART, minimum=1, maximum=8192, unit="KB"),
    _S("files.undo_keep", G_FILES, "Desfazer: operações guardadas", INT, "", LIVE, minimum=1, maximum=200),
    _S("files.undo_max_mb", G_FILES, "Desfazer: espaço máximo", INT, "", LIVE, minimum=10, maximum=5000, unit="MB"),
    # ---- segurança
    _S("safety.emergency_hotkey", G_SEC, "Tecla de emergência", HOTKEY, "Para tudo na hora. OBRIGATÓRIA: não pode ser desativada.", RESTART,
       locked="a tecla de emergência é obrigatória"),
    _S("safety.permission_mode", G_SEC, "Modo de permissões", CHOICE,
       "Equilibrado: abrir apps, copiar/colar, escrever texto e controlar janelas são livres; só ações nocivas (apagar, mover, editar arquivos, fechar janelas) pedem confirmação. "
       "Estrito: também confirma ações depois de ler conteúdo de fora.", RESTART,
       choices=(("balanced", "Equilibrado (só as nocivas confirmam)"), ("strict", "Estrito"))),
    _S("safety.yolo_hotkey", G_SEC, "Atalho do modo YOLO", HOTKEY,
       "Liga/desliga o modo YOLO (sem NENHUMA confirmação). Só funciona apertando a tecla: nunca por voz, nem pelo modelo. Desliga sozinho e ao reiniciar.", RESTART,
       optional=True),
    _S("safety.yolo_minutes", G_SEC, "YOLO: duração", INT, "Depois deste tempo o modo YOLO desliga sozinho.", RESTART, minimum=1, maximum=240, unit="min"),
    # ---- logs
    _S("logs.level", G_LOGS, "Nível de log", CHOICE, "", LIVE, choices=(("DEBUG", "Detalhado"), ("INFO", "Normal"), ("WARNING", "Só avisos"), ("ERROR", "Só erros"))),
    _S("logs.max_mb", G_LOGS, "Tamanho por arquivo", INT, "", RESTART, minimum=1, maximum=100, unit="MB"),
    _S("logs.keep_files", G_LOGS, "Arquivos guardados", INT, "", RESTART, minimum=1, maximum=50),
    # ---- atualizações (o token do GitHub NUNCA fica aqui: vai para o Cofre de Credenciais do Windows)
    _S("updates.enabled", G_UPD, "Verificar atualizações automaticamente", BOOL, "Desligado, o Eco só procura novas versões quando você pede (bandeja > Verificar atualizações).", LIVE),
    _S("updates.check_on_start", G_UPD, "Verificar ao iniciar", BOOL, "Procura uma nova versão assim que o Eco abre.", LIVE),
    _S("updates.interval_hours", G_UPD, "Verificar a cada", INT, "Intervalo entre verificações enquanto o Eco fica aberto.", LIVE, minimum=1, maximum=168, step=1, unit="h"),
    _S("updates.channel", G_UPD, "Canal", CHOICE, "Estável: só versões finais. Pré-lançamento: inclui versões de teste.", LIVE,
       choices=(("stable", "Estável"), ("prerelease", "Pré-lançamento"))),
    _S("updates.auto_install", G_UPD, "Oferecer instalação automática", BOOL, "Mostra «Instalar automaticamente» no aviso. Só instala com o SHA-256 conferido e sempre com a sua escolha.", LIVE),
    _S("updates.repo", G_UPD, "Repositório das versões", TEXT, "Formato dono/repositório no GitHub. Repositório privado precisa de um token somente-leitura (guardado no Windows, não aqui) ou do GitHub CLI logado.", LIVE),
    # ---- terminal integrado (desligado por padrão; o modo "livre" só se libera à mão no painel Terminal, por tempo)
    _S("terminal.mode", G_TERM, "Terminal integrado", CHOICE,
       "Desligado (padrão): o Eco não roda comandos. Confirmar sempre: cada comando pede o seu Sim. Lista permitida: comandos de leitura da lista (git status, dir...) rodam direto e o resto pergunta. Livre: sem perguntar, mas só vale depois de você liberar no painel Terminal, por tempo limitado; nunca por voz nem pela nuvem. Comandos perigosos são sempre bloqueados.", LIVE,
       choices=(("off", "Desligado"), ("confirm", "Confirmar sempre"), ("allowlist", "Lista permitida"), ("free", "Livre (liberado à mão)"))),
    _S("terminal.shell", G_TERM, "Terminal padrão", CHOICE, "Qual shell roda os comandos quando o pedido não diz.", LIVE,
       choices=(("powershell", "PowerShell"), ("cmd", "Prompt de Comando (cmd)"), ("bash", "Git Bash"))),
    _S("terminal.roots", G_TERM, "Pastas onde o terminal pode rodar", LIST, "Todo comando começa dentro de uma destas pastas (nunca o Windows, o perfil inteiro, AppData ou a pasta do Eco). Comandos que apontam para fora delas pedem confirmação.", LIVE),
    _S("terminal.allowed_commands", G_TERM, "Comandos da lista permitida", LIST, "Só valem no modo Lista permitida, e só como comando simples (sem ; & | > nem crases). Cada item vale pelo começo do comando: «git log» libera «git log --oneline».", LIVE),
    _S("terminal.blocked_extra", G_TERM, "Bloquear também", LIST, "Trechos de texto que sempre bloqueiam o comando, além da lista fixa (formatar disco, apagar o sistema, desligar o PC, segredos...).", LIVE),
    _S("terminal.timeout_s", G_TERM, "Tempo máximo de um comando", INT, "Passado esse tempo o Eco encerra o comando (só o que ele mesmo iniciou).", LIVE, minimum=10, maximum=3600, step=10, unit="s"),
    _S("terminal.max_output_kb", G_TERM, "Saída guardada para o painel", INT, "Acima disso o meio da saída é cortado.", LIVE, minimum=16, maximum=4096, step=16, unit="KB"),
    _S("terminal.result_chars", G_TERM, "Saída enviada ao modelo", INT, "Quantos caracteres da saída o modelo recebe (começo e fim).", LIVE, minimum=200, maximum=8000, step=100, unit="caracteres"),
    _S("terminal.free_minutes", G_TERM, "Modo livre: duração", INT, "Depois de liberado no painel Terminal, o modo livre desliga sozinho após este tempo, ao reiniciar e na parada de emergência.", LIVE, minimum=1, maximum=120, unit="min"),
    _S("brain.consent_terminal", G_TERM, "Agentes na nuvem que podem pedir comandos", LIST, "Vazio = nenhum. Mesmo autorizado, cada comando pede a sua confirmação com o nome do agente e passa pelas mesmas travas.", LIVE),
    # ---- caminhos dos programas (vazio = o Eco procura sozinho; caminho de rede nunca é aceito)
    _S("toolpaths.git", G_PATHS, "Git", PATH, "Vazio = procurar sozinho. Usado pelo Terminal integrado.", RESTART, optional=True),
    _S("toolpaths.git_bash", G_PATHS, "Git Bash (bash.exe)", PATH, "Vazio = procurar sozinho. Precisa ser o do Git for Windows, não o do WSL.", RESTART, optional=True),
    _S("toolpaths.powershell", G_PATHS, "PowerShell (pwsh.exe ou powershell.exe)", PATH, "Vazio = procurar sozinho.", RESTART, optional=True),
    _S("toolpaths.python", G_PATHS, "Python de apoio (python.exe)", PATH, "Vazio = procurar sozinho. Só para comandos de Python no Terminal.", RESTART, optional=True),
    _S("toolpaths.ffmpeg", G_PATHS, "FFmpeg (ffmpeg.exe)", PATH, "Vazio = procurar sozinho. O Eco não depende dele.", RESTART, optional=True),
    _S("toolpaths.whispercpp_dir", G_PATHS, "Pasta do whisper.cpp (escuta na placa de vídeo)", PATH, "Vazio = a pasta do Eco. Precisa conter jarvis_whisper.dll.", RESTART, optional=True),
    _S("toolpaths.ollama", G_PATHS, "Ollama (ollama.exe)", PATH, "Vazio = procurar sozinho. Opcional.", RESTART, optional=True),
    _S("toolpaths.lmstudio", G_PATHS, "LM Studio", PATH, "Vazio = procurar sozinho. Opcional.", RESTART, optional=True),
    _S("toolpaths.opencode", G_PATHS, "OpenCode (agente de nuvem)", PATH, "Vazio = procurar sozinho.", RESTART, optional=True),
    _S("toolpaths.antigravity", G_PATHS, "Google Antigravity (agy.exe)", PATH, "Vazio = procurar sozinho.", RESTART, optional=True),
    _S("toolpaths.claude", G_PATHS, "Claude Code (claude.exe)", PATH, "Vazio = procurar sozinho.", RESTART, optional=True),
    _S("toolpaths.codex", G_PATHS, "OpenAI Codex CLI (codex)", PATH, "Vazio = procurar sozinho.", RESTART, optional=True),
    _S("toolpaths.copilot", G_PATHS, "GitHub Copilot CLI (copilot)", PATH, "Vazio = procurar sozinho.", RESTART, optional=True),
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
