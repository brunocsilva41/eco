# Projeto Jarvis local — Plano (2026-11-18)

## 1. Objetivo
Assistente local, leve, em português do Brasil: ouve a voz do Bruno, fala, vê a tela, abre apps e controla o PC.
Tudo roda na máquina dele, sem depender de nuvem para o uso normal.

## 2. Hardware real (lido da máquina)
- CPU: Intel Xeon E5-2650 v4, 12 núcleos / 24 threads (não é o 2640 v3 que o Bruno citou).
- RAM: 16 GB DDR4.
- GPU: AMD Radeon RX 580 **2048SP**, 8 GB. Driver 31.0.21924.61 (antigo; atualizar o Adrenalin antes de medir).
- SO: Windows 10 Pro 19045. Disco F: com ~46 GB livres. Pasta do projeto: `F:\Jarvis`.
- OpenVINO NÃO serve: é da Intel e só vimos suporte a GPU Intel. Caminho da GPU AMD = **llama.cpp com Vulkan**.
- ROCm no Windows para Polaris: não usar.

## 3. Orçamento de recursos (regra de ouro)
- VRAM 8 GB: um único modelo de linguagem+visão carregado (~3–4 GB com contexto), deixando folga para o Windows e a tela.
- RAM 16 GB: Windows ~4 GB + Python + Whisper na CPU. Não carregar dois modelos grandes ao mesmo tempo.
- Whisper e Piper rodam na **CPU** (12 núcleos sobram). Motivo: relato de que Whisper em Vulkan no Windows com Polaris é lento por causa do driver AMD (307 s contra 23 s no Linux, fonte única, a confirmar medindo).
- Benchmarks de RX 580 achados são relatos de usuários (3–4B Q4–Q6: ~20–40 tok/s; 8B Q4: ~7–15 tok/s). Medir na máquina antes de decidir.

## 4. Arquitetura
Um serviço Python orquestrador (máquina de estados) + `llama-server` separado, só em 127.0.0.1.

```
Microfone -> VAD (Silero) -> [palavra de ativação ou tecla] -> STT (faster-whisper, CPU, int8)
   -> Orquestrador/Agente (llama-server, Qwen3-VL 4B GGUF, tool calling)
        -> Ferramentas: apps, janelas, UI Automation, mouse/teclado, screenshot, arquivos, web
   -> TTS (Piper pt_BR) -> alto-falante
Estados: IDLE -> LISTENING -> TRANSCRIBING -> THINKING/ACTING -> SPEAKING -> IDLE
Barge-in: VAD durante SPEAKING volta para LISTENING (só com fone ou cancelamento de eco).
```

## 5. Escolha por função (profissional, com alternativa)
| Função | Primária | Alternativa | Observação |
|---|---|---|---|
| Servidor de modelo | llama.cpp `llama-server`, build Windows Vulkan x64 (release oficial) | LM Studio / Ollama (mais fáceis, menos controle) | API compatível com OpenAI em localhost |
| Cérebro + visão | Qwen3-VL 4B Instruct, GGUF Q4_K_M + `--mmproj` | Gemma 3 4B (também tem visão); Qwen3 4B só texto + VL separado se faltar qualidade | Um modelo só economiza VRAM. Medir tok/s e qualidade de tool calling em pt-BR |
| Escuta (STT) | faster-whisper, modelo small ou medium, int8, CPU | whisper.cpp Vulkan (testar); distil-whisper | Testar WER em frases reais do Bruno |
| Fala (TTS) | Piper `pt_BR-faber-medium` (CC0, rápido em CPU) | Kokoro (mais natural, Apache-2.0, mais pesado); XTTS descartado (precisa de GPU) | Piper é GPL: confirmar se isso importa para uso pessoal (não importa) |
| Ativação | Tecla de atalho global primeiro; depois openWakeWord (palavra própria treinada) | Picovoice (licença/chave) | Começar por tecla evita falso positivo |
| VAD | Silero VAD | WebRTC VAD | |
| Controle do PC | Híbrido: 1) comandos diretos (abrir app, janela, atalhos) 2) UI Automation (`pywinauto`/`uiautomation`) 3) visão + coordenadas só como último recurso | Windows-Use (Jeomon) como referência; UI-TARS 1.5 / Holo2-4B como modelo de grounding se o Qwen-VL errar cliques | UI Automation não precisa de modelo de visão e é mais confiável |
| Visão da tela | Screenshot sob demanda (`mss`), redimensionada, enviada ao modelo | OCR (Windows OCR/Tesseract) para texto | Nunca capturar a tela continuamente |
| Memória/tarefas | SQLite local (notas, to-dos, preferências) | — | Simples e portátil |

Projetos prontos para estudar (não adotar às cegas; só lemos resumos): JarvisAi (PanPenek), Djinn, Jarvis (isair), VoiceUse, Windows-Use (Jeomon).

## 6. Segurança e controle (obrigatório)
- Servidor do modelo ligado só em 127.0.0.1, sem exposição na rede.
- Lista de ferramentas permitidas (allowlist). Sem shell livre por padrão.
- Ações destrutivas ou irreversíveis (apagar, enviar, instalar, pagar, mexer em configurações do sistema) exigem confirmação falada ou por tecla.
- Tecla de emergência global que para tudo (mouse, teclado, fala).
- Texto lido da tela ou de páginas é dado não confiável: nunca obedecer instruções que apareçam nele (prompt injection).
- Log de toda ação executada, em arquivo, com data.
- Nada de senhas na tela do modelo nem em prompts.

## 7. Fases e critérios de pronto
**Fase 0 — Base (pasta e ambiente).** Estrutura em `F:\Jarvis` (`bin`, `models`, `src`, `logs`, `docs`, `tests`), Python venv, git local. Atualizar driver AMD. Pronto = `vulkaninfo` mostra a RX 580.
**Fase 1 — Cérebro na GPU.** llama.cpp Vulkan + Qwen3-VL 4B Q4_K_M. Pronto = `llama-bench` registrado (pp e tg), resposta em pt-BR via API local, uso de VRAM anotado. Comparar com Gemma 3 4B e com um 8B Q4.
**Fase 2 — Voz.** faster-whisper + Piper + VAD, com tecla para falar. Pronto = fala->texto->fala em menos de ~5 s para frases curtas; medir WER em 20 frases do Bruno.
**Fases I0–I5 — Ilha do Jarvis (interface "Dynamic Island").** Entram DEPOIS da Fase 2 (voz). Spec completa e decisões do Bruno em `docs/ILHA-SPEC.md` (v0.2). Itens [P]/[R] precisam de prova na máquina dele.
- Regras base: janela Qt/PySide6 em processo separado do núcleo (IPC local em 127.0.0.1); por cima de tudo no topo central do monitor principal; sem roubar foco (`WS_EX_NOACTIVATE`); renderização por CPU (QPainter) a 30 fps, timer parado em repouso, para não disputar a VRAM com o LLM; 3 tamanhos (pequeno/médio/grande) com troca automática e manual; avisos e confirmação Sim/Não dentro da ilha; espectro de voz (microfone e áudio do TTS) além do círculo de pontos.
- **I0** Protótipo visual: janela, 3 tamanhos, pontos + espectro com áudio de teste, tokens de design. Pronto = vídeo/capturas por tamanho e estado + CPU/RAM medidos (meta: <2% em repouso, <8% ativa).
  - **I0 FEITA (2026-11-22; commits 89b5776 e seguinte), aguardando revisão visual do Bruno.** Pacote `src/jarvis/ui/island/` (window, tokens, waves, micicon, dsp, bridge, winapi, demo, strings); `Jarvis.cmd island-demo [--capture PASTA | --measure S | --seconds N | --reduce-motion]`. Colada ao topo central do monitor principal (só os cantos de baixo redondos), sem moldura, sempre no topo, sem foco (WS_EX_NOACTIVATE + Tool + DoesNotAcceptFocus); a janela tem o tamanho exato da pílula, então fora dela o clique passa. Crescer/encolher 260 ms (mola leve ao crescer, ease-out ao encolher; instantâneo com 'reduzir movimento'). Esconde com app em tela cheia (decisão do Bruno). Eventos do `EventBus` ligados pela `bridge.py` (contrato pronto; o demo já usa o EventBus real com eventos falsos; ligação ao processo real = I1).
  - Cor de destaque: âmbar do tema; troca em UMA constante (`ACCENT_ATTR`/`ACCENT_OVERRIDE`, `ui/island/tokens.py`). F9 só como constante (`HOTKEY`); registro global = I3. Cantos grandes são exceção pedida pelo Bruno ao DESIGN.md.
  - Layouts (px lógicos, grade de 4; detalhe em `tokens.py` e `docs/ILHA-SPEC.md` v0.3):

    | Tamanho | Medida | Conteúdo |
    |---|---|---|
    | Compacta (repouso) | 208x36 | mic 20, rótulo do estado em texto, cronômetro só em ACTING, 6 barras, ponto de status |
    | Média (conversa) | 380x64 | mic 24, rótulo ('Executando: ...'), cronômetro, última frase truncada, 14 barras ao vivo |
    | Grande (expandida) | 520x200 | cabeçalho (estado, chips Equilíbrio/Mudo/YOLO com contagem, cronômetro), espectro de 49 barras, fala e resposta (3 linhas, rolagem), ação atual (ferramenta, alvo, ok/erro/negado), uso do contexto, botões Sim/Não, Parar, Mudo, Configurações |

  - Ícone de microfone próprio (QPainterPath, traço 2 px, 4 estados: repouso, ouvindo com anel, mudo, erro) e ondas (barras simétricas, ataque 15 ms, queda 75 ms, respiração em silêncio, gradiente sutil, 60 fps só em ouvir/falar). Para falar usa a energia real da saída (`tts_rms`/evento `level`); no demo, áudio sintético.
  - Custo medido por quadro (tick + pintura, offscreen, camada estática em cache): compacta 0,7 ms; média 0,6 a 1,2 ms; grande 1,0 ms. A 60 fps em voz = 6 a 7% de 1 núcleo (0,3% da máquina de 24 núcleos); estados sem voz rodam a 30 fps (~2 a 3%); repouso sem timer de pintura. A medição por CPU total do processo ficou inflada porque a máquina estava a ~95% de carga por outros processos: ver STATUS.

- **I1 FEITA no código (2026-11-22; commit 47b514f); FALTA a prova com o modelo real (máquina estava com ffmpeg).** A Ilha roda como PROCESSO FILHO lançado pelo `app.py` na partida (`ui.island_enabled`, padrão true; `python -I -X utf8 -c ... island --child`), conversando por JSON-lines nos pipes stdin/stdout (sem rede, sem soquete). `ui/island/link.py` (lado do núcleo, sem Qt): fila limitada de 200 (descarta níveis antigos primeiro), gravador de pipe em thread própria (nunca bloqueia o núcleo), reinício automático com espera 1/2/4/8/15 s e no máximo 5 quedas seguidas, textos truncados e mascarados (senha/token/pin; digitar_texto, memória e arquivos só mostram o nome da ferramenta). `ui/island/child.py` (filho): EventBus local + `IslandBridge` de sempre; encerra sozinho quando o stdin fecha. Núcleo->Ilha: state, transcript (voz e texto digitado), reply_text, action_step, confirm_request/done, context_usage, yolo (com segundos restantes), mute, emergency, error, mode e `level` a 30 Hz (RMS do microfone ouvindo; RMS REAL do alto-falante falando). Ilha->núcleo: Sim/Não (`confirmer.answer(..., via='island')`), Mudo, Parar (mesma rota `EmergencyStop` da tecla), Configurações (publica `open_settings`, 3 s de intervalo). YOLO aparece nos 3 tamanhos (chip vermelho 'YOLO' na compacta e na média; 'YOLO mm:ss' na grande). Tela cheia com histerese (esconde após 2 leituras de 700 ms, volta após 3). F9 continua só no núcleo.
  - Desvio: o campo é `ui.island_enabled` (plano, 2 níveis como o resto do schema), não `ui.island.enabled`. Aparece em Configurações > Funcionamento > Ilha do Jarvis.
  - Medido (máquina NÃO livre, ~30% por produção de vídeo): filho ~91 MB RSS (3 processos, inclui o lançador do venv); CPU 0% em repouso, ~3,6% de 1 núcleo pensando, ~7% de 1 núcleo falando.
- **I2** Avisos de ação e confirmação Sim/Não por clique e por voz (timeout = NÃO).
- **I3** Gatilhos personalizáveis: palavra de ativação "Jarvis" (openWakeWord; gravar amostras reais), combinação de teclas (`RegisterHotKey`), API local com token; clique.
- **I4** Modo integrada (AppBar), multi-monitor, configurações, inicialização com o Windows, instalador.
- **I5** Profissionalização: config tipada, logs e auditoria, `doctor`, testes, watchdog.
- Espectro de voz (v0.2-A): barras/anel de 24–32 bandas reagindo ao microfone e ao ÁUDIO de saída do TTS (não ao texto), DSP separado do desenho; pontos = pensando, espectro = voz.
- Gatilhos OBRIGATÓRIOS e personalizáveis (v0.2-B): (1) palavra de ativação treinável (openWakeWord + amostras reais do Bruno); (2) combinação de teclas via `RegisterHotKey`, validando conflito (modos: segurar para falar, alternar, abrir ilha); (3) API local em 127.0.0.1 (REST + WebSocket, token Bearer, `/health` sem token) + servidor MCP com credencial própria; toda chamada passa pela mesma allowlist e confirmações e registra a origem. Config única versionada (`config.toml`).
- Design (v0.2-C): tokens de design em um único arquivo (cor, raio, grade de 8 px, movimento 120/220/360 ms), preto fosco, 1 cor de destaque, cores por estado, animação interrompível, respeitar "reduzir movimento" do Windows, cor nunca como única informação, DPI 100–200%. Revisão visual do Bruno antes de avançar de fase.
- Profissionalizar/melhorar/incluir (v0.2-D, detalhe no spec): config tipada, logs + auditoria, permissões por nível (0 ler, 1 controlar, 2 arriscado), testes, `doctor`, instalador + watchdog, governador de recursos (pausar animação/descarregar modelo), perfis, plugins com manifesto, memória SQLite, modo não perturbar, privacidade (indicador de microfone/tela).
- A PESQUISAR antes de implementar (sem fonte ainda): como o openWakeWord verifica falso positivo (ver repositório oficial); identificação de voz do dono; páginas da Apple (HIG/Live Activities) e da Microsoft (Fluent) para o design; exemplo Python/ctypes de AppBar (`APPBARDATA`); comportamento com jogos/tela cheia exclusiva; tempo de treino do openWakeWord na RX 580 ou CPU.
- Perguntas pendentes para o Bruno (ILHA-SPEC seção 7): (1) atalho e "ação/evento" como gatilho entram já na v1 ou depois? (2) cor de destaque: ciano ou outra? (3) qual atalho? voz do Jarvis masculina ou feminina? (4) mostrar a ilha com app em tela cheia aberto?
**Fase 3 — Ferramentas do PC.** Abrir/fechar apps, focar janelas, digitar, atalhos, UI Automation. Pronto = 10 tarefas de teste passam 9/10.
**Fase 4 — Visão.** Screenshot sob demanda e "o que tem na tela?"; cliques por visão só como fallback. Pronto = descreve a tela e acha 1 botão por pedido em 8/10 testes.
**Fase 5 — Agente completo.** Máquina de estados, confirmações, tecla de emergência, logs, memória SQLite. Pronto = fluxo completo por voz sem travar por 30 min.
**Fase 6 — Conforto.** Palavra de ativação (openWakeWord), barge-in, inicialização com o Windows, ícone na bandeja.
**Fase 7 — Distribuição (instalador e primeira execução).** Detalhe em `docs/INSTALADOR.md`. Entregas: (a) instalador Inno Setup 6 (`installer\Jarvis.iss`, pt-BR e en, sem admin por padrão, componentes, atualização por cima, desinstalador que pergunta antes de apagar dados, log, assinatura opcional por `JARVIS_SIGN_CMD`); (b) runtime = Python embeddable 3.14.3 + wheels travadas por hash, montado no build (venv não é relocável); (c) modelos FORA do .exe, `installer\manifest.json` (URLs oficiais fixadas por commit, SHA-256, licença), baixador com Range/SHA-256/espelhos e pacote offline; (d) `Jarvis.cmd setup` (Qt, mesma identidade da Ilha/Configurações): requisitos, modelos, microfone e som, teste de voz, calibragem do VAD, atalhos, permissões (YOLO só explicado), doctor, "Tudo pronto"; reabre como Reparar/Reconfigurar; (e) `installer\build.ps1` reproduzível (VERSION único, staging sem work/logs/data/models/venv/.git, ISCC, hash SHA-256 e notas). Pronto = instalar em pasta de teste em modo silencioso, `Jarvis.cmd doctor` 21/21 sem Python do sistema, telas capturadas, desinstalar sem sobra. Pendências: Windows limpo e outras GPUs, instalação por máquina (admin), assinatura de código, texto de licença do Jarvis (marcador em LICENSE.*.txt), piper-tts é GPL-3.0 (revisar antes de distribuir).

## 8. Riscos e pontos em aberto
- Qualidade de tool calling de modelo 4B em pt-BR pode ser fraca: medir cedo; plano B = modelo 8B Q4 (mais lento) ou ferramentas por comando fixo.
- Whisper em pt-BR: precisão não medida; escolher small x medium por teste.
- Driver AMD antigo pode limitar o Vulkan: atualizar e medir.
- Barge-in sem fone causa eco (o assistente se ouve): usar fone ou cancelamento de eco.
- Versão exata mais recente do llama.cpp e dos GGUF: conferir nas páginas oficiais na hora de baixar.
- Fontes eram em grande parte blogs e READMEs: não confiar sem teste local.

## 9. Fontes principais
llama.cpp (GitHub), discussão de benchmark RX 580 (ggml-org/llama.cpp #23109), guia RX 580 Vulkan (aivisionslab), Qwen3-VL GGUF (Hugging Face), Windows-Use (Jeomon), UI-TARS, Holo2-4B, Piper pt_BR faber, openWakeWord, whisper.cpp Vulkan Windows (DomoticX).

## Estado em 2026-11-22
- Núcleo auditado 2×; primeira execução real do `run --text` feita (bugs de partida, cache de prompt e alucinação de hora/janela corrigidos; atalho direto para hora/janela).
- UI: LevelMeter corrigido; itens baixos da Auditoria-2 (N-17, N-19, clique por coordenadas verificado) tratados.
- (b) feito: ctx 12288 (prompt fixo 34%, VRAM ~5,8 GB). Próximo:  Ilha I0-I5 com o OK do Bruno; WER real após `Jarvis.cmd record`. Detalhes em Shared\jarvis\STATUS.md.
- 2026-11-22: fala 0,9x + normalizador pt-BR; visão e mouse (clicar_em com votação, rolar_tela); Ilha I0 pronta, I1 (ao vivo) em andamento.
