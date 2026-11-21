# Decisões de design: base da repaginação (theme + kit)

Direção: `OpenBot\Shared\jarvis\DESIGN.md`. Skill: antislop, modo DURING (core + antislop-ui), declarado pelo dono na tarefa. Código: `src/jarvis/ui/theme.py`, `ui/strings.py`, `ui/kit/`. Galeria: `python -m jarvis.ui.kit.gallery`.

## Design Read
Ferramenta de controle pessoal, usada todo dia por uma pessoa só, em linguagem de painel de instrumentos: sóbria, densa na medida, legível a 1 m. **Dials: ENERGY 2 / RHYTHM 2 / MOTION 1.**
- ENERGY 2: um acento âmbar nos momentos-chave, resto neutro grafite.
- RHYTHM 2: seções com dois níveis de respiro (32/12 e 16/8); cartão só para unidade independente; estados e listas com composições diferentes.
- MOTION 1: só transições de 120 a 180 ms (foco, barra de ações, interruptor, toast). Único laço: indicador ouvindo/gravando. "Reduzir animações" do Windows zera tudo.

## Paleta (2 neutros + 1 acento + 3 estados)
Escuro (valores do DESIGN.md) e claro (mesma família de matiz grafite frio, elevação invertida: a superfície sobe em direção ao branco). Os estados e o acento no claro são DERIVADOS por código (`ensure_contrast`: mesmo matiz, luminosidade ajustada até a razão exigida contra todas as superfícies e o chip).

| Token | Escuro | Claro | Por quê |
|---|---|---|---|
| bg / surface / raised | #0E1013 / #151920 / #1C2129 | #EDEFF2 / #F7F8FA / #FFFFFF | fundo, painel, elemento elevado; hierarquia por tom, não por sombra |
| border / border_strong | #2A303B / #666D7B | #D4D8DF / #828995 | separador decorativo / borda de controle (>= 3:1) |
| text / text_muted | #E8EAED / #98A1AF | #14181E / #5B6471 | corpo >= 7:1, apoio >= 4.5:1 |
| accent (preenchimento) | #F5B544 | #F5B544 | botão primário, gravação ativa |
| accent_ink (texto/linha/foco) | #F5B544 | #936108 | âmbar legível sobre claro; anel de foco e marcador |
| on_accent | #1A1305 | #1A1305 | texto sobre âmbar |
| ok / warn / error | #62C98A / #FF8F5A / #FF5C6C | #267043 / #B13900 / #C10013 | estado sempre com ícone e texto |

Acento só em: botão primário, item de navegação atual (marcador), anel de foco, gravação ativa (anel da contagem, indicador), captura de tecla. Proibido: azul/roxo/ciano, gradiente, vidro, grade, neon.

## Pares de contraste calculados (WCAG 2.x, função `contrast_pairs` em `kit/color.py`)
Mínimos: texto normal 4.5, corpo principal 7 (meta interna), componente/foco 3. Todos passam (0 falhas nos dois temas).

| Par | Escuro | Claro | Mín. |
|---|---|---|---|
| texto / fundo | 15.81 | 15.46 | 7 |
| texto / superfície | 14.62 | 16.76 | 7 |
| texto / elevada | 13.41 | 17.81 | 7 |
| secundário / fundo | 7.31 | 5.20 | 4.5 |
| secundário / superfície | 6.76 | 5.64 | 4.5 |
| secundário / elevada | 6.20 | 5.99 | 4.5 |
| acento (tinta) / superfície | 9.71 | 5.00 | 4.5 |
| acento (tinta) / elevada | 8.91 | 5.31 | 4.5 |
| borda de campo / superfície | 3.39 | 3.32 | 3 |
| borda de campo / elevada | 3.11 | 3.52 | 3 |
| ok / superfície | 8.59 | 5.68 | 4.5 |
| warn / superfície | 7.83 | 5.72 | 4.5 |
| error / superfície | 5.87 | 6.03 | 4.5 |
| on_accent / primário (normal, hover, pressionado) | 10.16, 10.91, 7.54 | idem | 4.5 |
| texto sobre perigo | 6.14 | 6.41 | 4.5 |
| anel de foco / fundo | 10.50 | 4.61 | 3 |
| borda do primário / fundo | 10.50 | 4.61 | 3 |
| ok / chip ok | 6.57 | 4.71 | 4.5 |
| warn / chip warn | 6.14 | 4.66 | 4.5 |
| error / chip error | 4.93 | 4.68 | 4.5 |
| secundário / chip neutro | 5.16 | 5.21 | 4.5 |

Texto desabilitado (#65686E / #A1A3A6) é isento (WCAG), usado só em controles desabilitados.

## Tipografia
Segoe UI Variable Text, reserva Segoe UI (família de sistema do Windows: o produto é Windows-only, a fonte do sistema é a que o usuário já lê melhor e acompanha o ClearType). Escala em px de design convertida para pontos (px*72/96), então segue DPI e escala do Windows: **11 caption, 12 ajuda, 13 corpo (base), 16 seção, 20 título, 28 frase, 48 contador tabular**. Pesos 400, 600, 700 (só números grandes). Linha 1,4 corpo e 1,2 títulos (padrão do Qt aproxima). Numerais tabulares (`tnum`) em medidor e contador.

## Espaçamento, forma, profundidade
- Grade de 4: 4/8/12/16/24/32/48. Dentro do grupo 12, entre grupos 24 a 32, margem de janela 24.
- Raios 4 (campos, botões, chips de lista, marcador), 8 (cartão, aviso, toast), 12 (diálogo). Pílula só em StatusChip e no trilho do interruptor (que é um interruptor, não um botão).
- Borda 1 px; foco 2 px âmbar com 2 px de folga. Alvo mínimo 32 px.
- Sombra: nenhuma. Diálogo usa a moldura do Windows. Hierarquia por tom e borda.
- Movimento: 120/150/180 ms, ease-out cúbico.

## Decisões (uma linha de motivo cada, R-31)
- Marcador âmbar de 3 px no item atual da NavList: carrega estado (qual página está aberta), não enfeite.
- Interruptor com texto "Ligado/Desligado" e botão que muda de lado: estado nunca só por cor.
- Medidor com nome escrito em cada faixa e numeral: baixo/ótimo/saturado legível sem cor.
- Glow e pulso só no ListeningIndicator: é o estado vivo do produto (captura de áudio) e precisa ser visto de longe; usa um gradiente radial único, justificado por R-01/R-13.
- Ícones próprios: pontas retas, juntas em esquadro, cantos chanfrados a 45 graus (voz de mostrador de cabine, evita o visual de biblioteca arredondada); `settings` é um painel de ajustes porque configuração aqui é ajustar valores; `brain` representa o modelo; `memory` é caixa de arquivo.
- FieldRow lado a lado com ajuda de uma linha cortada com reticências e dica: mantém a coluna escaneável; `stacked` para campos largos.
- Section com dois níveis de ritmo (32/12 e 16/8) e sem caixa: hierarquia por espaço.
- Campos protegidos com cadeado e motivo escrito, controle desabilitado.
- ConfirmDialog: foco inicial em Cancelar, Esc cancela, alvo real inteiro, palavra digitada para destrutivas.
- NumberField sobre QLineEdit (não QSpinBox): o spin com QSS colapsava a área de edição; os botões -/+ têm 32 px.
- Estados vazio/carregando/erro alinhados à esquerda, escritos para humanos, com a ação que resolve.
- Strings centralizadas em `ui/strings.py` (dataclasses, `set_strings` para outro idioma), sem travessão.

## Checklist antislop (Delivery Gate)
Bloco 1 (Hard Gate), respostas todas "não" = PASS
- R-02 PASS: grep de travessão nos .py do kit, theme e strings: 0 ocorrências.
- R-03 PASS com ressalva: layout redimensionável e alvos >= 32 px; verificado só offscreen em 100/150/200%, sem janela real estreita.
- R-17/R-18/R-36/R-38 PASS: nenhum número, depoimento ou alegação inventada; textos da galeria são exemplos de interface e rotulados como tal; números do contraste são calculados.
- R-23 PASS: nenhum logotipo, avatar ou imagem criado.
- R-24/R-26 PASS: NavList da galeria muda de página de verdade; todo botão da galeria tem ação ou é demonstração de estado (rotulada).
- R-25 PASS: tabela acima, 0 falhas.
- R-27 PASS: EmptyState, LoadingState, ErrorState existem e aparecem na galeria.
- R-28 N/A (sem FAQ).
- R-32 PASS com ressalva: anel de foco desenhado em todo controle focável (ver print `foco-e-interacao`); Tab/Esc/Enter/Espaço implementados por herança Qt e código, exercitados só nos prints (Enter em KeyCapture, foco programático). Navegação completa por teclado não foi testada manualmente.
- R-33 PASS: nenhum script de patch.
- R-34 PASS: dois temas nos prints (escuro e claro, 100/150/200%), troca em tempo de execução.
- R-35 PARCIAL: galeria executada offscreen sem erros no console; cliques reais não feitos (instrução de não rodar testes).
- R-37 PASS: direção do DESIGN.md aplicada.
- R-39 PASS com ressalva: cursor de mão em botões, interruptor, lista, combo, nav; accessibleName/Description em todos; reduzir animações respeitado; o pulso do indicador passa de 5 s (loop) porque marca captura ativa que o usuário encerra com Parar. Leitor de tela não testado.
- R-40 N/A (desktop).

Bloco 2 (Purpose-Gate)
- R-01 PASS: sem gradientes, exceto o glow radial do indicador (motivo acima). R-04 PASS: conjunto próprio, relevância escrita acima, sem ícones de IA. R-06 PASS: fonte do sistema com motivo; sem monoespaçada nem caixa-alta espaçada. R-07 PASS: sem grade de fundo. R-08 PASS: sem setas decorativas. R-09 PASS: só o selo de estado, com função. R-10 PASS: sem vidro. R-12 PASS: sem sombras. R-13 PASS: um glow. R-14 PASS: um único Card, só para unidade independente. R-19 PASS: movimento 120 a 180 ms com propósito; o laço é o do indicador. R-22 PASS: sem ilustrações.

Bloco 3 (Liveliness): dials declarados e coerentes; um foco por tela (a ação primária âmbar); espaço estrutural (dois ritmos); um acento deliberado; motivo de identidade = marcador/foco âmbar + ícones chanfrados + numerais tabulares; Design Read declarado.

Bloco 4: C-1 a C-5, R-05, R-11, R-15, R-16 (sem buzzwords), R-20, R-21 (escuro padrão com tema claro funcional e modo sistema), R-29 (2 neutros + 1 acento + 3 estados), R-30, R-31: PASS. Ressalva R-20: a identidade completa só se confirma nas telas reais.

## Não verificado
Só offscreen; fonte Segoe UI Variable ausente nesta máquina (usou Segoe UI); DPI real por monitor, leitor de tela, hover real com mouse, e navegação completa por teclado não foram testados.

## Tela: Gravador de voz
Código: `src/jarvis/ui/recorder/` (fachada `ui/recorder_window.py`). Prints: `Shared/jarvis/ui-prints/gravador/<estado>-<tema>-<escala>.png`.

**Design Read:** ferramenta de uso diário, tarefa única e repetitiva (ler, gravar, conferir, seguir), linguagem de painel de instrumentos. Dials ENERGY 2 / RHYTHM 2 / MOTION 1. Decisão da tela: "gravei bem esta frase e posso ir para a próxima?".

**Decisões (R-31):**
- Coluna central de leitura (720 px) com a frase em 28 px como foco único; lista lateral em cartão único (unidade independente), o resto sem caixas.
- Gravar é o único botão âmbar; depois de gravar o âmbar passa para Próxima (a ação seguinte), nunca os dois juntos.
- Tecla de atalho escrita em cada botão (plaquinha de contorno): o atalho visível, sem depender da dica.
- Estado do take em StatusChip (ícone + palavra) e, na lista, ícone + palavra por linha: estado nunca só por cor.
- Faixas do medidor e avisos de nível escritos em três linhas (o que houve, por que importa, o que fazer).
- ListeningIndicator só durante a gravação (único glow); anel de contagem âmbar só gravando.
- Estados vazio, carregando e erro reais (conjunto, arquivo de frases ilegível, lista vazia).
- Fechar gravando, substituir arquivo e editar/remover/mover frase já gravada pedem ConfirmDialog com o alvo real.
- Posição e tamanho lembrados em QSettings; mínimo 900x620; miolo rola, ações ficam fixas.

**N-11:** `start_recording(preconfirmed=índice)`: o "Tentar de novo" guarda, no próprio fechamento do aviso, o índice cuja substituição já foi confirmada; só esse índice pula a pergunta. Trocar de item (`_leave_item`) apaga o aviso e a ação; se o item mudar enquanto a lista de microfones é relida, nada grava. Qualquer outro arquivo existente sempre passa por ConfirmDialog.

**Delivery Gate**
- Bloco 1: R-02 PASS (grep de travessão em `recorder/*.py` e fachada: 0; o "−" de dB é sinal de menos). R-03 PASS com ressalva (mínimo 900x620 sem corte, miolo rolável; ver prints `ocioso-minimo`; só offscreen). R-17/18/36/38 PASS (os números são medidos da gravação; nada inventado; frases são as do arquivo do Bruno). R-23 PASS (nenhum asset criado). R-24/26 PASS (todo botão tem ação real; Anterior/Próxima/Pular/Ouvir/Regravar/Gravar ligados ao controlador). R-25 PASS (só tokens do tema, pares já medidos). R-27 PASS (vazio, carregando, erro). R-28 N/A. R-32 PASS com ressalva (Tab em ordem, Espaço/Enter/Esc/setas/O/R/P, foco do kit; navegação real não testada). R-33 PASS. R-34 PASS (prints nos dois temas). R-35 PARCIAL (executado offscreen com microfone e som simulados, sem erros; cliques reais não feitos). R-37 PASS. R-39 PASS com ressalva (accessibleName/Description em tudo; leitor de tela não testado). R-40 N/A.
- Bloco 2: R-01/R-13 PASS (um glow, o indicador). R-04 PASS (ícones do kit relevantes: gravar, parar, ouvir, pular). R-06, R-07, R-08, R-10, R-12, R-22 PASS. R-09 PASS (só chips de estado). R-14 PASS (um Card). R-19 PASS (movimento 120 a 180 ms; laço só no indicador).
- Bloco 3: dials declarados; foco único por estado; acento só em Gravar/Próxima, seleção, anel e gravação; motivo = marcador âmbar + numerais tabulares + tecla escrita no botão.
- Bloco 4: C-1 a C-5, R-05, R-11, R-15, R-16, R-20, R-21, R-29, R-30, R-31 PASS.

**Não verificado (gravador):** microfone e som reais (simulados nas capturas), DPI por monitor real, leitor de tela, hover e teclado reais. Ressalva visual: a legenda "Saturado" do LevelMeter (componente do kit) é cortada em "Satura" na largura mínima; corrigir exige editar o kit, fora do escopo.

## Tela: Painel de memória
Código: `src/jarvis/ui/memory/` (vista, modelo, controlador); fachada `ui/memory_panel.py`. Prints: `Shared\jarvis\ui-prints\memoria\` (78 PNGs, 100/150/200%, escuro e claro, dados fictícios em banco temporário).

**Design Read:** ferramenta de controle pessoal, para uma pessoa que quer ver, corrigir e apagar o que o Jarvis guarda, no painel de instrumentos do DESIGN.md. Dials ENERGY 2 / RHYTHM 3 / MOTION 1 (esta tela varia mais que as Configurações: três áreas com composições diferentes).

**Decisões (motivo em uma linha):**
- Navegação por faixa horizontal de texto com sublinhado âmbar só na área aberta: estado, e diferente da coluna lateral das Configurações.
- Memórias e Conversas: lista à esquerda (busca, filtro, fixadas sob cabeçalho) e detalhe à direita: o usuário escolhe um item e decide sobre ele.
- Armazenamento: sem lista; aviso fixo, números reais em tipografia grande (sem cartões) e a coluna de cópia/exportação ao lado: é um painel de situação, não de seleção.
- Origem 'modelo'/'externo' marcada com ícone + texto na linha e no detalhe, e aviso próprio para conteúdo externo: a confiança nunca fica só na cor.
- Apagar fica em faixa própria (armazenamento) ou afastado dos demais botões (detalhes), e toda exclusão usa ConfirmDialog com o texto real; apagar tudo e apagar todas as conversas exigem digitar APAGAR.
- Leitor de conversa somente leitura: texto puro (Label PlainText), ferramenta e conteúdo untrusted na caixa "Dado de fora" com ícone; nada do banco vira HTML.
- Estados vazio, carregando, erro e "banco ocupado" (InlineBanner com 'Tentar de novo', testado com bloqueio real do SQLite) escritos para humanos.
- Modo sem histórico: `Memory` nem é criado, edição desabilitada, aviso fixo.

**Preservado do código antigo:** busca e filtro de memórias; adicionar, editar, fixar/desafixar, apagar memória (com esvaziar lixeira de memórias); apagar todas; exportar tudo JSON; busca de conversas com trechos; filtro por estado; leitor; retomar com aviso; renomear; exportar md/json; enviar para a lixeira; restaurar; esvaziar lixeira; dias restantes; cópia de segurança; números e prazos; aviso de banco sem criptografia; modo sem histórico; fechar a conexão ao fechar/destruir; `close_memory()`, `memory()`, `open_memory`, `main_memory`. Lógica sem Qt reaproveitada em `logic.py` e `service.py`.

**Delivery Gate**
- Bloco 1: R-02 PASS (grep de travessão em `ui/memory` e na fachada: 0). R-03 PASS com ressalva (mínimo 880x560, layouts com rolagem; sem janela real estreita). R-17/R-18/R-36/R-38 PASS (só números lidos do banco; exemplos rotulados "Exemplo fictício"). R-23 PASS (nenhum logotipo ou avatar). R-24/R-26 PASS (todo botão tem ação; Atualizar, abas, filtros e exclusões ligados). R-25 PASS (apenas tokens do tema, pares já calculados). R-27 PASS (vazio, carregando, erro e ocupado impressos nos dois temas). R-32 PASS com ressalva (Tab em ordem definida, Ctrl+F, Del, Enter, Esc, F5, foco visível; não exercitado à mão). R-33 PASS. R-34 PASS (dois temas, três escalas). R-35 PARCIAL: painel rodado offscreen com banco temporário, banco ocupado real e modo sem histórico verificados; cliques e diálogos nativos de arquivo não exercitados (instrução de não rodar testes). R-37 PASS. R-39 PASS com ressalva (accessibleName/Description em listas e controles; leitor de tela não testado). R-40 N/A.
- Bloco 2: R-01/R-12/R-13/R-10 PASS (sem gradiente, sombra, brilho ou vidro). R-04 PASS (ícones do kit: pin = fixada, brain = veio do modelo, alert = externo/expirada, trash = lixeira). R-09 PASS (selos só com estado real). R-14 PASS (nenhum cartão). R-19 PASS (só transições do kit).
- Bloco 3: dials declarados; um foco por tela (Adicionar, Restaurar, Fazer cópia); espaço estrutural; acento só em primário, aba atual, item atual e foco; motivo de identidade = marcador âmbar + ícones chanfrados + selos ícone e texto.
- Bloco 4: C-1 a C-5, R-05, R-11, R-15, R-16, R-20, R-21, R-29, R-30, R-31 PASS.

**Não verificado (painel de memória):** uso com o banco real e com o Jarvis em execução; diálogos nativos de salvar arquivo; leitor de tela; DPI real por monitor; navegação por teclado feita à mão; fonte Segoe UI Variable (usou Segoe UI); incorporação dentro da página das Configurações (feita por outro agente).

## Tela: Configurações
Código: `src/jarvis/ui/settings/` (vista `window.py`/`pages.py`, modelo `model.py`, controlador `controller.py`, fábrica `fieldfactory.py`, textos `texts.py`). Fachada: `ui/settings_window.py`. Prints: `OpenBot\Shared\jarvis\ui-prints\configuracoes\` (11 páginas + busca, alterações com erro, avisos; escuro e claro; 100, 150 e 200%).

**Design Read:** painel de ajustes de uso diário por uma pessoa, em linguagem de painel de instrumentos. ENERGY 2 / RHYTHM 2 / MOTION 1.

Decisões (motivo em uma linha):
- Navegação fixa de 240 px com marcador âmbar só no item atual e contadores de erro/alteração: diz onde há pendência sem abrir cada página.
- Coluna de leitura de 720 px, seções sem caixa em dois ritmos (32/12 e 16/8), FieldRow por campo: hierarquia por espaço, nunca cartão por campo.
- ActionBar só com pendências, com contagem e Salvar bloqueado por erro: a barra só existe quando há decisão a tomar.
- Selo "Requer reinício" por campo: é um estado real (vale só após reiniciar), por isso fica ao lado do rótulo.
- Campos protegidos (endereço do modelo, tecla de emergência) com cadeado e motivo, desabilitados: a segurança nunca fica escondida.
- Banner pós-salvar separa "já vale" de "exige reiniciar" e só oferece Aplicar agora/Reiniciar se o Jarvis estiver aberto: evita botão que não faz nada.
- Tema escuro/claro/sistema na página Geral, guardado em QSettings e não no config do Jarvis: é gosto da tela, não comportamento do assistente.
- Ferramentas arriscadas aparecem com "Sempre pede confirmação" e o interruptor travado ligado: a regra de segurança é dita, não só aplicada.
- Busca ignora acento e filtra campos de todas as páginas, esconde páginas sem resultado e mostra estado vazio com ação.
- Dispositivos de áudio e catálogo de ferramentas carregam em segundo plano ao abrir a página (`run_async`), com estados carregando/erro/vazio.
- Fechar, descartar, restaurar e recarregar do disco usam ConfirmDialog com a lista real de campos alterados.

**Delivery Gate**
Bloco 1 (todas "não" = PASS)
- R-02 PASS: grep de travessão em `ui/settings/` e na fachada: 0.
- R-03 PASS com ressalva: mínimo 960x600, coluna elástica; verificado só offscreen a 100/150/200%.
- R-17/R-18/R-36/R-38 PASS: nenhum número, depoimento ou alegação inventada; números da tela vêm do config, do catálogo e do estado real do Jarvis.
- R-23 PASS: nenhum logotipo, avatar ou imagem criado.
- R-24/R-26 PASS: toda página da navegação existe; todo botão tem ação (abrir pasta, gravador, salvar, descartar, restaurar, aplicar, reiniciar, recarregar). "Minha voz" depende do parâmetro `set_name` do gravador: sem ele, mostra erro claro.
- R-25 PASS: cores só dos tokens do tema (tabela de contraste da base, 0 falhas); `grep` de cor hexadecimal no pacote: 0.
- R-27 PASS: carregando, vazio e erro nas ferramentas, no painel de memória, na busca e nos dispositivos.
- R-28 N/A.
- R-32 PASS com ressalva: Tab, Esc, Ctrl+F, Ctrl+S implementados e foco âmbar do kit; navegação completa por teclado não foi exercitada à mão.
- R-33 PASS: nenhum script de patch.
- R-34 PASS: 11 páginas e os avisos conferidos nos dois temas e nas três escalas.
- R-35 PARCIAL: tela construída e capturada offscreen sem erros no console; carga de ferramentas, validação com erro, busca e avisos exercitados por código; cliques reais e gravação em disco não feitos.
- R-37 PASS: direção do DESIGN.md aplicada.
- R-39 PASS com ressalva: accessibleName/Description em tudo; leitor de tela não testado.
- R-40 N/A.
Bloco 2: R-01 PASS (sem gradiente nem glow). R-04 PASS (ícones do kit, sem ícones de IA). R-06 PASS. R-07 PASS. R-08 PASS. R-09 PASS (selo só para estado real). R-10 PASS. R-12 PASS. R-13 PASS. R-14 PASS (sem cartões). R-19 PASS (só transições do kit). R-22 PASS.
Bloco 3: dials declarados; um foco por tela (Salvar âmbar); espaço estrutural; um acento; motivo de identidade = marcador âmbar + ícones chanfrados; Design Read declarado.
Bloco 4: C-1 a C-5, R-05, R-11, R-15, R-16, R-20, R-21, R-29, R-30, R-31 PASS. Ressalva: o selo "Requer reinício" se repete em muitos campos por ser a realidade do schema.

**Não verificado (Configurações):** gravação real no config.toml, cliques com mouse, Jarvis em execução (Aplicar agora/Reiniciar), listagem real de dispositivos (os prints usam lista vazia, sem tocar em áudio), diálogos nativos de arquivo, leitor de tela, DPI real por monitor, fonte Segoe UI Variable (usou Segoe UI), integração com o gravador (`set_name`) e com o novo painel de memória.
