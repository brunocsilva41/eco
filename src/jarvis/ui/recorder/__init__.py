"""Gravador de voz ("Minha voz") do Eco: vista, modelo e controlador sobre ``jarvis.recording`` e o kit de UI.

Uso: ``open_recorder(cfg, parent=None, set_name="frases"|"eco")`` abre (ou traz a frente) a janela dentro de um
``QApplication`` ja ativo; ``main_recorder(cfg, set_name=...)`` roda como programa proprio. Fachada de
compatibilidade: ``jarvis.ui.recorder_window``.
"""
from __future__ import annotations

from .launcher import main_recorder, open_recorder
from .model import SET_FRASES, SET_JARVIS, SET_NAMES
from .window import RecorderWindow

__all__ = ["RecorderWindow", "SET_FRASES", "SET_JARVIS", "SET_NAMES", "main_recorder", "open_recorder"]
