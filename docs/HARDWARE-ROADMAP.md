# Suporte a hardware: débito técnico e próximos passos

Branch: `tech-debt/hardware-support`. **Este documento não implementa nada.** Ele registra o que hoje só foi
validado em um PC e o que precisa ser feito para o Eco funcionar bem em GPUs NVIDIA e Intel e em CPUs AMD e Intel
de qualquer geração. A entrega é prevista para uma versão posterior.

## 1. Situação atual (honesta)

O Eco **não depende de AMD no código**, mas **só foi desenvolvido, medido e testado** nesta máquina:
Windows 10 Pro x64, Xeon E5-2650 v4 (Intel, 12 núcleos, AVX2), 16 GB de RAM, AMD RX 580 2048SP 8 GB (Vulkan).
Tudo abaixo que não for essa combinação está **sem teste**.

| Camada | Como funciona hoje | Neutro de fabricante? | Testado fora da RX 580? |
|---|---|---|---|
| LLM local | `llama-server` do llama.cpp, build **Vulkan** (`b12531`), `-ngl 99`; `llm.device = auto` cai para CPU se o servidor não sobe | Em princípio sim (Vulkan roda em AMD, NVIDIA e Intel) | Não |
| Reconhecimento de fala (padrão) | faster-whisper (CTranslate2) **na CPU**, `compute_type` e `cpu_threads` configuráveis | Sim (CPU) | Não |
| Reconhecimento de fala (opcional) | whisper.cpp com backend Vulkan, ligado por um shim em C (`native\jarvis_whisper.c`) compilado com o Visual Studio Build Tools | Em princípio sim | Não |
| Voz (TTS) | Piper (ONNX) na CPU | Sim | Não |
| Detecção de hardware | `setup\hardware.py` verifica Vulkan e memória de vídeo mínima (4000 MB); mensagem cita AMD, NVIDIA e Intel | Sim | Não |
| Plataforma | Windows x64 apenas | Não (sem ARM64, Linux ou macOS) | Não |

Itens de **produção de vídeo** (encode `h264_amf`, `--gl=angle`) pertencem a outro projeto e **não fazem parte do Eco**.

## 2. Riscos e lacunas conhecidos

1. **Vulkan em NVIDIA e Intel nunca foi exercitado.** Pode haver diferenças de driver, de limites de memória e de
   desempenho. Em NVIDIA o caminho CUDA tende a ser bem mais rápido que Vulkan; hoje não é usado.
2. **Dimensionamento calibrado para 8 GB de VRAM.** Contexto, `ngl`, tamanho do modelo recomendado e o modelo de
   visão (`mmproj`) foram escolhidos para a RX 580. GPUs com 4, 6, 12 ou 24 GB precisam de recomendação própria.
3. **GPU integrada** (Intel UHD/Iris/Arc, AMD APU) divide memória com o sistema: a detecção de "VRAM" mente nesses casos.
4. **Várias GPUs** (notebook com integrada + dedicada): o Vulkan pode escolher a errada; não há seletor de dispositivo.
5. **CPU sem AVX2** (anterior à Haswell/Zen) ou com poucos núcleos: o fallback em CPU e o faster-whisper podem ficar
   inviáveis; não há detecção de conjunto de instruções nem aviso.
6. **Núcleos híbridos** (Intel 12ª geração em diante, P e E cores): `cpu_threads` padrão pode ser ruim; sem afinidade.
7. **Binários travados por hash no `manifest.json`** são só `win-vulkan-x64`; variantes CUDA, HIP ou SYCL não existem
   no manifesto, e o build do shim em C depende de uma ferramenta de compilação instalada na máquina de build.
8. **Drivers:** o Setup só avisa; não detecta versão mínima de driver nem orienta por fabricante.
9. **Desempenho relatado** (tok/s, latências, uso de CPU) vale **somente** para a RX 580 + Xeon.

## 3. Plano proposto (ordem sugerida)

### Fase A: medir e abstrair (sem mudar comportamento)
- Criar uma camada **`hardware profile`**: fabricante e modelo da GPU, VRAM dedicada x compartilhada, driver, versão da
  API Vulkan, núcleos físicos e lógicos, conjunto de instruções (AVX, AVX2, AVX-512), RAM, tipo de CPU (híbrida ou não).
- Persistir o perfil e mostrá-lo em `Eco.cmd doctor` e na varredura do Setup (já em preparo: etapa "Preparar o computador").
- Seletor de dispositivo Vulkan (`GGML_VK_VISIBLE_DEVICES` ou equivalente do build) nas Configurações, com teste.

### Fase B: recomendação automática por perfil
- Tabela de **perfis de hardware** (por exemplo: GPU ≥ 12 GB, 8 GB, 6 GB, 4 GB, só CPU, iGPU) que define modelo
  recomendado, quantização, `ngl`, contexto, STT (CPU x Vulkan) e TTS.
- Benchmark curto opcional no Setup ("medir este PC") que grava tok/s e latência de STT e escolhe o perfil.
- Não alterar valores já escolhidos pelo usuário.

### Fase C: NVIDIA
- Avaliar o build **CUDA** do llama.cpp (binário adicional no manifesto com hash) e quando preferi-lo ao Vulkan.
- Detectar GPU NVIDIA e driver; oferecer o backend CUDA como opção, com fallback ao Vulkan.
- faster-whisper/CTranslate2 em CUDA (cuDNN/cuBLAS): avaliar custo de tamanho do instalador e redistribuição de licença.
- Medir e documentar, em uma máquina com NVIDIA real, antes de afirmar suporte.

### Fase D: Intel (GPU e CPU)
- Testar Vulkan em Arc e iGPU; avaliar SYCL ou OpenVINO só se Vulkan for insuficiente.
- Ajustar `cpu_threads` e afinidade para CPUs híbridas; teste em P e E cores.
- Detectar ausência de AVX2 e orientar (modelo menor, STT menor, aviso de desempenho).

### Fase E: CPUs AMD (e demais)
- Validar em Ryzen (Zen 2 em diante) e APUs com gráficos integrados; confirmar ganho de HIP/Vulkan em APU.
- Documentar requisitos mínimos reais e o que acontece em CPUs antigas.

### Fase F: plataformas
- Windows ARM64 (Snapdragon): avaliar build nativo e NPU; está fora do escopo até haver dispositivo de teste.
- Linux e macOS: fora do escopo; exigem substituir UI Automation, caminhos, instalador e áudio.

## 4. Critérios de aceite (por combinação suportada)

Uma combinação só passa a constar como **suportada** quando, em máquina real:
- o Setup detecta o hardware corretamente e recomenda um perfil;
- `Eco.cmd doctor` passa sem erros;
- LLM, STT e TTS funcionam de ponta a ponta (voz → resposta falada), com latências medidas e registradas;
- o fallback em CPU funciona com a GPU desabilitada;
- a suíte automática e os testes de UI passam; o instalador é testado em pasta limpa;
- os números ficam em `docs\medicoes-*.md` com o modelo exato do hardware.

Sem esses passos a combinação fica descrita como **"não testada"** no README e na página do produto.

## 5. O que NÃO fazer
- Não anunciar suporte NVIDIA, Intel ou outras CPUs antes dos testes acima.
- Não trocar o padrão atual (Vulkan + CPU para fala) sem medir regressão na RX 580.
- Não incluir drivers nem instaladores de terceiros sem hash, licença e confirmação do usuário.

## 6. Perguntas em aberto
- Há acesso a máquinas NVIDIA, Intel Arc/iGPU e AMD Ryzen para teste? (sem elas, só testes sintéticos.)
- Qual o limite aceitável de tamanho do instalador (CUDA aumenta muito)?
- Priorizar NVIDIA (maior base de usuários) antes de Intel?
