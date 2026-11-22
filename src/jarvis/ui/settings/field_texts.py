"""Textos de cada campo, secao e opcao das Configuracoes (pt-BR, sem jargao, sem travessao).

Sao dados puros: ``texts.T`` expoe estes dicionarios. O schema (``jarvis.settings.schema``) continua dono
dos tipos e limites; aqui so mora o que a pessoa le. Campo sem entrada cai no rotulo do schema.
"""
from __future__ import annotations

# chave do campo -> (rotulo, ajuda de uma linha)
FIELDS: dict[str, tuple[str, str]] = {
    "safety.talk_key": ("Tecla para falar", "Uma tecla simples, sem Ctrl nem Alt. Exemplo: F9."),
    "safety.talk_mode": ("Como usar a tecla", "Segurar enquanto fala, ou apertar uma vez e parar sozinho no silêncio."),
    "safety.mute_hotkey": ("Tecla do modo mudo", "Liga e desliga o microfone do Jarvis."),
    "safety.confirm_yes_hotkey": ("Tecla para responder Sim", "Aceita uma ação que o Jarvis pediu para confirmar."),
    "safety.confirm_no_hotkey": ("Tecla para responder Não", "Recusa uma ação que o Jarvis pediu para confirmar."),
    "safety.confirm_timeout_s": ("Tempo para confirmar", "Sem resposta nesse tempo, a ação é recusada."),
    "ui.island_enabled": ("Mostrar a Ilha", "Some sozinha com jogo ou vídeo em tela cheia. Vale na próxima vez que o Jarvis abrir."),
    "safety.max_agent_steps": ("Passos por pedido", "Quantas ações seguidas o Jarvis faz antes de desistir de um pedido."),
    "safety.tool_timeout_s": ("Tempo máximo de cada ação", "Uma ação que passar disso é interrompida."),
    "tts.voice_onnx": ("Arquivo da voz", "O arquivo .onnx da voz que o Jarvis usa para falar."),
    "tts.voice_json": ("Ajustes da voz", "O arquivo .json que acompanha a voz."),
    "tts.length_scale": ("Velocidade da fala", "Valores menores falam mais rápido. Sem personalizar, vale a velocidade da voz."),
    "tts.volume": ("Volume da voz", "1 é o volume original da voz."),
    "audio.output_device": ("Saída de som", "Onde o Jarvis fala. O padrão do Windows acompanha o sistema."),
    "audio.input_device": ("Microfone", "Qual microfone o Jarvis escuta. O padrão do Windows acompanha o sistema."),
    "stt.model_dir": ("Pasta do modelo de escuta", "Modelos maiores entendem melhor e respondem mais devagar (hf_tiny, hf_base, hf_small)."),
    "stt.language": ("Idioma da fala", "Código de duas letras: pt, en, es."),
    "stt.compute_type": ("Modo de cálculo", "O modo leve usa menos do processador e serve para a maioria dos casos."),
    "stt.cpu_threads": ("Núcleos do processador", "Quantos núcleos a escuta pode usar."),
    "stt.beam_size": ("Cuidado na transcrição", "1 é mais rápido, 5 acerta mais."),
    "audio.vad_threshold": ("Sensibilidade à voz", "Maior exige voz mais clara. Menor aceita falas baixas e mais ruído."),
    "audio.end_silence_ms": ("Silêncio que encerra a frase", "Quanto silêncio o Jarvis espera antes de considerar a frase pronta."),
    "audio.min_speech_ms": ("Fala mínima", "Sons mais curtos que isso são ignorados."),
    "audio.max_utterance_s": ("Duração máxima da fala", "Frases mais longas que isso são cortadas."),
    "audio.pre_roll_ms": ("Início da frase", "Som guardado antes da fala ser detectada, para não cortar a primeira palavra."),
    "llm.model": ("Arquivo do modelo", "O arquivo .gguf do modelo de linguagem."),
    "llm.mmproj": ("Arquivo de visão", "Deixe vazio para o Jarvis não enxergar a tela."),
    "llm.ctx": ("Memória de trabalho", "Quanto texto o modelo considera de uma vez. Mais usa mais memória da placa de vídeo."),
    "llm.ngl": ("Camadas na placa de vídeo", "99 coloca o modelo todo na placa de vídeo. 0 usa só o processador."),
    "llm.temperature": ("Criatividade", "Menor deixa as respostas mais previsíveis."),
    "llm.max_tokens": ("Tamanho máximo da resposta", "Um pedaço de texto é parte de uma palavra."),
    "llm.request_timeout_s": ("Tempo limite da resposta", "Se o modelo demorar mais que isso, o Jarvis desiste do pedido."),
    "llm.startup_timeout_s": ("Tempo limite para abrir o modelo", "Quanto o Jarvis espera o modelo carregar ao iniciar."),
    "llm.port": ("Porta do modelo", "O modelo só atende neste computador."),
    "llm.host": ("Endereço do modelo", "Fixo neste computador para o modelo nunca ficar exposto na rede."),
    "llm.reasoning_off": ("Respostas diretas", "Ligue para modelos que gastam tempo pensando antes de responder."),
    "vision.max_side_px": ("Tamanho da imagem da tela", "Lado maior da captura enviada ao modelo. Menor é mais rápido."),
    "vision.jpeg_quality": ("Qualidade da imagem da tela", "Maior fica mais nítido e mais pesado."),
    "tools.disabled": ("Ferramentas ligadas", "Desligadas, o Jarvis nem sabe que existem."),
    "tools.confirm": ("Sempre pedir confirmação", "Além das arriscadas, que sempre pedem."),
    "apps.launch": ("Programas que o Jarvis pode abrir", "O nome que você fala e o programa que abre. Só estes abrem."),
    "apps.hotkeys": ("Atalhos de teclado permitidos", "As teclas de segurança do Jarvis nunca podem entrar aqui."),
    "apps.hotkeys_confirm": ("Atalhos que pedem confirmação", "Precisam estar na lista de atalhos permitidos."),
    "safety.max_typed_chars": ("Limite de digitação", "Máximo de caracteres que o Jarvis digita de uma vez."),
    "safety.typing_allowed_processes": ("Programas em que ele pode digitar", "Em qualquer outro, o Jarvis não digita."),
    "safety.typing_denied_extra": ("Também nunca digitar em", "Soma-se à lista fixa de bloqueio (terminais, Explorer e similares)."),
    "safety.typing_confirm": ("Quando confirmar a digitação", "Sempre, ou só quando o texto veio de fora ou parece um comando."),
    "memory.enabled": ("Guardar histórico e memória", "Desligado, nada das conversas é gravado no computador."),
    "memory.idle_minutes": ("Nova conversa após pausa", "Minutos sem falar até começar uma conversa nova. Zero nunca começa sozinho."),
    "memory.recall_top_k": ("Lembranças por pedido", "Quantas memórias o Jarvis consulta a cada pedido."),
    "memory.model_can_remember": ("O Jarvis pode sugerir memórias", "Ele propõe o que guardar sobre você."),
    "memory.conversation_ttl_days": ("Guardar conversas por", "Passado o prazo, vão para a lixeira."),
    "memory.trash_days": ("Guardar a lixeira por", "Tempo que o que foi apagado fica na lixeira."),
    "context.compact_at_pct": ("Resumir a conversa em", "Quando a conversa ocupa essa parte da memória de trabalho, o Jarvis a resume."),
    "context.keep_recent_messages": ("Mensagens recentes mantidas", "Ficam intactas quando a conversa é resumida."),
    "context.tool_result_max_chars": ("Tamanho máximo do resultado de uma ação", "Resultados maiores são cortados."),
    "context.summary_max_tokens": ("Tamanho do resumo", "Quanto espaço o resumo da conversa pode ocupar."),
    "files.roots": ("Pastas permitidas", "O Jarvis só mexe em arquivos dentro delas. Windows, Program Files e a pasta do Jarvis ficam sempre fora."),
    "files.max_read_kb": ("Leitura: tamanho máximo", "Arquivos maiores não são lidos."),
    "files.max_write_kb": ("Escrita: tamanho máximo", "Arquivos maiores não são gravados."),
    "files.undo_keep": ("Desfazer: operações guardadas", "Quantas operações em arquivos dá para desfazer."),
    "files.undo_max_mb": ("Desfazer: espaço máximo", "Limite de disco usado pelas cópias de segurança."),
    "safety.emergency_hotkey": ("Tecla de emergência", "Para tudo na hora. É obrigatória e não pode ser desligada."),
    "safety.permission_mode": ("Modo de permissões", "Estrito confirma também após ler conteúdo de fora."),
    "safety.yolo_hotkey": ("Atalho do modo YOLO", "Só por tecla: nunca por voz."),
    "safety.yolo_minutes": ("Duração do YOLO", "Depois deste tempo o modo YOLO desliga sozinho."),
    "logs.level": ("Detalhe do registro", "Mais detalhe ajuda a achar problemas e ocupa mais disco."),
    "logs.max_mb": ("Tamanho de cada arquivo", "Passando disso, o registro começa um arquivo novo."),
    "logs.keep_files": ("Arquivos guardados", "Os mais antigos são apagados."),
}

# motivo do cadeado dos campos protegidos
LOCKED: dict[str, str] = {
    "llm.host": "o modelo só pode atender neste computador, nunca pela rede",
    "safety.emergency_hotkey": "a tecla de emergência é obrigatória e precisa estar sempre ativa",
}

# chave do campo -> (valor -> rotulo) das opcoes
CHOICES: dict[str, dict[str, str]] = {
    "safety.talk_mode": {"hold": "Segurar para falar", "toggle": "Apertar e falar"},
    "stt.compute_type": {"int8": "Leve (recomendado)", "int8_float32": "Intermediário", "float32": "Máxima precisão"},
    "safety.typing_confirm": {"always": "Sempre", "untrusted_or_multiline": "Texto de fora ou parecido com comando"},
    "logs.level": {"DEBUG": "Detalhado", "INFO": "Normal", "WARNING": "Só avisos", "ERROR": "Só erros"},
}

# campo de caminho -> filtro do seletor de arquivo
PATH_FILTERS: dict[str, str] = {
    "tts.voice_onnx": "Voz (*.onnx);;Todos os arquivos (*.*)",
    "tts.voice_json": "Ajustes da voz (*.json);;Todos os arquivos (*.*)",
    "llm.model": "Modelo (*.gguf);;Todos os arquivos (*.*)",
    "llm.mmproj": "Arquivo de visão (*.gguf);;Todos os arquivos (*.*)",
}

# unidade do schema -> unidade exibida
UNITS: dict[str, str] = {"tokens": "pedaços", "caracteres": "caracteres"}

# id da secao -> (titulo, descricao curta)
SECTIONS: dict[str, tuple[str, str]] = {
    "appearance": ("Aparência", "O tema vale na hora e fica lembrado só neste computador."),
    "talk": ("Falar com o Jarvis", "As teclas que você usa no dia a dia."),
    "confirm": ("Confirmações", "O que acontece quando o Jarvis pede um Sim ou um Não."),
    "island": ("Ilha do Jarvis", "A janelinha no topo da tela que mostra o que o Jarvis está fazendo."),
    "limits": ("Limites de cada pedido", ""),
    "voice": ("Voz do Jarvis", "Os arquivos da voz que ele usa para responder."),
    "speech": ("Fala", ""),
    "output": ("Saída de som", ""),
    "mic": ("Microfone", ""),
    "model_stt": ("Modelo de escuta", ""),
    "detect": ("Quando a frase termina", "Ajusta como o Jarvis percebe que você começou e parou de falar."),
    "perf": ("Desempenho", ""),
    "llm_model": ("Modelo", "O arquivo que entende e responde."),
    "llm_work": ("Recursos e respostas", ""),
    "llm_net": ("Conexão local", "O modelo roda neste computador, em uma porta própria."),
    "vision": ("Visão da tela", "Só vale se houver um arquivo de visão acima."),
    "emergency": ("Parada de emergência", "Uma tecla que para tudo, sempre."),
    "permissions": ("Permissões", "O que o Jarvis pode acessar e fazer neste computador."),
    "tools": ("Ferramentas", ""),
    "apps": ("Programas e atalhos", ""),
    "typing": ("Digitação", "Quando o Jarvis escreve por você em outro programa."),
    "mem_basic": ("Histórico e memória", ""),
    "mem_keep": ("Por quanto tempo", ""),
    "mem_ctx": ("Conversas longas", "Como o Jarvis resume o que já foi dito para continuar lembrando."),
    "folders": ("Pastas permitidas", ""),
    "file_limits": ("Tamanho dos arquivos", ""),
    "undo": ("Desfazer", "As operações em arquivos podem ser desfeitas por um tempo."),
    "logs": ("Registro do programa", "O que o Jarvis anota sobre o que faz, útil para achar problemas."),
    "config_file": ("Arquivo de configuração", "Só aparece o que você mudou do padrão."),
    "reset": ("Voltar ao início", ""),
    "other": ("Outras opções", ""),
    "status": ("Estado do Jarvis", ""),
    "details": ("Detalhes técnicos", ""),
    "paths": ("Onde ficam os arquivos", ""),
}

# chave da pagina -> (titulo, frase de apoio)
PAGES: dict[str, tuple[str, str]] = {
    "general": ("Geral", "Como você fala com o Jarvis, quanto ele espera por você e como esta tela aparece."),
    "voice": ("Voz e áudio", "A voz que o Jarvis usa para responder e por onde o som sai."),
    "my_voice": ("Minha voz", "Grave suas frases e a palavra Jarvis para ele aprender a sua voz."),
    "listening": ("Reconhecimento", "Como o Jarvis escuta: microfone, modelo de escuta e quando a frase acabou."),
    "llm": ("Modelo de linguagem", "O modelo que entende e responde, e quanto do computador ele pode usar."),
    "tools": ("Ferramentas e segurança", "O que o Jarvis pode fazer sozinho e o que sempre depende da sua confirmação."),
    "memory": ("Memória e conversas", "O que o Jarvis guarda das conversas, por quanto tempo e quanto ele lembra."),
    "knows": ("O que o Jarvis sabe de mim", "Veja, corrija e apague o que o Jarvis guardou sobre você."),
    "files": ("Arquivos", "As pastas em que o Jarvis pode ler e escrever, e os limites de cada operação."),
    "advanced": ("Avançado", "Registro do programa e o arquivo de configuração."),
    "about": ("Sobre", "Estado atual do Jarvis e onde ficam os arquivos dele."),
}
