"""Painel "O que o Jarvis sabe de mim" (memórias, conversas, armazenamento e privacidade).

Pacote com vista, modelo e controlador (nenhum arquivo passa de 400 linhas):

* texts.py        textos pt-BR (dataclass imutável + ``T``)
* logic.py        formatação e mensagens de erro (sem Qt)
* service.py      acesso ao banco, roda em thread (sem Qt)
* rows.py         linhas das listas (sem Qt); rowview.py, a pintura delas
* controller.py   conexão, trabalho em segundo plano e avisos; ``*_ctl.py``, um controlador por área
* ``*_area.py``, listpane.py, memory_detail.py, conversation_view.py, reader.py, areabar.py: vistas só de apresentação
* panel.py        ``MemoryPanel``; window.py: ``open_memory`` e ``main_memory``

API pública (estável; ``ui/memory_panel.py`` reexporta)::

    MemoryPanel(cfg, parent=None)       QWidget com ``close_memory()`` e ``memory()``
    open_memory(cfg=None, parent=None)  janela própria
    main_memory() -> int                programa isolado (``python -m jarvis memory``)
"""
from __future__ import annotations

from .panel import MemoryPanel
from .window import main_memory, open_memory

__all__ = ["MemoryPanel", "main_memory", "open_memory"]
