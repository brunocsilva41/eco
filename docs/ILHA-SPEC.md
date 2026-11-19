# Ilha do Jarvis (Dynamic Island) — Spec v0.1 (2026-11-19)
Origem: entrevista com o Bruno. [E]=decisão dele, [P]=proposta nossa a validar, [R]=relato/fonte sem teste na máquina dele.

## 1. Decisões do Bruno [E]
- Tecnologia: janela leve nativa (Qt/PySide6 ou equivalente), separada do cérebro.
- Posição: por cima de tudo, centralizada no topo do monitor PRINCIPAL, sem reservar espaço.
- Também pediu: modo "solta" e modo "integrada/colada ao topo" (ver 3: mais um ponto a confirmar).
- Visual: preto fosco, cantos bem redondos, uma cor de destaque (sugestão ciano), transições suaves.
- Cérebro animado: círculo de pontos que pulsa e pisca enquanto ouve, pensa e fala (escala reduzida).
- Tamanhos: pequeno (cérebro/estado), médio (+ texto do que diz e faz), grande (chat e histórico, botão parar, campo de texto). Troca automática (cresce com a tarefa) + manual (clique/atalho que fixa).
- Gatilho primeira versão: palavra de ativação "Jarvis" (fala em pt-BR). Atalho global e clique ficam como extras [P]. O Bruno pediu "voz, atalho ou ação" no pedido original: confirmar se atalho/ação entram já na v1.
- Repouso: quase invisível (linha fina/ponto) e cresce ao ativar.
- Avisos do que faz: DENTRO da ilha, uma linha curta com ícone e passo atual (ex.: "Abrindo o Chrome...").
- Confirmação (apagar, enviar, instalar, pagar): na ilha, com botões Sim/Não e resposta por voz.

## 2. Arquitetura [P]
- Processo da ilha separado do núcleo (llama-server + voz + agente). Conversa por IPC local (WebSocket em 127.0.0.1 ou named pipe). Se a ilha travar, o Jarvis continua; se o núcleo cair, a ilha mostra erro.
- Eventos núcleo -> ilha: `state` (idle|listening|thinking|acting|speaking|error), `transcript`, `reply_text`, `action_step{icon,text,status}`, `confirm_request{id,text,risk}`, `level{mic,tts}` (para a animação).
- Eventos ilha -> núcleo: `trigger`(clique/atalho), `confirm_answer{id,yes|no}`, `stop`, `size_pref`, `text_input`.
- Estados -> aparência: idle=linha fina; listening=pontos pulsam com o volume da voz; thinking=pontos "neurônios" acendem em onda e conexões piscam; acting=linha de ação com ícone; speaking=pulsa com o áudio do TTS; error=vermelho curto.

## 3. Janela (Windows 10) [R]
- Frameless + translucent + always-on-top. Não roubar foco: `WS_EX_NOACTIVATE` via Win32 (setar lendo o estilo atual e fazendo OR) + `Qt.WA_ShowWithoutActivating`. Motivo: o Jarvis digita/clica em outros apps e não pode tirar o foco deles.
- Click-through quando em repouso: `WS_EX_LAYERED | WS_EX_TRANSPARENT`; ao ativar, remover o click-through para aceitar cliques. `WA_TransparentForMouseEvents` sozinho não funcionou em relato do fórum Qt.
- Modo "integrada/colada": opções (a) flutuar sobre as janelas sem reservar espaço [E]; (b) AppBar do Windows (`SHAppBarMessage`: ABM_NEW, ABM_QUERYPOS, ABM_SETPOS e ABM_REMOVE ao fechar) para reservar a faixa do topo e as janelas maximizadas não passarem por baixo. Doc oficial Microsoft confirma o fluxo; exemplo em Python/ctypes não achado, validar a estrutura APPBARDATA na doc. O Bruno escolheu (a) como padrão; (b) como opção nas configurações [P].
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
I3 Palavra de ativação "Jarvis" (openWakeWord) + atalho + clique.
I4 Modo integrada (AppBar), multi-monitor, configurações, inicialização com o Windows.

## 7. Pendências / perguntas ao Bruno
- Atalho e "ação/evento" como gatilho entram na v1 ou depois?
- Cor de destaque (ciano ou outra)?
- Qual atalho? Voz do Jarvis: masculina ou feminina?
- Mostrar a ilha quando um app em tela cheia estiver aberto?

## Fontes
Microsoft Learn (SHAppBarMessage, Application Desktop Toolbars, ABM_QUERYPOS/SETPOS); fórum Qt (WS_EX_NOACTIVATE, click-through em PySide6); Stack Overflow (SetWindowLong WS_EX_NOACTIVATE); PyOverlayKit (PyPI/GitHub); Qt docs (particles, scene graph vs QPainter); wiki Qt Graphics Overview; QNanoPainter.

---
# ATUALIZAÇÃO v0.2 (2026-11-19) — pedidos novos do Bruno

## A. Espectro de voz (além dos pontos) [E]
- Além do círculo de pontos, a ilha mostra as frequências da voz reagindo em tempo real: barras/anel que seguem (1) o microfone quando o Bruno fala e (2) o áudio do TTS quando o Jarvis responde.
- Método [R, projetos de visualizador]: janela Hann + rFFT; 24–32 bandas em escala logarítmica (np.geomspace entre ~80 Hz e ~8 kHz); suavização com constante de tempo (~0,06 s, independente do fps) com ataque rápido e queda lenta; DSP separado do desenho. Entrada de áudio com sounddevice.
- Para o TTS: o ÁUDIO que sai (não o texto) passa pelo mesmo analisador, sincronizado com o que toca (compensar o atraso do buffer de saída).
- Composição: pontos = "pensamento" (thinking); barras de espectro = "voz" (listening/speaking). Podem se fundir: o anel de pontos vira o anel do espectro ao falar.

## B. Gatilhos obrigatórios (todos personalizáveis) [E]
1. Voz: palavra de ativação personalizável. [R] openWakeWord permite treinar palavra própria com voz sintética (Piper) + ruído; projeto HAwake traz interface e roda em PowerShell/Windows; dado de um modelo 100% sintético: falsos alarmes caíram de ~4.000 para ~90/hora só com ruído sintético e a zero com áudio real, então gravar amostras REAIS do Bruno. Treino completo levou ~1 h numa GPU forte (4090): estimar bem mais na RX 580 ou treinar na CPU. Verificador de falso positivo: não confirmado como se faz, pesquisar no repositório oficial. Tela de configuração: digitar a palavra, gravar 10–20 amostras, testar sensibilidade e ver taxa de falsos.
2. Combinação de teclas: `RegisterHotKey` do Windows é o preferido em relação a hook de baixo nível [R]; checar o retorno, porque combinações reservadas pelo Windows 10 falham em silêncio (ex.: Win+J): se falhar, pedir outra combinação. Modos: apertar-e-falar (segurar), alternar, e "abrir ilha". Tela de configuração: capturar a combinação e validar conflito. Alerta: antivírus pode marcar hooks globais de teclado (pynput).
3. API/função: o Jarvis é chamável por outros programas e scripts: API local em 127.0.0.1 [R: padrão de projetos]: REST + WebSocket de eventos, JSON-RPC, token Bearer no cabeçalho Authorization (nunca na URL), health check como única rota sem token, desligar/administrar só por loopback. Também expor um servidor MCP para outros agentes (ex.: os do OpenBot) chamarem o Jarvis, com credencial própria. Funções iniciais: `trigger(source)`, `say(text)`, `ask(text)`, `run(command)`, `status()`, `stop()`, `set_size()`. Cada chamada registra a origem e passa pela mesma lista de ações permitidas e confirmações.
- Config única (arquivo versionado, ex.: `config.toml`): palavra, sensibilidade, teclas, token da API, porta, tamanho padrão, tema.

## C. Design excepcional e profissional [P]
- Sistema de design com tokens (cor, raio, espaçamento em grade de 8 px, tipografia, sombra, movimento) em um único arquivo; sem valores soltos no código.
- Visual: preto OLED fosco (#000/#0A0A0C), borda interna fina de 1 px translúcida, cantos com raio proporcional ao tamanho (pílula), 1 cor de destaque + 1 de alerta + 1 de sucesso; tipografia Segoe UI Variable (nativa do Win 11; no Win 10 usar Inter ou Segoe UI) com números tabulares.
- Cores por estado: ouvindo=ciano; pensando=violeta suave; agindo=azul; falando=ciano brilhante; confirmação=âmbar; erro=vermelho curto; sucesso=verde curto.
- Movimento: tokens (rápido 120 ms, normal 220 ms, lento 360 ms); curva ease-out/spring para crescer e encolher; toda animação interrompível; o estado sempre responde na hora a uma ação do usuário.
- Acessibilidade: respeitar "reduzir movimento" do Windows (versão sem partículas, só mudança de cor e barra simples); cor nunca é a única informação (ícone + texto); contraste alto; DPI 100–200%; leitura por leitor de tela quando possível.
- Detalhes premium: ícones consistentes (um só conjunto, ex.: Fluent/Lucide), microtransições entre texto de passos, sombra suave, sem janelas extras, sem piscar, glow discreto no cérebro.
- Prova visual: capturas/vídeo em cada tamanho e estado + medida de CPU/RAM; revisão pelo Bruno antes de avançar.

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
- Cancelamento de eco e barge-in (interromper o Jarvis falando); push-to-talk como padrão seguro.
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
