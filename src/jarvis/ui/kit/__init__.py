"""Kit de componentes do Jarvis (PySide6). Base: ``ui/theme.py`` (tokens) e ``ui/strings.py`` (textos pt-BR).

Regras do kit
-------------
* Componentes nao tem logica de negocio: recebem valores, emitem sinais tipados.
* Controles de valor seguem o mesmo contrato: ``value()``, ``set_value(v)``, sinal
  ``valueChanged(<tipo>)``, ``set_invalid(bool)``. (TextField str, NumberField float, ComboField
  object, ToggleSwitch bool, PathField str, ChipList list, KeyCaptureField str)
* Estados: normal, hover, foco (anel ambar 2 px), pressionado, desabilitado, erro. Todos tem
  ``accessibleName``/``accessibleDescription``.
* Cor, tamanho, raio e espaco vem SO de ``theme`` (``pal()``, ``SPACE``, ``RADIUS``, ``TYPE``,
  ``SIZE``); texto vem de ``strings.S``. Nunca coloque numero ou cor solta numa tela.
* Tema em tempo de execucao: ``ThemeManager.instance().set_mode("dark"|"light"|"system")``.
  Componentes pintados se repintam sozinhos (``watch_theme``); stylesheet e regenerada.
* Animacao: ``base.animate`` (120 a 180 ms) respeita "reduzir animacoes"; tudo pertence a um widget
  pai, entao nada vaza. Unico laco permitido: ``ListeningIndicator`` (ouvindo/gravando).

Composicao de uma tela (coluna de leitura, barra de acoes fixa)::

    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget
    from jarvis.ui.theme import ThemeManager, SIZE, SPACE
    from jarvis.ui.kit import (ActionBar, ComboField, FieldRow, NavList, NumberField, Section,
                               SearchField, TextField, ToggleSwitch, InlineBanner)

    ThemeManager.instance().apply(app)                 # uma vez, no inicio

    nav = NavList()                                    # coluna de 240 px
    nav.add_entry("voz", "Voz e audio", "mic")
    nav.add_entry("seg", "Ferramentas e seguranca", "shield")
    nav.currentKeyChanged.connect(show_page)           # str com a chave

    page = QWidget()
    col = QVBoxLayout(page)                            # coluna de no maximo SIZE.reading_width
    col.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xl)
    voz = Section("Entrada de voz", "Escolha o microfone e o quanto ele escuta.")
    voz.add(FieldRow("Microfone", ComboField([("Padrao do Windows", "default")]),
                     help="Usado em todas as conversas."))
    voz.add(FieldRow("Sensibilidade", NumberField(60, minimum=0, maximum=100, suffix="%"),
                     help="Mais alto capta falas mais baixas.", restart_required=True))
    voz.add(FieldRow("Ouvir sem apertar tecla", ToggleSwitch(True), help="Fica sempre ao alcance da voz."))
    col.addWidget(voz)
    avancado = Section("Avancado", level=2)            # level 2: ritmo mais curto
    row = avancado.add(FieldRow("Pasta de logs", PathField("C:/Jarvis/logs", mode="dir"), stacked=True))
    col.addWidget(avancado)
    col.addStretch(1)

    bar = ActionBar()                                  # so aparece com alteracoes pendentes
    bar.saveRequested.connect(save)
    bar.set_changes(2)                                 # "2 alteracoes pendentes"; set_changes(2, errors=1) bloqueia Salvar
    row.set_error("Esta pasta nao existe. Escolha outra para os logs serem gravados.")  # erro junto do campo

Busca com Ctrl+F: ``SearchField().bind_shortcut(janela)`` e ``searchChanged(str)``.
Confirmacao: ``ConfirmDialog.ask(janela, title="Apagar memoria", target=texto_real, destructive=True,
confirm_text="Apagar", require_word="APAGAR")``. Aviso: ``Toast.show_message(janela, "ok", "Salvo")``
ou ``InlineBanner.error(o_que, por_que, o_que_fazer)``. Galeria: ``python -m jarvis.ui.kit.gallery``.
"""
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

# Importacao preguicosa (PEP 562): theme.py importa kit.color, entao este pacote nao pode importar os
# componentes no topo (eles importam theme). ``from jarvis.ui.kit import Button`` funciona normalmente.
_EXPORTS: dict[str, str] = {
    "ActionBar": ".actionbar",
    "Button": ".buttons",
    "ButtonVariant": ".buttons",
    "Card": ".layout",
    "ChipList": ".chips",
    "ComboField": ".fields",
    "ConfirmDialog": ".dialogs",
    "CountdownRing": ".meters",
    "ElidedLabel": ".base",
    "EmptyState": ".states",
    "ErrorState": ".states",
    "FieldRow": ".layout",
    "IconSet": ".icons",
    "InlineBanner": ".feedback",
    "KeyCaptureField": ".keycapture",
    "Label": ".base",
    "LevelMeter": ".meters",
    "ListeningIndicator": ".indicator",
    "LoadingState": ".states",
    "MessageBlock": ".feedback",
    "NavList": ".navlist",
    "NumberField": ".fields",
    "PathField": ".fields",
    "ProgressBar": ".meters",
    "SearchField": ".search",
    "Section": ".layout",
    "StatusChip": ".status",
    "TextField": ".fields",
    "Toast": ".feedback",
    "ToggleSwitch": ".toggle",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(import_module(_EXPORTS[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from .actionbar import ActionBar
    from .base import ElidedLabel, Label
    from .buttons import Button, ButtonVariant
    from .chips import ChipList
    from .dialogs import ConfirmDialog
    from .feedback import InlineBanner, MessageBlock, Toast
    from .fields import ComboField, NumberField, PathField, TextField
    from .icons import IconSet
    from .indicator import ListeningIndicator
    from .keycapture import KeyCaptureField
    from .layout import Card, FieldRow, Section
    from .meters import CountdownRing, LevelMeter, ProgressBar
    from .navlist import NavList
    from .search import SearchField
    from .states import EmptyState, ErrorState, LoadingState
    from .status import StatusChip
    from .toggle import ToggleSwitch
