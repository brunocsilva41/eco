"""Configurações do Eco: esquema por campo, validação, gravação atômica e canal de controle com o app em execução."""
from .store import Changes, Problem, SaveResult, SettingsError, SettingsStore

__all__ = ["SettingsStore", "SettingsError", "Problem", "Changes", "SaveResult"]
