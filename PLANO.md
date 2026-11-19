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
- **I0** Protótipo visual: janela, 3 tamanhos, pontos + espectro com áudio de teste, tokens de design. Pronto = vídeo/capturas por tamanho e estado + CPU/RAM medidos (meta: <2% em repouso, <8% ativa; a medir).
- **I1** Ligar ao núcleo por IPC: estados reais e transcrição.
- **I2** Avisos de ação e confirmação Sim/Não por clique e por voz (timeout = NÃO).
- **I3** Gatilhos personalizáveis: palavra de ativação "Jarvis" (openWakeWord; gravar amostras reais), combinação de teclas (`RegisterHotKey`), API local com token; clique.
- **I4** Modo integrada (AppBar), multi-monitor, configurações, inicialização com o Windows, instalador.
- **I5** Profissionalização: config tipada, logs e auditoria, `doctor`, testes, watchdog.
- Perguntas pendentes para o Bruno (ILHA-SPEC seção 7): (1) atalho e "ação/evento" como gatilho entram já na v1 ou depois? (2) cor de destaque: ciano ou outra? (3) qual atalho? voz do Jarvis masculina ou feminina? (4) mostrar a ilha com app em tela cheia aberto?
**Fase 3 — Ferramentas do PC.** Abrir/fechar apps, focar janelas, digitar, atalhos, UI Automation. Pronto = 10 tarefas de teste passam 9/10.
**Fase 4 — Visão.** Screenshot sob demanda e "o que tem na tela?"; cliques por visão só como fallback. Pronto = descreve a tela e acha 1 botão por pedido em 8/10 testes.
**Fase 5 — Agente completo.** Máquina de estados, confirmações, tecla de emergência, logs, memória SQLite. Pronto = fluxo completo por voz sem travar por 30 min.
**Fase 6 — Conforto.** Palavra de ativação (openWakeWord), barge-in, inicialização com o Windows, ícone na bandeja.

## 8. Riscos e pontos em aberto
- Qualidade de tool calling de modelo 4B em pt-BR pode ser fraca: medir cedo; plano B = modelo 8B Q4 (mais lento) ou ferramentas por comando fixo.
- Whisper em pt-BR: precisão não medida; escolher small x medium por teste.
- Driver AMD antigo pode limitar o Vulkan: atualizar e medir.
- Barge-in sem fone causa eco (o assistente se ouve): usar fone ou cancelamento de eco.
- Versão exata mais recente do llama.cpp e dos GGUF: conferir nas páginas oficiais na hora de baixar.
- Fontes eram em grande parte blogs e READMEs: não confiar sem teste local.

## 9. Fontes principais
llama.cpp (GitHub), discussão de benchmark RX 580 (ggml-org/llama.cpp #23109), guia RX 580 Vulkan (aivisionslab), Qwen3-VL GGUF (Hugging Face), Windows-Use (Jeomon), UI-TARS, Holo2-4B, Piper pt_BR faber, openWakeWord, whisper.cpp Vulkan Windows (DomoticX).
