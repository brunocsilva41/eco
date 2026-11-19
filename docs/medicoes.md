# Medições (máquina do Bruno) — 2026-11-19

Hardware: Xeon E5-2650 v4, 16 GB RAM, RX 580 2048SP 8 GB, driver AMD 31.0.21924.61 (NÃO atualizado).
llama.cpp: build b12531 (commit e4b620af1), `llama-b12531-bin-win-vulkan-x64.zip`, sha256 conferido.
Vulkan: llama.cpp detecta "AMD Radeon RX 580 2048SP (AMD proprietary driver)"; fp16: 0, matrix cores: none. (`vulkaninfo` não está instalado.)
Comando: `llama-bench -m <gguf> -ngl 99 -p 512 -n 128 -r 3`

| Modelo (Q4_K_M) | Arquivo | pp512 t/s | tg128 t/s | VRAM do servidor (c=4096, +mmproj) |
|---|---|---:|---:|---:|
| Qwen3-VL 4B Instruct | 2.32 GiB | 192.9 ± 3.2 | 20.9 ± 1.1 | +3.71 GB |
| Gemma 3 4B it | 2.31 GiB | 227.1 ± 3.1 | 16.4 ± 1.8 | +3.86 GB |
| Qwen3-VL 8B Instruct | 4.68 GiB | 102.3 ± 3.0 | 16.3 ± 0.4 | +5.99 GB |

VRAM: contador "GPU Adapter Memory\Dedicated Usage" antes/depois de carregar (base ~0,9 GB do Windows). Total com 8B ≈ 6,9 GB de 8.

Teste de API (llama-server 127.0.0.1:8089, --jinja, 1 amostra cada, não é benchmark de qualidade):
- Qwen3-VL 4B: pt-BR ok ("Saia às 8h20."); tool call correto (`abrir_app {"nome":"Bloco de Notas"}`).
- Gemma 3 4B: pt-BR ok; tool call FALHOU (disse que abriu, sem chamar a ferramenta — alucinação).
- Qwen3-VL 8B: pt-BR ok; tool call correto.
- A 1ª requisição do 4B levou ~5 s (inclui aquecimento); latência de regime não medida.

Limites: 1 amostra de tool calling por modelo; visão (imagem) ainda não testada; driver antigo.

---
# Rodada 2 — candidatos novos (2026-11-19), mesmo build b12531

Fonte dos arquivos: API do Hugging Face em 2026-11-19 (ggml-org/gemma-4-E4B-it-GGUF, unsloth/Qwen3.5-4B-GGUF, unsloth/Qwen3.5-9B-GGUF); SHA256 de todos conferido. Qwen/Qwen3.5-4B-GGUF oficial não existe (usei Unsloth).
Gemma 4 E4B: só havia Q4_0 (4,26 GiB), não Q4_K_M. Qwen3.5 e Gemma 4 são modelos com "thinking": testados com `--reasoning off` (sem isso gastam os tokens pensando e a resposta vem vazia).

`llama-bench -ngl 99 -p 512 -n 128 -r 3 -fa 0,1` (t/s; fa = flash attention):

| Modelo | fa=0 pp512 | fa=0 tg128 | fa=1 pp512 | fa=1 tg128 | VRAM do servidor (+) |
|---|---:|---:|---:|---:|---:|
| Qwen3-VL 4B Q4_K_M | 200,6 ± 2,5 | 19,75 ± 0,05 | 161,7 ± 2,9 | 20,93 ± 0,17 | +3,71 GB |
| Qwen3.5 4B Q4_K_M | 215,7 ± 0,2 | 18,27 ± 0,21 | 210,8 ± 0,5 | 18,14 ± 0,13 | +3,77 GB |
| Gemma 4 E4B Q4_0 (7,46 B params totais) | 205,1 ± 50,3* | 12,24 ± 0,75 | 206,5 ± 5,6 | 14,02 ± 0,16 | +3,87 GB |
| Qwen3.5 9B Q4_K_M | 113,1 ± 0,4 | 14,32 ± 0,09 | 110,4 ± 0,5 | 13,90 ± 0,32 | +6,29 GB (total ~7,2 de 8 GB) |
(*) variância alta, rodou com download em andamento.

- `--device Vulkan0`: funciona; só há 1 GPU, sem efeito medido (Qwen3-VL 4B fa=0: 203,4 / 19,3 com download rodando em paralelo).
- Flash attention no Vulkan da RX 580: sem ganho consistente (tg ±1 t/s, pp do Qwen3-VL cai ~20% com fa=1). Manter o padrão (fa desligado/auto).

Teste de API (1 amostra, `--reasoning off`, pergunta: sair a que horas para reunião às 9h com 40 min de trânsito):
- Qwen3.5 4B: "Saia às 8h20" correto, 1,5 s; tool call correto.
- Qwen3.5 9B: correto, 2,8 s; tool call correto.
- Gemma 4 E4B: respondeu "7h20" (ERRADO); tool call correto.
- Resumo de tool calling (Bloco de Notas): Qwen3-VL 4B ok, Qwen3-VL 8B ok, Qwen3.5 4B ok, Qwen3.5 9B ok, Gemma 4 E4B ok, Gemma 3 4B falhou.
Não testado: áudio do Gemma 4 no llama.cpp (fica para a F2), visão, Qwen3-ASR, TTS, vídeo.

---
# Rodada 3 — MoE, KV cache, MTP, RAM (2026-11-19), build b12531

## RAM
`Win32_PhysicalMemory`: 2 pentes de 8 GB, DDR4 a 2133 MT/s (configurado 2133), fabricante "Undefined". Sobraram 6–7 GB livres durante os testes com o MoE. Quantos canais estão ativos NÃO deu para confirmar por software (o Xeon E5 v4 suporta 4; só 2 slots estão ocupados). Teórico: 2133 MT/s x 8 B = ~17 GB/s por canal; com 2 canais ~34 GB/s (conta minha, não medida). `wmic` não usado (obsoleto); usei CIM.

## KV cache (Qwen3-VL 4B Q4_K_M, -fa 1)
| ctk / ctv | pp512 | tg128 |
|---|---:|---:|
| f16 / f16 | 196,3 ± 0,1 | 21,95 ± 0,24 |
| f16 / q8_0 | 189,4 ± 4,7 | 20,60 ± 0,39 |
| q8_0 / f16 | 157,3 ± 2,8 | 19,06 ± 0,22 |
| q8_0 / q8_0 | 145,8 ± 1,1 | 18,25 ± 0,11 |
KV q8_0 funciona no Vulkan com -fa 1, mas é 7–25% MAIS LENTO e não medi a qualidade. Só vale para economizar VRAM em contexto longo; com contexto 4096 não é necessário. Manter f16.

## MoE: gpt-oss-20b MXFP4 (ggml-org, 11,27 GiB, 24 camadas), -ngl 99, --n-cpu-moe N
| N (camadas c/ experts na CPU) | pp512 | tg128 | VRAM máx | RAM livre |
|---:|---:|---:|---:|---:|
| 24 (= --cpu-moe) | 7,6 ± 1,2 | 2,52 ± 0,08 | 2,62 GB | 7,0 GB |
| 20 | 16,1 ± 5,7 | 4,25 ± 1,97 | 4,18 GB | 6,6 GB |
| 16 | 47 ± 46 | 8,87 ± 0,91 | 7,77 GB | 7,1 GB |
| 12 | 93,1 ± 5,4 | 9,98 ± 1,46 | 7,15 GB | 6,0 GB |
| 8 | falhou: "unable to allocate Vulkan0 buffer" | | | |
(`-r 2`; alta variância; VRAM = pico do contador, inclui ~0,9 GB do Windows. N=16 gravou 7,77 GB, acima do N=12: provavelmente buffer de computação maior, não investigado.)
Conclusão: o melhor ponto é N=12 (~10 tok/s, 93 pp), preso à RAM DDR4-2133 e quase sem folga de VRAM (7,15 de 8 GB), sem visão/áudio. É PIOR que o Qwen3-VL 4B (~20 tok/s, 200 pp, 3,7 GB). MoE não compensa nesta máquina com 16 GB de RAM; -fit off não foi necessário (usei -ncmoe manual).

## MTP / speculative (Gemma 4 E4B Q4_0, llama-server, 144 tokens, temp 0)
O build aceita `--spec-type` (none, draft-simple, draft-eagle3, draft-mtp, draft-dflash, ..., ngram-*).
| Config | tg t/s | aceitação |
|---|---:|---|
| sem spec | 14,9 | — |
| `--spec-type draft-mtp -md mtp-gemma-4-E4B-it-Q4_0.gguf` (57 MB) | 18,0 | 74/210 (35%) |
| `--spec-type ngram-mod` | 14,9 (1ª vez) / 56 (repetindo o MESMO prompt) | 128/128 só na repetição |
MTP deu +21% no Gemma 4 E4B (continua abaixo do Qwen3-VL 4B puro: 18 contra ~20 t/s, e com a conta de hora errada). O 56 t/s do ngram é artefato de repetir o mesmo prompt; não é ganho real em conversa. MTP não testado no Qwen3.5 (não baixei GGUF com cabeças MTP).
