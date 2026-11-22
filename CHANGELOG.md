# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]
- Licença do projeto ainda pendente de definição.

## [0.1.2] - 2026-11-22
### Corrigido
- **Parava de responder (ouvia e voltava ao repouso):** o áudio podia chegar sem sinal (microfone preso depois de a máquina travar). Agora o Jarvis detecta fala sem som, reabre o microfone sozinho depois de 2 ocorrências e avisa; o log registra o pico do áudio.
- **Calculadora e apps da Microsoft Store:** `abrir_app` agora coloca a janela em foco; `digitar_texto` e `apertar_atalho` aceitam o parâmetro `janela` (trazem o app para a frente antes) e a Calculadora entra nos destinos permitidos (`safety.typing_allowed_titles`). Provado: abrir, digitar `12+7=` e o visor mostra 19.
- **Configurações abriam várias janelas e demoravam:** abre em ~1 s (páginas montadas sob demanda), com trava de instância única entre processos e sem repetir o clique.
### Adicionado
- **Controle de janelas:** `janela_acao` (minimizar, maximizar, restaurar, metade esquerda/direita, centralizar) e `ver_tela` com `alvo="janela"` (olha só o app em foco).
- **Escuta aberta:** o Jarvis ouve sozinho, sem apertar tecla (`safety.listen_mode = open`, atalho `Ctrl+Alt+L`, botão na Ilha e item na bandeja).
- **Ícone na bandeja do sistema** com menu: Abrir Configurações, Ilha do Jarvis (tamanho, posição, fixar), Escuta contínua, Silenciar microfone, Verificar atualizações…, Sobre e Encerrar o Jarvis.
- **Verificador de atualizações** (consulta a última release publicada).
- **Ilha:** alfinete corrigido (fixada nunca some), transparência (vidro) ajustável e dock lateral vertical (direita/esquerda).

## [0.1.1] - 2026-11-22
### Corrigido
- **Assistente de instalação não encontrava modelos já existentes no PC.** Agora ele procura sozinho (nome e tamanho, depois confere o SHA-256) em pastas comuns, instalações anteriores, cache do Hugging Face, LM Studio e Ollama; botão «Procurar no computador inteiro» para varrer os discos. Os arquivos conferidos são ligados à instalação por link físico (sem ocupar espaço extra) ou copiados quando estão em outro disco. `Jarvis.cmd setup --scan [--deep] [--use-found]` faz o mesmo sem janela; `--fetch` também aproveita o que já existe antes de baixar.
- **Escolher pasta:** o assistente (botão «Escolher pasta...») e `Jarvis.cmd setup --scan --folder PASTA` examinam a pasta e subpastas, conferem o SHA-256 e mostram o que dá para usar, o que tem o mesmo tamanho mas conteúdo diferente e o que não está lá; só os arquivos válidos são trazidos.
- Botões da etapa de modelos reorganizados (rótulos não são mais cortados).

## [0.1.0] - 2026-11-22
Primeira versão. Desenvolvida entre 2026-11-19 e 2026-11-22 (33 commits).

### Adicionado
- **CPU × GPU por serviço (medido):** LLM, visão e escuta de comandos na GPU; voz Piper, detector de voz, captura de tela, Ilha e UI Automation na CPU. Escuta com whisper.cpp Vulkan (small): 0,98 s e 0,38 CPU-s por frase, WER 11,8% contra 18,4% do base na CPU. Chaves `llm.device`, `llm.mmproj_device`, `stt.device`, `tts.device` (`auto`/`gpu`/`cpu`); queda segura para a CPU com aviso; `Jarvis.cmd doctor` mostra onde cada serviço roda.
- **Leveza:** modelo sem mmap (−2,35 GB de RAM), descarga do modelo e da escuta por inatividade (`llm.sleep_idle_s`, libera ~5 GB de VRAM), servidor com 2 threads (CPU −43%), núcleo fixo de ferramentas em cache (1º token 0,8–1,4 s), Ilha leve (34–48 MB, ~0% escondida).
- **Base e medições (F0/F1):** estrutura do projeto; build do llama.cpp com Vulkan; varreduras de modelos (Gemma 4 E4B,
  Qwen3.5 4B/9B, MoE), KV cache, flash-attention e RAM; benchmark e validação de STT (whisper.cpp x faster-whisper).
- **Núcleo:** configuração tipada e validada (`config.toml`), agente com chamada de ferramentas, cliente e servidor
  llama.cpp supervisionado, áudio com VAD, STT e TTS, CLI (`doctor`, `run`, `tools`, `config`).
- **Voz:** fala Piper a 0,9x, normalizador pt-BR de números, horas, datas, dinheiro, unidades, extensões e marcas;
  pronúncias próprias em `data/pronuncias.json`; saída de áudio segue o padrão do Windows.
- **Visão e mouse:** `ver_tela`, `clicar_controle` unificado (UIA com reserva visual presa à janela em foco),
  `clicar_em`, `clicar_na_tela`, `rolar_tela`; trava contra ação inventada pelo modelo.
- **Ferramentas e roteamento:** ferramentas de apps, janelas, teclado, arquivos (Lixeira e desfazer) e memória;
  roteamento por pedido (3 a 18 ferramentas em vez de 35).
- **Memória:** sessões, memória de longo prazo (FTS5), busca de conversas, compactação de contexto, painel
  "O que o Jarvis sabe de mim".
- **Interface:** tokens de tema e kit de componentes; Configurações (11 páginas), gravador de voz "Minha voz".
- **Ilha:** janela no topo da tela (3 tamanhos, estados, ondas, ícone vetorial), processo filho ligado ao núcleo por
  JSON nos pipes, botões Sim/Não, Mudo, Parar e Configurações, chip YOLO, esconde em tela cheia.
- **Distribuição:** instalador Inno Setup (pt-BR/en), runtime Python embutido com wheels travadas por hash,
  `installer/manifest.json` com SHA-256, baixador com retomada, pacote offline, assistente `Jarvis.cmd setup`.

### Segurança
- Auditoria 1 e 2: janela própria nos diálogos, confirmações com o conteúdo real, raízes e nomes sensíveis, HMAC na
  auditoria, servidor do modelo só em loopback com chave de API por arquivo, emergência só vale se registrada.
- Permissões: modo equilibrado confirma só ações nocivas; modo YOLO só por ação manual (atalho físico ou clique assinado).

### Alterado
- Contexto padrão do modelo em 12288 (prompt fixo em 34%).

### Desempenho
- Modelo sem mmap (RAM do servidor 2,85 GB para ~0,5 GB); descarga por inatividade (`llm.sleep_idle_s`, ~5 GB de VRAM
  liberados); pré-aquecimento ao ouvir; atalho direto para hora e janela ativa; prompt estável para preservar o cache.

### Corrigido
- Partida falhava quando o prompt fixo passava de 50% (colisão do parâmetro `kind` no EventBus).
- Cache do prompt invalidado a cada minuto (hora no início do prompt).
- Rótulo "Saturado" cortado no medidor de nível.
