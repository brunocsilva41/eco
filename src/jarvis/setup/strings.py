"""Textos do assistente de configuração (100% pt-BR). Tom: direto, sem jargão; erro diz o que houve e o que fazer."""
from __future__ import annotations

WINDOW_TITLE = "Configurar o Jarvis"
WINDOW_TITLE_REPAIR = "Reparar ou reconfigurar o Jarvis"

STEP_TITLES = {
    "welcome": "Boas-vindas",
    "hardware": "Seu computador",
    "models": "Modelos de IA",
    "audio": "Microfone e som",
    "voice": "Teste de voz",
    "vad": "Calibrar a escuta",
    "hotkeys": "Atalhos",
    "permissions": "Permissões",
    "doctor": "Verificação final",
    "done": "Tudo pronto",
}

STEP_SUBTITLES = {
    "welcome": "Em poucos minutos o Jarvis fica pronto para uso.",
    "hardware": "Conferimos o que o seu PC tem. Nada é alterado, nenhum driver é mexido.",
    "models": "O Jarvis pensa, ouve e fala no seu PC. Para isso precisa baixar os modelos uma única vez.",
    "audio": "Escolha por onde o Jarvis ouve e fala. O padrão acompanha o que o Windows usa.",
    "voice": "Ouça o Jarvis falar e confira se ele escuta você.",
    "vad": "Ajusta o quanto o Jarvis exige de voz para começar a ouvir, no seu ambiente.",
    "hotkeys": "Teclas que funcionam em qualquer programa.",
    "permissions": "Defina o quanto o Jarvis pode fazer sozinho.",
    "doctor": "Última checagem: modelos, GPU, áudio, atalhos e ferramentas.",
    "done": "",
}

BACK = "Voltar"
NEXT = "Avançar"
FINISH = "Concluir"
SKIP = "Pular esta etapa"
EXIT_TITLE = "Sair da configuração?"
EXIT_BODY = "O que você já fez fica salvo. Ao abrir de novo, o assistente continua de onde parou."
EXIT_CONFIRM = "Sair"
EXIT_STAY = "Continuar configurando"
STEP_OF = "Etapa {n} de {total}"
RAIL_A11Y = "Etapa {n} de {total}: {title}{state}"
RAIL_DONE = ", concluída"
RAIL_NOW = ", etapa atual"

# --- boas-vindas
W_HEADLINE = "Vamos preparar o Jarvis"
W_LEAD = ("O Jarvis é um assistente de voz em português que roda inteiramente no seu computador: "
          "você fala, ele entende, responde e ajuda a controlar o PC.")
W_POINTS = (
    ("shield", "Tudo local", "Sua voz, suas conversas e sua tela não saem do computador. Só os modelos são baixados, uma vez."),
    ("lock", "Você no controle", "Ações que mudam algo pedem sua confirmação. Há uma tecla de emergência que para tudo."),
    ("refresh", "Dá para refazer", "Esta configuração pode ser aberta de novo quando quiser, pelo menu Iniciar."),
)
W_RESUME_TITLE = "Você parou na etapa “{step}”"
W_RESUME_BODY = "Dá para continuar de onde parou. Suas escolhas anteriores foram guardadas."
W_RESUME_ACTION = "Continuar de onde parei"
W_REPAIR_TITLE = "Modo reparar e reconfigurar"
W_REPAIR_BODY = "Tudo que já está certo é reaproveitado. Arquivos de modelo são conferidos e só o que faltar é baixado de novo."
W_VERSION = "Versão {v}"

# --- hardware
H_RECHECK = "Verificar de novo"
H_CHECKING = "Verificando o computador..."
H_OK = "Seu computador está pronto para o Jarvis."
H_WARN = "Dá para continuar, mas há avisos abaixo."
H_FAIL = "Há problemas que impedem o bom funcionamento. Veja os itens com erro."
H_FAIL_CONFIRM_TITLE = "Continuar mesmo com problemas?"
H_FAIL_CONFIRM_BODY = "Alguns requisitos não foram atendidos. O Jarvis pode não funcionar. Você pode voltar e corrigir, ou continuar assim."
H_FAIL_CONFIRM = "Continuar assim mesmo"
STATUS_TEXT = {"ok": "Ok", "warn": "Atenção", "fail": "Erro"}

# --- modelos
M_VISION_FOCUS = "Cérebro (visão e linguagem)"
M_TOTAL = "Para baixar: {need}. Espaço livre: {free}."
M_ALL_OK = "Todos os modelos estão no lugar e conferidos."
M_MISSING = "Faltam {n} arquivo(s) ({size})."
M_DOWNLOAD = "Baixar agora"
M_RESUME = "Retomar download"
M_PAUSE = "Pausar"
M_VERIFY = "Conferir arquivos"
M_OFFLINE = "Usar pacote offline..."
M_OFFLINE_PICK = "Escolha a pasta (ou o .zip) do pacote offline de modelos"
M_OFFLINE_DONE = "Importado do pacote offline: {n} arquivo(s)."
M_OFFLINE_NONE = "Nenhum arquivo do manifesto foi encontrado nesse pacote."
M_STATE_OK = "Pronto"
M_STATE_MISSING = "Falta baixar"
M_STATE_PART = "Parcial (retoma de onde parou)"
M_STATE_BAD = "Arquivo inválido"
M_PHASE = {"baixando": "Baixando", "verificando": "Conferindo integridade (SHA-256)", "copiando": "Copiando", "pronto": "Concluído"}
M_PROGRESS = "{phase}: {name}"
M_SPEED = "{speed}/s"
M_ETA = "faltam {eta}"
M_SOURCE = "de {host}"
M_OFFLINE_ERR = "Sem conexão com a internet"
M_OFFLINE_WHY = "Não consegui falar com o servidor dos modelos."
M_OFFLINE_TODO = "Conecte-se e tente de novo, ou use o pacote offline (botão abaixo). O que já foi baixado não se perde."
M_ERR = "O download falhou"
M_SKIP_TITLE = "Seguir sem os modelos?"
M_SKIP_BODY = "Sem os modelos o Jarvis não consegue ouvir, pensar nem falar. Você pode baixá-los depois reabrindo esta configuração."
M_SKIP_CONFIRM = "Seguir sem baixar"
M_LICENSE = "Licença: {lic}"
M_SELECT_STT = "Reconhecimento de fala"
M_STT_SMALL = "Whisper small (recomendado)"
M_STT_BASE = "Whisper base (mais leve)"
M_PRIVACY = "Os downloads usam só HTTPS e cada arquivo é conferido por SHA-256 antes de ser aceito."

# --- áudio
A_MIC = "Microfone"
A_MIC_HELP = "“Padrão do Windows” segue o que você escolher em Configurações > Som."
A_OUT = "Saída de som"
A_OUT_HELP = "Onde a voz do Jarvis toca."
A_REFRESH = "Atualizar lista"
A_LIVE = "Fale para ver o medidor se mexer"
A_LIVE_FAIL = "Não consegui abrir este microfone"
A_LIVE_FAIL_TODO = "Escolha outro na lista ou confira se ele está conectado e liberado em Configurações > Privacidade > Microfone."
A_NO_MIC = "Nenhum microfone encontrado"
A_SILENT = "Este microfone está sem sinal"
A_SILENT_WHY = "Nenhum som chegou nos últimos segundos. Ele pode estar mudo, desligado ou sem permissão."
A_SILENT_TODO = "Confira o botão de mudo do fone/microfone e Configurações do Windows > Privacidade > Microfone, ou escolha outro na lista."

# --- teste de voz
V_SPEAK = "Ouvir o Jarvis falar"
V_SPEAK_TEXT = "Olá! Eu sou o Jarvis. Se você está me ouvindo, o som está funcionando."
V_SPEAKING = "Falando..."
V_STOP = "Parar"
V_ECHO = "Gravar e ouvir de volta"
V_ECHO_HELP = "Grava 4 segundos e toca em seguida, para você ouvir como o Jarvis escuta."
V_ECHO_REC = "Gravando... fale agora ({s} s)"
V_ECHO_PLAY = "Tocando a gravação..."
V_NO_MODEL = "A voz do Jarvis ainda não foi baixada"
V_NO_MODEL_TODO = "Volte à etapa Modelos e baixe a voz. O teste do microfone abaixo funciona sem ela."
V_ECHO_TIP = "Dica: use fones para o eco não voltar ao microfone."
V_HEARD_LOW = "Não ouvi quase nada. Aproxime o microfone ou aumente o volume de entrada."
V_HEARD_OK = "Captei sua voz com bom nível."
V_HEARD_HOT = "Sua voz estourou o medidor. Afaste o microfone um pouco."

# --- VAD
D_INTRO = ("Dois passos rápidos: primeiro silêncio, depois uma frase. Com isso o Jarvis escolhe o ponto em que considera que "
           "você está falando e não ruído.")
D_START = "Começar calibragem"
D_STEP1 = "1 de 2: fique em silêncio por {s} s..."
D_STEP2 = "2 de 2: diga “Jarvis, que horas são?” ({s} s)"
D_RESULT = "Sensibilidade sugerida: {thr}"
D_RESULT_HELP = "Ruído de fundo: {noise} dB. Sua voz: {speech} dB. (O padrão do Jarvis é 0,50.)"
D_USE = "Usar este valor"
D_KEEP = "Manter o padrão (0,50)"
D_NO_MODEL = "O detector de voz ainda não foi baixado"
D_NO_MODEL_TODO = "Volte à etapa Modelos. Você pode pular esta etapa: o padrão funciona na maioria dos casos."
D_AGAIN = "Calibrar de novo"
D_APPLIED = "Valor {thr} será salvo."

# --- atalhos
K_TALK = "Falar com o Jarvis"
K_TALK_HELP = "Segure a tecla enquanto fala. Uma tecla simples, sem Ctrl/Alt (padrão F9)."
K_EMERGENCY = "Parada de emergência"
K_EMERGENCY_HELP = "Para tudo: ações, fala, mouse e teclado. É obrigatória e sempre funciona."
K_MUTE = "Ligar/desligar o microfone"
K_MUTE_HELP = "Silencia a escuta sem fechar o Jarvis."
K_FREE = "Livre"
K_BUSY = "Em uso por outro programa"
K_SUGGEST = "Sugerir outra"
K_TESTING = "Testando..."
K_RUNNING = "O Jarvis está aberto e já usa estes atalhos; não dá para testar agora."
K_INVALID = "Atalho inválido ou repetido"
K_NOTE = "Sim e Não das confirmações (Ctrl+Alt+Y e Ctrl+Alt+N) e outros atalhos ficam em Configurações > Permissões."
K_ALTS = ("ctrl+alt+f11", "ctrl+alt+shift+f12", "ctrl+shift+f12", "ctrl+alt+f10")
K_ALTS_TALK = ("f8", "f10", "f7")

# --- permissões
P_BALANCED = "Equilibrado (recomendado)"
P_BALANCED_BODY = ("Abrir programas, trocar de janela, volume, copiar e colar e escrever texto funcionam sem perguntar. "
                   "Apagar ou mover arquivos, fechar janelas e salvar pedem sua confirmação.")
P_STRICT = "Estrito"
P_STRICT_BODY = ("Igual ao equilibrado, mas depois que o Jarvis lê algo de fora (uma página, um e-mail) quase tudo "
                 "passa a pedir confirmação. Mais seguro, mais perguntas.")
P_YOLO_TITLE = "Modo YOLO (não pode ser ligado aqui)"
P_YOLO_BODY = ("O YOLO desliga as confirmações por um tempo limitado (30 minutos por padrão) e é para quem aceita o risco. "
               "Por segurança, ele só liga por Configurações > Permissões ou pela tecla física Ctrl+Alt+Shift+Y, nunca por voz "
               "e nunca por este assistente. As travas duras (pastas do sistema, terminais, Lixeira) continuam valendo.")

# --- doctor
X_RUN = "Verificar de novo"
X_RUNNING = "Rodando a verificação (leva alguns segundos)..."
X_ALL_OK = "Tudo certo. O Jarvis está pronto."
X_SOME_FAIL = "Há itens com problema. Veja a dica em cada um."
X_FAIL_HINTS = {
    "modelo LLM": "Volte à etapa Modelos e baixe o modelo de visão e linguagem.",
    "mmproj (visão)": "O projetor de visão não foi baixado: o Jarvis funciona, mas sem enxergar a tela.",
    "GPU Vulkan": "Sem GPU Vulkan o Jarvis usa a CPU (mais lento). Atualize o driver de vídeo pelo site do fabricante.",
    "llama-server": "A instalação está incompleta. Rode o instalador de novo (opção Reparar).",
    "porta do LLM": "Outro programa usa a porta do modelo. Feche-o ou troque a porta em Configurações > Modelo.",
    "atalho emergência": "Escolha outro atalho de emergência na etapa Atalhos.",
}
X_DEFAULT_HINT = "Veja o detalhe ao lado e, se precisar, volte à etapa correspondente."

# --- fim
F_HEADLINE = "Tudo pronto"
F_LEAD = "O Jarvis está configurado. Segure {talk} e fale para começar."
F_SUMMARY = "Resumo"
F_AUTOSTART = "Iniciar o Jarvis com o Windows"
F_AUTOSTART_HELP = "Você pode desligar depois no menu Iniciar > Configurações > Aplicativos > Inicialização."
F_OPEN = "Abrir o Jarvis agora"
F_CLOSE = "Fechar"
F_SUM_MODELS = "Modelos"
F_SUM_MIC = "Microfone"
F_SUM_OUT = "Saída"
F_SUM_TALK = "Falar"
F_SUM_EMERG = "Emergência"
F_SUM_PROFILE = "Permissões"
F_SUM_VAD = "Sensibilidade"
F_DEFAULT_DEV = "padrão do Windows"
F_INCOMPLETE = "Alguns modelos ainda não foram baixados. Reabra “Reparar ou reconfigurar o Jarvis” no menu Iniciar para concluir."
