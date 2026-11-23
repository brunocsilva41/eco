"""Paginas da galeria do kit: cada funcao devolve o conteudo de uma pagina (usa o proprio kit)."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..theme import RADIUS, SIZE, SPACE, TYPE, contrast_pairs, make_font, pal
from . import icons
from .actionbar import ActionBar
from .base import Label, watch_theme
from .buttons import Button
from .chips import ChipList
from .feedback import InlineBanner
from .fields import ComboField, NumberField, PathField, TextField
from .indicator import ListeningIndicator
from .keycapture import KeyCaptureField
from .layout import Card, FieldRow, Section
from .meters import CountdownRing, LevelMeter, ProgressBar
from .navlist import NavList
from .search import SearchField
from .states import EmptyState, ErrorState, LoadingState
from .status import StatusChip
from .toggle import ToggleSwitch

PAGE_WIDTH = SIZE.reading_width + SIZE.target * 8


@dataclass
class Page:
    key: str
    title: str
    icon: str
    widget: QWidget
    focus: list[tuple[str, QWidget]] = field(default_factory=list)


def row(*widgets: QWidget, gap: int = SPACE.md, stretch_last: bool = False) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(gap)
    for w in widgets:
        lay.addWidget(w)
    if not stretch_last:
        lay.addStretch(1)
    return box


def captioned(caption: str, widget: QWidget) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(SPACE.xs)
    lay.addWidget(Label(caption, "caption"))
    lay.addWidget(widget)
    return box


class _PageSurface(QWidget):
    """Pagina com fundo do tema (um QWidget comum com stylesheet nao pinta o fundo sozinho)."""

    def __init__(self) -> None:
        super().__init__()
        watch_theme(self)

    def paintEvent(self, _e: QPaintEvent) -> None:
        QPainter(self).fillRect(self.rect(), QColor(pal().bg))


def _page_shell() -> tuple[QWidget, QVBoxLayout]:
    page = _PageSurface()
    page.setFixedWidth(PAGE_WIDTH)
    lay = QVBoxLayout(page)
    lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xxl)
    lay.setSpacing(0)
    return page, lay


class _Swatches(QWidget):
    """Amostras da paleta atual: nome, hex e texto de exemplo sobre cada superficie."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(SIZE.target * 3 + SPACE.xl)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        watch_theme(self)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cells = [("fundo", p.bg, p.text), ("superfície", p.surface, p.text), ("elevada", p.raised, p.text),
                 ("acento", p.accent, p.on_accent), ("ok", p.ok_bg, p.ok), ("atenção", p.warn_bg, p.warn), ("erro", p.error_bg, p.error)]
        w = (self.width() - SPACE.sm * (len(cells) - 1)) / len(cells)
        for i, (name, bg, fg) in enumerate(cells):
            r = QRectF(i * (w + SPACE.sm), 0, w, SIZE.target * 2.5)
            g.setPen(QColor(p.border))
            g.setBrush(QColor(bg))
            g.drawRoundedRect(r, RADIUS.md, RADIUS.md)
            g.setPen(QColor(fg))
            g.setFont(make_font(TYPE.body, TYPE.semibold))
            g.drawText(r.adjusted(SPACE.md, SPACE.md, 0, 0), int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft), name)
            g.setFont(make_font(TYPE.caption))
            g.drawText(r.adjusted(SPACE.md, 0, 0, -SPACE.md), int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft), bg)
        y = SIZE.target * 2.5 + SPACE.md
        for i, (name, color) in enumerate([("texto secundário", p.text_muted), ("acento (tinta)", p.accent_ink), ("borda de campo", p.border_strong),
                                           ("desabilitado", p.text_disabled)]):
            g.setPen(QColor(color))
            g.setFont(make_font(TYPE.body))
            g.drawText(QRectF(i * (self.width() / 4), y, self.width() / 4, SIZE.target), int(Qt.AlignmentFlag.AlignVCenter), f"{name}  {color}")
        g.end()


class _Scales(QWidget):
    """Espacamento (4..48), raios (4/8/12) e duracoes, desenhados com os tokens."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(SIZE.target * 3)
        watch_theme(self)

    def sizeHint(self) -> QSize:
        return QSize(PAGE_WIDTH, SIZE.target * 3)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = pal()
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        g.setFont(make_font(TYPE.caption))
        x = 0.0
        for v in (4, 8, 12, 16, 24, 32, 48):
            g.setPen(Qt.PenStyle.NoPen)
            g.setBrush(QColor(p.text_muted))
            g.drawRect(QRectF(x, 0, v, SPACE.lg))
            g.setPen(QColor(p.text_muted))
            g.drawText(QRectF(x, SPACE.xl, max(v, SPACE.xl), SPACE.lg), int(Qt.AlignmentFlag.AlignLeft), str(v))
            x += v + SPACE.md
        x = 0.0
        for v in (RADIUS.sm, RADIUS.md, RADIUS.lg):
            r = QRectF(x, SIZE.target + SPACE.md, SIZE.target * 1.5, SIZE.target)
            g.setBrush(QColor(p.raised))
            g.setPen(QColor(p.border_strong))
            g.drawRoundedRect(r, v, v)
            g.setPen(QColor(p.text_muted))
            g.drawText(r, int(Qt.AlignmentFlag.AlignCenter), f"raio {v}")
            x += SIZE.target * 1.5 + SPACE.md
        g.end()


def foundations() -> Page:
    page, lay = _page_shell()
    lay.addWidget(Label("Fundamentos", "title"))
    pal_sec = Section("Paleta do tema atual", "Dois neutros, um acento âmbar e três estados. O par claro usa a mesma lógica.", level=1)
    pal_sec.add(_Swatches())
    lay.addWidget(pal_sec)
    ratios = Section("Contraste calculado (WCAG)", "Mínimo exigido entre parênteses. Todos os pares passam.", level=2)
    grid = QGridLayout()
    grid.setHorizontalSpacing(SPACE.xl)
    grid.setVerticalSpacing(SPACE.xs)
    pairs = [r for r in contrast_pairs(pal()) if "superficie" in r[0] or ("fundo" not in r[0] and "elevada" not in r[0])]
    for i, (name, _fg, _bg, ratio, need) in enumerate(pairs):
        lbl = Label(f"{name}: {ratio:.2f} ({need:g})", "help")
        grid.addWidget(lbl, i // 2, i % 2)
    holder = QWidget()
    holder.setLayout(grid)
    ratios.add(holder)
    lay.addWidget(ratios)
    typ = Section("Escala tipográfica", "Segoe UI Variable com reserva Segoe UI. 11, 12, 13 (base), 16, 20, 28 e 48 tabular.", level=1)
    for kind, text in (("display", "Frase 7 de 20 (28 / 600)"), ("title", "Configurações (20 / 600)"), ("heading", "Voz e áudio (16 / 600)"),
                       ("label", "Microfone (13 / 600)"), ("body", "Texto de corpo, linha de 1,4 (13 / 400)"),
                       ("help", "Ajuda de uma linha (12 / 400, secundário)"), ("caption", "Legenda e rótulo de faixa (11 / 400)"),
                       ("counter", "0123456789")):
        typ.add(Label(text, kind))  # type: ignore[arg-type]
    lay.addWidget(typ)
    sc = Section("Espaçamento, raios e movimento", "Grade de 4 px. Raios 4 (campos, botões), 8 (cartões), 12 (diálogos). Transições de 120 a 180 ms.", level=2)
    sc.add(_Scales())
    lay.addWidget(sc)
    ic = Section("Ícones (traço 1,5 px, grade de 24)", "Um único conjunto, com pontas retas e cantos chanfrados. Mostrado em 16 e 20 px.", level=1)
    grid2 = QGridLayout()
    grid2.setHorizontalSpacing(SPACE.lg)
    grid2.setVerticalSpacing(SPACE.md)
    cols = 8
    for i, name in enumerate(icons.NAMES):
        from PySide6.QtWidgets import QLabel
        cell = QWidget()
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(SPACE.xs)
        ico = QLabel()
        ico.setPixmap(icons.pixmap(name, pal().text, SIZE.icon_lg, ico))
        ico.setAccessibleName(name)
        cl.addWidget(ico, 0, Qt.AlignmentFlag.AlignLeft)
        cl.addWidget(Label(name, "caption"))
        grid2.addWidget(cell, i // cols, i % cols)
    holder2 = QWidget()
    holder2.setLayout(grid2)
    ic.add(holder2)
    lay.addWidget(ic)
    lay.addStretch(1)
    return Page("fundamentos", "Fundamentos", "edit", page)


def controls() -> Page:
    page, lay = _page_shell()
    focus: list[tuple[str, QWidget]] = []
    lay.addWidget(Label("Controles", "title"))
    btn = Section("Botões", "Primário só para a ação principal da tela. Perigo só para o que apaga.", level=1)
    states_row: list[QWidget] = []
    for variant in ("primary", "secondary", "danger", "text"):
        b = Button("Salvar", variant=variant, icon_name="check")  # type: ignore[arg-type]
        d = Button("Desabilitado", variant=variant)  # type: ignore[arg-type]
        d.setEnabled(False)
        states_row.append(captioned(variant, row(b, d, gap=SPACE.sm)))
        if variant in ("primary", "secondary", "danger"):
            focus.append((f"botao-{variant}", b))
    btn.add(row(*states_row[:2], gap=SPACE.xl))
    btn.add(row(*states_row[2:], gap=SPACE.xl))
    icon_buttons = [Button(n, icon_name=i, icon_only=True) for n, i in (
        ("Gravar", "record"), ("Parar", "stop"), ("Ouvir", "listen"), ("Pular", "skip"), ("Próxima", "next"),
        ("Anterior", "prev"), ("Apagar", "trash"), ("Fixar", "pin"), ("Editar", "edit"), ("Atualizar", "refresh"))]
    btn.add(captioned("somente ícone (32 x 32, com nome acessível)", row(*icon_buttons, gap=SPACE.xs)))
    lay.addWidget(btn)
    fl = Section("Campos", "Normal, com valor, desabilitado e com erro.", level=1)
    e = TextField("Valor digitado")
    dis = TextField("Desabilitado")
    dis.setEnabled(False)
    bad = TextField("valor inválido")
    bad.set_invalid(True)
    fl.add(row(captioned("vazio", TextField(placeholder="Texto de apoio")), captioned("valor", e), gap=SPACE.lg))
    fl.add(row(captioned("desabilitado", dis), captioned("erro", bad), gap=SPACE.lg))
    focus.append(("campo-texto", e))
    num = NumberField(60, minimum=0, maximum=100, suffix="%")
    combo = ComboField([("Padrão do Windows", "default"), ("Headset USB", "usb")])
    fl.add(row(captioned("número (setas, PageUp/Down)", num), captioned("lista", combo), gap=SPACE.lg))
    focus += [("numero", num), ("lista", combo)]
    fl.add(captioned("caminho", PathField("C:/Eco/logs", mode="dir")))
    chips = ChipList(["notepad.exe", "calc.exe"])
    fl.add(captioned("lista de itens (Enter adiciona, x remove)", chips))
    focus.append(("lista-itens", chips))
    lay.addWidget(fl)
    sw = Section("Interruptores e atalhos", "O estado aparece também em texto e na posição do botão.", level=2)
    t_on, t_off, t_dis, t_bad = ToggleSwitch(True), ToggleSwitch(False), ToggleSwitch(True), ToggleSwitch(False)
    t_dis.setEnabled(False)
    t_bad.set_invalid(True)
    sw.add(row(captioned("ligado", t_on), captioned("desligado", t_off), captioned("desabilitado", t_dis), captioned("erro", t_bad), gap=SPACE.xl))
    kc = KeyCaptureField("Ctrl+Alt+J")
    sw.add(row(captioned("tecla de atalho (Enter para mudar)", kc), captioned("sem tecla", KeyCaptureField("")), gap=SPACE.lg))
    focus += [("interruptor", t_on), ("tecla", kc)]
    lay.addWidget(sw)
    fr = Section("Linhas de campo", "Rótulo, ajuda de uma linha, controle, erro e selo. Nunca um cartão por campo.", level=1)
    r1 = FieldRow("Microfone", ComboField([("Padrão do Windows", "default")]), help="Usado em todas as conversas.")
    r2 = FieldRow("Sensibilidade", NumberField(60, minimum=0, maximum=100, suffix="%"), help="Mais alto capta falas mais baixas.", restart_required=True)
    r3 = FieldRow("Pasta de logs", PathField("D:/nao-existe"), help="Onde o Eco guarda os registros.", stacked=True)
    r3.set_error("Essa pasta não existe. Escolha outra, ou o Eco não consegue gravar os registros.")
    r4 = FieldRow("Tecla de emergência", KeyCaptureField("Ctrl+Alt+Esc"), help="Interrompe tudo na hora.",
                  locked_reason="não pode ser alterada, ela é a trava de segurança")
    r5 = FieldRow("Ouvir sem apertar tecla", ToggleSwitch(True), help="Fica sempre ao alcance da voz.")
    for r in (r1, r2, r3, r4, r5):
        fr.add(r)
    lay.addWidget(fr)
    lay.addStretch(1)
    return Page("controles", "Controles", "settings", page, focus)


def feedback_and_states() -> Page:
    page, lay = _page_shell()
    lay.addWidget(Label("Estado, medidores e retorno", "title"))
    st = Section("Selos de estado", "Sempre ícone e texto. Única pílula do kit.", level=1)
    st.add(row(StatusChip("ok", "Microfone pronto"), StatusChip("warn", "Modo mudo"), StatusChip("error", "Sem conexão"), StatusChip("neutral", "Sem dados"),
               gap=SPACE.md))
    lay.addWidget(st)
    me = Section("Medidor de nível e contagem", "Faixas baixo, ótimo e saturado com nome escrito. Contagem em numeral tabular.", level=1)
    meters = []
    for db in (-55.0, -23.0, -3.0):
        m = LevelMeter()
        m.set_level(db)
        meters.append(m)
        me.add(m)
    ring_idle, ring_on = CountdownRing(20), CountdownRing(20)
    ring_idle.set_remaining(20)
    ring_on.set_remaining(12.4)
    ring_on.set_active(True)
    prog = ProgressBar(7, 20)
    me.add(row(captioned("parado", ring_idle), captioned("gravando", ring_on), gap=SPACE.xl))
    me.add(captioned("Frase 7 de 20", prog))
    lay.addWidget(me)
    ind = Section("Indicador de captura", "O único elemento com brilho e pulso (reduzir animações o deixa estático).", level=2)
    ind.add(row(ListeningIndicator("idle"), ListeningIndicator("listening"), ListeningIndicator("recording"), gap=SPACE.xl))
    lay.addWidget(ind)
    bn = Section("Avisos", "Erro diz o que houve, por que importa e o que fazer.", level=1)
    bn.add(InlineBanner.error("Não consegui abrir o microfone", "Sem ele o Eco não ouve você.",
                              "Feche o outro programa que usa o microfone e tente de novo.", action_text="Tentar de novo", dismissible=True))
    bn.add(InlineBanner("warn", "A tecla de emergência está sem uso", "Ela interrompe tudo caso algo saia do controle.", "Confira em Ferramentas e segurança."))
    bn.add(InlineBanner("ok", "Configurações salvas", "", ""))
    lay.addWidget(bn)
    es = Section("Vazio, carregando e erro", level=1)
    es.add(row(EmptyState("Nenhuma memória ainda", "O Eco guarda aqui o que você pede para lembrar.", action_text="Adicionar memória"),
               LoadingState("as memórias"), ErrorState("Não consegui ler as memórias", "Sem elas ele esquece o que você pediu.", "Tente de novo.")))
    lay.addWidget(es)
    lay.addStretch(1)
    return Page("feedback", "Estado e retorno", "alert", page)


def structure() -> Page:
    page, lay = _page_shell()
    lay.addWidget(Label("Navegação e estrutura", "title"))
    nv = Section("Lista de navegação", "Marcador âmbar só no item atual. Contadores com ícone e número.", level=1)
    nav = NavList()
    nav.setFixedHeight((SIZE.target + SPACE.sm) * 7 + SPACE.sm)
    for key, text, ic in (("geral", "Geral", "settings"), ("voz", "Voz e áudio", "mic"), ("rec", "Reconhecimento", "ear"), ("llm", "Modelo de linguagem", "brain"),
                          ("seg", "Ferramentas e segurança", "shield"), ("mem", "Memória e conversas", "memory"), ("arq", "Arquivos", "folder")):
        nav.add_entry(key, text, ic)
    nav.set_counts("voz", changes=2)
    nav.set_counts("seg", errors=1, changes=1)
    nav.set_current("voz")
    search = SearchField()
    nv.add(row(nav, search, gap=SPACE.xl))
    lay.addWidget(nv)
    ab = Section("Barra de ações", "Aparece só com alterações pendentes. Com erro, Salvar fica bloqueado e a barra diz quantos faltam.", level=1)
    bar1, bar2 = ActionBar(show_when_clean=True), ActionBar(show_when_clean=True)
    bar1.set_changes(3)
    bar2.set_changes(2, errors=1)
    ab.add(bar1)
    ab.add(bar2)
    lay.addWidget(ab)
    cd = Section("Cartão", "Só para uma unidade independente: aqui, uma memória que pode ser lida, fixada ou apagada sozinha.", level=1)
    card = Card("Memória fixada")
    card.add(Label("O texto real da memória aparece aqui, inteiro e legível.", "body", wrap=True))
    card.add(row(Button("Editar", icon_name="edit"), Button("Apagar", variant="danger", icon_name="trash")))
    cd.add(card)
    lay.addWidget(cd)
    lay.addStretch(1)
    return Page("estrutura", "Navegação e estrutura", "folder", page, [("nav", nav), ("busca", search)])


def build_pages() -> list[Page]:
    return [foundations(), controls(), feedback_and_states(), structure()]
