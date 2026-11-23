# Setup: preparar o computador, caminhos dos programas e verificação total

Etapa nova do assistente de configuração: **3. Preparar o computador** (entre "Seu computador" e "Modelos de IA").
Código: `src/jarvis/setup/prereqs.py` (checagens e downloads oficiais), `src/jarvis/setup/pages_prepare.py` (tela),
`src/jarvis/setup/tool_dialog.py` (personalizar caminho), `src/jarvis/core/toolpaths.py` (catálogo, validação, busca, varredura).

## O que a etapa faz
- **Verificação total** em uma lista com status por item (Ok / Atenção / Erro / Opcional), versão encontrada, **onde foi achado**
  (caminho personalizado, PATH do Windows, instalação padrão, pasta do Eco) e o que fazer. 27 itens: pastas do Eco, biblioteca do
  Visual C++, GPU/Vulkan (e idade do driver), servidor do modelo, internet (hosts dos downloads), modelos/voz/escuta, Git, Git Bash,
  PowerShell, Python, FFmpeg, Ollama, LM Studio, whisper.cpp, pastas de modelos e de dados e os 5 agentes ACP.
- **Botões por linha:** Resolver (baixar/instalar/abrir site oficial/reparar) e **Personalizar**.
- **Barra no topo:** Preparar o que for seguro, Verificar de novo, Reparar (confere SHA-256 e rebaixa o corrompido), Salvar relatório
  (JSON + texto em `data\setup\prepare-report.*`).
- **Instaladores de terceiros** (Visual C++, Ollama): só do site oficial (lista de hosts, HTTPS, redirecionamento para host fora da
  lista é recusado), com retomada; a **assinatura digital (Authenticode)** é conferida antes de qualquer execução e o arquivo sem
  assinatura válida é apagado. Duas confirmações explícitas (baixar; instalar, mostrando quem assinou e o SHA-256). O Visual C++
  pede UAC do Windows. Ollama: opcional, só detecta/sugere modelo (por memória de vídeo) e baixa modelo se você pedir.
- Modelos do Eco: baixador do manifesto (SHA-256 obrigatório, retomada). Nada é pago; nada é instalado sem clique e confirmação.

## Caminhos personalizados
Campo + **Procurar**, **Detectar automaticamente**, **Restaurar padrão**, validação ao vivo e **Salvar** (só se válido).
Valem para: llama-server, pasta de modelos e de dados, modelo .gguf, mmproj, modelos de escuta, voz Piper, whisper.cpp, Git, Git Bash,
PowerShell, Python, FFmpeg, Ollama, LM Studio e agentes (OpenCode, Antigravity, Claude Code, Codex, Copilot).
Ficam no `config.toml` (seção `[toolpaths]`, mais os campos que já existiam como `llm.model`), com telas em
**Configurações > Caminhos dos programas**. Vazio = o Eco procura sozinho.

**Validação** (`toolpaths.validate_path`): não é caminho de rede/UNC/unidade mapeada; existe; é o tipo certo (arquivo/pasta); é
MESMO aquela ferramenta (nome, resposta de `--version`, arquivos marcadores, formato GGUF, JSON válido); versão mínima; permissão de
escrita nas pastas; executável fora das pastas confiáveis e **sem assinatura digital válida exige confirmação** ("Confio, usar este
programa"). Mensagens dizem o que houve e o que fazer.

**Quem usa:** agentes ACP (`brain/acp/agents.py`), Terminal (`terminal/runner.py` shells; `terminal/policy.py` põe a pasta do Git/Python/
FFmpeg/Ollama personalizados no PATH do terminal), escuta GPU (`audio/stt.py`), Setup/prereqs, `doctor`. Caminho personalizado que deixar de
valer não derruba nada: o Eco usa a busca automática e avisa.

## Repetir a verificação
- Tela do Setup (Verificar de novo / Reparar) e Configurações.
- `Eco.cmd doctor` (rápido) e **`Eco.cmd doctor --full`** (varredura total); `--full --json` e `--full --out ARQUIVO` exportam o relatório.

## Piscar das telas (corrigido)
Causas medidas com `tests\ui\flash_probe.py` (EnumWindows a cada 15 ms):
1. **Console preto visível** ao abrir as Configurações: `DETACHED_PROCESS` + `python.exe` do venv (o lançador cria o Python real com
   console novo). Correção: `win/spawn.py` lança com `pythonw.exe` e `CREATE_NO_WINDOW`.
2. **~130 janelinhas "python"** (widgets sem pai recebendo `setVisible(True)`): `ui/kit/visibility.py:set_shown`.
3. Janela principal passa a nascer transparente e só ficar visível depois da primeira pintura (`show_after_first_paint`).
Antes: 201 janelas distintas, 67 visíveis, 1 console. Depois: 6 janelas, 1 visível, 0 console. Teste: `tests\test_no_flash.py`.

## Testes
`tests\test_toolpaths.py` (34: caminho correto, errado, inexistente, de outra ferramenta, com espaços e acentos, de rede, não confiável,
versão antiga, pastas/arquivos de modelo, uso por agentes/Terminal/PATH/doctor), `tests\test_prepare.py` (26: downloads, retomada,
assinatura, UI com dublês), `tests\ui\test_setup_prepare.py` (diálogos reais, clique/teclado reais com `--native`), `tests\test_no_flash.py`.
Prova real: download do Visual C++ da Microsoft (interrompido e retomado, assinatura Valid "Microsoft Corporation", adulterado = HashMismatch).

## Pendências / limites conhecidos
- O instalador do Visual C++ e o do Ollama **não foram executados** em teste (exigem UAC e alteram o PC); o fluxo foi provado com
  dublês e o download/assinatura reais.
- Ollama como **cérebro ativo** não está ligado: o cliente do Eco usa endpoints do llama.cpp (`/tokenize`, `/props`) que o Ollama não
  tem. Hoje só detecta, sugere e baixa modelo. Tamanhos dos modelos sugeridos são aproximados.
- RX 580 não está na lista oficial do Ollama (pode rodar na CPU): o aviso está na tela.
- Matriz em 200% de DPI, multi-monitor real e leitor de tela não foram feitas aqui (ver relatório do QA).
- Polimento visual adicional da etapa (agrupar/colapsar a lista longa, filtro "só o que precisa de atenção") fica para depois.
- Textos antigos ainda dizem "Eco" até a renomeação global para Eco.
