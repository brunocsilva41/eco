"""Níveis de risco das ações (camada neutra: segurança e ferramentas dependem daqui, não uma da outra)."""
from __future__ import annotations

from enum import IntEnum


class Risk(IntEnum):
    READ = 0       # só lê/consulta
    CONTROL = 1    # controla o PC de forma reversível (abrir app, focar janela)
    RISKY = 2      # destrutivo, irreversível, envio, instalação, pagamento, digitação, configuração do sistema
