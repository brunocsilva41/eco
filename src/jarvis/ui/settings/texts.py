"""Todas as strings da tela de Configuracoes (pt-BR) em um unico lugar, no mesmo padrao de ``ui/strings.py``.

Dataclasses imutaveis agrupadas por area; ``T`` e o conjunto ativo. Regras de redacao: frases curtas, sem
jargao, sem travessao; erro responde "o que houve, por que importa, o que fazer". Rotulos e ajuda de cada
campo ficam em ``field_texts`` e saem por ``T.label(spec)`` / ``T.help(spec)``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.settings.schema import FieldSpec

from . import field_texts


def plural(n: int, one: str, many: str) -> str:
    """'1 campo' / '3 campos' (``one`` e ``many`` sem o numero)."""
    return f"{n} {one if n == 1 else many}"


@dataclass(frozen=True)
class Window:
    title: str = "Jarvis: Configurações"
    heading: str = "Configurações"
    nav_name: str = "Categorias de configuração"
    emergency_caption: str = "Tecla de emergência"
    emergency_none: str = "Não definida"
    emergency_hint: str = "Para tudo na hora."
    search_placeholder: str = "Buscar nas configurações (Ctrl+F)"
    search_name: str = "Buscar nas configurações"
    content_name: str = "Conteúdo da página"
    loading_page: str = "as configurações"
    fix_before_save: str = "Corrija os campos marcados antes de salvar."
    fix_before_save_why: str = "O arquivo só é gravado quando tudo estiver válido."


@dataclass(frozen=True)
class Search:
    found: str = "{fields} em {pages}"
    field_one: str = "campo"
    field_many: str = "campos"
    page_one: str = "página"
    page_many: str = "páginas"
    empty_title: str = "Nada encontrado para “{q}”"
    empty_body: str = "Tente outra palavra, como microfone, voz, arquivos ou confirmação."
    clear: str = "Limpar busca"


@dataclass(frozen=True)
class General:
    theme_label: str = "Tema"
    theme_help: str = "Vale na hora, sem reiniciar."
    theme_dark: str = "Escuro"
    theme_light: str = "Claro"
    theme_system: str = "Seguir o Windows"


@dataclass(frozen=True)
class Banner:
    saved: str = "Configurações salvas."
    reset_done: str = "Padrões restaurados."
    nothing: str = "Nada mudou em relação ao que já estava gravado."
    next_open: str = "Valem na próxima vez que o Jarvis abrir: {items}."
    pending: str = "Já aguardavam reinício: {items}."
    live_after: str = "Valem assim que o Jarvis recarregar: {items}."
    needs_restart: str = "Exigem reiniciar o Jarvis: {items}."
    running: str = "O Jarvis está aberto agora."
    closed: str = "O Jarvis está fechado. Tudo vale na próxima vez que ele abrir."
    apply_now: str = "Aplicar agora"
    restart: str = "Reiniciar o Jarvis"
    apply_sent: str = "Pedido enviado. O Jarvis recarrega em instantes."
    restart_sent: str = "Pedido enviado. O Jarvis reabre sozinho só se foi aberto pelo Jarvis.cmd."
    more: str = "e mais {n}"
    dismiss: str = "Dispensar aviso"
    disk_what: str = "O arquivo de configuração mudou no disco"
    disk_why: str = "Outro programa ou uma edição manual alterou o arquivo depois que esta tela abriu."
    disk_todo: str = "Recarregue para ver o que mudou, ou dispense o aviso para manter o que está na tela. Salvar sobrescreve o arquivo."
    disk_reload: str = "Recarregar do disco"
    load_what: str = "Não consegui ler o arquivo de configuração"
    load_why: str = "Ele tem erros, então esta tela mostra os valores padrão. Salvar substitui o arquivo e guarda uma cópia do anterior."
    load_todo: str = "Corrija o arquivo à mão e recarregue, ou salve para recomeçar do padrão. Detalhe: {detail}"
    reload_what: str = "O arquivo em disco tem erros"
    reload_why: str = "Não consegui ler: {detail}"
    reload_todo: str = "Suas edições foram mantidas. Corrija o arquivo e recarregue."
    write_what: str = "Não consegui gravar as configurações"
    write_permission: str = "O arquivo está somente leitura ou aberto em outro programa."
    write_disk: str = "O disco devolveu um erro: {detail}."
    write_other: str = "Aconteceu um erro inesperado: {detail}."
    write_todo: str = "Suas alterações continuam na tela. Resolva o problema e salve de novo."
    request_what: str = "Não consegui avisar o Jarvis"
    request_todo: str = "Confira se ele está aberto e tente de novo."
    general_what: str = "Há um problema que envolve mais de um campo"
    general_todo: str = "Corrija os valores citados."


@dataclass(frozen=True)
class Dialogs:
    reset_title: str = "Restaurar o padrão de tudo?"
    reset_message: str = "Todas as suas personalizações voltam ao valor de fábrica. O arquivo atual fica guardado como cópia de segurança."
    reset_target: str = "{path}"
    reset_confirm: str = "Restaurar padrão"
    discard_title: str = "Descartar as alterações?"
    discard_message: str = "Os campos voltam ao que está gravado. Alterados:"
    discard_confirm: str = "Descartar"
    close_title: str = "Fechar com alterações não salvas?"
    close_message: str = "Elas serão perdidas. Alterados:"
    close_confirm: str = "Descartar e fechar"
    close_cancel: str = "Continuar editando"
    restart_title: str = "Reiniciar o Jarvis?"
    restart_message: str = "O Jarvis fecha e abre de novo. Qualquer fala ou ação em andamento é interrompida."
    restart_confirm: str = "Reiniciar"
    reload_title: str = "Recarregar do disco?"
    reload_message: str = "As alterações não salvas desta tela serão perdidas."
    reload_confirm: str = "Recarregar"


@dataclass(frozen=True)
class Yolo:
    title: str = "Modo YOLO"
    badge: str = "Sem confirmações"
    intro: str = "Desliga TODAS as confirmações por {minutes} minutos. Depois o Jarvis volta ao normal sozinho."
    facts: tuple[str, ...] = (
        "As travas duras continuam: pastas protegidas, Lixeira em vez de apagar de vez e terminais bloqueados.",
        "Só liga por clique aqui ou pelo atalho do teclado. Nunca por voz, nem por pedido do modelo.",
        "Desligar é sempre possível: por aqui, pelo atalho ou dizendo \"desligar YOLO\".",
    )
    on_button: str = "Ativar modo YOLO"
    off_button: str = "Desativar YOLO"
    on_tip: str = "Pede ao Jarvis para entrar no modo YOLO (você confirma antes)."
    off_tip: str = "Pede ao Jarvis para sair do modo YOLO agora."
    running: str = "Jarvis em execução"
    not_running: str = "Jarvis não está rodando"
    not_running_why: str = "Abra o Jarvis para ligar ou desligar o modo YOLO por aqui."
    sent_on: str = "Pedido enviado. O Jarvis avisa quando o modo YOLO ligar."
    sent_off: str = "Pedido enviado. O Jarvis avisa quando o modo YOLO desligar."
    failed: str = "Não consegui enviar o pedido ao Jarvis. Confira se a pasta de dados está acessível e tente de novo."
    dialog_title: str = "Ativar o modo YOLO?"
    dialog_message: str = ("Por {minutes} minutos o Jarvis vai agir sem pedir NENHUMA confirmação: abrir, digitar, "
                           "mover e fechar coisas. As travas duras continuam valendo.")
    dialog_target: str = "Modo YOLO por {minutes} minutos"
    dialog_confirm: str = "Ativar YOLO"
    card_name: str = "Modo YOLO: desliga todas as confirmações por um tempo"


@dataclass(frozen=True)
class Tools:
    intro: str = "Ligue ou desligue cada ferramenta. As arriscadas sempre pedem confirmação e isso não pode ser desligado."
    col_on: str = "Ligada"
    col_confirm: str = "Sempre confirmar"
    risk_read: str = "Só lê informações"
    risk_control: str = "Age no computador"
    risk_risky: str = "Arriscada"
    risky_always: str = "Sempre pede confirmação"
    on_name: str = "Ligar a ferramenta {name}"
    confirm_name: str = "Sempre pedir confirmação para {name}"
    loading: str = "a lista de ferramentas"
    fail_what: str = "Não consegui listar as ferramentas"
    fail_why: str = "Os valores salvos continuam intactos. Detalhe: {detail}"
    fail_todo: str = "Tente de novo."
    empty_title: str = "Nenhuma ferramenta encontrada"
    empty_body: str = "O catálogo veio vazio. Feche e abra esta tela; se continuar, veja o registro do programa."
    counts: str = "{on} de {total} ligadas"


@dataclass(frozen=True)
class Devices:
    default: str = "Padrão do Windows"
    current: str = "{name} (atual)"
    loading: str = "Procurando dispositivos..."
    failed_title: str = "Não consegui listar os dispositivos de áudio"
    failed_detail: str = "Você ainda pode manter o valor atual. Detalhe: {detail}"


@dataclass(frozen=True)
class Dictionary:
    name_header: str = "Nome falado"
    program_header: str = "Programa"
    name_placeholder: str = "Como você chama"
    program_placeholder: str = "Escolha o programa"
    add: str = "Adicionar programa"
    remove: str = "Remover {name}"
    empty: str = "Nenhum programa liberado. O Jarvis não abre nada."
    row_name: str = "Nome falado {n}"
    row_program: str = "Programa {n}"
    filter: str = "Programas (*.exe);;Todos os arquivos (*.*)"


@dataclass(frozen=True)
class OptionalField:
    custom: str = "Personalizar"
    default: str = "Padrão da voz"


@dataclass(frozen=True)
class PathList:
    add_folder: str = "Adicionar pasta..."
    choose: str = "Escolher pasta"


@dataclass(frozen=True)
class MyVoice:
    phrases_title: str = "Frases de treino"
    phrases_body: str = "Leia frases em voz alta para o Jarvis aprender o seu jeito de falar."
    phrases_button: str = "Gravar minhas frases"
    wake_title: str = "A palavra Jarvis"
    wake_body: str = "Grave você dizendo Jarvis para ele reconhecer quando for chamado."
    wake_button: str = "Gravar a palavra Jarvis"
    privacy: str = "O microfone só liga quando você clica em gravar dentro do gravador. As gravações ficam só neste computador."
    fail_what: str = "Não consegui abrir o gravador"
    fail_missing: str = "O gravador não está disponível nesta instalação."
    fail_version: str = "Esta versão do gravador ainda não abre direto neste conjunto."
    fail_other: str = "Detalhe: {detail}"
    fail_todo: str = "Tente de novo. Se continuar, abra o gravador pelo menu do Jarvis."


@dataclass(frozen=True)
class Knows:
    missing_title: str = "O painel de memória não está disponível agora"
    missing_body: str = "Suas memórias continuam guardadas no computador e nada foi apagado. Você pode tentar abrir de novo."
    retry: str = "Tentar de novo"


@dataclass(frozen=True)
class Advanced:
    config_label: str = "Arquivo de configuração"
    config_help: str = "Onde as suas escolhas ficam gravadas."
    open_folder: str = "Abrir a pasta"
    open_failed: str = "Não consegui abrir a pasta"
    reset_label: str = "Restaurar todas as opções"
    reset_help: str = "Apaga as suas personalizações. Uma cópia de segurança fica guardada."
    reset_button: str = "Restaurar padrão"


@dataclass(frozen=True)
class About:
    state_label: str = "Situação"
    running: str = "Aberto"
    closed: str = "Fechado"
    pid: str = "Processo {pid}"
    since: str = "desde {when}"
    unknown: str = "Verificando..."
    python: str = "Versão do Python"
    qt: str = "Versão do PySide6"
    data_dir: str = "Pasta de dados"
    log_dir: str = "Pasta de registros"
    models_dir: str = "Pasta de modelos"
    config_file: str = "Arquivo de configuração"
    pending_restart: str = "Aguardando reinício: {items}."
    time_format: str = "%d/%m/%Y %H:%M"


@dataclass(frozen=True)
class Nav:
    general: str = "Geral"
    voice: str = "Voz e áudio"
    my_voice: str = "Minha voz"
    listening: str = "Reconhecimento"
    llm: str = "Modelo de linguagem"
    tools: str = "Ferramentas e segurança"
    memory: str = "Memória e conversas"
    knows: str = "O que o Jarvis sabe de mim"
    files: str = "Arquivos"
    advanced: str = "Avançado"
    about: str = "Sobre"


@dataclass(frozen=True)
class Texts:
    window: Window = field(default_factory=Window)
    search: Search = field(default_factory=Search)
    general: General = field(default_factory=General)
    banner: Banner = field(default_factory=Banner)
    dialogs: Dialogs = field(default_factory=Dialogs)
    tools: Tools = field(default_factory=Tools)
    yolo: Yolo = field(default_factory=Yolo)
    devices: Devices = field(default_factory=Devices)
    dictionary: Dictionary = field(default_factory=Dictionary)
    optional: OptionalField = field(default_factory=OptionalField)
    path_list: PathList = field(default_factory=PathList)
    my_voice: MyVoice = field(default_factory=MyVoice)
    knows: Knows = field(default_factory=Knows)
    advanced: Advanced = field(default_factory=Advanced)
    about: About = field(default_factory=About)
    nav: Nav = field(default_factory=Nav)

    # ---- textos por campo (dados em field_texts)
    def label(self, spec: FieldSpec) -> str:
        return field_texts.FIELDS.get(spec.key, (spec.label, spec.help))[0]

    def help(self, spec: FieldSpec) -> str:
        return field_texts.FIELDS.get(spec.key, (spec.label, spec.help))[1]

    def label_for(self, key: str) -> str:
        entry = field_texts.FIELDS.get(key)
        return entry[0] if entry else key

    def locked(self, spec: FieldSpec) -> str:
        return field_texts.LOCKED.get(spec.key, spec.locked) if spec.locked else ""

    def choice_label(self, spec: FieldSpec, value: str, fallback: str) -> str:
        return field_texts.CHOICES.get(spec.key, {}).get(value, fallback)

    def path_filter(self, key: str) -> str:
        return field_texts.PATH_FILTERS.get(key, "")

    def unit(self, spec: FieldSpec) -> str:
        return field_texts.UNITS.get(spec.unit, spec.unit)

    def section(self, section_id: str) -> tuple[str, str]:
        return field_texts.SECTIONS.get(section_id, (section_id, ""))

    def page(self, key: str) -> tuple[str, str]:
        return field_texts.PAGES.get(key, (key, ""))


T = Texts()
