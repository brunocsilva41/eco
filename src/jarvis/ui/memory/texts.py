"""Textos do painel de memória (pt-BR), no mesmo padrão de ``ui/strings.py``: dataclasses imutáveis e o objeto ``T``.

Regras de redação: frases curtas, sem jargão, sem travessão; todo erro responde "o que houve, por que importa, o que
fazer". Para outro idioma, crie outra instância de ``Texts`` e use ``set_texts`` antes de abrir o painel.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def plural(n: int, one: str, many: str) -> str:
    """``plural(1, 'memória', 'memórias') -> '1 memória'``."""
    return f"{n} {one if n == 1 else many}"


@dataclass(frozen=True)
class Header:
    title: str = "O que o Eco sabe de mim"
    subtitle: str = "Tudo o que o Eco guarda fica neste computador. Aqui você vê, corrige e apaga."
    window_title: str = "Eco: o que o Eco sabe de mim"
    areas_name: str = "Áreas do painel de memória"
    tab_memories: str = "Memórias"
    tab_conversations: str = "Conversas"
    tab_storage: str = "Armazenamento e privacidade"
    refresh: str = "Atualizar a área aberta"
    busy: str = "Trabalhando..."
    panel_name: str = "O que o Eco sabe de mim"
    panel_desc: str = "Memórias, conversas e dados guardados no banco local do Eco."


@dataclass(frozen=True)
class NoHistory:
    what: str = "Modo sem histórico"
    why: str = "O Eco não grava nada em disco, então não há o que ver, editar ou apagar aqui. Tudo some quando ele fecha."
    todo: str = "Para voltar a guardar conversas e memórias, ligue a memória nas Configurações e reinicie o Eco."
    empty_title: str = "Nada guardado neste modo"
    empty_memories: str = "Sem histórico, o Eco não guarda memórias. Ligue a memória nas Configurações para ele voltar a lembrar."
    empty_conversations: str = "Sem histórico, o Eco não guarda conversas. Ligue a memória nas Configurações para ele voltar a guardá-las."


@dataclass(frozen=True)
class Errors:
    busy_what: str = "O banco de memória está ocupado"
    busy_why: str = "O Eco pode estar gravando agora. Nada foi perdido."
    busy_todo: str = "Espere um instante e tente de novo."
    open_what: str = "Não consegui abrir a memória"
    open_todo: str = "Confira se a pasta de dados existe e tem espaço, depois tente de novo."
    fail_what: str = "Não consegui concluir"
    fail_todo: str = "Se isso se repetir, o detalhe está no log do Eco."
    unknown_why: str = "Algo deu errado por dentro."
    show_what: str = "Não consegui mostrar o resultado"
    load_what: str = "Não consegui carregar a lista"
    closed_what: str = "A memória foi fechada"
    closed_todo: str = "Feche e abra esta seção de novo para recarregar."
    lock_words: tuple[str, ...] = ("locked", "ocupado", "busy", "indisponível")


@dataclass(frozen=True)
class Common:
    save_ok: str = "Pronto"
    selected_none: str = "Nada selecionado"
    loading_list: str = "a lista"
    search_hint: str = "Ctrl+F busca, Del apaga o item selecionado"
    date_none: str = "nunca"
    read_only: str = "Somente leitura"
    cancel: str = "Cancelar"


@dataclass(frozen=True)
class Memories:
    search_placeholder: str = "Buscar nas memórias (Ctrl+F)"
    search_name: str = "Buscar nas memórias"
    kind_name: str = "Filtrar memórias por tipo"
    kind_all: str = "Todos os tipos"
    kinds: dict[str, str] = field(default_factory=lambda: {
        "fato": "Fato", "preferencia": "Preferência", "tarefa": "Tarefa", "nota": "Nota"})
    kind_plural: dict[str, str] = field(default_factory=lambda: {
        "fato": "Fatos", "preferencia": "Preferências", "tarefa": "Tarefas", "nota": "Notas"})
    add: str = "Adicionar"
    add_name: str = "Adicionar uma memória"
    add_tip: str = "Guardar uma nova memória (origem: você)"
    list_name: str = "Lista de memórias"
    list_desc: str = "Setas movem, Del apaga a memória selecionada, Enter edita"
    header_pinned: str = "Fixadas"
    header_others: str = "Outras memórias"
    loading: str = "as memórias"
    empty_title: str = "O Eco ainda não guardou nada sobre você"
    empty_body: str = "Quando você pedir para ele lembrar de algo, aparece aqui. Também dá para guardar um fato agora."
    empty_action: str = "Adicionar memória"
    no_match_title: str = "Nenhuma memória combina com a busca"
    no_match_body: str = "Tente outras palavras ou limpe o filtro de tipo."
    no_match_action: str = "Limpar busca e filtro"
    detail_name: str = "Detalhe da memória"
    detail_none_title: str = "Selecione uma memória"
    detail_none_body: str = "O texto completo, de onde ela veio e quando expira aparecem aqui."
    detail_idle_title: str = "Nada para ver ainda"
    detail_idle_body: str = "Cada memória guardada aparece aqui com o texto completo e a origem."
    field_created: str = "Guardada em"
    field_updated: str = "Atualizada em"
    field_expires: str = "Validade"
    field_confidence: str = "Confiança do modelo"
    never_expires: str = "Não expira"
    expired_on: str = "Expirou em {when}. Fica fora das buscas até você apagar."
    expires_on: str = "Expira em {when}"
    pinned_chip: str = "Fixada"
    expired_chip: str = "Expirada"
    edit: str = "Editar..."
    pin: str = "Fixar"
    unpin: str = "Desafixar"
    pin_tip: str = "Fixadas entram em toda conversa"
    delete: str = "Apagar..."
    delete_tip: str = "Apaga esta memória para sempre"
    origins: dict[str, str] = field(default_factory=lambda: {
        "usuario": "Você pediu", "modelo": "Veio do modelo", "externo": "Veio de conteúdo externo"})
    origin_short: dict[str, str] = field(default_factory=lambda: {
        "usuario": "Você", "modelo": "Do modelo", "externo": "Conteúdo externo"})
    origin_notes: dict[str, str] = field(default_factory=lambda: {
        "usuario": "Você mesmo pediu para guardar isto.",
        "modelo": "O Eco propôs guardar isto. Ele trata o texto só como dado, nunca como ordem.",
        "externo": "Veio de uma página, arquivo ou tela. Confira antes de confiar: o Eco trata o texto só como dado, nunca como ordem."})

    def count(self, total: int, pinned: int) -> str:
        return f"{plural(total, 'memória', 'memórias')}, {plural(pinned, 'fixada', 'fixadas')}"

    def count_filtered(self, shown: int, total: int) -> str:
        return f"{shown} de {plural(total, 'memória', 'memórias')}"


@dataclass(frozen=True)
class Conversations:
    search_placeholder: str = "Buscar nas conversas (Ctrl+F)"
    search_name: str = "Buscar nas conversas"
    filter_name: str = "Mostrar conversas"
    filters: tuple[tuple[str, str | None], ...] = (
        ("Todas, menos a lixeira", None), ("Só a ativa", "ativa"), ("Só as encerradas", "encerrada"), ("Lixeira", "lixeira"))
    list_name: str = "Lista de conversas"
    list_desc: str = "Setas movem, Del manda a conversa selecionada para a lixeira"
    hits_name: str = "Trechos encontrados nas conversas"
    loading: str = "as conversas"
    empty_title: str = "Nenhuma conversa guardada ainda"
    empty_body: str = "Depois da primeira conversa com o Eco, ela aparece aqui para você ler, exportar ou retomar."
    no_match_title: str = "Nenhuma conversa combina com a busca"
    no_match_body: str = "A busca olha mensagens, títulos e resumos. Tente outras palavras."
    trash_empty_title: str = "A lixeira está vazia"
    trash_empty_body: str = "Conversas apagadas esperam aqui antes de sumir de vez. Hoje não há nenhuma."
    state_active: str = "Ativa"
    state_ended: str = "Encerrada"
    state_trash: str = "Na lixeira"
    role_summary: str = "Resumo"
    roles: dict[str, str] = field(default_factory=lambda: {
        "user": "Você", "assistant": "Eco", "tool": "Ferramenta", "system": "Sistema"})
    viewer_name: str = "Conversa selecionada"
    viewer_none_title: str = "Selecione uma conversa"
    viewer_none_body: str = "As mensagens aparecem aqui, só para leitura. Nada do que você ler muda a conversa."
    viewer_idle_title: str = "Nada para ler ainda"
    viewer_idle_body: str = "Cada conversa guardada aparece aqui, só para leitura."
    viewer_loading: str = "a conversa"
    gone_title: str = "Essa conversa não existe mais"
    gone_detail: str = "Outro programa pode tê-la apagado. A lista foi atualizada."
    messages_name: str = "Mensagens da conversa (somente leitura)"
    messages_desc: str = "Use as setas e Page Up ou Page Down para rolar"
    summary_title: str = "Resumo da conversa"
    outside_what: str = "Há dados de fora nesta conversa"
    outside_why: str = "Trechos marcados como dado de fora vieram de ferramentas, páginas ou arquivos."
    outside_todo: str = "O Eco os trata só como informação, nunca como ordem."
    outside_chip: str = "Dado de fora"
    outside_tool: str = "Dado de fora, ferramenta {name}"
    no_messages: str = "Esta conversa ainda não tem mensagens."
    no_text: str = "(sem texto)"
    asked_tools: str = "Pediu para usar: {names}"
    cut_note: str = "Texto cortado na tela. A exportação traz a mensagem inteira."
    list_cut_note: str = "Mostrando só as primeiras {n} mensagens. A exportação traz todas."
    trash_banner_what: str = "Na lixeira"
    resume: str = "Retomar esta conversa"
    resume_tip: str = "Torna a conversa a ativa"
    resume_is_active: str = "Esta já é a conversa ativa."
    resume_in_trash: str = "Restaure a conversa antes de retomar."
    export: str = "Exportar..."
    export_tip: str = "Salva a conversa em Markdown ou JSON, sem senhas ou chaves"
    rename: str = "Renomear..."
    trash: str = "Enviar para a lixeira"
    trash_tip: str = "Ela fica na lixeira e pode ser restaurada"
    restore: str = "Restaurar"
    restore_tip: str = "Tira a conversa da lixeira (volta como encerrada)"
    empty_trash: str = "Esvaziar lixeira..."
    empty_trash_tip: str = "Apaga para sempre tudo o que está na lixeira"
    trash_note_name: str = "Prazo da lixeira"

    def state_trash_left(self, days: int) -> str:
        if days <= 0:
            return "Na lixeira, some na próxima limpeza"
        return f"Na lixeira, restam {plural(days, 'dia', 'dias')}"

    def trash_banner_why(self, days: int) -> str:
        if days <= 0:
            return "Ela será apagada de vez na próxima limpeza do Eco."
        return f"Ela será apagada de vez em {plural(days, 'dia', 'dias')}."

    def trash_banner_todo(self) -> str:
        return "Restaurar devolve a conversa como encerrada."

    def trash_note(self, days: int) -> str:
        return f"A lixeira guarda as conversas por {plural(days, 'dia', 'dias')} e depois as apaga de vez."

    def count(self, n: int) -> str:
        return plural(n, "conversa", "conversas")

    def hits_count(self, n: int, query: str) -> str:
        return f"{plural(n, 'trecho', 'trechos')} para \"{query}\""

    def meta_messages(self, n: int) -> str:
        return plural(n, "mensagem", "mensagens")


@dataclass(frozen=True)
class Storage:
    area_name: str = "Armazenamento e privacidade"
    unencrypted_what: str = "O banco não é criptografado"
    unencrypted_why: str = ("Qualquer pessoa com acesso à sua conta do Windows pode ler o arquivo. "
                            "Cópias de segurança e exportações têm o mesmo conteúdo.")
    unencrypted_todo: str = "Guarde cópias só onde você controla o acesso."
    on_chip: str = "Histórico ligado"
    off_chip: str = "Modo sem histórico"
    on_note: str = "O Eco guarda conversas e memórias neste computador."
    off_note: str = "Nada é gravado em disco. Tudo o que o Eco ouve nesta sessão some quando ele fecha."
    stored_title: str = "O que está guardado"
    memories: str = "Memórias"
    conversations: str = "Conversas"
    messages: str = "Mensagens"
    none_stored: str = "Nada guardado por este modo."
    calculating: str = "calculando..."
    opening: str = "abrindo..."
    path_label: str = "Arquivo do banco"
    size_label: str = "Tamanho"
    retention_label: str = "Prazos"
    old_file: str = "{size}. Arquivo antigo: não é lido nem alterado enquanto o histórico estiver desligado."
    no_file: str = "Nenhum arquivo de banco encontrado."
    copy_title: str = "Cópia e exportação"
    copy_desc: str = "Leve seus dados para fora do Eco. Os arquivos gerados não são criptografados."
    backup: str = "Fazer cópia de segurança..."
    backup_tip: str = "Copia o banco inteiro para um arquivo à sua escolha"
    export_all: str = "Exportar tudo (JSON)..."
    export_all_tip: str = "Salva memórias e conversas em JSON, sem senhas ou chaves"
    refresh: str = "Atualizar números"
    danger_title: str = "Apagar"
    danger_desc: str = "Estas ações não têm volta. Cada uma pede que você digite APAGAR."
    wipe_memories_label: str = "Apagar todas as memórias"
    wipe_memories_help: str = "Remove tudo o que o Eco sabe de você, inclusive as fixadas."
    wipe_memories: str = "Apagar todas as memórias..."
    wipe_conversations_label: str = "Apagar todas as conversas"
    wipe_conversations_help: str = "Remove conversas e mensagens, inclusive a ativa e a lixeira."
    wipe_conversations: str = "Apagar todas as conversas..."

    def retention(self, ttl_days: int, trash_days: int) -> str:
        return (f"Conversas sem uso há {plural(ttl_days, 'dia', 'dias')} vão para a lixeira. "
                f"A lixeira guarda por {plural(trash_days, 'dia', 'dias')} e depois apaga de vez.")

    def pinned_note(self, n: int) -> str:
        return plural(n, "fixada", "fixadas")

    def trashed_note(self, n: int) -> str:
        return f"mais {n} na lixeira"


@dataclass(frozen=True)
class Dialogs:
    word: str = "APAGAR"
    add_title: str = "Adicionar memória"
    edit_title: str = "Editar memória"
    text_label: str = "Texto da memória"
    text_help: str = "De 3 a 1000 caracteres. Senhas e chaves não são guardadas."
    kind_label: str = "Tipo"
    pin_label: str = "Fixar"
    pin_help: str = "Entra em toda conversa. Máximo de {max}."
    expire_label: str = "Validade"
    expire_help: str = "Em dias. Zero significa que não expira."
    days_suffix: str = "dias"
    save_new: str = "Guardar"
    save_edit: str = "Salvar"
    char_count: str = "{n} de {max} caracteres"
    rename_title: str = "Renomear conversa"
    rename_label: str = "Novo título"
    rename_help: str = "Até 80 caracteres."
    rename_ok: str = "Renomear"
    rename_empty: str = "O título não pode ficar vazio."
    delete_memory_title: str = "Apagar esta memória"
    delete_memory_msg: str = "Ela deixa de existir para o Eco e não dá para recuperar."
    delete_memory_ok: str = "Apagar memória"
    wipe_memories_title: str = "Apagar todas as memórias"
    wipe_memories_ok: str = "Apagar todas as memórias"
    wipe_conversations_title: str = "Apagar todas as conversas"
    wipe_conversations_ok: str = "Apagar todas as conversas"
    wipe_conversations_msg: str = ("Isto apaga para sempre todas as conversas e mensagens, inclusive a ativa e as da lixeira. "
                                   "As memórias de longo prazo não são afetadas. Se o Eco estiver em execução, "
                                   "o próximo pedido dele abre uma conversa nova.")
    trash_title: str = "Enviar a conversa para a lixeira"
    trash_ok: str = "Enviar para a lixeira"
    trash_active_extra: str = " Esta é a conversa ativa: se o Eco estiver em execução, o próximo pedido dele abre uma conversa nova."
    empty_trash_title: str = "Esvaziar a lixeira"
    empty_trash_ok: str = "Esvaziar lixeira"
    empty_trash_msg: str = "As conversas abaixo serão apagadas para sempre."
    resume_title: str = "Retomar esta conversa"
    resume_ok: str = "Retomar conversa"
    resume_msg: str = ("A conversa ativa de agora será encerrada e esta passa a ser a ativa. "
                       "Aviso: o Eco em execução só vê a mudança no próximo pedido que você fizer a ele.")
    export_conv_title: str = "Exportar conversa"
    export_conv_filter: str = "Markdown (*.md);;JSON (*.json);;Todos os arquivos (*)"
    export_all_title: str = "Exportar memórias e conversas"
    export_all_filter: str = "JSON (*.json);;Todos os arquivos (*)"
    backup_title: str = "Cópia de segurança do banco"
    backup_filter: str = "Banco SQLite (*.db);;Todos os arquivos (*)"

    def trash_msg(self, days: int, messages: int) -> str:
        return f"Ela tem {plural(messages, 'mensagem', 'mensagens')} e fica na lixeira por {plural(days, 'dia', 'dias')}, onde pode ser restaurada."

    def wipe_memories_msg(self, n: int, pinned: int) -> str:
        return (f"Isto apaga para sempre {plural(n, 'memória', 'memórias')} de longo prazo do Eco, "
                f"{plural(pinned, 'fixada', 'fixadas')} incluídas. As conversas não são afetadas.")

    def wipe_memories_target(self, n: int, pinned: int) -> str:
        return f"Todas as memórias: {plural(n, 'item', 'itens')}, {plural(pinned, 'fixada', 'fixadas')}"

    def wipe_conversations_target(self, sessions: int, trashed: int, messages: int) -> str:
        return (f"Todas as conversas: {sessions}, mais {trashed} na lixeira, "
                f"{plural(messages, 'mensagem', 'mensagens')} no total")


@dataclass(frozen=True)
class Notices:
    saved_title: str = "Memória guardada"
    edited_title: str = "Memória alterada"
    pinned_title: str = "Memória fixada"
    unpinned_title: str = "Memória desafixada"
    deleted_title: str = "Memória apagada"
    wiped_memories_title: str = "Memórias apagadas"
    renamed_title: str = "Conversa renomeada"
    trashed_title: str = "Conversa na lixeira"
    restored_title: str = "Conversa restaurada"
    restored_detail: str = "Ela voltou como encerrada."
    trash_emptied_title: str = "Lixeira esvaziada"
    wiped_conversations_title: str = "Conversas apagadas"
    resumed_title: str = "Conversa retomada"
    resumed_detail: str = "O Eco em execução só a vê depois do próximo pedido que você fizer a ele."
    exported_title: str = "Conversa exportada"
    exported_all_title: str = "Dados exportados"
    exported_note: str = "Trechos com cara de senha ou chave foram omitidos."
    backup_title: str = "Cópia de segurança gravada"
    backup_note: str = "Ela não é criptografada: guarde com cuidado."

    def removed(self, n: int, one: str, many: str) -> str:
        return plural(n, one, many)


@dataclass(frozen=True)
class Texts:
    header: Header = field(default_factory=Header)
    no_history: NoHistory = field(default_factory=NoHistory)
    errors: Errors = field(default_factory=Errors)
    common: Common = field(default_factory=Common)
    memories: Memories = field(default_factory=Memories)
    conversations: Conversations = field(default_factory=Conversations)
    storage: Storage = field(default_factory=Storage)
    dialogs: Dialogs = field(default_factory=Dialogs)
    notices: Notices = field(default_factory=Notices)


PT_BR = Texts()
T: Texts = PT_BR


def tr() -> Texts:
    """Conjunto ativo lido na hora (respeita ``set_texts``). O resto do pacote usa ``tr()``, nunca guarda literais."""
    return T


def set_texts(texts: Texts) -> None:
    """Troca o conjunto ativo (outro idioma). Chame antes de criar o painel."""
    global T
    T = texts
