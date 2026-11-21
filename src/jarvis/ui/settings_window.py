"""Fachada de compatibilidade da tela de Configuracoes (o codigo vive em ``jarvis.ui.settings``).

    from jarvis.ui.settings_window import open_settings, main_settings
    main_settings()                      # programa proprio (cria o QApplication)
    open_settings(cfg, parent=janela)    # dentro de um app Qt ja em execucao

``collect_values(window)`` e ``apply_values(window, valores)`` leem e preenchem o formulario.
"""
from __future__ import annotations

from .settings.app import apply_values, collect_values, main_settings, open_settings
from .settings.window import SettingsWindow

__all__ = ["SettingsWindow", "open_settings", "main_settings", "collect_values", "apply_values"]
