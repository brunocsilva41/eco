# Terminal integrado do Eco

O Eco roda comandos de linha de comando (git, npm, python, listar arquivos de um projeto...) por voz ou texto, com o cérebro local
e, se você autorizar, com um agente na nuvem. **Vem desligado.** Ligue em Configurações, página **Terminal**.

## O que existe

| Peça | Onde |
|---|---|
| Ferramentas `executar_comando`, `terminal_saida`, `terminal_cancelar`, `terminal_historico` | `src/jarvis/tools/terminal_tools.py` |
| Política (bloqueios, pastas, segredos, lista permitida) | `src/jarvis/terminal/policy.py` |
| Executor (sessão, streaming, tempo limite, cancelamento, Job Object) | `src/jarvis/terminal/runner.py` |
| Painel Terminal (janela própria) | `src/jarvis/ui/terminal/` · bandeja: **Abrir o Terminal** · `Eco.cmd terminal` |
| Configurações (10 campos, grupo `Terminal` do schema) | `[terminal]` no `config.toml` e `brain.consent_terminal` |

## Modos (`terminal.mode`)

| Modo | O que acontece |
|---|---|
| `off` (padrão) | As ferramentas nem aparecem para o modelo local nem para a nuvem; o painel recusa comandos manuais. |
| `confirm` | Todo comando pede o seu Sim. A pergunta mostra o comando **exato**, o terminal e a pasta. |
| `allowlist` | Comando **simples** da lista (`git status`, `git log`, `dir`...) roda direto; o resto pergunta. |
| `free` | Sem perguntar, **mas só depois de você liberar no painel** (botão «Liberar modo livre…», com confirmação), por `free_minutes`. Desliga sozinho, ao reiniciar e na parada de emergência. Nunca por voz, ferramenta ou nuvem. |

Vale sempre, em qualquer modo:

- **Pedido da nuvem** (agente ACP): precisa do consentimento por agente (`brain.consent_terminal`) e **sempre** pergunta, com o nome do agente (até no modo livre armado e para comandos da lista permitida).
- **Rodada com conteúdo de fora** (o Eco leu a tela, uma página, um arquivo antes): sempre pergunta.
- **Comando bloqueado**: nem pergunta, nem roda (veja abaixo).
- Pasta fora de `terminal.roots` (ou `..` que escapa): a execução é recusada; um caminho absoluto no comando que aponta para fora volta a **perguntar**, mesmo na lista permitida ou no livre.

## Bloqueio fixo (nenhum modo libera)

Formatar/particionar disco · apagar raiz, Windows, Program Files, perfil · `reg delete/save/restore/load/import` e gravações em HKLM/`Run` ·
`shutdown`, `Restart-Computer`, `Stop-Computer`, `logoff` · `taskkill`, `Stop-Process`, `pkill`, `kill <pid>` (o Eco só encerra o que **ele** iniciou) ·
ler `.ssh`, `.aws`, `.gnupg`, `.git-credentials`, `.netrc`, a pasta do OpenBot/OpenCode, `auth.json`, o Eco instalado, `data\control` ·
`iex`/`Invoke-Expression`, baixar e executar (`curl ... | bash`), PowerShell `-enc`, `mshta`, `certutil -urlcache`, `rundll32`, `msiexec` ·
`runas`, tarefas agendadas, serviços, contas/grupos, firewall, `Set-ExecutionPolicy`, exclusões do Defender, `cmdkey`, `gh auth token`, `git credential`,
listar variáveis de ambiente. Você acrescenta trechos em `terminal.blocked_extra`.

> **Limite honesto:** é uma rede de proteção por texto (o comando é normalizado: aspas, crases, `^`, invisíveis e Unicode), não uma sandbox.
> As defesas reais são a confirmação mostrando o comando exato, a pasta de trabalho restrita, o ambiente do filho **sem segredos** e o log.
> Ofuscação criativa pode escapar do texto; por isso o modo livre existe só por tempo, à mão, e a nuvem nunca o usa.

## Como roda

- Cada comando é um processo filho **do Eco** (PowerShell, `cmd` ou Git Bash) dentro de um **Job Object** do Windows: parar = derrubar só a árvore que o Eco iniciou.
  Terminou normal: o Job é solto sem matar o que o comando deixou de propósito em segundo plano (`Start-Process notepad`). Tempo limite, cancelamento, emergência e fechamento do Eco matam tudo.
- **Sessão**: a pasta atual vale entre comandos (`cd sub` num comando, `dir` no próximo) e há histórico dos últimos 60. Um comando por vez.
- **Ambiente limpo**: variáveis com cara de token/senha/chave (`*TOKEN*`, `*SECRET*`, `GITHUB_*`, `OPENAI_*`, `JARVIS_*`...) nem chegam ao filho; `GIT_TERMINAL_PROMPT=0` (nunca fica esperando senha).
- **Saída**: redigida linha a linha (tokens `ghp_`/`github_pat_`/`sk-`/`AKIA`, JWT, `senha=`/`password=`, `https://user:senha@`, chave privada), guardada com limite (`max_output_kb`: começo + fim) e devolvida ao modelo como **dado não confiável** (`result_chars`, começo + fim), nunca como instrução.
- Comando demorado: a ferramenta espera `aguardar_s` (padrão 20 s, máx. 60 s) e devolve «ainda rodando» com o andamento; o modelo usa `terminal_saida` / `terminal_cancelar`. O tempo máximo de um comando é `terminal.timeout_s`.
- **Auditoria** (`jarvis.audit`): comando (já redigido), pasta, shell, código de saída, duração e quantos bytes. **Nunca** a saída.

## Painel Terminal

Outro processo que lê `data/terminal/state.json` e `runs/<id>.log` (saída em tempo real, 0,4 s) e conversa com o Eco por **pedidos assinados** (HMAC, validade 30 s, mesma chave do YOLO):
digitar um comando à mão (vale o modo, o bloqueio fixo e as pastas; sem confirmação, porque foi você), **Parar**, **Copiar saída**, **Copiar comando**, **Limpar** (`Ctrl+L`),
liberar/desligar o modo livre. Mostra se o Eco está conectado e o modo atual.

## Provas (22/11/2026)

- `tests/test_terminal.py`: 30 testes com comandos **reais** (PowerShell, cmd, Git Bash, git num repositório temporário): bloqueios (60+ comandos), falsos positivos, lista permitida, normalização, redação, ambiente sem segredos, pastas e junção que escapa, saída truncada, tempo limite derrubando a árvore **sem matar um processo alheio**, cancelamento, segundo comando recusado, confirmação com comando exato, modo livre (armar/expirar/emergência), pedidos assinados/forjados/vencidos, auditoria sem saída.
- `tests/test_terminal_cloud.py`: 8 testes com o agente de exemplo (MCP em loopback): sem consentimento a ferramenta é invisível; com consentimento pergunta com o nome «OpenCode»; negar não roda; modo livre armado e lista permitida **ainda perguntam** para a nuvem; perigoso é recusado sem perguntar.
- `tests/ui/test_terminal.py` e `tests/ui/test_terminal_settings.py`: painel e página das Configurações em 100/125/150/200% × claro/escuro (offscreen) e janela real com **clique real do mouse** (SendInput) em Parar/Copiar. Relatório e capturas em `capturas/ui-prints/terminal/`.

## Não coberto

Veja o relatório final do pedido: voz real ponta a ponta com o terminal, uso por agentes reais da nuvem (só o agente de exemplo) e instalação limpa com o terminal ligado.
