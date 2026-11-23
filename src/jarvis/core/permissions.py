"""Modo de permissões e modo YOLO.

YOLO = sem confirmações. Só pode ser LIGADO por ação manual do usuário (atalho de teclado físico tratado em app.py);
nunca por voz, pelo modelo, por ferramenta, por arquivo de configuração ou pelo canal de controle: por isso o estado
vive só na memória deste processo, não é persistido (some ao reiniciar) e expira sozinho. Desligar é sempre permitido
(por voz, atalho, emergência ou expiração). As travas duras dos manipuladores (pastas protegidas, lixeira, terminais
bloqueados para digitação, teclas de segurança) NÃO dependem de confirmação e continuam valendo no YOLO.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

MODES = ("balanced", "strict")
MAX_MINUTES = 240


class Yolo:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until = 0.0                      # monotonic; 0 = desligado
        self._listeners: list[Callable[[bool, str], None]] = []

    def on_change(self, fn: Callable[[bool, str], None]) -> None:
        self._listeners.append(fn)

    def active(self) -> bool:
        with self._lock:
            if self._until and time.monotonic() >= self._until:
                self._until = 0.0
                expired = True
            else:
                return self._until > 0
        if expired:
            self._notify(False, "expirou")
        return False

    def remaining_s(self) -> float:
        with self._lock:
            return max(0.0, self._until - time.monotonic()) if self._until else 0.0

    def activate_manual(self, minutes: int) -> None:
        """Chamado SOMENTE pelo atalho físico (app.py). Nenhuma ferramenta, voz ou config chama isto."""
        minutes = max(1, min(MAX_MINUTES, int(minutes)))
        with self._lock:
            self._until = time.monotonic() + minutes * 60
        log.warning("MODO YOLO LIGADO por %d min (ação manual): confirmações desativadas", minutes)
        self._notify(True, f"ligado por {minutes} min")

    def deactivate(self, reason: str) -> None:
        with self._lock:
            was = self._until > 0
            self._until = 0.0
        if was:
            log.warning("MODO YOLO DESLIGADO (%s)", reason)
            self._notify(False, reason)

    def _notify(self, on: bool, why: str) -> None:
        for fn in list(self._listeners):
            try:
                fn(on, why)
            except Exception:  # noqa: BLE001
                log.exception("ouvinte do YOLO falhou")


YOLO = Yolo()
