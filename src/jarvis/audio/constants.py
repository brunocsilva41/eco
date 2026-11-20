"""Constantes compartilhadas pelo subsistema de áudio (fonte única; não redefina nos módulos)."""
from __future__ import annotations

SAMPLE_RATE = 16000                 # captura, VAD e Whisper trabalham sempre a 16 kHz mono
STALL_INPUT_S = 2.0                 # sem callback de ENTRADA por tanto tempo = microfone morto
STALL_OUTPUT_S = 3.0                # sem callback de SAÍDA por tanto tempo = alto-falante travado
JOIN_S = 1.0                        # espera máxima ao juntar threads auxiliares curtas (monitor de reprodução)
SYNTH_JOIN_S = 5.0                  # espera máxima ao juntar threads que podem estar no meio de uma síntese
