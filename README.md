# Jarvis

Assistente de voz **local** em português do Brasil para Windows. Ouve, entende, enxerga a tela e controla o PC por
ferramentas permitidas, tudo na sua máquina, sem nuvem.

Versão atual: **0.1.0** (primeira versão; veja [CHANGELOG.md](CHANGELOG.md) e [docs/RELEASE-v0.1.0.md](docs/RELEASE-v0.1.0.md)).

## Recursos
- **Voz:** reconhecimento de fala com faster-whisper (CPU) e VAD Silero; fala com Piper (voz pt-BR, CPU), com normalizador
  de números, horas, datas e siglas; interrupção ao apertar F9.
- **Visão da tela:** `ver_tela` descreve o que está na tela usando um modelo de visão e linguagem local (Qwen3-VL 4B).
- **Controle de mouse e teclado:** por UI Automation (UIA) sempre que possível; se o controle não é achado pelo nome,
  cai em localização visual (duas leituras que precisam concordar) e só clica dentro da janela que estava em foco.
- **Ilha:** janela discreta no topo da tela com estado, ondas de voz, ação em curso e botões Sim/Não, Mudo, Parar e
  Configurações (3 tamanhos; some em tela cheia).
- **Memória local:** conversas e memória de longo prazo em SQLite (busca FTS5), painel "O que o Jarvis sabe de mim",
  modo sem histórico.
- **Segurança:** servidor do modelo só em loopback, ferramentas em lista permitida, confirmações só para ações nocivas,
  auditoria com HMAC (detalhes abaixo).

## Requisitos
- Windows 10 (build 19044 ou superior) ou Windows 11, 64 bits.
- 16 GB de RAM recomendados.
- GPU com suporte a Vulkan e 8 GB de VRAM recomendados (pico medido de 6,8 GB com modelo, visão e escuta). Testado em uma AMD Radeon RX 580 de 8 GB; outras GPUs (NVIDIA, Intel) **não foram testadas**.
- Cerca de 3,5 GB de disco para os modelos, mais o programa.

## Instalação
**Instalador:** execute `Jarvis-Setup-<versão>.exe` (instala por usuário, sem administrador, por padrão). Ao final abre o
assistente de configuração (requisitos, modelos, microfone e som, teste de voz, calibragem, atalhos, permissões, verificação).

**Pela linha de comando:** `Jarvis.cmd setup` (também `setup --repair`, `--status`, `--offline`).

Os modelos (~3,5 GB) **não vão dentro do instalador**: são baixados por HTTPS com retomada, de URLs fixadas por revisão, e
só são gravados se o **SHA-256** bater com o de `installer\manifest.json`. Há pacote offline (`setup --make-pack`).
Detalhes em [docs/INSTALADOR.md](docs/INSTALADOR.md). O instalador atual **não é assinado** (o SmartScreen avisará).

## Uso
```
Jarvis.cmd doctor        confere o ambiente
Jarvis.cmd               roda por voz (igual a "run")
Jarvis.cmd run --text    também aceita comandos digitados
Jarvis.cmd settings      Configurações
Jarvis.cmd record        gravador de voz ("Minha voz")
Jarvis.cmd memory        painel de memória e conversas
Jarvis.cmd tools         lista as ferramentas e o risco de cada uma
```
- **F9:** segure e fale; solte para enviar. Apertar durante uma resposta interrompe o Jarvis.
- **Ctrl+Alt+F12:** emergência, PARA TUDO (ações, fala, mouse e teclado).
- **Ctrl+Alt+Y / Ctrl+Alt+N:** confirma (sim) / recusa (não). Por voz: "sim" e "não"; ações mais sensíveis pedem "confirmo".
  Sem resposta em 15 s vale NÃO.
- **Ctrl+Alt+M:** liga/desliga o microfone.
- **Configurações** (`Jarvis.cmd settings` ou botão da Ilha): atalhos, voz, modelo, permissões, Ilha, privacidade.
  Os atalhos podem ser trocados lá.

## Segurança
- O servidor do modelo escuta **somente em 127.0.0.1**, com chave de API aleatória por execução.
- Só existem as ferramentas registradas (sem shell livre). Digitação só em programas de uma lista permitida; arquivos só em
  pastas permitidas, apagar vai para a Lixeira, com desfazer.
- No modo padrão (equilibrado) só as ações **nocivas** pedem confirmação (apagar/mover/editar arquivos, fechar janela,
  esquecer memória, Ctrl+S, Enter em diálogo, texto com cara de comando). O modo estrito confirma mais.
- **Modo YOLO** (sem confirmações, com prazo e que expira sozinho) só liga por **ação manual**: atalho físico ou botão nas
  Configurações. Por voz ou texto o Jarvis apenas abre as Configurações. Pastas protegidas e terminais continuam bloqueados.
- Log de auditoria em `logs\audit.jsonl` (texto digitado só como tamanho e hash).
- **O texto lido da tela, de janelas e de arquivos é dado não confiável:** nunca é tratado como instrução.
- Limite honesto: a assinatura do YOLO usa uma chave em `data\control\`; protege contra o modelo e a voz, não contra
  um programa malicioso rodando com o seu usuário.

## Privacidade
Tudo roda localmente: reconhecimento, modelo, voz e memória. Nada é enviado para a nuvem durante o uso. A internet é usada
apenas para baixar os modelos na instalação. Memória e histórico ficam em SQLite local **não criptografado** em `data\`.

## Estrutura de pastas
| Pasta | Conteúdo |
|---|---|
| `src\jarvis\` | código (config, app, agente, llm, audio, tools, files, memory, settings, ui, setup, win) |
| `src\` (demais) | scripts de benchmark e medição (F0/F1/F2) |
| `installer\` | instalador Inno Setup, `build.ps1`, `manifest.json`, runtime travado por hash |
| `docs\` | instalador, design, especificação da Ilha, pesquisas e medições |
| `tests\` | frases e resultados de bancada (áudios e logs ficam fora do git) |
| `PLANO.md`, `config.toml` | plano do projeto; configuração de exemplo |

Fora do git (criados na máquina): `bin\` (llama.cpp), `models\`, `data\`, `logs\`, `venv\`, `work\`.

## Compilar o instalador
Requer Windows e PowerShell; o Inno Setup 6 é baixado e verificado pelo próprio script se faltar.
```powershell
installer\build.ps1          # release
installer\build.ps1 -Fast    # compressão rápida, para testes
```
A versão vem de `installer\VERSION`. Saída em `installer\dist\` (`.exe`, `.sha256` e notas). Veja [docs/INSTALADOR.md](docs/INSTALADOR.md).

## Licenças de terceiros
| Componente | Licença |
|---|---|
| piper-tts | **GPL-3.0** (revisar antes de distribuir a terceiros) |
| PySide6 (Qt) | **LGPL-3.0** |
| llama.cpp | MIT |
| faster-whisper | MIT |
| Modelos (Qwen3-VL, Whisper, voz Piper, Silero VAD) | conforme `installer\manifest.json` |

A lista completa gerada no build fica em `THIRD-PARTY.txt` dentro do instalador.

## Onde cada serviço roda (CPU × GPU)
Regra medida: GPU por padrão; CPU só onde medi menor tempo (diferença < 10% = menos CPU-s). Modelo de linguagem, visão e escuta rodam na placa de vídeo (Vulkan); voz, detector de voz, captura de tela e interface na CPU. Cada escolha tem chave em `config.toml` (`llm.device`, `llm.mmproj_device`, `stt.device`, `tts.device`: `auto`, `gpu` ou `cpu`); se a GPU falhar, o Jarvis cai para a CPU com aviso. `Jarvis.cmd doctor` mostra onde cada serviço roda e `docs/medicoes-release.md` traz os números.

## Estado e desempenho (medido)
Medido na máquina de desenvolvimento (RX 580 8 GB, Xeon E5-2650 v4, 16 GB): modelo ~19,8 tok/s de geração e ~187 tok/s de
prompt; VRAM total ~6,1 GB de 8 GB com o modelo carregado; RAM do servidor ~500 MB; partida a frio ~42 s. Latência da voz
do fim da fala ao primeiro som ~3 a 4 s com o modelo em cache; WER em frases sintetizadas 11,8% (ruído de 8 dB: 17,8%) com a escuta na GPU; WER com gravações reais de pessoas: **não medido**. Limitações e itens não verificados em
[docs/RELEASE-v0.1.0.md](docs/RELEASE-v0.1.0.md).

## LICENÇA
**PENDENTE.** O autor ainda não definiu a licença do Jarvis. Até que seja definida, **todos os direitos são reservados**
(não há permissão de uso, cópia ou redistribuição). Não existe arquivo `LICENSE` neste repositório de propósito.
