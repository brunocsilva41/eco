"""Fachada de compatibilidade do painel "O que o Jarvis sabe de mim".

O painel foi repaginado e mora no pacote ``jarvis.ui.memory`` (vista, modelo e controlador). Este módulo só
reexporta a API pública, que continua estável::

    from jarvis.ui.memory_panel import MemoryPanel, open_memory, main_memory

    MemoryPanel(cfg, parent=None)       # QWidget com close_memory() e memory(); embutido nas Configurações
    open_memory(cfg=None, parent=None)  # abre (ou traz à frente) a janela própria; devolve o MemoryPanel
    main_memory() -> int                # programa isolado: ``python -m jarvis memory``

Regras que não mudaram: todo acesso ao banco roda em thread, a conexão fecha com o painel, o modo sem histórico
(``cfg.memory.enabled`` falso) nem abre o banco, e erros viram texto em português (o detalhe vai para o log).
"""
from __future__ import annotations

from .memory import MemoryPanel, main_memory, open_memory

__all__ = ["MemoryPanel", "main_memory", "open_memory"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main_memory())
