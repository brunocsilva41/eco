"""Todas as strings da UI (pt-BR) em um unico lugar, preparadas para i18n.

Cada area e um dataclass imutavel; ``S`` e o conjunto ativo. Para outro idioma, crie outra
instancia de ``Strings`` e troque com ``set_strings``. Componentes leem ``S`` na hora de montar
o texto, nunca guardam literais. Regras de redacao: frases curtas, sem jargao, sem travessao,
erro sempre responde "o que houve, por que importa, o que fazer".
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Common:
    cancel: str = "Cancelar"
    confirm: str = "Confirmar"
    save: str = "Salvar"
    discard: str = "Descartar"
    reset_defaults: str = "Restaurar padrão"
    close: str = "Fechar"
    retry: str = "Tentar de novo"
    browse: str = "Procurar..."
    add: str = "Adicionar"
    remove: str = "Remover"
    clear: str = "Limpar"
    search: str = "Buscar"
    increase: str = "Aumentar"
    decrease: str = "Diminuir"
    on: str = "Ligado"
    off: str = "Desligado"
    none: str = "Nenhuma"


@dataclass(frozen=True)
class Fields:
    restart_required: str = "Requer reinício"
    restart_hint: str = "A mudança só vale depois de reiniciar o Eco."
    locked: str = "Protegido"
    modified: str = "Alterado"
    error_prefix: str = "Erro"
    chip_placeholder: str = "Digite e tecle Enter"
    chip_remove: str = "Remover {item}"
    chip_duplicate: str = "{item} já está na lista."
    path_choose_file: str = "Escolher arquivo"
    path_choose_dir: str = "Escolher pasta"
    key_none: str = "Nenhuma tecla definida"
    key_capturing: str = "Pressione a combinação (Esc cancela, Backspace limpa)"
    key_hint: str = "Enter ou Espaço para mudar a tecla"
    search_placeholder: str = "Buscar"
    search_clear: str = "Limpar busca"


@dataclass(frozen=True)
class Bar:
    save_busy: str = "Salvando..."

    def pending(self, n: int) -> str:
        return "Sem alterações" if n == 0 else (
            "1 alteração" if n == 1 else f"{n} alterações")

    def errors(self, n: int) -> str:
        return "1 erro para corrigir" if n == 1 else f"{n} erros para corrigir"


@dataclass(frozen=True)
class Status:
    ok: str = "Tudo certo"
    warn: str = "Atenção"
    error: str = "Erro"
    neutral: str = "Sem estado"
    listening: str = "Ouvindo"
    recording: str = "Gravando"
    idle: str = "Parado"
    level_low: str = "Baixo"
    level_ok: str = "Ótimo"
    level_clip: str = "Saturado"
    meter_name: str = "Nível do microfone"
    countdown_name: str = "Tempo restante"
    seconds: str = "s"

    def db(self, v: float) -> str:
        return f"{round(v):d} dB".replace("-", "−")   # round() devolve int: nunca "-0"


@dataclass(frozen=True)
class Dialog:
    type_to_confirm: str = "Para continuar, digite {word}"
    target_label: str = "Item afetado"
    cannot_undo: str = "Esta ação não pode ser desfeita."
    delete: str = "Apagar"


@dataclass(frozen=True)
class Banner:
    why: str = "Por que importa"
    todo: str = "O que fazer"
    dismiss: str = "Dispensar aviso"


@dataclass(frozen=True)
class States:
    loading_default: str = "Carregando"
    error_title_default: str = "Não foi possível carregar"
    empty_title_default: str = "Nada por aqui ainda"


@dataclass(frozen=True)
class Nav:
    errors: str = "{n} com erro"
    changes: str = "{n} alterado"

    def describe(self, label: str, errors: int, changes: int) -> str:
        parts = [label]
        if errors:
            parts.append(f"{errors} {'erro' if errors == 1 else 'erros'}")
        if changes:
            parts.append(f"{changes} {'alteração' if changes == 1 else 'alterações'}")
        return ", ".join(parts)


@dataclass(frozen=True)
class Strings:
    common: Common = field(default_factory=Common)
    fields: Fields = field(default_factory=Fields)
    bar: Bar = field(default_factory=Bar)
    status: Status = field(default_factory=Status)
    dialog: Dialog = field(default_factory=Dialog)
    banner: Banner = field(default_factory=Banner)
    states: States = field(default_factory=States)
    nav: Nav = field(default_factory=Nav)


PT_BR = Strings()
S: Strings = PT_BR


def set_strings(strings: Strings) -> None:
    """Troca o conjunto ativo (outro idioma). Chame antes de criar as janelas."""
    global S
    S = strings
