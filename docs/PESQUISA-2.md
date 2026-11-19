# Pesquisa 2 — modelos com áudio, vídeo e fala rápida (2026-11-18)
Status: fatos vindos de páginas/relatos; NADA medido na RX 580 do Bruno ainda. [C]=confirmado em fonte primária (doc oficial/model card), [R]=relato/blog, [?]=conflito ou não verificado.

## Modelos multimodais que o llama.cpp roda (doc oficial docs/multimodal.md) [C]
- Áudio: Ultravox 0.5 (1B e 8B), Voxtral-Mini-3B-2507, Qwen3-ASR 0.6B/1.7B.
- Áudio+visão: Qwen2.5-Omni 3B/7B, Qwen3-Omni 30B-A3B (grande demais), Gemma 4 E2B/E4B.
- Vídeo: só SmolVLM2 256M/500M listado (sem instruções). Para os demais, vídeo = amostrar quadros e enviar como imagens [R].
- Doc não cita Vulkan; testar. Projetor vai para GPU por padrão (--no-mmproj-offload desliga). Alguns modelos precisam -c 8192.

## Candidatos por papel
| Papel | Candidato | Fatos | Risco |
|---|---|---|---|
| Cérebro+visão | Qwen3-VL 4B Instruct GGUF (oficial Qwen, + mmproj) | [C] GGUF oficial; suporte llama.cpp desde 30/out/2025 [R] | vídeo nativo [?] |
| Cérebro+visão | Qwen3.5 4B / 9B (mar/2026, Apache 2.0, multimodais nativos) | [R] 4B 4-bit ~5,5 GB; 9B ~6,5 GB (tabela Unsloth); llama.cpp sem vídeo [R] | 9B tende a apertar 8 GB com contexto; sem benchmark de tool calling achado |
| Áudio+visão num modelo | Gemma 4 E4B / E2B | [R] áudio até 30 s, vídeo até 60 s por quadros; E4B Q4_K_M ~5 GB em disco, ~10 GB estimado com KV 8k (fonte única, conflita com 4,5 GB da tabela Google) | Áudio no llama.cpp: discussão #21334 (abr/2026) deu erro "audio input is not supported"; precisa build atual + mmproj com áudio. Testar |
| Áudio+visão | Qwen2.5-Omni 3B | [C] llama.cpp entra áudio+imagem, sem vídeo e sem saída de áudio | relato de áudio fraco e alucinação em áudio longo |
| STT | Qwen3-ASR 0.6B/1.7B (GGUF oficial ggml-org, 1.7B Q8 = 2,17 GB) | [C] português listado (blog Alibaba); 30 idiomas; streaming, TTFT 92 ms (0.6B, em GPU grande) | WER pt-BR oficial não achado; versões afinadas pt-PT: 12,9% -> 8,5% (blog 3º, [?]) |
| STT | faster-whisper large-v3-turbo / small int8 CPU | [R] turbo ~6x mais rápido que v3 em CPU i7 | não medido em Xeon |
| STT | Parakeet TDT 0.6B v3 | [R] pt mediana RTF 0,081 em CPU (1 dataset); cobre só 25 idiomas europeus | idioma/precisão a medir |
| STT | Moonshine | [R] sem português | descartado |
| STT streaming | Voxtral Mini 4B Realtime | [R] precisa ~16 GB | descartado p/ 8 GB |
| Fala->fala | Moshi 7B | [R] ~16 GB VRAM | descartado |
| Fala->fala | Voxtral Mini 3B | [R] ~9,5 GB em fp16; GGUF Q4 sem número de VRAM | não é fala->fala; só entende áudio |
| TTS | Piper pt_BR faber | [R] CPU, 1,7 s p/ 1º áudio (Picovoice), CC0 | voz robótica |
| TTS | Kyutai Pocket TTS 100M (v2, mai/2026, 6 idiomas incl. português; GGUF/ONNX existem) | [R] README lista portuguese; ~200 ms em 2 núcleos (afirmação Kyutai); 1,7 s no teste Picovoice | licença e qualidade pt-BR a confirmar no cartão HF kyutai/pocket-tts |
| TTS | Kokoro 82M | [R] 3,7 s p/ 1º áudio em CPU (Picovoice); pt-BR existe | mais lento |
| TTS | Supertonic 3 | [R] lista português; repo arquivado, OpenRAIL-M com restrições | avaliar licença |
| TTS | Phonon-40m-pt (Gradium) | [R] CC BY-NC 4.0 | ok só uso pessoal |
| TTS | Orpheus 3B, Chatterbox, XTTS | [R] pesados / lentos em CPU | descartados |

## RX 580 2048SP: o que se sabe
- [R] Vulkan reconhece "AMD Radeon RX 580 2048SP"; flag --device Vulkan0 obrigatória em um guia; ~17,8 tok/s com Mistral 7B (guia 2026); RX 480: Llama 7B Q4_0 ~15 tok/s tg, ~125 pp.
- [R] Vulkan sem kernel de flash attention em alguns hardwares, KV quantizado limitado (comentário de 2025, não específico para Polaris): testar -fa on/off.
- [R] driver AMDVLK vs Mesa/Adrenalin pode dar ~40% de diferença (Reddit, 2025).
- Sem dado de Qwen/Gemma 4B na placa: só estimativas (willitrunai). Medir com llama-bench.

## Tool calling em modelo pequeno
- [R, 1 blog] Qwen3-4B-Instruct-2507 melhor 4B tool-caller no teste dele; usar o template nativo de tool calling.
- Phi-4-mini, Granite 4.1 8B citados com BFCL por fontes 3ªs. Sem BFCL de Qwen3.5/Gemma 4. BFCL parado desde abr/2026.

## Decisão provisória (a validar por medição)
A) Pipeline: Qwen3-ASR 1.7B Q8 (GPU ou CPU) ou faster-whisper CPU -> Qwen3-VL 4B Q4_K_M (GPU) -> Pocket TTS ou Piper (CPU).
B) Modelo único: Gemma 4 E4B com áudio+visão; só se o teste de áudio no llama.cpp passar em build atual.
Teste obrigatório: mesmo conjunto de 20 frases pt-BR, mesmo hardware, registrar latência fim-a-fim, VRAM e erro.

## Fontes (22)
1 github.com/ggml-org/llama.cpp docs/multimodal.md; 2 llama.cpp PR #13784 (Qwen2.5-Omni); 3 HF ggml-org/Qwen2.5-Omni-3B-GGUF; 4 llama.cpp discussão #13949; 5 llama.cpp discussão #21334 (Gemma 4 áudio); 6 llama.cpp discussão #23109 (bench RX 580); 7 HF Qwen/Qwen3-VL-4B-Instruct-GGUF; 8 ComfyUI-QwenVL (vídeo por quadros); 9 HF ggml-org/Qwen3-ASR-1.7B-GGUF; 10 Alibaba Cloud blog Qwen3-ASR; 11 arXiv 2601.21337 (Qwen3-ASR); 12 Google AI model card Gemma 4; 13 dsebastien.net/gemma-4; 14 Unsloth Qwen3.5 docs; 15 insiderllm Qwen3.5 small; 16 Picovoice on-device TTS benchmark; 17 github kyutai-labs/pocket-tts; 18 Kyutai blog 2026-05-04; 19 vidclean Parakeet vs Whisper CPU; 20 northflank melhores STT 2026; 21 dev.to aivisionslab RX 580 Vulkan; 22 d-central / tinygpt tool-calling.
