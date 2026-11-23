"""Fachada de compatibilidade do gravador de voz. O codigo vive em ``jarvis.ui.recorder``.

API estavel (usada pelas Configuracoes e pelo CLI ``python -m jarvis record``):

* ``RecorderWindow``: a janela;
* ``open_recorder(cfg, parent=None, set_name="frases") -> RecorderWindow``: abre ou traz a frente; ``set_name`` e
  "frases" (conjunto de frases do usuário) ou "eco" (amostras da palavra Eco); outro valor levanta ``ValueError``;
* ``main_recorder(cfg, set_name="frases") -> int``: roda como programa proprio e devolve o codigo de saida.
"""
from __future__ import annotations

from .recorder import RecorderWindow, main_recorder, open_recorder

__all__ = ["RecorderWindow", "main_recorder", "open_recorder"]
