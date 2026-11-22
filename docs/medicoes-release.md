# Medições de release — Jarvis v0.1.0 (2026-11-22)

Máquina: Xeon E5-2650 v4 (12 núcleos/24 threads), 16 GB de RAM, AMD RX 580 2048SP 8 GB (Vulkan), Windows 10 Pro 19045.
Modelo: Qwen3-VL-4B Q4_K_M (2,3 GiB) + mmproj; contexto 12288; voz Piper `pt_BR-faber-medium`; STT faster-whisper `base` int8.
Todos os números abaixo foram MEDIDOS nesta máquina com os scripts em `work\` (não versionados). "n/m" = não medido.
Durante as medições havia 4 processos `ffmpeg` de outros agentes, parados (downloads de mídia, sem CPU/GPU); não eram render.

## 1. Partida
| Etapa | Tempo |
|---|---|
| `import jarvis.app` | 0,53 s |
| Microfone / VAD Silero | 1,0–1,9 s |
| Voz Piper (carregar) | 1,2–2,0 s |
| Whisper base (carregar) | 1,5–4,1 s |
| `llama-server` pronto (cache de disco quente) | 6,8–9,0 s (primeira vez após boot: ~25 s) |
| Ilha: processo filho até "ready" | 0,69 s |
| **Jarvis utilizável** (todas as etapas em paralelo) | **~10 s** |
| Aquecimento do prompt fixo (segundo plano, uma vez) | 23 s |
Primeira resposta rápida (cache quente) só depois do aquecimento: ~33 s após abrir.

## 2. Recursos
| Componente | RAM | VRAM | CPU |
|---|---|---|---|
| `llama-server` ativo (sem mmap) | 0,50 GB | 6,1 GB (total com sistema) | 0% parado |
| `llama-server` dormindo (`llm.sleep_idle_s`) | 0,36–0,73 GB | volta a 0,98 GB (nível-base) | 0% |
| `llama-server` com mmap (antes) | 2,85 GB | igual | — |
| Núcleo (voz, VAD, Whisper, Piper, agente) | 393–442 MB | 0 | 0,3–1% parado; média 47% / pico 196% de 1 núcleo durante a conversa |
| Ilha escondida | 1,4–6 MB | 0 | ≈ 0% |
| Ilha visível | 17–32 MB | 0 | 0,03% estática; 2–4% falando/ouvindo |
RAM livre do sistema com tudo ligado: 8,0 GB de 15,9 GB.
CPU do `llama-server` gerando: 56% de 1 núcleo com 12 threads → 28–32% com `-t 2` (llama-bench, mesma velocidade).

## 3. Velocidade do modelo (`llama-bench`, prompt 2048 / geração 64)
| Configuração | prompt tok/s | geração tok/s |
|---|---|---|
| atual (sem flash-attn, KV f16, lote 512) | 187 | 19,8 |
| lote 1024 | 182 | 19,3 |
| flash-attn | 140 | 20,2 |
| flash-attn + KV q8_0 | 129 | 17,7 |
| `-t 1` / `-t 2` / `-t 4` / `-t 12` (prompt 1024) | 189 / 189 / 187 / 177 | 21,9 / 21,9 / 21,9 / 21,5 |
Em uso real: prompt 140–177 tok/s, geração 15,6–20,7 tok/s (cai com o prompt mais longo).

## 4. Latência (fim da fala → primeiro som)
| Trecho | Tempo |
|---|---|
| Fim da fala → VAD fecha a frase (`end_silence_ms` 700) | 0,72–0,76 s |
| STT base (frase de 1,4–3,4 s) | 0,67–0,96 s |
| 1º token do modelo, prompt em cache | 0,7–1,4 s |
| 1º token, conjunto de ferramentas fora do cache | 4–13 s (uma vez) |
| Pedido sem modelo (hora, janela ativa) | 0,01 s |
| Piper: 1º trecho de áudio | 0,07–0,16 s |
| Abrir a saída de áudio até o 1º som (MME / WASAPI) | 0,17–0,22 s / 0,10 s |
| **Total típico (pedido simples, cache quente)** | **~3 a 4 s** (voz ~1,5 s + modelo ~1 s + 1ª oração ~1 s + saída 0,2 s) |
| Acordar o modelo dormindo | 6 s de recarga + reprocessar o prompt (até ~23 s) |
A 1ª oração da fala agora sai na primeira vírgula/dois-pontos (≥ 24 letras), sem esperar o ponto final.

## 5. Ilha
Janela aparece 65 ms depois de receber o estado "Ouvindo" (animação completa 280 ms); processo filho pronto em 0,69 s; privada 34–48 MB (antes 824 MB).

## 6. Instalador
Ver `installer\dist\Jarvis-Setup-0.1.0-NOTAS.md` (tamanho e SHA-256 do `.exe` e provas de instalação/desinstalação).

## 7. Reconhecimento de voz (frases pt-BR sintetizadas, 20 frases)
| Modelo | limpo | ruído 15 dB | ruído 8 dB | distante | latência/frase |
|---|---|---|---|---|---|
| base | 16,4% | 17,1% | 33,6% | 24,3% | 0,8 s |
| small | 13,8% | 16,4% | 18,4% | 13,8% | 2,5 s |
Vocabulário no `initial_prompt` reduziu o WER do base em 2–4 pontos. WER com a voz real do Bruno: n/m (não há gravações).

## 8. Os 5 maiores gargalos medidos
1. **Prompt de 3,4 mil tokens a frio (23 s) a 150–177 tok/s.** Corrigido: núcleo fixo e ordenado de ferramentas, prefixo em cache → 1º token 0,7–1,4 s; custo pago uma vez, em segundo plano. Extra de memória (rara) ainda custa ~13 s.
2. **Acordar depois de dormir** (6 s + reprocessar). Mitigado por pré-aquecimento ao ouvir; ajustável (`llm.sleep_idle_s`, 0 desliga). Candidato: salvar o cache de prompt em disco.
3. **Fallback visual de clique 5–13 s** (duas leituras de imagem). Precisão 4/5 com 1024 px; 768 px era mais rápido mas 3/5 — mantido 1024. O caminho por UIA leva 0,1–0,6 s e resolve a maioria.
4. **STT com WER alto sob ruído no modelo base** (33,6% a 8 dB). Mitigado com vocabulário; `small` é bem melhor mas ~3× mais lento — opção para ambiente ruidoso.
5. **CPU do `llama-server` gerando (56% de 1 núcleo com 12 threads)**. Corrigido com `-t 2` (28–32%), sem perder velocidade.
Corrigidos e baratos: RAM do servidor (−2,35 GB com `-lm none`), VRAM ociosa (−5 GB com sleep), CPU/RAM da Ilha, divisor de fala (1ª oração mais cedo), saída de áudio no padrão do Windows.

## 9. Ajustes finais de CPU (medidos depois do relatório acima)
- `llama-server` em uso real com `-t 2`: CPU média 59% → **23%** de 1 núcleo (pico 252% → 56%).
- Whisper base, CPU por frase (regra da política: diferença < 10% = menos CPU-s): 2 threads 1,66 s / 3,3 CPU-s; 4 threads 1,04 s / 4,2; **6 threads 0,94 s / 5,6 (adotado)**; 12 threads 0,86 s / 10,3. Padrão `stt.cpu_threads` 12 → 6.

## 10. Mapa CPU × GPU por serviço (regra da política: GPU por padrão; CPU só onde medir menor tempo; <10% = menos CPU-s; empate = GPU)
Tabela completa também em `Shared\triade\POLITICA-GPU.md` e `estudio-br\config\recursos.json` (tarefas `jarvis_*`). Chaves em `config.toml`: `llm.device`, `llm.mmproj_device`, `stt.device`, `tts.device` (`auto`|`gpu`|`cpu`). `Jarvis.cmd doctor` mostra onde cada serviço roda.
| Serviço | Vencedor | GPU | CPU | Padrão |
|---|---|---|---|---|
| LLM Qwen3-VL 4B (llama.cpp Vulkan) | **GPU** | 199 tok/s prompt, 21,8 tok/s geração, 5 CPU-s | 146 / 6,5 tok/s, 165 CPU-s (12 thr); 85 CPU-s (6 thr) | `llm.device=auto` (GPU; cai para CPU com aviso se não subir) |
| LLM: flash-attn / KV q8_0 / lote 1024 | CPU-lado do contexto: desligados | prompt 140 / 129 / 182 tok/s contra 187 | — | desligados |
| LLM: threads residuais | **2** | 21,9 tok/s, CPU 28–32% | 12 thr: 21,5 tok/s, CPU 56% | `-t 2` |
| Visão (mmproj) | **GPU** | 7,6 s por imagem, 2,1 CPU-s, +0,77 GB de VRAM | 40,8 s, 72 CPU-s | `llm.mmproj_device=auto` |
| Escuta (STT, comandos de 1,4–3,4 s) | **GPU** whisper.cpp Vulkan small | 0,98 s, 0,38 CPU-s, WER 11,8% (ruído 8 dB: 17,8%) | faster-whisper base: 0,89 s, 5,3 CPU-s, WER 18,4% (34,9%); small: 2,5 s | `stt.device=auto` (GPU); cai para o faster-whisper |
| Voz Piper (VITS ONNX) | **CPU** | DirectML 0,164 s (40 fonemas) / 0,153 s (110) | 0,060 s / 0,120 s | `tts.device=cpu` |
| VAD Silero | **CPU** | DirectML 1,51 ms/janela | 0,30 ms/janela (0,9% de 1 núcleo) | CPU |
| Captura de tela + JPEG | **CPU** | DXGI 16 ms / 48 ms de CPU | GDI 49 ms / 27 ms de CPU; JPEG 58 ms | CPU (DXGI ganharia 33 ms; exige dxcam+OpenCV; <1% da latência de visão) |
| UI/Ilha (Qt) | **CPU** | n/m (custaria VRAM e acordadas) | 0% escondida, 3,8% de 1 núcleo falando | CPU |
| UI Automation | **CPU** | n/a | 0,07–0,6 s | CPU |
**Orçamento de VRAM (pico medido, tudo ligado):** 6.780 MB de 8.192 MB (modelo+KV ~5,1 GB, visão 0,77 GB, escuta ~1 GB, sistema ~1 GB). Cabe, com ~1,4 GB de folga. Disputa com render de vídeo: depois de `llm.sleep_idle_s` (600 s) o Jarvis descarrega modelo, visão e escuta (~5 GB livres); antes disso, e para liberar na hora, `llm.device = cpu`. Testes na GPU foram feitos sem render ativo (os `ffmpeg` presentes eram downloads parados).
**Segurança:** se a GPU falha, cai para CPU com aviso, sem travar: LLM (partida sem GPU → `-ngl 0` + visão na CPU, evento `gpu_fallback`), escuta (carga ou execução falha → faster-whisper, avisos no log). Comprovado simulando falhas (modelo ggml inexistente; partida do servidor falhando).
**Desempenho da escuta na GPU, ponta a ponta:** carregar 2,1–2,5 s (uma vez); a frase leva 0,9–1,0 s; WER nas 20 frases: limpo 11,8%, ruído 15 dB 14,5%, 8 dB 17,8%.
