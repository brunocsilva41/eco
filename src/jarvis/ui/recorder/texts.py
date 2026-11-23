"""Textos do gravador de voz (pt-BR) em um unico lugar, no padrao de ``ui/strings.py``.

Cada area e um dataclass imutavel e ``T`` e o conjunto ativo. Regras de redacao: frases curtas, sem
jargao, sem travessao; todo erro responde "o que houve, por que importa, o que fazer". Os textos de
componentes do kit (Baixo/Otimo/Saturado, Ouvindo, Gravando) vivem em ``ui/strings.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Window:
    title: str = "Eco: Minha voz"
    heading: str = "Minha voz"
    set_label: str = "Conjunto"
    set_frases: str = "Frases"
    set_jarvis: str = "Palavra Eco"
    mic_label: str = "Microfone"
    mic_refresh: str = "Atualizar lista de microfones"
    close_hint: str = "Esc cancela a gravação em andamento ou fecha a janela."

    def noun(self, set_name: str) -> str:
        return "Amostra" if set_name == "eco" else "Frase"

    def position(self, set_name: str, n: int, total: int) -> str:
        return f"{self.noun(set_name)} {n} de {total}"

    def recorded(self, n: int, total: int) -> str:
        return f"Gravadas: {n} de {total}"

    def file(self, name: str) -> str:
        return f"Arquivo {name}"


@dataclass(frozen=True)
class Mics:
    default: str = "Padrão do Windows"
    none_found: str = "Nenhum microfone encontrado"

    def default_named(self, label: str) -> str:
        return f"{self.default} ({label})"

    def marked_default(self, label: str) -> str:
        return f"{label} (padrão)"

    def missing(self, name: str) -> str:
        return f"{name} (indisponível)"


@dataclass(frozen=True)
class Action:
    label: str
    key: str


@dataclass(frozen=True)
class Actions:
    record: Action = Action("Gravar", "Espaço")
    stop: Action = Action("Parar", "Espaço")
    saving: Action = Action("Salvando...", "Espaço")
    listen: Action = Action("Ouvir", "O")
    stop_audio: Action = Action("Parar áudio", "O")
    redo: Action = Action("Regravar", "R")
    skip: Action = Action("Pular", "P")
    next: Action = Action("Próxima", "Enter")
    prev: Action = Action("Anterior", "Esq")
    record_tip: str = "Grava o item atual até o fim da contagem."
    stop_tip: str = "Para agora e mantém o que já foi gravado."


@dataclass(frozen=True)
class Badges:
    pending: str = "Pendente"
    skipped: str = "Pulada"
    recorded: str = "Gravada"
    recording: str = "Gravando"
    saving: str = "Salvando"
    ok: str = "Gravada, nível bom"
    low: str = "Gravada, nível baixo"
    clip: str = "Gravada, saturada"
    unsaved_silence: str = "Não salva: silêncio"
    unsaved_short: str = "Não salva: curta demais"


@dataclass(frozen=True)
class Stage:
    countdown_caption: str = "Tempo restante"
    meter_caption: str = "Nível do microfone"
    meter_help: str = "Fale em tom natural. O pico deve passar pela faixa Ótimo."
    wave_empty: str = "Sem gravação deste item."
    wave_recording: str = "Gravando... fale agora."
    saved_next: str = "Gravada. Aperte Enter para ir à próxima."
    complete: str = "Conjunto concluído. Use Ouvir ou Regravar para revisar."
    peak: str = "Pico"
    rms: str = "RMS"
    clip_rate: str = "Saturação"
    duration: str = "Duração"


@dataclass(frozen=True)
class Message:
    what: str
    why: str = ""
    todo: str = ""


@dataclass(frozen=True)
class Levels:
    low: Message = Message(
        "Nível baixo", "Voz fraca demais dificulta o reconhecimento da fala.",
        "Fale mais perto do microfone ou aumente o ganho de entrada e regrave.")
    clip: Message = Message(
        "Áudio saturado", "O som estourou e ficou distorcido, o que atrapalha o reconhecimento.",
        "Afaste-se um pouco do microfone ou diminua o ganho de entrada e regrave.")
    silence: Message = Message(
        "Quase só silêncio", "O microfone não captou sua voz, então esta gravação não foi salva.",
        "Confira se é o microfone certo e se ele não está mudo. Depois use Gravar para tentar de novo.")
    short: Message = Message(
        "Gravação curta demais", "Menos de meio segundo não é salvo, porque não dá para medir a fala.",
        "Aperte Gravar e deixe a contagem correr até terminar a frase.")
    finished: Message = Message(
        "Conjunto concluído", "", "Revise com Ouvir ou Regravar, ou feche a janela.")


@dataclass(frozen=True)
class Failures:
    retry: str = "Tentar de novo"
    missing: Message = Message(
        "Microfone indisponível", "Sem ele não há como gravar.",
        "Confira o cabo ou o USB, escolha outro microfone na lista e tente de novo.")
    busy: Message = Message(
        "Microfone em uso por outro programa", "Dois programas não gravam do mesmo microfone ao mesmo tempo.",
        "Feche chamadas e gravadores que o estejam usando e tente de novo.")
    permission: Message = Message(
        "O Windows bloqueou o microfone", "Sem permissão o Eco só recebe silêncio.",
        "Abra Configurações do Windows, Privacidade e segurança, Microfone, e permita apps de área de trabalho.")
    format: Message = Message(
        "Este microfone não grava em 16 kHz mono", "O Eco precisa desse formato para ouvir bem.",
        "Escolha outro microfone na lista e tente de novo.")
    stalled: Message = Message(
        "O microfone parou de enviar áudio", "A gravação em andamento foi perdida.",
        "Veja se ele foi desconectado ou desativado e tente de novo.")
    other: Message = Message(
        "Não consegui abrir o microfone", "Sem ele não há como gravar.",
        "Veja se está conectado e se o Windows permite o acesso, depois tente de novo.")
    mic_list: Message = Message(
        "Não consegui listar os microfones", "Sem a lista só dá para usar o microfone padrão.",
        "Confira o som do Windows e use Atualizar. Tentar de novo lê a lista outra vez.")
    save: Message = Message(
        "Não consegui salvar a gravação", "O áudio ainda está na tela, mas não foi para o arquivo.",
        "Confira o espaço em disco e as permissões da pasta, e tente de novo.")
    not_saved: Message = Message(
        "A gravação não foi salva", "O arquivo atual foi mantido como estava.", "Use Regravar se quiser substituí-lo.")
    playback: Message = Message(
        "Não consegui tocar o áudio", "Sem isso não dá para conferir a gravação.",
        "Confira a saída de som do Windows e tente de novo.")
    unreadable_take: Message = Message(
        "A gravação existente não pôde ser lida", "O arquivo pode estar corrompido.",
        "Regrave este item para substituí-lo.")
    phrases_file: Message = Message(
        "Não consegui ler o arquivo de frases", "Por segurança a lista abre vazia e não será alterada.",
        "Confira o arquivo de frases e use Tentar de novo.")
    edit_blocked: Message = Message(
        "Edição bloqueada", "O arquivo de frases não pôde ser lido e não será sobrescrito.",
        "Corrija o arquivo e reabra o conjunto.")
    load_set: Message = Message(
        "Não consegui montar este conjunto", "Sem ele não há o que gravar.",
        "Confira a pasta de dados do Eco e tente de novo.")


@dataclass(frozen=True)
class Sidebar:
    title_frases: str = "Frases"
    title_jarvis: str = "Amostras"
    count_one: str = "1 item"
    list_name: str = "Lista de itens para gravar"
    add: str = "Adicionar"
    edit: str = "Editar frase"
    remove: str = "Remover frase"
    up: str = "Mover para cima"
    down: str = "Mover para baixo"

    def count(self, n: int) -> str:
        return self.count_one if n == 1 else f"{n} itens"


@dataclass(frozen=True)
class RowStatus:
    pending: str = "Pendente"
    recorded: str = "Gravada"
    skipped: str = "Pulada"


@dataclass(frozen=True)
class Editor:
    add_title: str = "Adicionar frase"
    edit_title: str = "Editar frase"
    field_label: str = "Frase"
    field_help: str = "De 3 a 300 caracteres. Frases repetidas não entram."
    placeholder: str = "Digite a frase que você vai ler"
    save: str = "Salvar"
    cancel: str = "Cancelar"
    remove_title: str = "Remover frase"
    remove_message: str = "A frase sai da lista de leitura."
    remove_confirm: str = "Remover"
    paired_title: str = "Esta frase já tem gravação"
    paired_edit: str = "editar a frase"
    paired_remove: str = "remover a frase"
    paired_move: str = "mover a frase"
    paired_confirm: str = "Continuar"

    def paired_message(self, file: str, action: str) -> str:
        return (f"A gravação {file} é ligada à frase pelo número. Ao {action}, o áudio e o texto "
                "podem ficar fora de par.")

    def counter(self, n: int, maximum: int) -> str:
        return f"{n} de {maximum}"


@dataclass(frozen=True)
class Confirms:
    overwrite_title: str = "Substituir a gravação?"
    overwrite_confirm: str = "Substituir"
    overwrite_cancel: str = "Manter a atual"
    close_title: str = "Gravação em andamento"
    close_message: str = "Fechar agora descarta a gravação que está sendo feita."
    close_confirm: str = "Fechar e descartar"
    close_cancel: str = "Continuar gravando"

    def overwrite_message(self, file: str) -> str:
        return f"Já existe a gravação {file}. Gravar de novo troca esse arquivo pela nova gravação."


@dataclass(frozen=True)
class States:
    loading_frases: str = "as frases"
    loading_jarvis: str = "as amostras"
    empty_title: str = "Nenhuma frase na lista"
    empty_body: str = ("Adicione as frases que você quer ler. Cada uma vira uma gravação numerada, "
                       "e a lista fica salva no arquivo de frases.")
    empty_action: str = "Adicionar frase"
    empty_locked_body: str = "Este conjunto não tem itens para gravar."


@dataclass(frozen=True)
class Api:
    invalid_set: str = "set_name inválido: {value!r}. Use 'frases' (suas frases) ou 'eco' (amostras da palavra Eco)."
    needs_app: str = "open_recorder precisa de um QApplication ativo; use main_recorder(cfg) fora da interface."


@dataclass(frozen=True)
class Texts:
    window: Window = field(default_factory=Window)
    mics: Mics = field(default_factory=Mics)
    actions: Actions = field(default_factory=Actions)
    badges: Badges = field(default_factory=Badges)
    stage: Stage = field(default_factory=Stage)
    levels: Levels = field(default_factory=Levels)
    failures: Failures = field(default_factory=Failures)
    sidebar: Sidebar = field(default_factory=Sidebar)
    rows: RowStatus = field(default_factory=RowStatus)
    editor: Editor = field(default_factory=Editor)
    confirms: Confirms = field(default_factory=Confirms)
    states: States = field(default_factory=States)
    api: Api = field(default_factory=Api)


T = Texts()
