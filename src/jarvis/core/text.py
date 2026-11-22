"""Divisão incremental de texto em streaming em frases prontas para falar."""
from __future__ import annotations

import re
from typing import Callable

# fim de frase: . ! ? … seguido de espaço/fim; não corta decimais ("3.5") nem "1." de listas
_BOUNDARY = re.compile(r"(?<=[.!?…])(?<!\d\.)\s+|\n{1,}")
_CLAUSE = re.compile(r"[,;:]\s+")


class SentenceSplitter:
    """feed() recebe pedaços do stream; chama `emit` a cada frase completa; flush() solta o resto.

    Frases muito curtas (< min_chars) são coladas à seguinte para a fala não ficar picotada ("Ok." + "Abri o app.").
    """

    def __init__(self, emit: Callable[[str], None], min_chars: int = 12) -> None:
        self._emit = emit
        self._min = min_chars
        self._buf = ""
        self._carry = ""
        self._emitted = False                    # já soltou algo? (a PRIMEIRA fala sai na 1ª oração, sem esperar o ponto final)

    def feed(self, chunk: str) -> None:
        self._buf += chunk
        parts = _BOUNDARY.split(self._buf)
        self._buf = parts[-1]
        for sentence in parts[:-1]:
            self._push(sentence)
        if not self._emitted and not self._carry and len(self._buf) >= 40:
            m = _CLAUSE.search(self._buf, 24)    # vírgula/dois-pontos/ponto e vírgula seguido de espaço, depois de ~24 letras
            if m:
                head, self._buf = self._buf[:m.start() + 1], self._buf[m.end():]
                self._push(head)

    def flush(self) -> None:
        if self._buf.strip():
            self._push(self._buf)
        self._buf = ""
        if self._carry.strip():
            self._emit(self._carry.strip())
        self._carry = ""

    def _push(self, sentence: str) -> None:
        self._emitted = True
        s = (self._carry + " " + sentence).strip() if self._carry else sentence.strip()
        if not s:
            return
        if len(s) < self._min:
            self._carry = s
            return
        self._carry = ""
        self._emit(s)
