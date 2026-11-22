"""Carga das DLLs do Windows. Cada modulo recebe a SUA instancia: argtypes/restype ficam no objeto da DLL, e modulos
diferentes declaram assinaturas diferentes para a mesma funcao (compartilhar a instancia as sobrescreveria)."""
from __future__ import annotations

import ctypes


def load_dll(name: str) -> ctypes.WinDLL:
    return ctypes.WinDLL(name, use_last_error=True)
