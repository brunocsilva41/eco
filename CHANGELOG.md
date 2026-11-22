# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]
- Licença do projeto ainda pendente de definição.

## [0.1.0] - 2026-11-22
Primeira versão. Desenvolvida entre 2026-11-19 e 2026-11-22 (33 commits).

### Adicionado
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
