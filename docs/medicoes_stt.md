# Medicoes STT: faster-whisper em CPU (int8), pt-BR

Data: 2026-11-19. Fase 2, parte STT. Medicao PARCIAL (limite de ~30 min): ver "Nao medido".

## Ambiente
- Windows 10, Xeon E5-2650 v4 (12 nucleos/24 threads), 16 GB RAM. Sempre `device="cpu"`, `compute_type="int8"`, GPU nao usada.
- Python 3.14.3 (venv F:\Jarvis\venv), faster-whisper 1.2.1, ctranslate2 4.9.0, av 19.0.2. Instalado so `psutil 7.2.2` (medir RAM).
- Modelos (download_root proprio, pastas novas em F:\Jarvis\models\whisper\):
  - small: `Systran/faster-whisper-small` (hf_small, 464 MB)
  - medium: `Systran/faster-whisper-medium` (hf_medium, 1460 MB)
  - large-v3-turbo: `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (hf_large-v3-turbo, 1547 MB). Nome e repo vem do mapa interno do faster-whisper 1.2.1 (`faster_whisper/utils.py`); a API do HF redirecionou esse repo para `dropbox-dash/faster-whisper-large-v3-turbo` em 2026-11-19 (nao investiguei o motivo).
- Fontes consultadas em 2026-11-19: https://huggingface.co/api/models?author=Systran&search=faster-whisper (lista Systran: tiny/base/small/medium/large-v1/v2/v3, distil; NAO ha turbo no Systran); utils.py do faster-whisper instalado.

## Metodo
- Audio: `F:\Jarvis\tests\audio_piper\01..06.wav` (voz sintetica Piper, 22 kHz, duracao media ~2,1 s inferida de tempo/RTF). SO as 6 primeiras frases por configuracao (3 para o medium), por causa do tempo. Audio SINTETICO nao e a voz do Bruno: o WER abaixo e teste de fumaça, NAO o WER real. Com 6 frases (~44 palavras) um erro a mais muda o WER em ~2 pontos: resultados de WER sao muito ruidosos.
- Tempo = so `transcribe()` + consumo dos segmentos (decodificacao do WAV fora da medicao; 1 transcricao de aquecimento descartada). RTF = tempo / duracao do audio. `language="pt"`, `condition_on_previous_text=False`.
- RAM: RSS apos carga e pico (`peak_wset`, inclui a carga) via psutil, um processo por modelo/threads.
- WER: minusculas, pontuacao removida, "%" -> "por cento", Levenshtein por palavras. Numeros por extenso vs algarismos contam como erro (ex.: "3" vs "tres").
- Problema encontrado: faster-whisper 1.2.1 chama `av.open(metadata_errors=...)`, que falha com av 19 (TypeError). Contorno no script: decodificar com PyAV direto e passar o array numpy. Nao atualizei/rebaixei pacotes.
- Durante o 1o teste de small (descartado) havia download de modelos em paralelo; os numeros finais abaixo foram feitos com os downloads concluidos, mas o PC tem o OpenBot e outros processos abertos (nao isolei carga de fundo).

## Resultados (audio Piper, `tests\stt_results_piper.jsonl`)
| modelo | threads | beam | vad | n frases | carga (s) | media (s) | min (s) | max (s) | RTF | RSS pos-carga (MB) | pico (MB) | WER |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| small | 8 | 1 | off | 6 | 3,0 | 3,34 | 3,21 | 3,56 | 1,58 | 366 | 696 | 0,182 |
| small | 12 | 1 | off | 6 | 3,6 | 3,21 | 2,87 | 3,48 | 1,50 | 362 | 696 | 0,182 |
| small | 12 | 1 | on | 6 | 3,6 | 3,21 | 2,73 | 4,62 | 1,52 | 362 | 696 | 0,182 |
| small | 12 | 5 | off | 6 | 3,6 | 2,94 | 2,63 | 3,46 | 1,37 | 362 | 696 | 0,114 |
| small | 12 | 5 | on | 6 | 3,6 | 3,10 | 2,71 | 3,54 | 1,49 | 362 | 696 | 0,114 |
| small | 24 | 1 | off | 6 | 22,9 | 4,78 | 3,34 | 5,95 | 2,24 | 365 | 698 | 0,182 |
| medium | 12 | 1 | off | 3 | 25,3 | 8,24 | 7,69 | 9,24 | 4,13 | 865 | 1522 | 0,143 (3 frases) |
| large-v3-turbo | 12 | 1 | off | 6 | 67,4 | 12,59 | 11,88 | 13,86 | 5,96 | 947 | 1881 | 0,045 |

Observacoes (so o medido):
- Nenhuma configuracao chegou perto de 1,5 s neste PC com este stack. O menor tempo medido foi ~2,6 s (small, 12 threads, beam 5).
- 24 threads ficou PIOR que 12 e 8 (small: 4,78 s vs 3,21 s vs 3,34 s). 8 e 12 praticamente empatam.
- beam 5 nao foi mais lento que beam 1 no small (diferenca dentro do ruido) e baixou o WER de 0,182 para 0,114 nas 6 frases.
- vad on/off: sem diferenca de tempo relevante nem de WER nestes audios curtos; vad on teve um maximo maior (4,6 s) em uma frase.
- Tempo quase constante por frase indica custo fixo grande (o Whisper processa janela de 30 s); nao medi a causa.
- Qualidade (WER nas 6 frases): turbo 0,045 < small beam5 0,114 < medium 0,143 (so 3 frases) ~ small beam1 0,182. Nao comparavel com rigor.

## Recomendacao (provisoria)
- Nenhuma opcao atende a meta de ~1,5 s nesta medicao. Entre as medidas: `small`, int8, cpu_threads=12 (ou 8), beam_size=5, language="pt", vad_filter=True so no pipeline de captura continua (nao mudou tempo/WER aqui). ~3 s, ~0,7 GB de pico.
- turbo e medium sao 4 a 6x mais lentos que small aqui (12 s e 8 s por frase de ~2 s): inviaveis em CPU para o assistente neste teste.
- Para chegar a <1,5 s seria preciso investigar (NAO testado): `whisper.cpp`/outro runtime, modelos menores (base/tiny, `distil`), reduzir a janela, ou checar se o ctranslate2 4.9.0 em Python 3.14 esta usando AVX2 e se ha carga de fundo atrapalhando.

## Nao medido / limites
- Grade completa pedida (3 modelos x threads 8/12/24 x beam 1/5 x vad on/off) NAO foi feita: apenas as linhas da tabela. medium e turbo so com 12 threads, beam 1, vad off; turbo beam 5 / vad e threads 8/24 nao medidos; medium com 3 frases.
- WER real (voz do Bruno) nao medido. Audio SAPI (`tests\audio_sapi\`, voz Microsoft Maria Desktop pt-BR, 20 WAVs gerados por mim) existe mas nao foi usado.
- Frases 7-20 do Piper nao foram transcritas (so 1-6).

## Comandos
```
# download (ja feito)
F:\Jarvis\venv\Scripts\python.exe F:\Jarvis\src\f2\dl_whisper.py small medium large-v3-turbo
# uma configuracao
F:\Jarvis\venv\Scripts\python.exe -I F:\Jarvis\src\f2\stt_bench.py --model small --threads 12 --beams 1 5 --vads 0 1 --audio-dir F:\Jarvis\tests\audio_piper --tag piper --limit 20
# grade completa (demorada)
F:\Jarvis\venv\Scripts\python.exe -I F:\Jarvis\src\f2\stt_bench.py --grid --audio-dir F:\Jarvis\tests\audio_piper --tag piper
# WER real: gravar (precisa do Bruno) e depois medir
F:\Jarvis\venv\Scripts\python.exe -I F:\Jarvis\src\f2\record_bruno.py
F:\Jarvis\venv\Scripts\python.exe -I F:\Jarvis\src\f2\stt_bench.py --grid --audio-dir F:\Jarvis\tests\audio_bruno --tag bruno
```
Scripts: `src\f2\stt_bench.py`, `src\f2\record_bruno.py` (nao executado), `src\f2\dl_whisper.py`. Arquivos auxiliares em tests\: `stt_results_piper.jsonl` (inclui hipoteses), `stt_test.jsonl`, `run_reduced.sh`, `bench_*.log`.
