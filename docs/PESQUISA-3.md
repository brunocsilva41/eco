# Pesquisa 3 — MoE, quantização, offload, desempenho (2026-11-18)
[C]=fonte primária/doc, [R]=blog/relato, [?]=conflito. Nada medido na RX 580 2048SP + Xeon E5-2650 v4 + 16GB.

## 1. MoE: "carrega só o que usa"
Ideia: modelo de muitos parâmetros, poucos ativos por token (ex.: 30B-A3B = 3B ativos). Os "experts" ficam na RAM; atenção, KV e camadas densas ficam na GPU.
Flags llama.cpp [C: guia Doctor-Shotgun, HF]:
- `-ngl 999 --cpu-moe` (ou `-ot "exps=CPU"`): todos experts na CPU, resto na GPU.
- `--n-cpu-moe N`: experts na CPU só nas N camadas mais altas; N menor = mais na GPU = mais rápido e menos folga de VRAM. Achar N por tentativa, vendo VRAM a cada execução; `-fit off` ao ajustar.
- `-b 4096 -ub 4096` recomendado no guia, mas ub maior gasta VRAM de buffer: em 8 GB talvez precise reduzir.
Relatos [R, GPUs NVIDIA 8GB, não Vulkan/Polaris]: Qwen3-Coder 30B-A3B: --cpu-moe 13 tok/s; --n-cpu-moe 40 ~32 tok/s; RTX 3070 8GB Qwen3.6-35B-A3B: 4 -> 33 tok/s com n-cpu-moe 28.
Limite real: velocidade depende da largura de banda da RAM. Xeon E5 v4 quad-channel DDR4-2400 ~77 GB/s por soquete (conta minha) [?]; relatos de Gemma 4 26B em Xeon antigo sem GPU: 5–12 tok/s [R]. Quantas canais/MHz o Bruno tem: MEDIR (wmic memorychip).
Com 16 GB de RAM: Windows + app ocupam ~5–6 GB; sobra ~10 GB para experts. Um MoE de ~30B em Q4 (~17–20 GB) NÃO cabe sem swap; só quants 2–3 bits (~10 GB) e com perda de qualidade [R: Pinggy UD-IQ2_XXS 9,93 GB]. Ou seja: 16 GB de RAM é o gargalo, mais que a GPU.

## 2. Modelos MoE/candidatos
| Modelo | Fato | Serve? |
|---|---|---|
| gpt-oss-20b (3,6B ativos) | [R] cabe em 16 GB de memória total (card oficial) | Possível com RAM; sem visão/áudio; testar. |
| Gemma 4 26B-A4B | [R] ~15,6 GB em Q4; qualidade >= Qwen3.5-35B-A3B em código/multilíngue (blog) | Aperta nos 16 GB de RAM com o sistema |
| Qwen3.5-35B-A3B / Qwen3.6-35B-A3B | [R] 19–22 GB em Q4; guias pedem 32–64 GB de RAM | Não cabe bem; só 2-bit |
| Qwen3.5-9B (denso) | [R] recomendado para 8 GB (PCSP) | Principal candidato forte |
| Gemma 4 E4B / E2B | "E"=parâmetros efetivos (Per-Layer Embeddings) | Candidatos leves, com áudio+visão |
Conclusão provisória: para 8 GB VRAM + 16 GB RAM, o ganho real vem de (a) 9B denso em Q4/Q5 na GPU, (b) 4B com folga de contexto, (c) MoE só se a RAM subir para 32 GB. Upgrade de RAM para 32 GB tende a ser o melhor custo-benefício para MoE [inferência minha, a validar].

## 3. Quantização
- KLD (divergência do modelo original; menor = melhor) [R, tabela Unsloth Qwen3.5 + bartowski]: IQ4_XS pior que Q4_K_M em fidelidade (0,0235 vs 0,0192; 0,0188 vs 0,0139), mas menor. Unsloth Dynamic Q4_K_XL: KLD 0,0137 vs 0,0192 do Q4_K_M, +0,68 GB. Regra: Q4_K_M ou UD-Q4_K_XL se cabe; IQ4_XS só para economizar; abaixo de 4 bits, IQ vence Q [R].
- imatrix/calibração melhora quants baixos [R]. Preferir quants de Unsloth (Dynamic) ou bartowski (imatrix).
- KV cache: q8_0 corta KV pela metade com qualidade praticamente igual (teste PPL em modelo 0,5B) [R]; q4_0 corta 4x mas arrisca qualidade; exige flash attention em várias fontes [?]. Em Vulkan há patches/relatos de FA com KV quantizado (build b11413) [R, 2ª mão]. Testar `-fa on` + `-ctk q8_0 -ctv q8_0` e conferir qualidade e velocidade na Polaris.

## 4. Velocidade extra
- Speculative decoding clássico (modelo rascunho 0,5B–1B): de 0x a 2,5x, depende do par [R]; piorou em uma RTX 5060 Ti. Doc oficial: docs/speculative.md (llama.cpp) [C: existe].
- MTP (multi-token prediction): entrou no llama.cpp em 16/mai/2026 (PR #22673) [R], ganho 1,4–2,2x; só funciona com GGUF treinado com cabeças MTP (ex.: Qwen3.5/3.6 MTP); sintaxe de flag varia: conferir `--help` do build [?]. Sem dado em Vulkan/Polaris.
- Para voz: não esperar o fim da frase; fazer TTS por frases (streaming) e STT com VAD.

## 5. Plano de teste (para o agente)
Para cada candidato (Qwen3-VL 4B, Qwen3.5 4B/9B, Gemma 4 E4B, e 1 MoE em 2–3 bits): llama-bench com `-fa 0/1`, `-ctk/-ctv f16/q8_0`, `-ngl`, e para MoE `--n-cpu-moe` em varredura. Registrar pp, tg, VRAM, RAM, qualidade em 20 prompts pt-BR e 10 chamadas de ferramenta.

## Fontes
1 HF blog Doctor-Shotgun (guia MoE offload); 2 dev.to Qwen3-Coder 30B 8GB; 3 Medium "One flag tripled tok/s"; 4 windowsforum n-cpu-moe; 5 willitrunai Qwen3/3.5 requisitos; 6 Pinggy small LLMs 8GB; 7 PCSP melhores modelos por VRAM; 8 betterclaw Gemma 4 vs Qwen 3.5; 9 canitrun.dev 16GB; 10 Unsloth Qwen3.5 GGUF benchmarks; 11 openclawdc IQ4_XS vs Q4_K_M; 12 tonisagrista quantização; 13 llama.cpp docs/speculative.md; 14 cloudmagazin MTP; 15 Unsloth MTP docs; 16 llmrequirements MTP merge; 17 llmhardware KV cache quant; 18 techplained KV Q8; 19 insiderllm CPU-only LLMs; 20 point.free Gemma 4 em Xeon 2016; 21 inventivehq MoE on CPU.
