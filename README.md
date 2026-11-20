# Jarvis local

Assistente de voz em português do Brasil, 100% local: ouve (faster-whisper, CPU), pensa (llama.cpp Vulkan na RX 580,
Qwen3-VL 4B), fala (Piper, CPU) e controla o PC por ferramentas permitidas.

## Como executar
```
F:\Jarvis\Jarvis.cmd doctor        confere o ambiente (rode primeiro)
F:\Jarvis\Jarvis.cmd               roda por voz (igual a "run")
F:\Jarvis\Jarvis.cmd run --text    também aceita comandos digitados (/sair encerra)
F:\Jarvis\Jarvis.cmd tools         lista o que o Jarvis pode fazer
F:\Jarvis\Jarvis.cmd config        mostra a configuração efetiva
```
O Jarvis sobe o `llama-server` sozinho (só em 127.0.0.1) e o encerra ao sair; se a porta já tiver um servidor saudável, reutiliza.

## Como usar
- **Segure F9** e fale; solte para enviar. Apertar F9 durante uma resposta interrompe o Jarvis.
- **Ctrl+Alt+F12**: PARA TUDO (ações, fala, mouse e teclado). Sem essa tecla registrada o Jarvis não inicia.
- **Ctrl+Alt+M**: liga/desliga o microfone.
- **Confirmações** (fechar janela etc.): diga "sim"/"não", ou Ctrl+Alt+Y / Ctrl+Alt+N, ou digite no modo `--text`. Sem resposta em 15 s = NÃO.
- Mudar teclas, microfone, modelo de voz etc.: `F:\Jarvis\config.toml` (valores inválidos são recusados com a lista de erros).

## Segurança (resumo)
Servidor só em loopback; só as ferramentas registradas existem (sem shell livre); apps só os da lista `[apps.launch]`;
atalhos só os da lista; ações arriscadas pedem confirmação; texto da tela/janelas é tratado como DADO NÃO CONFIÁVEL;
cada ação vai para `logs\audit.jsonl`; texto digitado não vai para o log; a memória recusa senhas/PINs. Nenhum segredo em código ou arquivos.

## Estrutura (`src\jarvis`)
| Módulo | Função |
|---|---|
| `config.py` | configuração tipada e validada (`config.toml`) |
| `app.py` | orquestrador: estados, threads, atalhos, barge-in, emergência |
| `agent.py` | laço LLM <-> ferramentas, limites de passos, anti-laço, imagens |
| `llm/` | `server.py` (processo llama-server, Job Object) e `client.py` (streaming, tool calling) |
| `audio/` | microfone+VAD, reprodução, STT, TTS, dispositivos, verificações |
| `tools/` | registro (allowlist/risco/confirmação/timeout/auditoria) e ferramentas |
| `win/` | SendInput, janelas, atalhos globais, teclas |
| `safety.py`, `memory.py`, `voice.py`, `doctor.py` | confirmação/emergência, SQLite, fila de fala, diagnóstico |

## Estado
Código completo, **ainda não testado de ponta a ponta com voz real** (só `doctor`, compilação e importação). Pendências: WER real com as 20 frases do
Bruno, medir a latência fim a fim, Ilha (interface), palavra de ativação, API/MCP, atualização do driver AMD. Ver `docs\medicoes*.md` e `PLANO.md`.
