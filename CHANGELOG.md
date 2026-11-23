# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

## [0.2.0] - 2026-11-22
Primeira versão como **Eco** (antes Jarvis). Resumo: terminal integrado, cérebro em nuvem opcional por ACP, atualização
automática com permissão de administrador sob demanda, Setup que prepara o PC, Configurações reformuladas e uma rodada
completa de QA das telas (5088 verificações, 14 defeitos corrigidos).
### Renomeado
- **Jarvis agora é Eco** em toda a interface, no instalador (`Eco-Setup-<versão>.exe`, atalhos, `Eco.cmd`) e na documentação.
  O pacote Python interno continua `jarvis`. Instalações antigas: o instalador remove os atalhos e a entrada de inicialização
  do nome antigo; a pasta `Documents\Jarvis` e a chave de auditoria antigas continuam sendo usadas se existirem. O instalador
  usa a pasta `Eco` e **não** move uma instalação antiga: para levar memória e conversas, copie a pasta `data` da instalação antiga.
### Projeto
- Licença **MIT**; adicionados `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, modelos de issue e de Pull Request.
- Workflows de GitHub Actions: CI, release por tag em etapas separadas e publicação da página do produto (GitHub Pages).
### Corrigido (QA das telas)
- Busca das Configurações não funcionava ao digitar; interruptor só valia no primeiro clique; o aviso (toast) derrubava o app no
  segundo aviso; Esc na busca fechava as Configurações; janela passava da tela a 150% e 200% (Salvar/Descartar inacessíveis);
  etapa final do Assistente quebrava ao voltar; Ilha lateral grande passava da tela a 200%; painel Atualizações vinha vazio.
- Atualização: queda de download via `gh` dizia "repositório privado"; instalação falhava (código 901) quando o app abria de um
  PowerShell 7; "sem permissão de escrita" falso por trava passageira do antivírus. Quando falta permissão de escrita, o
  instalador agora pede a elevação pelo aviso do Windows (UAC) e relança o Eco sem privilégios.
- Relatório completo: `docs/` e a pasta de QA (5088/5088 verificações, 0 defeitos abertos nas telas atuais).

### Corrigido (janelas piscando ao abrir)
- **Configurações piscavam várias vezes:** (1) um console preto do `python.exe` aparecia por um instante (lançador do venv com `DETACHED_PROCESS`): as telas agora abrem por `pythonw.exe` com `CREATE_NO_WINDOW` (`win/spawn.py`); (2) cerca de 130 janelinhas soltas nasciam durante a montagem (widget sem pai com `setVisible(True)`): `ui/kit/visibility.py`; (3) a janela principal só fica visível depois da primeira pintura. Medido com EnumWindows a cada 15 ms: antes 201 janelas distintas, 67 visíveis e 1 console; depois 6 janelas, 1 visível, 0 console. Teste: `tests/test_no_flash.py`, `tests/ui/flash_probe.py`.

### Adicionado (Setup: preparar o computador, caminhos e verificação total)
- **Etapa «Preparar o computador»** no assistente: varredura total em lista (27 itens) com status, versão encontrada, onde foi achado (caminho personalizado, PATH, instalação padrão, pasta do Eco) e o que fazer; botões Resolver, Personalizar, Reparar e Salvar relatório (JSON e texto). Baixa o que falta dos modelos (SHA-256) e, com confirmação, instaladores oficiais (Visual C++, Ollama) com assinatura digital conferida antes de executar. Ollama opcional: detecta e sugere modelo pela memória de vídeo.
- **Caminhos personalizados** (`[toolpaths]` + Configurações > Caminhos dos programas): Git, Git Bash, PowerShell, Python, FFmpeg, Ollama, LM Studio, whisper.cpp e os 5 agentes ACP, além de modelos/pastas existentes. Procurar, Detectar automaticamente, Restaurar padrão e validação ao vivo (não é rede, existe, é a ferramenta certa por nome e `--version`, versão mínima, permissão de escrita; executável fora das pastas confiáveis e sem assinatura pede confirmação). Agentes ACP, Terminal (shells e PATH), escuta GPU, Setup e `doctor` passam a usá-los.
- `Eco.cmd doctor --full` (`--json`, `--out`): varredura total repetível. Veja `docs/SETUP.md`.

### Adicionado (Terminal integrado, desligado por padrão)
- **O Eco roda comandos de linha de comando** (git, npm, python, `dir`...) por voz ou texto: ferramentas `executar_comando`, `terminal_saida`, `terminal_cancelar`, `terminal_historico` (`tools/terminal_tools.py`), com PowerShell, cmd ou Git Bash, pasta atual lembrada entre comandos, saída em streaming, tempo limite e cancelamento. Cada comando é um processo filho do Eco num Job Object: parar derruba só o que ele iniciou, nunca processo alheio.
- **Segurança configurável** (grupo `Terminal` com 10 campos, página nova nas Configurações): `off` (padrão), `confirm`, `allowlist` e `free` (só liberado à mão no painel, por tempo; nunca por voz nem pela nuvem). Pasta de trabalho restrita (`terminal.roots`), bloqueio fixo (formatar, apagar o sistema, `reg delete`, desligar, matar processos, segredos, `iex`...), ambiente do filho sem segredos, saída redigida, confirmação com o comando exato, auditoria sem a saída. Nuvem: só com `brain.consent_terminal` e **sempre** pergunta com o nome do agente.
- **Painel Terminal** (`python -m jarvis terminal`, bandeja «Abrir o Terminal»): histórico, saída em tempo real, Parar, Copiar saída/comando, Limpar, comando à mão e botão para liberar o modo livre; conversa com o Eco por pedidos assinados. `ToolSpec.visible` (ferramenta que some conforme a config).
- Provas: 30 + 8 testes automáticos com comandos reais (git em repositório temporário, PowerShell, cmd, Git Bash, agente de exemplo da nuvem) e QA de UI (100–200% × claro/escuro, clique real do mouse). Veja `docs/TERMINAL.md`.

### Adicionado (Cérebro em nuvem via ACP, opcional)
- **`brain/acp`**: cliente ACP (Agent Client Protocol, JSON-RPC por stdio) em Python puro, sem interface: processo filho por stdio, tempo limite, cancelamento (`session/cancel`, e encerra o processo se o agente não responder), reinício automático. Agentes suportados: OpenCode, Google Antigravity, Claude Code, OpenAI Codex CLI e GitHub Copilot CLI (detecção de instalação e teste de login na tela). O agente usa o próprio login; o Eco não guarda senha nem token.
- **Cérebro selecionável** (`[brain]`): local (llama.cpp) é o padrão; nuvem é opt-in e cai sozinha para o local se falhar (`fallback_local`). Aviso na Ilha a cada uso e auditoria sem conteúdo (tamanho, hash curto, ferramentas, tempo).
- **Ferramentas do Eco como servidor MCP em loopback** (porta efêmera, token por sessão, só `127.0.0.1`): passam pelo mesmo `ToolRegistry`. Ação no PC pedida pela nuvem sempre pede confirmação forte com o nome do agente.
- **Privacidade**: só texto por padrão; tela, memória e arquivos só com consentimento por agente (`consent_screen|memory|files`); `fs/*` e `terminal/*` do cliente negados; `session/request_permission` ligado ao confirmador (ferramentas próprias do agente negadas por padrão).
- Grupo "Cérebro em nuvem" no schema (10 campos) e widget autocontido `ui/settings/cloud_brain_page.py`. Documentação em `docs/CEREBRO-NUVEM.md`; 33 testes (`tests/test_cloud_brain.py`) e prova ao vivo com o Antigravity (pedido real, ferramenta via MCP, confirmação negada). Não provado de ponta a ponta com OpenCode (sem login de provedor), Claude, Codex e Copilot.
- **Todos os agentes funcionais ou com plano B provado** (22/11): OpenCode (modelo gratuito do próprio OpenCode escolhido só no filho, sem tocar na config global), Antigravity e Claude Code funcionam ponta a ponta; Codex e Copilot estão logados mas com a cota da conta esgotada: o Eco detecta (conta/modelo/login/cota, sem repetir trechos do erro) e usa o modelo local. Causa do "Internal error" do Claude: o adaptador executava o atalho do npm (`spawn EFTYPE`); corrigido com `CLAUDE_CODE_EXECUTABLE` e ambiente do filho limpo de variáveis herdadas de outra sessão.
- **Ações no PC por agente** (`brain.action_modes`: negar / confirmar sempre / permissões normais) e **modelo por agente** (`brain.models`), no schema e na tela. Pasta de trabalho do agente movida para fora de qualquer repositório git (o Copilot indexava o repositório).
- **Tela**: painel `CloudBrainPanel` ligado à navegação, com **Testar** (pedido mínimo real), **Como entrar** (comando exato), situação por agente e consentimentos. Fluxo de voz medido: STT local 0,9–1,3 s, TTS local 0,1–0,3 s até o 1º áudio, nuvem 7–37 s. 43 testes, `tests/e2e_cloud_voice.py` e capturas em `capturas/ui-prints/config-v2/nuvem/`.
- Licença do projeto ainda pendente de definição.
### Configurações v2 (visual e menus)
- **Menus suspensos (os "colapsáveis" bugados):** a lista agora abre ABAIXO do campo, sem cobrir o valor, com largura que cabe o texto mais longo, linhas de 32 px, destaque ao passar o mouse/teclado, marca (✓) e negrito no item atual e sem a borda âmbar. Corrige os bugs de lista reproduzidos na janela real e em 100 %/150 %, escuro/claro (`capturas/ui-prints\config-v2\BUGS-ANTES.md`).
- **Seções em cartões** com fios entre as linhas, cabeçalho de página com ícone, barra Salvar/Descartar sempre visível (desabilitada sem alterações) e ajuda dos campos em várias linhas (nada some com reticências).
- **Grupos avançados recolhíveis** (animação de altura, setas, Enter/Espaço, estado lembrado por seção neste computador). Busca e erros abrem o grupo sozinhos e ele volta ao estado lembrado ao limpar a busca.
- **Busca com realce** do trecho achado (no rótulo e na ajuda) e contador de resultados por página na navegação.
- Páginas novas na navegação: **Cérebro em nuvem** e **Atualizações** (campos do schema + painel próprio quando o módulo existir); seção que estava sem texto (`llm_power`) corrigida.
- Preservado: schema, validação, travas, canal de controle, YOLO só manual, montagem sob demanda das páginas.

### Adicionado — atualização automática
- **Atualização automática profissional** (`docs/ATUALIZACAO.md`): verificação ao iniciar e a cada N horas (configurável/desligável), pop-up com notas e opções Baixar, Instalar automaticamente, Lembrar depois e Ignorar esta versão, download com retomada, SHA-256 obrigatório (várias fontes devem concordar; só HTTPS), instalação por cima (`/VERYSILENT /NORESTART`) com fechamento seguro e relançamento, canal estável/pré-lançamento, repositório privado por token somente-leitura no Cofre do Windows ou `gh`. Seção `[updates]` no schema e página «Atualizações». «Verificar atualizações…» da bandeja usa o fluxo completo.
- **Elevação automática (UAC):** instalação em Program Files / "para todos os usuários" não pede mais ação manual: «Instalar agora» abre o pedido do Windows (`runas`) e segue sozinho; o instalador é copiado para pasta só de administrador e o SHA-256 é conferido antes e depois da elevação. UAC recusado não fecha o Eco nem perde o download («Tentar de novo»). O Eco volta a abrir como usuário normal (não elevado, via explorer.exe). Pasta de desenvolvimento é recusada com explicação em português.

## [0.1.4] - 2026-11-22
### Corrigido
- **Pedido de permissão:** depois de responder na Ilha, o foco podia estar em outra janela e a ação era recusada de novo. Agora o Eco devolve o foco à janela que originou o pedido antes de tentar. Provado com clique real em «Sim» na Ilha: a liberação foi gravada e a ação rodou.
### Adicionado
- **Mouse e visão:** `mover_mouse` (passar o mouse por descrição), `arrastar` (de um item até outro, por descrição; o botão é sempre solto, mesmo em erro) e `localizar_na_tela` (diz onde está algo, sem tocar). Mesmas travas do clique: só dentro da janela em foco, nunca janelas do Eco, de senhas ou diálogos. Provado: mover (±1 px), arrastar selecionou texto no Bloco de Notas, ponto fora da janela é recusado. A precisão da localização por imagem não foi remedida nesta versão.

## [0.1.3] - 2026-11-22
### Corrigido
- **Ações recusadas por falta de permissão não apareciam na Ilha.** Agora toda recusa aparece na Ilha com o motivo, e as recusas por LISTA de permissão (digitar em outro programa, atalho não liberado) viram um **pedido de permissão**: a Ilha mostra «Permitir e lembrar?» com Sim/Não (também por voz ou atalho). Sim libera na hora e grava no config.toml; Não mantém a recusa. Programas bloqueados por segurança (terminais, gerenciadores de senha) nunca são oferecidos. No modo YOLO libera só para a sessão.

## [0.1.2] - 2026-11-22
### Corrigido
- **Parava de responder (ouvia e voltava ao repouso):** o áudio podia chegar sem sinal (microfone preso depois de a máquina travar). Agora o Eco detecta fala sem som, reabre o microfone sozinho depois de 2 ocorrências e avisa; o log registra o pico do áudio.
- **Calculadora e apps da Microsoft Store:** `abrir_app` agora coloca a janela em foco; `digitar_texto` e `apertar_atalho` aceitam o parâmetro `janela` (trazem o app para a frente antes) e a Calculadora entra nos destinos permitidos (`safety.typing_allowed_titles`). Provado: abrir, digitar `12+7=` e o visor mostra 19.
- **Configurações abriam várias janelas e demoravam:** abre em ~1 s (páginas montadas sob demanda), com trava de instância única entre processos e sem repetir o clique.
### Adicionado
- **Controle de janelas:** `janela_acao` (minimizar, maximizar, restaurar, metade esquerda/direita, centralizar) e `ver_tela` com `alvo="janela"` (olha só o app em foco).
- **Escuta aberta:** o Eco ouve sozinho, sem apertar tecla (`safety.listen_mode = open`, atalho `Ctrl+Alt+L`, botão na Ilha e item na bandeja).
- **Ícone na bandeja do sistema** com menu: Abrir Configurações, Ilha do Eco (tamanho, posição, fixar), Escuta contínua, Silenciar microfone, Verificar atualizações…, Sobre e Encerrar o Eco.
- **Verificador de atualizações** (consulta a última release publicada).
- **Ilha:** alfinete corrigido (fixada nunca some), transparência (vidro) ajustável e dock lateral vertical (direita/esquerda).

## [0.1.1] - 2026-11-22
### Corrigido
- **Assistente de instalação não encontrava modelos já existentes no PC.** Agora ele procura sozinho (nome e tamanho, depois confere o SHA-256) em pastas comuns, instalações anteriores, cache do Hugging Face, LM Studio e Ollama; botão «Procurar no computador inteiro» para varrer os discos. Os arquivos conferidos são ligados à instalação por link físico (sem ocupar espaço extra) ou copiados quando estão em outro disco. `Eco.cmd setup --scan [--deep] [--use-found]` faz o mesmo sem janela; `--fetch` também aproveita o que já existe antes de baixar.
- **Escolher pasta:** o assistente (botão «Escolher pasta...») e `Eco.cmd setup --scan --folder PASTA` examinam a pasta e subpastas, conferem o SHA-256 e mostram o que dá para usar, o que tem o mesmo tamanho mas conteúdo diferente e o que não está lá; só os arquivos válidos são trazidos.
- Botões da etapa de modelos reorganizados (rótulos não são mais cortados).

## [0.1.0] - 2026-11-22
Primeira versão. Desenvolvida entre 2026-11-19 e 2026-11-22 (33 commits).

### Adicionado
- **CPU × GPU por serviço (medido):** LLM, visão e escuta de comandos na GPU; voz Piper, detector de voz, captura de tela, Ilha e UI Automation na CPU. Escuta com whisper.cpp Vulkan (small): 0,98 s e 0,38 CPU-s por frase, WER 11,8% contra 18,4% do base na CPU. Chaves `llm.device`, `llm.mmproj_device`, `stt.device`, `tts.device` (`auto`/`gpu`/`cpu`); queda segura para a CPU com aviso; `Eco.cmd doctor` mostra onde cada serviço roda.
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
  "O que o Eco sabe de mim".
- **Interface:** tokens de tema e kit de componentes; Configurações (11 páginas), gravador de voz "Minha voz".
- **Ilha:** janela no topo da tela (3 tamanhos, estados, ondas, ícone vetorial), processo filho ligado ao núcleo por
  JSON nos pipes, botões Sim/Não, Mudo, Parar e Configurações, chip YOLO, esconde em tela cheia.
- **Distribuição:** instalador Inno Setup (pt-BR/en), runtime Python embutido com wheels travadas por hash,
  `installer/manifest.json` com SHA-256, baixador com retomada, pacote offline, assistente `Eco.cmd setup`.

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
