# Jarvis v0.1.0 - notas da release

Primeira versão do assistente de voz local em pt-BR. Artefato: `Jarvis-Setup-0.1.0.exe` (170,6 MiB; SHA-256 no arquivo
`.exe.sha256`). Os modelos (~3,5 GB) são baixados à parte, com conferência de hash.

## Destaques
- 100% local: reconhecimento (faster-whisper), modelo de visão e linguagem (Qwen3-VL 4B via llama.cpp Vulkan) e voz (Piper).
- Controla o PC por ferramentas permitidas; UIA primeiro, localização visual como reserva.
- Ilha no topo da tela com estado, ondas, ação e botões Sim/Não, Mudo, Parar, Configurações.
- Confirmações só nas ações nocivas; YOLO só por ação manual; tecla de emergência (Ctrl+Alt+F12).
- Memória local com painel de transparência; auditoria com HMAC.
- Instalador por usuário (sem admin), assistente de primeira execução e pacote offline.

## Requisitos
Windows 10 build 19044+ ou 11, x64; 16 GB de RAM recomendados; GPU com Vulkan (testado em RX 580 8 GB); ~3,5 GB para modelos.

## Números medidos (RX 580 8 GB, Xeon E5-2650 v4, 16 GB)
- Qwen3-VL 4B Q4_K_M: 187 tok/s de prompt e 19,8 tok/s de geração (llama-bench, prompt 2048 / geração 64).
- VRAM em uso ~5,8 a 6,1 GB de 8 GB com o modelo carregado; dormindo volta a ~1 GB.
- RAM: servidor ~500 MB, núcleo ~393 MB; partida a frio ~42 s, ~9 s com o disco em cache; aquecimento ~30 s.
- Pedido típico com cache: 1 a 3 s até a primeira frase (via texto); com ferramenta ~3 a 4 s.
- Acordar do modo dormindo: ~6 s de recarga mais reprocessar o prompt (23 a 47 s no teste com prompt longo).
- Instalador: build completo em 283 s; `doctor` 21/21 numa instalação de teste.

## Limitações conhecidas
- O modelo de 4B às vezes escolhe mal entre ferramentas e descreve mal alvos; o clique visual em linguagem natural acertou
  ~50% nos testes (recusar é o comportamento seguro). Pode inventar dados que não vêm de ferramenta (hora e janela têm atalho direto).
- Falha ocasional, uma única vez, ao abrir a saída de áudio na primeira fala.
- `digitar_texto` pode ser recusado se a janela recém-aberta não vem para a frente.
- Taint estrito: depois de ler conteúdo de fora, mais ações pedem confirmação no modo estrito.
- Memória e histórico em SQLite **não criptografado**.
- A chave de assinatura do YOLO fica em arquivo: não protege contra malware com o seu usuário.
- `Jarvis.cmd` não aceita argumentos com espaço entre aspas.
- Bug conhecido no kit de UI: `ToggleSwitch.hideEvent` usa uma animação já apagada (o assistente usa subclasse protegida).
- Instalador sem assinatura de código (SmartScreen avisa "editor desconhecido").
- `piper-tts` é GPL-3.0 e PySide6 é LGPL-3.0: revisar antes de distribuir a terceiros. Licença do Jarvis pendente.

## O que NÃO foi verificado
- Voz de ponta a ponta com microfone real e latência fim a fim; WER com as gravações do autor (pendente).
- Windows limpo (sem VC++ Redistributable, sem Vulkan), outras GPUs (NVIDIA, Intel), instalação por máquina com admin.
- Cliques reais no assistente de instalação (o fluxo foi guiado por código), teste de voz audível, leitor de tela, SmartScreen,
  `/DOWNLOADMODELS=1`, atualização de versão com mudança de AppId.
- Teclado e mouse fora da Calculadora e de poucos aplicativos; multi-monitor e DPI por monitor; tela cheia real.
- Atalho do YOLO apertado de verdade; ação nociva real (apagar) de ponta a ponta; restauração pela Lixeira.
- Ilha: tamanho grande com dados reais, Jarvis encerrado à força, CPU/RAM com a máquina totalmente livre.
- Fonte: `STATUS.md` do desenvolvimento (2026-11-22).
