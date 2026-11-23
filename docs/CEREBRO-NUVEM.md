# Cérebro em nuvem via ACP (opcional)

O Eco pensa **no seu PC** (llama.cpp Vulkan na RX 580) e continua assim por padrão. Quem quiser pode, **por escolha própria**, deixar um agente na nuvem (OpenCode, Antigravity, Claude Code, Codex, Copilot) responder pelo protocolo **ACP**. O agente usa o **próprio login** (assinatura) do usuário: o Eco nunca vê nem guarda senha, token ou chave.

> Por que ACP e não a API direta: o login por assinatura (Claude, ChatGPT, Copilot) não pode ser reaproveitado em chamadas diretas de API. O ACP resolve porque quem fala com o provedor é o próprio agente, já logado.

## 1. O protocolo em 1 minuto (v1, conferido na documentação oficial)

JSON-RPC 2.0, **uma mensagem JSON por linha** no stdin/stdout de um processo filho.

| Passo | Direção | Mensagem |
|---|---|---|
| 1 | cliente → agente | `initialize` `{protocolVersion:1, clientCapabilities, clientInfo}` → `{agentCapabilities, authMethods, agentInfo}` |
| 2 | cliente → agente | `authenticate {methodId}` (só se o agente exigir e o método não for de terminal) |
| 3 | cliente → agente | `session/new {cwd (absoluto), mcpServers[]}` → `{sessionId}` |
| 4 | cliente → agente | `session/prompt {sessionId, prompt:[{type:"text",text}]}` |
| 5 | agente → cliente | `session/update` (notificação): `agent_message_chunk`, `tool_call`, `tool_call_update`, `plan`… |
| 6 | agente → cliente | `session/request_permission {toolCall, options[]}` → `{outcome:{outcome:"selected",optionId}}` ou `cancelled` |
| 7 | agente → cliente | `fs/read_text_file`, `fs/write_text_file`, `terminal/*` (só se o cliente anunciou) |
| 8 | agente → cliente | resposta de `session/prompt` com `stopReason` (`end_turn`, `max_tokens`, `refusal`, `cancelled`…) |
| — | cliente → agente | `session/cancel` (notificação): o agente deve responder o prompt com `stopReason:"cancelled"` |

Erro `-32000` = "autenticação necessária". `mcpServers` aceita `stdio` (`command/args/env`) e, se `mcpCapabilities.http`, `http` (`url/headers`). SDKs oficiais existem para Python, TypeScript, Rust, Kotlin; o Eco usa um **cliente próprio em Python puro** (~400 linhas, sem dependências) para não depender de pacote externo no instalador.

## 2. Como o OpenBot usa ACP nesta máquina (investigado sem ler segredos)

- O OpenBot (`%APPDATA%\OpenBot`) guarda **runtimes próprios** de cada provedor em `provider-runtimes\{antigravity,claude,codex,copilot,opencode,bun}\win32-x64` e, **por conta**, pastas isoladas em `provider-accounts\<id>\…` (por ex. `antigravity-acp\log\acp-server-*.log`, confirmando que o Antigravity roda por ACP). Cada conta tem a sua configuração e o seu login, separados dos CLIs globais.
- O Eco **não reaproveita** essas pastas nem o login do OpenBot: usa os CLIs **globais** instalados e logados pelo usuário (`opencode`, `agy`, `claude`, `codex`, `copilot`). Nenhum arquivo de credencial foi lido (só a **existência** de arquivos como indício, e só para o rótulo "login provável").

## 3. Matriz por agente (22/11/2026, medida neste PC; pedido real por texto e fluxo de voz STT→agente→TTS)

| Agente | Comando | Estado real | Login | Latência medida (nuvem) | Limitações / o que falta |
|---|---|---|---|---|---|
| **OpenCode** 2.2.5 | `opencode acp` | **funciona** (ponta a ponta, ação confirmada) | Sem login de provedor: o modelo padrão (`openrouter/...`) falha por crédito/auth. O Eco troca, **só no processo filho**, para um modelo gratuito do próprio OpenCode (`opencode/big-pickle`, `*-free`) e lembra a escolha (`data\cloud_models.json`). A config global do OpenCode **não é tocada**. | início 4 s · pedido 7–8 s | O modelo gratuito é fraco (na prova, a pergunta da hora chamou `hora_atual` mas a fala não citou a hora). Para um modelo melhor: `opencode auth login` e fixe o modelo em «Modelo por agente». `session/new` falha ~30% das vezes: 3 tentativas automáticas. |
| **Google Antigravity** 1.5.9 | `agy acp` | **funciona** (ponta a ponta, ação confirmada e negada) | logado (global do `agy`) | início 14 s a frio · pedido 11–15 s (até 37 s) | O mais lento; modelo `gemini-3.8-flash-high`. |
| **Claude Code** 2.1.325 | `npx -y @agentclientprotocol/claude-agent-acp` | **funciona** (ponta a ponta, ação confirmada) | logado | início 12 s · 1º pedido 68 s (frio) e depois 7 s; modelo `haiku` (o padrão `opus` levou 34 s num pedido mínimo) | **Causa real do "Internal error"**: o adaptador executava o atalho do npm e falhava com `spawn EFTYPE`. Corrigido apontando `CLAUDE_CODE_EXECUTABLE` para o `claude.exe` e removendo variáveis herdadas de uma sessão-pai (`CLAUDECODE`, `CLAUDE_CODE_*`, `CLAUDE_AGENT_SDK_*`). |
| **OpenAI Codex CLI** 0.163.0 | `npx -y @agentclientprotocol/codex-acp` | **instalado e logado, mas a conta está SEM COTA** (*usage limit*, volta em 27/11/2026). O Eco detecta e usa o plano B local | logado (ChatGPT) | 10–45 s até detectar a falha | Só o usuário resolve (esperar a renovação ou trocar de plano). O primeiro erro (modelo `gpt-6-sol` não suportado com conta ChatGPT) também é detectado e tenta `gpt-6-luna[low]`, `gpt-5.6-luna[low]`, `gpt-5.6-terra[low]`. |
| **GitHub Copilot CLI** 1.0.114 | `copilot --acp` | **instalado e logado, mas a conta está SEM COTA** (*monthly quota exceeded*). Plano B local | logado | 5–19 s até detectar | Só o usuário resolve (cota mensal). Achado de privacidade: com o diretório de trabalho dentro do repositório git, o Copilot **enfileirou a indexação remota do repositório**; por isso a pasta de trabalho agora é `%LOCALAPPDATA%\Eco\cloud_cwd`, fora de qualquer repositório. |

Etapas locais medidas (CPU, sem GPU): Piper gera a fala de entrada em 0,1 s; **faster-whisper (STT) 0,9–1,3 s** por frase curta (carga dos modelos 16 s, uma vez); **Piper (TTS) 0,11–0,28 s até o primeiro áudio**. Quase toda a latência é do agente na nuvem.

Detecção de login por agente: a tela mostra "instalado · login provável/não encontrado/não verificado" (só a EXISTÊNCIA de arquivo, nunca o conteúdo) e o botão **Testar** faz um pedido mínimo real e responde: *pronto*, *sem login* (com «Como entrar»), *sem cota*, *modelo indisponível* ou *não respondeu*.

### Comando que SÓ o usuário pode rodar (login interativo/OAuth; o Eco nunca faz login por ninguém)
| Agente | Situação | Comando |
|---|---|---|
| OpenCode | funciona com modelo gratuito; opcional para um modelo melhor | `opencode auth login` |
| Antigravity | já logado | (nenhum) |
| Claude Code | já logado | (nenhum) |
| Codex | logado, sem cota até 27/11 | nenhum comando resolve (esperar ou trocar de plano); outra conta: `codex login` |
| Copilot | logado, sem cota no mês | nenhum comando resolve; outra conta: `copilot` e digitar `/login` |

## 4. Arquitetura (`src/jarvis/brain/acp/`)

```
Agent.handle ──(brain.kind="cloud")──> CloudBrain.ask ──ACP/stdio──> processo do agente
      ▲  falha / sem login / tempo                        │ session/request_permission
      └── fallback automático ao modelo local              ▼
                                         policy.decide_permission ──> ConfirmationBroker (Ilha/voz/tecla)
                       agente ──MCP http(127.0.0.1, token)──> LoopbackMcpServer ──> ToolRegistry.execute (mesmas travas)
```

- `client.py` — `AcpClient`: processo filho por stdio, leitor em thread, pedidos com tempo limite, `session/cancel` + encerramento do **nosso** PID (árvore via `taskkill /T`) se o agente não responder em 5 s. `fs/*` e `terminal/*` **não são anunciados** e, se pedidos, recebem erro `-32601`.
- `agents.py` — catálogo, `command_for`, `detect_all`, `probe`.
- `cloud.py` — `CloudBrain`: inicia/reinicia o agente sob demanda (OpenCode: até 3 tentativas no `session/new`, falha intermitente medida de ~30%), prompt só de texto, aviso na Ilha, auditoria, `CloudUnavailable` para o fallback.
- `mcp_server.py` — MCP "Streamable HTTP" mínimo (POST JSON) só em `127.0.0.1`, porta efêmera, `Authorization: Bearer` aleatório por sessão, recusa `Host`/`Origin` não loopback, sem log de acesso. `mcp_stdio_bridge.py` serve agentes que só falam MCP por stdio (ponte para o servidor loopback; recusa URL fora de loopback).
- `policy.py` — privacidade e permissões (abaixo).
- Integração: `Agent.set_cloud` + `Agent._handle_cloud` (agent.py), `CloudBrain` criado em `app._build` (nada inicia até `brain.kind = "cloud"`), `ToolRegistry.execute(..., cloud_label=)`.

## 4b. Fluxo de voz (ordem do usuário)
1. **Captura e transcrição locais** (microfone → VAD → faster-whisper). Nenhum áudio sai do PC.
2. Só o **texto** da transcrição vai ao *provider*: o agente na nuvem (ACP) **ou** o llama.cpp local (padrão e plano B).
3. Com a resposta, a **síntese é local** (Piper) e o Eco fala. Prova: `tests\e2e_cloud_voice.py <agente>` (áudio de entrada gerado pelo Piper; a captura por microfone real não entra nesse teste).

## 5. Segurança e privacidade

1. **Padrão = local.** Nuvem só com `brain.kind = "cloud"`, escolhido na tela. Voz/transcrição continuam locais; só o **texto do pedido** vai ao agente.
2. **Só texto por padrão.** Ver tela (`ver_tela`, `localizar_na_tela`, `listar_controles`, `listar_janelas`, `janela_ativa`), memória/conversas e arquivos exigem **consentimento por agente** (`brain.consent_screen|memory|files`). Sem consentimento a ferramenta **nem aparece** na lista MCP e uma chamada direta é recusada. Imagem de tela só segue com consentimento de tela. `lembrar`, `esquecer` e `editar_memoria` **nunca** são oferecidas à nuvem.
3. **Ações no PC por agente (`brain.action_modes`)**: `deny` (o agente só recebe consultas; qualquer ação é recusada e nem aparece na lista MCP), `confirm` (padrão: toda ação pede confirmação forte com o nome do agente) ou `normal` (vale o Modo de permissões do Eco; ações nocivas ainda confirmam; a rodada segue marcada como vinda de fora).
3b. **Mesmas travas.** Toda ferramenta passa por `ToolRegistry.execute`: allowlist, validação de argumentos, pastas protegidas, teclas de segurança, terminais bloqueados. Ação que **age no PC** (CONTROL/RISKY) pede **confirmação forte** na Ilha/voz/tecla com o nome do agente ("O agente X, na nuvem, quer: …"); consultas READ são livres. A rodada é marcada como contaminada (`tainted`). YOLO continua só manual.
4. **fs/terminal do cliente: negados** (não anunciados; pedidos recebem erro).
5. **`session/request_permission` → confirmador do Eco.** Ferramentas do Eco (`jarvis_<ferramenta>`) → `allow_once` (o registro confirma de verdade). Ferramentas **próprias** do agente (shell, editar arquivos, web): **negadas** por padrão; com `brain.builtin_tools = "ask"` viram confirmação forte. Nunca `allow_always`. Limite conhecido: o título vem do agente; ele só serve para não perguntar duas vezes, a trava real é o registro.
6. **Pasta de trabalho vazia** (`data\cloud_cwd`) e, no OpenCode, `OPENCODE_CONFIG_CONTENT` negando bash/edit/write/webfetch/external_directory.
7. **Aviso e auditoria.** A cada uso a Ilha mostra "Nuvem: <agente>" (evento `action_step` com `tool="nuvem"`; início, ok/erro) e o terminal recebe um `notice`. `audit.jsonl` registra agente, **tamanho e hash curto** do texto (nunca o conteúdo), ferramentas chamadas, desfecho e tempo, mais cada decisão de permissão.
8. **Resposta da nuvem** é gravada na conversa como `untrusted` (dado, nunca instrução) para rodadas locais seguintes.
9. **Falha → local.** Sem agente, sem login, tempo esgotado, erro ou resposta que começa com "Error:" → `CloudUnavailable` → o modelo local responde e a Ilha/terminal avisam (`brain.fallback_local`; desligado, o Eco fala que não conseguiu).
10. Cancelar (tecla de emergência, "para") envia `session/cancel`; sem resposta em 5 s o processo do agente é encerrado.

## 6. Configuração (`config.toml`, seção `[brain]`; tela "Cérebro em nuvem")

| Chave | Padrão | Aplica |
|---|---|---|
| `kind` | `"local"` (`"cloud"`) | na hora |
| `agent` | `"opencode"` (`antigravity`, `claude`, `codex`, `copilot`) | na hora |
| `fallback_local` | `true` | na hora |
| `use_tools` | `true` | na hora |
| `builtin_tools` | `"deny"` (`"ask"`) | na hora |
| `consent_screen` / `consent_memory` / `consent_files` | `[]` | na hora |
| `action_modes` | `{}` (= `confirm` para todos; `deny`/`confirm`/`normal` por agente) | na hora |
| `models` | `{}` (modelo do próprio agente; o Eco troca se falhar e lembra) | na hora |
| `request_timeout_s` | `90` (10..600) | na hora |
| `startup_timeout_s` | `45` (5..300) | na hora |

Não existe campo de chave/token: o login é do agente. Para entrar: `opencode auth login`, `claude` (`/login`), `codex login`, `copilot` (`/login`), `agy`.

### Widget (`ui/settings/cloud_brain_page.py`)
`CloudBrainPanel(controller)` no contrato de `blocks.external_panel` (já ligado na página "Cérebro em nuvem" por `categories.py`, seção `cloud_panel`): lê e grava via `controller.model.current` / `controller.edit` e sincroniza os campos avançados do schema. Sem controller funciona autônomo (`values()`, `set_values()`, sinal `changed`). Por agente: situação, **Testar**, **Como entrar** (comando exato + copiar), modo das ações no PC e o que o agente pode ver.

## 7. Testes
`venv\Scripts\python.exe -I -W error tests\test_cloud_brain.py` — 43 testes com um agente de exemplo (`tests\fake_acp_agent.py`): streaming, fs/terminal negados, capacidades anunciadas, login ausente, timeout, cancelamento cooperativo e com agente que ignora, morte e reinício do processo, permissões (negar/perguntar/ferramenta do Eco/título forjado), servidor MCP (token, Host, ferramenta não listada, ponte stdio, URL fora de loopback), consentimento por agente, confirmação forte com nome do agente, auditoria sem conteúdo, fallback do `Agent`, validação da config e cobertura do schema.
Prova ao vivo: `venv\Scripts\python.exe -I tests\acp_live_proof.py antigravity "Que horas são? Use a ferramenta."`.

## 8. Provas (22/11/2026)
- **43 testes** (`tests\test_cloud_brain.py`, ~23 s, com agente de exemplo): protocolo, cancelamento/reinício, permissões, MCP, consentimento, modos de ação por agente, troca de modelo, detecção de falha por texto (conta, modelo, login, cota) sem falso positivo em respostas em português, ambiente limpo do filho, fallback do `Agent`.
- **Ponta a ponta por agente** (`tests\e2e_cloud_voice.py`; JSON em `F:\Jarvis\work\e2e\`): Antigravity, OpenCode e Claude: pergunta da hora (consulta via MCP → `hora_atual`) e «abrir o Bloco de Notas» com confirmação **SIM** (a ação rodou) e, no Antigravity, também **NÃO** (`abrir_app:denied`, nada abriu). Codex e Copilot: falha por cota detectada → `CloudUnavailable(kind="quota")` → plano B local, sem repetir trechos do erro.
- **Interface** (`tests\ui_cloud_prints.py`, `tests\ui_cloud_island.py`; capturas em `capturas/ui-prints\config-v2\nuvem\`): página montada pela navegação (`external_panel` → `CloudBrainPanel`) em janela REAL e offscreen, 100% e 150%, claro e escuro; estados do «Testar», «Como entrar», modo por agente e consentimentos refletidos no formulário (e o campo avançado do schema acompanha); **clique real em «Testar» (Antigravity): pronto em 19 s**; Ilha com «nuvem: <agente>» (consultando/respondeu/falhou com motivo) e popup de confirmação com o nome do agente.

## 9. Limites conhecidos / não verificado
- A captura por **microfone real** não foi exercitada (áudio sintético do Piper); a escuta real é a do núcleo.
- O fallback ao **llama.cpp local de verdade** não foi rodado (GPU com o Eco instalado); o caminho foi testado no `Agent` com provider local simulado.
- Codex e Copilot dependem da cota da conta do usuário; só a detecção e o plano B foram provados.
- Latência de 7 a 37 s na nuvem (quase tudo é do agente) contra ~1–3 s do local; a fala só começa com a resposta inteira.
- Agentes com ferramentas **próprias** que não pedem permissão não passam pelo Eco; a pasta de trabalho é vazia e fora de repositórios, e o preâmbulo manda usar só o MCP.
- Mesmo com consentimento, o conteúdo das ferramentas liberadas (ex.: texto de arquivo) vai ao provedor do agente.
