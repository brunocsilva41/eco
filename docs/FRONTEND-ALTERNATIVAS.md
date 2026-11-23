# Front-end do Eco: Qt (Python) x alternativas

Data: 22/11/2026. Máquina: Windows 10 Pro, Xeon E5-2650 v4 (24 threads), 16 GB, RX 580 8 GB. Medido com ffmpeg ocioso (downloads,
sem render) e carga de CPU ~17%. **Nada de produção foi alterado.** Protótipos, scripts e dados em `F:\Jarvis_proto_ui\`; prints em
`capturas/ui-prints\proto-ui\`. Status: **proposta para o usuário aprovar; nenhuma migração feita.**

## 1. Resposta direta às perguntas do usuário

- **O front-end é Python?** Sim: PySide6 (Qt Widgets) para a Ilha, bandeja, Configurações, Gravador, Memória e Terminal. O backend
  (voz, STT, TTS, llama.cpp, ferramentas, schema) também é Python. A interface roda em processos separados que falam com o núcleo por
  um canal JSON em stdin/stdout.
- **Por que a janela do Python pisca ao abrir Configurações?** Reproduzido e provado: o app lança as Configurações com
  `creationflags = DETACHED_PROCESS | CREATE_NO_WINDOW` (`src/jarvis/app.py:202-203` e `:528-529`). Pela documentação do Windows,
  `CREATE_NO_WINDOW` é **ignorado** quando combinado com `DETACHED_PROCESS`; com o `python.exe` do venv (que relança o Python base),
  o filho ganha um **console visível** (993x579, preto, título `...\python.exe`) que fica aberto enquanto a tela existe.
  Teste (`measure/measure_qt.py`, `measure/grab_flash.py`, captura em `ui-prints/proto-ui/flicker/`):

  | Flags de lançamento | Janela de console visível | Janela real de Configurações |
  |---|---|---|
  | `0x08000008` (DETACHED + NO_WINDOW, como o app) | **sim, 2 de 2 execuções** | 1,40–1,42 s |
  | `0x08000000` (só CREATE_NO_WINDOW) | **não, 0 de 2** | 1,34–1,37 s |

  Correção proposta (2 linhas): tirar `DETACHED_PROCESS` desses dois `Popen` e preferir `pythonw.exe` quando existir. No instalador
  o Eco já roda por `pythonw.exe`, então o console tende a não aparecer lá (não testei a instalação do usuário). Também vi a janela
  real aparecer **em branco** antes de pintar: dá para esconder até o primeiro quadro pintado.
  Um episódio isolado mostrou uma janela Qt de 619x96 com título "python" por vários segundos e a janela real só aos 4,8 s, com CPU
  alta; não reapareceu em 4 execuções limpas e coincidiu com outros agentes editando o código. **Não consegui isolar a causa.**

## 2. O que foi medido

### 2.1 Qt atual (PySide6 Widgets)

| Medida | Resultado |
|---|---|
| Configurações: 1ª janela real visível | 1,34–1,42 s (dev, venv) |
| Configurações: RAM (árvore: 2x python + conhost) | 157–164 MB working set, ~103 MB privado (USS) |
| Configurações: CPU em repouso (8 s) | 0–3% de 1 núcleo |
| Ilha visível, repouso compacto | 83 MB WS / 44 MB USS, 0,8% CPU, 15 fps (respiração) |
| Ilha pensando | 85 MB WS / 46 MB USS, 1,2% CPU, 31 fps |
| Ilha ouvindo | 88 MB WS / 47 MB USS, 23% CPU, 59,7 fps |
| Ilha grande falando | 93 MB WS / 52 MB USS, 28% CPU, 59,5 fps (intervalo p95 17,8 ms) |
| Processo filho da Ilha escondida (bandeja viva) | 23 MB WS / 12 MB USS, 0% CPU |
| Bandeja-só | 75 MB WS / 38 MB USS |
| Runtime PySide6 no instalador (staging) | 209 MB (Qt Widgets mínimo ≈ 54 MB; resto é Designer, qmlls, opengl32sw 20 MB, traduções, QML) |
| Instalador final v0.1.3 | 176 MB |

### 2.2 Protótipo Tauri 2 (tao + wry + WebView2), duas janelas (Ilha + Configurações) + bandeja

Build release (LTO, strip): **3,1 MB** `.exe`, 5 min 50 s na 1ª compilação, ~2,5 min nas seguintes. UI em HTML/CSS/JS puro
(sem framework, 0,1 MB), alimentada pelo **schema real** exportado do Python (14 páginas, 116 campos) e o backend Python falando por HTTP
loopback (`backend_stub.py`: `/state`, `/level`, `/schema`, telemetria de fps).

| Medida (ambas as janelas abertas) | Resultado |
|---|---|
| Ilha visível | 0,07 s |
| Configurações visíveis | 0,71–0,74 s |
| Processos | 8 (1 exe + 7 `msedgewebview2`) |
| RAM total após 8 s | 442–455 MB WS / 145–154 MB USS |
| RAM com estados animados | até 500 MB WS / 182 MB USS |
| CPU repouso (árvore inteira) | 5,6–6% de 1 núcleo (GPU ~10%, renderer ~9% em uma amostra sem backend) |
| CPU pensando / ouvindo / falando | 15,5% / 23,4% / 21,6% (fps ~55, limitado a 60) |
| Confirmar / erro | 6,5% / 2,8% |

Ajustes que foram necessários para chegar nisso: a 1ª versão gastava 31–55% de CPU em repouso (animação CSS infinita, polling constante,
`requestAnimationFrame` a 165 Hz, a taxa deste monitor). Tirei a respiração do repouso, limitei a 60 fps e só consulto o nível de
áudio quando ouvindo/falando.

### 2.3 Protótipo QML (Qt Quick) da Ilha, mesma runtime PySide6 já instalada

| Estado | fps | CPU | RAM |
|---|---|---|---|
| Repouso (animação infinita de opacidade) | 165 (sem limite) | 12,9% | 79 MB WS / 33 MB USS |
| Ouvindo | 62,5 | 6,6% | 80 MB WS / 33 MB USS |
| Falando | 62,5 | 13,3% | 85 MB WS / 39 MB USS |

Primeiro quadro 1,76 s (carga do motor QML). Contra a Ilha Widgets: ouvindo 23% → 6,6% e falando 28% → 13,3% de CPU, RAM ~10% menor.
O repouso precisa do mesmo cuidado (parar a animação), senão renderiza a 165 fps.

### 2.4 Comparação resumida (conjunto Ilha + Configurações)

| | Qt Widgets (hoje) | Tauri + WebView2 | QML (só Ilha) |
|---|---|---|---|
| Abertura das Configurações | 1,34–1,42 s | **0,71–0,74 s** | n/m |
| RAM (working set) | **~245–260 MB** | 442–500 MB | 80–85 MB (só Ilha) |
| RAM (privado, USS) | **~150 MB** | 145–182 MB | 33–39 MB (só Ilha) |
| CPU repouso | **~1%** | ~6% | 0% (após parar animação) |
| CPU falando | 28% (Ilha) | 21,6% (árvore + GPU) | **13,3%** |
| Tamanho no instalador | 209 MB (≈54 MB se podado) | **3,1 MB** + WebView2 compartilhado | 0 extra (já existe) |
| Processos | 2–3 | 8 | 2–3 |

Observação importante: o working set do WebView2 conta páginas compartilhadas entre os processos; em memória privada o Tauri fica no
mesmo patamar do Qt. Mesmo assim **não reduz RAM**, ao contrário do que a literatura popular sugere: no Windows o Tauri usa o WebView2,
que é Chromium (ver fontes).

## 3. Alternativas: análise

Medi só Qt Widgets, QML e Tauri/WebView2. O resto abaixo vem de documentação e de artigos (links na seção 6) e **não foi medido aqui**.

| Opção | Peso | Transparência / sempre no topo / click-through | IPC com Python | Esforço e riscos |
|---|---|---|---|---|
| **Qt Widgets (hoje)** | 54–209 MB de runtime; RAM baixa | OK, já feito (vidro, dock, alfinete) | processo único, sem ponte | zero migração; visual exige muito código |
| **QML (PySide6)** | 0 extra | OK (testado: pílula transparente sempre no topo) | mesmo processo/canal | médio: reescrever telas em QML; boa para animação |
| **Tauri 2 + WebView2** | exe 3 MB; WebView2 compartilhado | OK: `transparent`, `alwaysOnTop`, `set_ignore_cursor_events` (testado a Ilha; click-through só pelo flag, sem teste de clique real) | sidecar/stdio ou HTTP loopback (testado HTTP) | precisa de Rust no build, WebView2 no PC, assinatura e antivírus a tratar |
| Electron | ~150–250 MB e RAM maior (Chromium próprio) | OK | stdio/WebSocket | mais pesado que Tauri; só se precisar de Chromium fixo |
| WPF / WinUI 3 (.NET) | runtime .NET + WinAppSDK; sem medição | WPF `AllowsTransparency` tem limites com WebView2; WinUI exige empacotar | named pipe/HTTP | reescrever tudo em C#; fora do ecossistema Python |
| Slint | binário pequeno (segundo o fornecedor) | suporte a janela sem borda; sem medição minha | stdio/HTTP | linguagem própria, ecossistema novo |
| Flutter desktop | ~130+ MB de hello world (artigo) | possível, plugins | stdio/HTTP | Dart novo, o mais pesado dos citados |
| Wails (Go) | pequeno, também usa WebView2 | similar ao Tauri | HTTP/stdio | Go no build; mesma dependência do WebView2 |
| Dear ImGui | muito leve | possível | in-process/HTTP | sem acessibilidade nem visual de produto |

**WebView2 no Windows 10:** o Windows 11 já traz o runtime; no Windows 10 a Microsoft o distribui para a imensa maioria dos PCs, mas
"uma pequena parte" não tem. O instalador deve checar o registro e embutir o bootstrapper de ~2 MB como plano B (nesta máquina o
runtime 157.0.4341.60 já está instalado, 878 MB no disco, compartilhado com outros apps).

## 4. Recomendação

1. **Não migrar tudo para Tauri agora.** Os números não sustentam a troca por desempenho: mesma RAM privada, 2x de working set,
   6% de CPU em repouso contra ~1%, 8 processos, mais uma toolchain (Rust) e uma dependência do sistema (WebView2). O ganho real é
   o instalador (3 MB contra 209 MB) e a velocidade de iteração visual (HTML/CSS) para chegar a um visual estilo Apple/Linear.
2. **Corrigir já, dentro do Qt** (resolve a queixa concreta, risco baixo):
   - Remover `DETACHED_PROCESS` do lançamento das Configurações e do terminal (e usar `pythonw.exe`) para acabar com o console que pisca.
   - Esconder a janela até o primeiro quadro pintado (sem janela branca).
   - Podar o PySide6 do instalador (de 209 MB para ~55–70 MB): remove Designer, qmlls, `opengl32sw`, traduções e QML não usados.
3. **Ilha em QML** é o melhor retorno para animação: metade da CPU da Ilha atual com a mesma runtime, e dá o efeito "Dynamic Island"
   com molas e morph. Migrar somente a Ilha (um arquivo QML + ponte Python) mantendo as Configurações em Widgets.
4. **Se o usuário quiser o teto de beleza nas Configurações** (cartões, animações, busca com realce como no protótipo), a opção híbrida é
   levantar as Configurações como janela WebView2 **sob demanda** (aberta só quando o usuário pede, fechada devolve a memória), com a
   Ilha continuando nativa. O protótipo já provou: schema real renderizado (116 campos), busca, listas suspensas abaixo do campo
   com ✓, grupos recolhíveis com altura animada, tema claro/escuro, 150% sem espremer a ajuda, abertura em ~0,7 s.
   Medir isoladamente o custo de **só** a janela de Configurações no WebView2 (não medi) antes de decidir.

## 5. Plano de migração incremental (só com aprovação)

| Fase | O que | Critério de aceite |
|---|---|---|
| 0 | Correções no Qt: flags do `Popen`, janela branca, poda do PySide6 | sem console visível em 20 aberturas; instalador menor; testes de UI verdes |
| 1 | Ilha em QML atrás de uma opção `ui.island_engine = widgets|qml` | fps 60 estável, CPU <15% falando, mesmos estados e travas, testes de UI |
| 2 | (opcional) Configurações em WebView2 sob demanda, mesmo schema e mesma validação do Python por HTTP loopback com token | 116 campos, validação idêntica, abertura <1 s, travas e YOLO só manual preservados |
| 3 | Decidir com dados se bandeja/Setup/Memória acompanham | só se a fase 2 provar ganho |

Sempre reaproveitado: schema (`settings/schema.py`), validação, canal de controle, backend. A ponte HTTP do protótipo (loopback,
porta aleatória, token por sessão) segue o mesmo desenho do servidor MCP local já feito para o cérebro em nuvem.

## 6. Riscos

- **WebView2:** ausente em parte dos Windows 10; precisa do bootstrapper e de detecção; atualiza sozinho (comportamento futuro muda).
- **Rust no build** e a necessidade de manter dois ecossistemas (Python + Rust/JS); CI mais lento (~6 min na 1ª compilação).
- **Antivírus/SmartScreen:** exe novo sem assinatura aumenta falsos positivos; assinar o código ajuda (já é pendência do instalador).
- **Transparência com WebView2:** funcionou aqui (Windows 10, runtime 157); janelas transparentes com `shadow` e DPI misto são fontes
  conhecidas de bugs, e o click-through total só foi verificado pelo flag, não por clique real.
- **Acessibilidade:** Qt expõe UI Automation; HTML expõe via Chromium (bom), mas o conjunto precisa ser validado com leitor de tela
  (não testei nenhum).
- **Segurança:** a ponte HTTP exige token, `Host` fixo e só loopback; o frontend nunca recebe segredos.

## 7. Não medido ou não verificado

- Custo isolado da janela de Configurações no WebView2 (as medições são do conjunto Ilha + Configurações).
- DPI real de 150%/200% e multi-monitor (150% foi simulado com zoom CSS e container query; a tela física tem 1 escala).
- Click-through verificado só pelo flag `set_ignore_cursor_events`, sem clique real do mouse atravessando a janela.
- Leitor de tela, teclado completo e contraste AA nos protótipos.
- Alternativas Electron, WinUI 3, Slint, Flutter, Wails e ImGui: só documentação e artigos, sem protótipo.
- O efeito das correções de flags na instalação do usuário (não mexi nela); no instalado o console pode não aparecer.
- Causa do episódio isolado da janela "python" de 619x96.

## 8. Fontes

- Tauri x Electron (artigos, números divergentes; um deles mede só macOS): [Tauri vs Electron: performance, bundle size and the real trade-offs](https://dev.to/gethopp/tauri-vs-electron-performance-bundle-size-and-the-real-trade-offs-1el4), [Tauri vs. Electron vs. Deno Desktop vs. Electrobun](https://betterstack.com/community/guides/scaling-nodejs/tauri-vs-electron-vs-deno-vs-electrobun/), [issue tauri-apps/tauri #5889 (memória com WebView2)](https://github.com/tauri-apps/tauri/issues/5889)
- WebView2 no Windows 10 e distribuição: [Delivering the WebView2 Runtime to Windows 10 consumers](https://blogs.windows.com/msedgedev/2022/06/27/delivering-the-microsoft-edge-webview2-runtime-to-windows-10-consumers/), [Distribuir apps com WebView2](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution), [Evergreen vs fixed](https://learn.microsoft.com/microsoft-edge/webview2/concepts/evergreen-vs-fixed-version)
- Janelas transparentes/click-through no Tauri (posts e issues da comunidade): [tauri-apps/tauri #11461](https://github.com/tauri-apps/tauri/issues/11461), [#9250](https://github.com/tauri-apps/tauri/issues/9250), [#9557](https://www.github.com/tauri-apps/tauri/issues/9557)
- Sidecar Python e IPC: [Tauri sidecar (docs)](https://v2.tauri.app/fr/develop/sidecar/), [pytauri: IPC](https://pytauri.github.io/pytauri/0.6/usage/tutorial/py-js-ipc)
- Slint, Flutter, Wails, WinUI (comparações, sem rigor): [Tauri 2.0 vs Flutter 4.0 desktop](https://dev.to/johalputt/comparison-tauri-20-vs-flutter-40-desktop-for-cross-platform-app-performance-5cng), [Slint: alternative to Flutter](https://slint.dev/alternative-to-flutter), [web-to-desktop framework comparison](https://git.tdem.in/Elanis/web-to-desktop-framework-comparison), [WinUI e RAM (Windows Latest)](https://www.windowslatest.com/2026/10/02/windows-11s-winui-just-got-basic-features-and-less-ram-hogging-after-years-of-losing-apps-to-the-web/)
- A busca não encontrou benchmark rigoroso de WebView2 isolado no Windows; os números acima de Tauri são **desta máquina**.

## 9. Arquivos do experimento (`F:\Jarvis_proto_ui\`)

`measure\measure_qt.py`, `grab_flash.py`, `fps_island.py` (Qt atual) · `measure_tauri.py`, `prof_tauri.py`, `shot_tauri.py`,
`shots_variants.py`, `gif_island.py`, `cdp.mjs` (Tauri) · `qml\island.qml`, `run_qml.py` · `tauri-proto\` (projeto) ·
`backend_stub.py` · `export_schema.py`. Prints e GIF em `capturas/ui-prints\proto-ui\` (34 arquivos, incluindo
`tauri-ilha-animacao.gif`, 6 estados em escuro e claro, e 6 telas de Configurações em 100% e 150%).
