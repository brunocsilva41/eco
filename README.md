# Jarvis local

Assistente de voz em português do Brasil, 100% local: ouve (faster-whisper, CPU), pensa (llama.cpp Vulkan na RX 580,
Qwen3-VL 4B), fala (Piper, CPU) e controla o PC por ferramentas permitidas.

## Como executar
```
F:\Jarvis\Jarvis.cmd doctor        confere o ambiente (rode primeiro)
F:\Jarvis\Jarvis.cmd               roda por voz (igual a "run")
F:\Jarvis\Jarvis.cmd run --text    também aceita comandos digitados (/sair encerra)
F:\Jarvis\Jarvis.cmd settings      tela de Configurações
F:\Jarvis\Jarvis.cmd record        gravador de voz ("Minha voz")
F:\Jarvis\Jarvis.cmd tools         lista as ferramentas (com o risco de cada uma)
F:\Jarvis\Jarvis.cmd config        mostra a configuração efetiva
```
O Jarvis sobe o `llama-server` sozinho (só em 127.0.0.1, com chave de API aleatória por execução) e o encerra ao sair.
Se a porta já tiver outro servidor de modelo, o Jarvis NÃO o usa: feche-o ou mude `llm.port`.
Pedido de reinício pelas Configurações: o `Jarvis.cmd` sobe o Jarvis de novo (código de saída 75).

## Como usar
- **Segure F9** e fale; solte para enviar (ou, em "Apertar e falar", aperte uma vez). Apertar F9 durante uma resposta interrompe o Jarvis.
- **Ctrl+Alt+F12**: PARA TUDO (ações, fala, mouse e teclado). Sem essa tecla registrada o Jarvis não inicia, e se ela deixar de funcionar o Jarvis para de agir no PC.
- **Ctrl+Alt+M**: liga/desliga o microfone.
- **Confirmações**: por voz diga "sim"/"não" (ações arriscadas exigem "confirmo" ou "autorizo"), ou Ctrl+Alt+Y / Ctrl+Alt+N, ou digite no modo `--text`. Sem resposta em 15 s = NÃO.
- Tudo é configurável pela tela de Configurações (`Jarvis.cmd settings`) ou em `F:\Jarvis\config.toml` (valores inválidos são recusados com a lista de erros).

## Segurança (resumo fiel ao código)
- O servidor do modelo só escuta em loopback e exige chave de API.
- Só as ferramentas registradas existem (sem shell livre). Cada ferramenta tem risco: leitura, controla o PC ou ARRISCADA.
  ARRISCADAS (fechar janela, editar/mover/apagar arquivo, esquecer/editar memória) sempre pedem confirmação mostrando o alvo real.
- `digitar_texto` só digita em programas da lista permitida (Bloco de Notas, Word...) e nunca em terminais, Explorer, Executar etc.;
  pede confirmação com o programa e o título reais e reconfere o foco durante a digitação. Não existe Enter embutido no texto.
- Atalhos de teclado só os da lista; Enter, Ctrl+S/V/X pedem confirmação; as teclas de segurança do Jarvis nunca podem ser liberadas ao agente.
- Depois de ler conteúdo de fora (tela, janelas, arquivos, memórias), TODA ação na mesma rodada passa a exigir confirmação.
- Arquivos: só dentro das pastas permitidas (padrão `Documentos\Jarvis`), sem links/junções, sem programas; apagar vai para a Lixeira; há "desfazer".
- Auditoria em `logs\audit.jsonl` (ações, confirmações e quem aprovou; texto digitado só como tamanho + hash).
- Memória e histórico em SQLite local (NÃO criptografado), recusam senhas/PINs/cartões/CPF; "modo sem histórico" nas Configurações.
- Nenhum segredo em código ou arquivos de configuração.

## Estrutura (`src\jarvis`)
| Módulo | Função |
|---|---|
| `config.py` | configuração tipada e validada (`config.toml`) |
| `settings/`, `ui/` | tela de Configurações, esquema por campo, gravação atômica; tema e janelas Qt |
| `recording/`, `ui/recorder_window.py` | gravador de voz ("Minha voz") e base para a palavra de ativação |
| `app.py` | orquestrador: estados, threads, atalhos, barge-in, emergência, recarga de config |
| `agent.py`, `context/` | laço LLM <-> ferramentas; orçamento de tokens e compactação de conversa |
| `memory/` | sessões e mensagens, memória de longo prazo (FTS5), busca de conversas, migrações |
| `llm/` | `server.py` (processo, Job Object, supervisão) e `client.py` (streaming, tool calling) |
| `audio/`, `voice.py` | microfone+VAD, reprodução, STT, TTS, fila de fala |
| `tools/`, `files/` | registro (allowlist/risco/confirmação/timeout/auditoria) e ferramentas |
| `win/`, `safety.py`, `doctor.py` | SendInput/janelas/atalhos/DPI; confirmação e emergência; diagnóstico |

## Estado
Código completo e auditado uma vez, mas **ainda não testado de ponta a ponta com voz real** (nenhum teste foi escrito/rodado
por decisão do Bruno; só `doctor`, compilação e importação). Pendências: testes de execução real, WER com as 20 frases do Bruno,
latência fim a fim, Ilha (interface), palavra de ativação, API/MCP, atualização do driver AMD.
Áudio: o Jarvis prefere as APIs MME (primeiro), WASAPI e DirectSound e só usa WDM-KS se for indicado por índice (ou se for a única existente, com aviso). O `doctor` mostra o estado real dos serviços de áudio (Service Control Manager) e as APIs disponíveis.
