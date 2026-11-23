"""Painel Terminal do Eco (janela própria): comandos, saída em tempo real, parar, copiar e limpar.

    python -m jarvis terminal                              # programa isolado
    from jarvis.ui.terminal import TerminalPanel, open_terminal, main_terminal
"""
from __future__ import annotations

from .panel import TerminalPanel, main_terminal, open_terminal

__all__ = ["TerminalPanel", "main_terminal", "open_terminal"]
