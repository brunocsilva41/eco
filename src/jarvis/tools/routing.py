"""Roteamento de ferramentas por pedido: o modelo de 4B só VÊ as ferramentas que fazem sentido para o que foi pedido.

Com 35 ferramentas ele escolhia errado (clicar_controle x clicar_em x clicar_na_tela, arquivo x memória...). Cada pedido recebe um
conjunto pequeno e ESTÁVEL (mesma ordem sempre: o prefixo do prompt se repete e o cache do servidor continua valendo).
Ferramentas internas (clicar_em, clicar_na_tela) nunca são oferecidas: clicar_controle já cai nelas sozinho.
"""
from __future__ import annotations

import re
import time

from ..core.textutil import fold

BASE = ("hora_atual", "janela_ativa", "ver_tela")
BUNDLES: dict[str, tuple[str, ...]] = {
    "apps": ("abrir_app", "listar_apps_permitidos", "abrir_pasta", "focar_janela", "janela_acao", "fechar_janela", "listar_janelas", "ajustar_volume"),
    "controle": ("clicar_controle", "digitar_texto", "apertar_atalho", "rolar_tela", "mover_mouse", "arrastar", "localizar_na_tela", "focar_janela"),
    "arquivos": ("listar_pasta", "ler_arquivo", "criar_arquivo", "editar_arquivo", "copiar_arquivo", "mover_arquivo",
                 "apagar_arquivo", "desfazer", "abrir_pasta"),
    "memoria": ("lembrar", "esquecer", "editar_memoria", "listar_memorias", "buscar_memoria", "buscar_conversas",
                "abrir_conversa", "listar_conversas", "nova_conversa", "resumir_conversa"),
}
CORE_BUNDLES = ("apps", "controle", "arquivos")                          # sempre oferecidos, sempre nesta ordem
HIDDEN = frozenset({"clicar_em", "clicar_na_tela"})          # registradas, mas nunca oferecidas ao modelo

_KEYWORDS: dict[str, re.Pattern[str]] = {name: re.compile(p) for name, p in {
    "apps": r"\b(abr|inici|execut|rod[ae]|lanc|program|aplicativ|app\b|apps\b|janela|fech|minimiz|maximiz|volume|som\b|audio|mudo|"
            r"aument|diminu|abaix|troc|alternar|foc[ao]|trazer|navegador|chrome|edge|bloco|calculadora|paint)",
    "controle": r"\b(cliq|clic|toque|aperte|apert|digit|escrev|tecl|atalho|col[ae]\b|colar|selecion|rol[ae]r?\b|role\b|scroll|"
                r"botao|menu|aba\b|link|icone|mouse|cursor|enter\b|esc\b|ctrl|copi[ae]|pagina|marque|desmarque|preench)",
    "arquivos": r"\b(arquiv|pasta|documento|download|area de trabalho|desktop|apag|delet|exclu|mov[ae]|renome|cri[ae]|salv|"
                r"ler\b|leia|planilha|pdf|imagem|foto|copi[ae]|desfaz|lixeira|\.txt|\.docx|\.pdf)",
    "memoria": r"\b(lembr|memori|esquec|conversa|anot|guard|resum|ontem|historico|o que (eu|voce) (falou|disse|pedi)|nova conversa)",
}.items()}
_STICKY_S = 180.0
_last: tuple[float, frozenset[str]] = (0.0, frozenset())


def reset() -> None:
    global _last
    _last = (0.0, frozenset())


def bundles_for(user_text: str) -> frozenset[str]:
    text = fold(user_text)
    return frozenset(name for name, pat in _KEYWORDS.items() if pat.search(text))


def route(user_text: str) -> tuple[list[str], frozenset[str]]:
    """(nomes de ferramentas oferecidas, conjuntos escolhidos). Sem nenhuma palavra-chave, repete o conjunto dos últimos 3 min
    (continuação: 'e agora clique em OK'); sem histórico, só a base."""
    global _last
    hits = bundles_for(user_text)
    if not hits and time.monotonic() - _last[0] <= _STICKY_S:
        hits = _last[1]
    if hits:
        _last = (time.monotonic(), hits)
    # NÚCLEO FIXO e ORDENADO (base + apps + controle) em TODO pedido; extras (arquivos, memória) só ACRESCENTADOS no fim.
    # Assim todos os pedidos compartilham o mesmo prefixo longo no cache do servidor (medido: 1º token 0,7-0,9 s em cache
    # contra 5-9 s ao trocar o miolo da lista de ferramentas).
    names: list[str] = list(BASE)
    for bundle in CORE_BUNDLES + tuple(b for b in BUNDLES if b not in CORE_BUNDLES and b in hits):
        names.extend(n for n in BUNDLES[bundle] if n not in names)
    return names, hits
