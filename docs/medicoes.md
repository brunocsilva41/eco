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
