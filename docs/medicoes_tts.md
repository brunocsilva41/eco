# Medicoes TTS em CPU (Fase 2)

Data: 2026-11-19. Maquina: Xeon E5-2650 v4, 16 GB, Windows 10, CPU apenas (sem GPU). Python 3.14.4 (venv F:\Jarvis\venv).
Versoes: piper-tts 1.8.0, onnxruntime 1.32.0, numpy 2.5.5. Nada foi instalado no venv.

## Piper pt_BR-faber-medium
- Fonte: https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR/faber/medium (consultada em 2026-11-19).
- Arquivos em F:\Jarvis\models\piper-faber\: .onnx 63.221.984 bytes, SHA256 75e913eb463db0b6ac7ddf68d3e4c9ac19ace36dc3b710a81039b448352b8ffc (igual ao LFS oid do HF); .onnx.json 6.257 bytes (tamanho igual ao do HF).
- Taxa de amostragem: 22050 Hz (config e WAV conferidos). WAV 16 bits mono em F:\Jarvis\tests\audio_piper\01.wav a 20.wav, na ordem das frases.
- API real 1.8.0 (lida no codigo instalado): `PiperVoice.load(model, config, use_cuda=False)`; `voice.synthesize(text, syn_config=None)` e um gerador que devolve um `AudioChunk` por SENTENCA (`.audio_int16_array`); `synthesize_wav(...)` grava WAV. CLI: `python -m piper -m modelo.onnx -f saida.wav`.
- Comando: `F:\Jarvis\venv\Scripts\python.exe -I F:\Jarvis\src\f2\tts_bench.py piper` (1 aquecimento fora da medicao, depois 20 frases, 1 execucao cada; threads do onnxruntime em padrao, nao ajustadas).

| Metrica | media | min | max |
|---|---|---|---|
| Tempo ate 1o audio (s) | 0,144 | 0,084 | 0,196 |
| Tempo total de sintese (s) | 0,144 | 0,085 | 0,196 |
| Duracao do audio (s) | 2,41 | 1,37 | 3,24 |
| RTF (total/duracao) | 0,060 | 0,054 | 0,064 |

Observacoes: as 20 frases tem uma sentenca cada, entao primeiro chunk = total; em textos longos o primeiro audio sai apos a 1a sentenca. O tempo ate o primeiro audio inclui fonemizacao (espeak). Medicao de uma rodada so, sem repeticoes; a variacao entre rodadas nao foi medida. Tempo de carga do modelo nao medido.
Qualidade, naturalidade e erros de pronuncia: NAO avaliados; precisa de escuta do usuário (os WAV estao prontos).
Licenca: piper-tts e GPL-3.0-or-later (metadados do pacote). Licenca da voz faber: ver MODEL_CARD no repositorio (nao verificada por mim).

## Alternativas (nao medidas)
- Kokoro (hexgrad/Kokoro-82M, Apache-2.0, ultima modificacao 2025-04-10): tem vozes pt-BR (pf_dora, pm_alex, pm_santa). Pacote kokoro-onnx 0.6.1 no PyPI exige Python <3.14, portanto nao instala no venv 3.14. Precisaria de um segundo Python (3.10-3.13; `py -0` mostra so o 3.14.4 instalado). Pulado. O script ja tem um backend `kokoro` (pasta models\kokoro, voz pf_dora) nao testado.
- Kyutai Pocket TTS (kyutai/pocket-tts, cc-by-4.0, modificado em 2026-10-21): idiomas declarados no HF incluem pt; modelo com acesso restrito (gated, exige aceitar termos). Pacote pocket-tts 4.0.1 exige torch>=2.5 (pesado); nao instalado, pulado. Nao verificado se roda em CPU no Python 3.14/Windows.
