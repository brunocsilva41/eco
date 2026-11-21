"""Gravador de voz do Jarvis (frases para medir o STT e amostras da futura palavra de ativação).

Camadas (a lógica não importa Qt; a interface vive em ``jarvis.ui.recorder``, com a fachada ``jarvis.ui.recorder_window``):

* ``phrasebook``      lista de frases em arquivo UTF-8, gravação atômica;
* ``audio_analysis``  pico, RMS, saturação, silêncio e veredito (``assess``);
* ``wavio``           WAV 16 kHz mono PCM16, escrita atômica;
* ``session``         conjuntos (``sentences_set``, ``wakeword_set``) e ``RecordingSession``;
* ``recorder``        ``MicRecorder`` (duração exata, medidor ao vivo) e lista de microfones;
* ``player``          reprodução interrompível.

Como abrir a janela
-------------------
Como programa independente (``python -m jarvis record``)::

    from jarvis.config import load
    from jarvis.ui.recorder_window import main_recorder

    raise SystemExit(main_recorder(load(), set_name="frases"))      # ou "jarvis"

A partir das Configurações (seção "Minha voz"), com um ``QApplication`` já em execução::

    from jarvis.ui.recorder_window import open_recorder

    window = open_recorder(cfg, parent=self, set_name="jarvis")   # reutiliza a janela se já estiver aberta

Saídas: frases em ``tests/audio_bruno/NN.wav``; palavra de ativação em ``<data>/wakeword/jarvis/NNN.wav``.
"""
