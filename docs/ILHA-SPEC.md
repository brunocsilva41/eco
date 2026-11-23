# Ilha do Eco (Dynamic Island) — Spec v0.1 (2026-11-19)
Origem: entrevista com o usuário. [E]=decisão dele, [P]=proposta nossa a validar, [R]=relato/fonte sem teste na máquina dele.

## 1. Decisões do usuário [E]
- Tecnologia: janela leve nativa (Qt/PySide6 ou equivalente), separada do cérebro.
- Posição: por cima de tudo, centralizada no topo do monitor PRINCIPAL, sem reservar espaço.
- Também pediu: modo "solta" e modo "integrada/colada ao topo" (ver 3: mais um ponto a confirmar).
- Visual: preto fosco, cantos bem redondos, uma cor de destaque (sugestão ciano), transições suaves.
- Cérebro animado: círculo de pontos que pulsa e pisca enquanto ouve, pensa e fala (escala reduzida).
- Tamanhos: pequeno (cérebro/estado), médio (+ texto do que diz e faz), grande (chat e histórico, botão parar, campo de texto). Troca automática (cresce com a tarefa) + manual (clique/atalho que fixa).
- Gatilho primeira versão: palavra de ativação "Eco" (fala em pt-BR). Atalho global e clique ficam como extras [P]. O usuário pediu "voz, atalho ou ação" no pedido original: confirmar se atalho/ação entram já na v1.
- Repouso: quase invisível (linha fina/ponto) e cresce ao ativar.
- Avisos do que faz: DENTRO da ilha, uma linha curta com ícone e passo atual (ex.: "Abrindo o Chrome...").
- Confirmação (apagar, enviar, instalar, pagar): na ilha, com botões Sim/Não e resposta por voz.

## 2. Arquitetura [P]
- Processo da ilha separado do núcleo (llama-server + voz + agente). Conversa por IPC local (WebSocket em 127.0.0.1 ou named pipe). Se a ilha travar, o Eco continua; se o núcleo cair, a ilha mostra erro.
- Eventos núcleo -> ilha: `state` (idle|listening|thinking|acting|speaking|error), `transcript`, `reply_text`, `action_step{icon,text,status}`, `confirm_request{id,text,risk}`, `level{mic,tts}` (para a animação).
- Eventos ilha -> núcleo: `trigger`(clique/atalho), `confirm_answer{id,yes|no}`, `stop`, `size_pref`, `text_input`.
- Estados -> aparência: idle=linha fina; listening=pontos pulsam com o volume da voz; thinking=pontos "neurônios" acendem em onda e conexões piscam; acting=linha de ação com ícone; speaking=pulsa com o áudio do TTS; error=vermelho curto.

## 3. Janela (Windows 10) [R]
- Frameless + translucent + always-on-top. Não roubar foco: `WS_EX_NOACTIVATE` via Win32 (setar lendo o estilo atual e fazendo OR) + `Qt.WA_ShowWithoutActivating`. Motivo: o Eco digita/clica em outros apps e não pode tirar o foco deles.
- Click-through quando em repouso: `WS_EX_LAYERED | WS_EX_TRANSPARENT`; ao ativar, remover o click-through para aceitar cliques. `WA_TransparentForMouseEvents` sozinho não funcionou em relato do fórum Qt.
- Modo "integrada/colada": opções (a) flutuar sobre as janelas sem reservar espaço [E]; (b) AppBar do Windows (`SHAppBarMessage`: ABM_NEW, ABM_QUERYPOS, ABM_SETPOS e ABM_REMOVE ao fechar) para reservar a faixa do topo e as janelas maximizadas não passarem por baixo. Doc oficial Microsoft confirma o fluxo; exemplo em Python/ctypes não achado, validar a estrutura APPBARDATA na doc. O usuário escolheu (a) como padrão; (b) como opção nas configurações [P].
- Monitor principal, centro do topo; reposicionar quando a resolução/monitor mudar.
- Jogos/tela cheia exclusiva: pode não aparecer por cima; testar e documentar [?].

## 4. Animação do cérebro, sem roubar a GPU [P]
- A RX 580 é do LLM (VRAM é curta). Renderizar a ilha por CPU (QPainter) a 30 fps, 60–120 pontos, e PARAR o timer em repouso. Meta: <2% de CPU em repouso, <8% ativa (a medir).
- Alternativa: Qt Quick scene graph (usa GPU) só se o QPainter não ficar fluido; Qt avisa que o custo de partículas cresce com a quantidade; evitar "affectors" em muitos pontos [R].
- Animações de tamanho com curva suave (spring/ease-out) de ~250 ms; nada de bloquear a thread de UI.

## 5. Avisos e confirmação
- Fila de passos: só 1 linha visível (o passo atual), histórico completo no tamanho grande.
- Cada ação mostra: ícone do app/tipo, verbo curto, resultado (ok/erro) e some em ~1,5 s.
- Confirmação: a ilha expande, mostra a ação em 1 linha, botões Sim/Não e escuta "sim/não" por voz; timeout = NÃO. Ação de risco alto sempre exige confirmação, mesmo por voz.
- Tecla de emergência global e botão Parar sempre visíveis quando agindo.

## 6. Fases (entram depois da Fase 2 de voz)
I0 Protótipo visual: janela, 3 tamanhos, animação do cérebro com dados falsos; prova = vídeo curto + medição de CPU/RAM.
I1 Ligar ao núcleo por IPC: estados reais e transcrição.
I2 Avisos de ação e confirmação Sim/Não por clique e voz.
I3 Palavra de ativação "Eco" (openWakeWord) + atalho + clique.
I4 Modo integrada (AppBar), multi-monitor, configurações, inicialização com o Windows.

## 7. Pendências / perguntas ao usuário
- Atalho e "ação/evento" como gatilho entram na v1 ou depois?
- Cor de destaque (ciano ou outra)?
- Qual atalho? Voz do Eco: masculina ou feminina?
- Mostrar a ilha quando um app em tela cheia estiver aberto?

## Fontes
Microsoft Learn (SHAppBarMessage, Application Desktop Toolbars, ABM_QUERYPOS/SETPOS); fórum Qt (WS_EX_NOACTIVATE, click-through em PySide6); Stack Overflow (SetWindowLong WS_EX_NOACTIVATE); PyOverlayKit (PyPI/GitHub); Qt docs (particles, scene graph vs QPainter); wiki Qt Graphics Overview; QNanoPainter.

---
# ATUALIZAÇÃO v0.2 (2026-11-19) — pedidos novos do usuário

## A. Espectro de voz (além dos pontos) [E]
- Além do círculo de pontos, a ilha mostra as frequências da voz reagindo em tempo real: barras/anel que seguem (1) o microfone quando o usuário fala e (2) o áudio do TTS quando o Eco responde.
- Método [R, projetos de visualizador]: janela Hann + rFFT; 24–32 bandas em escala logarítmica (np.geomspace entre ~80 Hz e ~8 kHz); suavização com constante de tempo (~0,06 s, independente do fps) com ataque rápido e queda lenta; DSP separado do desenho. Entrada de áudio com sounddevice.
- Para o TTS: o ÁUDIO que sai (não o texto) passa pelo mesmo analisador, sincronizado com o que toca (compensar o atraso do buffer de saída).
- Composição: pontos = "pensamento" (thinking); barras de espectro = "voz" (listening/speaking). Podem se fundir: o anel de pontos vira o anel do espectro ao falar.

## B. Gatilhos obrigatórios (todos personalizáveis) [E]
1. Voz: palavra de ativação personalizável. [R] openWakeWord permite treinar palavra própria com voz sintética (Piper) + ruído; projeto HAwake traz interface e roda em PowerShell/Windows; dado de um modelo 100% sintético: falsos alarmes caíram de ~4.000 para ~90/hora só com ruído sintético e a zero com áudio real, então gravar amostras REAIS do usuário. Treino completo levou ~1 h numa GPU forte (4090): estimar bem mais na RX 580 ou treinar na CPU. Verificador de falso positivo: não confirmado como se faz, pesquisar no repositório oficial. Tela de configuração: digitar a palavra, gravar 10–20 amostras, testar sensibilidade e ver taxa de falsos.
2. Combinação de teclas: `RegisterHotKey` do Windows é o preferido em relação a hook de baixo nível [R]; checar o retorno, porque combinações reservadas pelo Windows 10 falham em silêncio (ex.: Win+J): se falhar, pedir outra combinação. Modos: apertar-e-falar (segurar), alternar, e "abrir ilha". Tela de configuração: capturar a combinação e validar conflito. Alerta: antivírus pode marcar hooks globais de teclado (pynput).
3. API/função: o Eco é chamável por outros programas e scripts: API local em 127.0.0.1 [R: padrão de projetos]: REST + WebSocket de eventos, JSON-RPC, token Bearer no cabeçalho Authorization (nunca na URL), health check como única rota sem token, desligar/administrar só por loopback. Também expor um servidor MCP para outros agentes (ex.: os do OpenBot) chamarem o Eco, com credencial própria. Funções iniciais: `trigger(source)`, `say(text)`, `ask(text)`, `run(command)`, `status()`, `stop()`, `set_size()`. Cada chamada registra a origem e passa pela mesma lista de ações permitidas e confirmações.
- Config única (arquivo versionado, ex.: `config.toml`): palavra, sensibilidade, teclas, token da API, porta, tamanho padrão, tema.

## C. Design excepcional e profissional [P]
- Sistema de design com tokens (cor, raio, espaçamento em grade de 8 px, tipografia, sombra, movimento) em um único arquivo; sem valores soltos no código.
- Visual: preto OLED fosco (#000/#0A0A0C), borda interna fina de 1 px translúcida, cantos com raio proporcional ao tamanho (pílula), 1 cor de destaque + 1 de alerta + 1 de sucesso; tipografia Segoe UI Variable (nativa do Win 11; no Win 10 usar Inter ou Segoe UI) com números tabulares.
- Cores por estado: ouvindo=ciano; pensando=violeta suave; agindo=azul; falando=ciano brilhante; confirmação=âmbar; erro=vermelho curto; sucesso=verde curto.
- Movimento: tokens (rápido 120 ms, normal 220 ms, lento 360 ms); curva ease-out/spring para crescer e encolher; toda animação interrompível; o estado sempre responde na hora a uma ação do usuário.
- Acessibilidade: respeitar "reduzir movimento" do Windows (versão sem partículas, só mudança de cor e barra simples); cor nunca é a única informação (ícone + texto); contraste alto; DPI 100–200%; leitura por leitor de tela quando possível.
- Detalhes premium: ícones consistentes (um só conjunto, ex.: Fluent/Lucide), microtransições entre texto de passos, sombra suave, sem janelas extras, sem piscar, glow discreto no cérebro.
- Prova visual: capturas/vídeo em cada tamanho e estado + medida de CPU/RAM; revisão pelo usuário antes de avançar.

## D. Onde profissionalizar, melhorar e incluir
Profissionalizar:
- Config tipada e versionada, com validação e valores padrão; migração entre versões.
- Logs estruturados com rotação + log de auditoria de toda ação do PC (quem pediu: voz, tecla ou API).
- Modelo de permissões por ferramenta (nível 0 ler, 1 controlar, 2 arriscado) com confirmação e lista permitida; sem shell livre.
- Testes: unidade (DSP, máquina de estados, parser de comandos), integração (IPC), e roteiro manual de aceitação; CI local.
- Comando `doctor`: checa driver Vulkan, modelos, microfone, porta, permissões e mostra o que falta.
- Instalador/atualização: empacotar (PyInstaller/Nuitka ou instalador MSIX/Inno) com inicialização com o Windows; hash dos modelos; reinício automático se o núcleo cair (watchdog).
- Observabilidade local: painel de latência por etapa (VAD, STT, LLM, TTS) e uso de VRAM/RAM.
Melhorar:
- Governador de recursos: diminuir ou pausar a animação e descarregar modelos quando houver jogo/vídeo pesado; modelo some da VRAM após N minutos parado.
- Latência: TTS em streaming por frase, STT com VAD, cache do prompt do sistema; orçamento de latência alvo (fala->primeira palavra < ~3 s).
- Cancelamento de eco e barge-in (interromper o Eco falando); push-to-talk como padrão seguro.
- Indicador de privacidade: ícone fixo mostrando quando o microfone/tela estão em uso; modo "mudo" por tecla.
- Resiliência: se o LLM travar, a ilha avisa e oferece reiniciar.
Incluir:
- Perfis (trabalho, casa, foco) com atalhos e tom de voz diferentes.
- Sistema de plugins/ferramentas com manifesto (nome, permissão, descrição) para o agente listar o que sabe fazer.
- Memória e notas (SQLite) e lembretes proativos na ilha.
- Histórico pesquisável e exportação; modo "não perturbe".
- Atalhos de texto: digitar na ilha como alternativa à voz.
- Possível identificação de voz do dono [?]: não pesquisado; tratar como pesquisa futura.

## E. Fases atualizadas
I0 protótipo visual (3 tamanhos, pontos + espectro com áudio de teste, tokens de design, medição de CPU);
I1 IPC com o núcleo; I2 avisos + confirmação Sim/Não; I3 gatilhos: voz personalizada + combinação de teclas + API local com token; I4 AppBar/multi-monitor/configurações/autostart/instalador; I5 profissionalização (logs, auditoria, doctor, testes, watchdog).

## Fontes novas
openWakeWord (GitHub/HF), HAwake e outros treinadores, LiveKit wakeword docs; RegisterHotKey/pynput (GitHub issues, wxPython forum, PyPI global-hotkeys); projetos de visualizador FFT (Realtime_PyAudio_FFT, lookas, cli-audio-visualizer); padrões de API local (Kimi CLI server API, Flynn gateway, Octomind WebSocket, guias MCP); guias de movimento e reduced-motion (Intuit, Cloudscape, Atlassian, Smashing Magazine, WCAG 2.3.3). Não achei as páginas da Apple (HIG/Live Activities) nem da Microsoft (Fluent) nas buscas: conferir diretamente.

---
# ATUALIZAÇÃO v0.3 (2026-11-22): layouts dos 3 tamanhos (implementados na I0)

Posição: topo central do monitor principal, colada à borda (sem margem), só cantos de baixo arredondados, janela do tamanho exato da pílula (clique fora passa), sem foco. Troca de tamanho 260 ms (mola ao crescer). Automático: repouso=compacta, conversa=média, confirmação=grande; clique fixa/alterna (grande, média, compacta, automático).

| Tamanho | Medida | Regiões (x,y em px lógicos) | Dados |
|---|---|---|---|
| Compacta | 208x36 | mic 20 @(12,8); rótulo @x40; cronômetro (só ACTING); 6 barras 3+3 px; ponto 6 px à direita | estado (ícone, texto, ponto), tempo da ação |
| Média | 380x64 | mic 24 @(16,20); rótulo 13 semibold @(52,10); cronômetro à direita; frase 12 @(52,32); 14 barras @x280 | estado, ação ('Executando: ...'), última frase (fala ou resposta), cronômetro, nível ao vivo |
| Grande | 520x200 | cabeçalho y12 (mic 24, estado 16, chips, cronômetro); espectro y44..72 (49 barras 6+4); fala/resposta y78..129 (3 linhas de 17, rolagem); ação y134..150; linha y156..188 (contexto + botões 32) | state, transcript, reply_text, action_step, context_usage, yolo (contagem), mute, permission_mode, confirm_request |

Tipografia do tema (11/12/13/16), numerais tabulares nos números (cronômetro, contexto, YOLO). Eventos do núcleo entram por `ui/island/bridge.py`: state, transcript, reply_text, action_step, confirm_request/confirm_done, context_usage, yolo, mute, emergency, error; `level` só alimenta as ondas. Saída da Ilha: `confirm_answered`, `stop_requested`, `mute_toggled`, `settings_requested` (a ligar ao núcleo na I1).

---
# ATUALIZAÇÃO v0.4 (2026-11-22): escondida por padrão, modo flutuante, redesign, atalhos nos botões, otimização

## Presença (escondida por padrão)
A janela fica OCULTA (SW_HIDE): zero timers, zero repinturas. Aparece só quando:
- (a) o mouse chega ao centro do topo da tela (zona do tamanho da Ilha x 3 px; permanência de 160 ms contra acidente; `ui.island_hover_reveal`);
- (b) o núcleo entra em LISTENING (tecla F9 e, no futuro, a palavra de ativação: o gatilho é o ESTADO, não há detecção de palavra na Ilha), e nos estados seguintes (transcrevendo, pensando, agindo, falando);
- (c) há confirmação pendente: SEMPRE aparece (até em tela cheia) e fica até responder ou expirar (sem resposta = Não);
- (d) erro e parada de emergência (5 s), mudo e YOLO ligado/desligado (aviso de 2,5 s com texto próprio na compacta).
Esconde sozinha `ui.island_hide_delay_s` (padrão 3 s) depois de IDLE, NUNCA com o mouse em cima, em confirmação, falando/agindo ou fixada pelo alfinete (Ilha grande). Entrada: desliza do topo + fade 280 ms; saída 200 ms; 'reduzir animações' = instantâneo. Tela cheia (jogo/vídeo) continua escondida, exceto confirmação; a checagem de tela cheia só roda com a Ilha visível (700 ms) ou no instante de revelar.
`ui.island_autohide = false` mantém a Ilha sempre visível (como antes).

## Zona do mouse: janela mínima x polling (MEDIDO, com a Ilha escondida, 30 s)
| Estratégia | Ciclos de CPU | Acordadas |
|---|---|---|
| janela-zona transparente (`HotZone`, alfa 1/255) | 0,02 Mciclos/s | 0,0 /s |
| `GetCursorPos` a 10 Hz (`CursorPoller`) | 3,84 Mciclos/s | 17,6 /s |
Escolhida: a janela-zona (zero acordadas). Custo: a faixa de 256x3 px no centro do topo não deixa o clique passar para o app de baixo enquanto a Ilha está escondida. Reserva: `JARVIS_ISLAND_ZONE=poll`.

## Modo de posição (`ui.island_mode`, ao vivo)
`docked`: colada ao topo, só os cantos de baixo arredondados. `floating`: pílula totalmente arredondada, afastada `ui.island_float_gap_px` (0..64, padrão 10) do topo, borda branca a 9% e sombra suave (8 camadas translucidas pintadas UMA vez no cache do tamanho; sem QGraphicsEffect/blur). Config, schema, Configurações > Funcionamento > Ilha do Eco: `island_mode`, `island_float_gap_px`, `island_autohide`, `island_hide_delay_s`, `island_hover_reveal`. O núcleo manda a mensagem `config` ao subir o filho e a cada `config_applied` (aplicação ao vivo, sem reiniciar).

## Redesign
Preto profundo `#050608`, cor de destaque única (`tokens.ACCENT_*`), ok/aviso/erro da paleta (AA). Grade de 4 px. Tamanhos: compacta 208x36, média 380x64, grande 600x248 (cabeçalho com emblema, título, chips de modo/YOLO/mudo, contexto, tempo e alfinete; espectro; conversa; ação com progresso linear; botões com keycap). Ícones TODOS em vetor (`glyphs.py`, grade 24, traço 1,75/2 px): microfone (repouso, ouvindo com anel, mudo, erro), parar, check, x, mudo, engrenagem, alfinete, raio (YOLO), escudo, contexto, ferramenta, erro, relógio. Ícones de estado próprios e animados: Ouvindo (anel pulsante), Transcrevendo (linhas), Pensando (3 pontos orbitais), Executando (engrenagem + arco de progresso), Falando (ondas), Confirmando (escudo pulsando). Morfose: cada tamanho é pintado uma vez no tamanho nativo; a troca é cross-fade + escala 0,94 a 1 com mola. Texto/estado trocam com fade + deslocamento de 3 px (150 ms). Ondas em camadas: halo (brilho), barras de fundo, barras da frente com gradiente, picos que caem; reagem ao nível real. Respiração no repouso nos primeiros 6 s visíveis. Botões: hover (110 ms), pressionado, anel de foco de teclado de 2 px.

## Atalhos nos botões
Sim ⟨Ctrl+Alt+Y⟩, Não ⟨Ctrl+Alt+N⟩, Parar ⟨Ctrl+Alt+F12⟩, Mudo ⟨Ctrl+Alt+M⟩, Falar ⟨F9⟩ (dica; o gatilho é o núcleo), YOLO ⟨Ctrl+Alt+Shift+Y⟩ (clique só abre Configurações > Permissões: o YOLO NUNCA liga por clique), Configurações (sem atalho). Os valores vêm de `safety.*_hotkey` pela mensagem `config` do núcleo. Local, SÓ com o foco da Ilha (ela nunca rouba foco nem captura teclas globais): Enter = Sim e Esc = Não durante a confirmação; Tab/Shift+Tab/Espaço nos botões.

## Otimização (antes -> depois, processo filho real, máquina livre: ffmpeg parados, carga 2 a 10%)
| Decisão | Efeito |
|---|---|
| Sem numpy no filho (ondas e níveis em listas de float); `bridge`/`waves` não importam `dsp` | memória PRIVADA 824 MB -> 34 MB (o OpenBLAS reservava ~790 MB); conjunto de trabalho visível 84 -> 62 MB |
| Sem ThemeManager.apply (stylesheet), sem kit/Button, botões pintados à mão; barramento local sem threads | menos módulos, menos QWidget |
| Escondida = janela oculta + `SetProcessWorkingSetSize` (-1,-1) ao esconder e na partida; caches (ícones, sprites, camadas) liberados ao esconder | conjunto de trabalho escondida 80 -> 1,4 a 6 MB; privado 34 MB |
| Zona do mouse por janela mínima | 0,02 Mciclos/s escondida (0 acordadas/s) |
| Timers só com a Ilha visível e algo animando; 60 fps voz/transições, 30 fps pensar/agir/confirmar, 15 fps respiração (6 s), 0 fps estático | repouso visível estático 0,03% de 1 núcleo |
| Ondas por sprites (1 pixmap por altura em px físicos, cacheados) em vez de retângulos com gradiente por quadro | quadro grande 3,9 -> 1,0 ms |
| Ícones de estado e botões cacheados como QPixmap por quadro de animação/estado | quadro médio 0,68 -> 0,31 ms |
| Recorte do corpo só durante transição; camadas estáticas por tamanho e DPR (texto pintado só quando muda) | |
| Prioridade BELOW_NORMAL no filho | |
Números (MESMO harness para os dois: processo filho real, estados enviados pelo pipe, níveis a 30 Hz, `QueryProcessCycleTime`, % de 1 núcleo a 3 GHz assumidos; máquina com ffmpeg parados e carga 2 a 28%):
| Fase | ANTES (I1) | DEPOIS (v2) |
|---|---|---|
| Escondida (sem janela) | n/a (sempre visível) | ~0% (0,02 Mciclos/s), conjunto de trabalho 1,4 a 6 MB, privado 34 MB |
| Visível em repouso estático | 0,06% | 0,03% |
| Respiração do repouso (6 s) | 2,9% (sem limite) | 1,2% (15 fps, só 6 s) |
| Ouvindo (média, 60 fps) | 10,7% | 3,9% |
| Falando (média, 60 fps) | 9,9% | 3,8% |
| Transcrevendo / pensando / executando (30 fps) | 4,4 / 4,7 / 4,5% | 1,9 / 2,0 / 2,8% |
| Confirmação (grande, 30 fps) | 9,0% | 2,6% |
| Conjunto de trabalho visível | 85 a 90 MB | 19 a 32 MB |
| Memória privada | 824 MB | 34 a 48 MB |
| Revelar + ouvir + esconder (1 ciclo) | n/a | 87 a 133 ms de CPU |
(Pelo `cpu_percent` do psutil o 'antes' deu 4,9% ouvindo e 4,7% falando com a máquina mais livre; o harness de ciclos é mais fiel.) Metas: RAM < 60 MB escondida (34 MB privado, 1,4 MB de conjunto de trabalho: atingida); CPU escondida ~0% (atingida); <= 5% de 1 núcleo falando (3,8%: atingida).
