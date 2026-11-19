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
