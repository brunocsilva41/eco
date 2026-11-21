"""Leitor de mensagens (somente leitura): ``ReadScroll`` e os blocos de mensagem.

Todo texto vem de ``Label`` do kit, que é texto puro: nada do banco vira HTML nem é interpretado. Mensagens de
ferramenta e conteúdo marcado como não confiável ficam numa caixa própria com a marca ÍCONE + "Dado de fora".
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFocusEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ...memory import Message
from ..kit import Label, StatusChip
from ..kit.base import paint_focus_ring
from ..theme import RADIUS, SIZE, SPACE
from .banners import BannerSlot
from .logic import MAX_VIEW_CHARS, called_tools, fmt_ts, is_outside_data
from .service import ConversationData
from .texts import tr


class ReadScroll(QScrollArea):
    """Área rolável que aceita foco (setas e Page Up/Down rolam) e mostra o anel de foco do kit."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setViewportMargins(SIZE.focus_ring, SIZE.focus_ring, SIZE.focus_ring, SIZE.focus_ring)

    def focusInEvent(self, e: QFocusEvent) -> None:  # noqa: N802
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e: QFocusEvent) -> None:  # noqa: N802
        super().focusOutEvent(e)
        self.update()

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(e)
        if self.hasFocus():
            g = QPainter(self)
            paint_focus_ring(g, QRectF(self.rect()), RADIUS.sm)
            g.end()


def _selectable(label: Label) -> Label:
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def divider() -> QFrame:
    line = QFrame()
    line.setProperty("kit", "bar")           # só a borda de 1 px do kit
    line.setFixedHeight(SIZE.border)
    return line


def message_block(m: Message) -> QWidget:
    """Uma mensagem: quem falou, quando, o texto (cortado em MAX_VIEW_CHARS) e as ferramentas pedidas."""
    c = tr().conversations
    outside = is_outside_data(m)
    box = QFrame()
    box.setProperty("kit", "chip" if outside else "plain")
    col = QVBoxLayout(box)
    pad = SPACE.md if outside else 0
    col.setContentsMargins(pad, pad, pad, pad)
    col.setSpacing(SPACE.xs)
    head = QHBoxLayout()
    head.setSpacing(SPACE.sm)
    role = c.roles.get(m.role, m.role)
    chip = c.outside_tool.format(name=m.name) if m.role == "tool" and m.name else c.outside_chip
    head.addWidget(Label(role, "label"))
    if outside:
        head.addWidget(StatusChip("warn", chip, icon_name="alert"))
    head.addWidget(Label(fmt_ts(m.ts), "help"))
    head.addStretch(1)
    col.addLayout(head)
    content = m.content[:MAX_VIEW_CHARS]
    col.addWidget(_selectable(Label(content or c.no_text, "body", wrap=True)))
    tools = called_tools(m)
    if tools:
        col.addWidget(Label(c.asked_tools.format(names=", ".join(tools)), "help", wrap=True))
    if len(m.content) > MAX_VIEW_CHARS:
        col.addWidget(Label(c.cut_note, "help", wrap=True))
    box.setAccessibleName(f"{chip if outside else role}, {fmt_ts(m.ts)}. {content[:300]}")
    return box


def build_reader_page(data: ConversationData) -> QWidget:
    """Resumo da conversa, aviso de dado de fora e as mensagens, em ordem."""
    c = tr().conversations
    page = QWidget()
    col = QVBoxLayout(page)
    col.setContentsMargins(0, 0, SPACE.md, 0)
    col.setSpacing(SPACE.md)
    if data.summary:
        col.addWidget(Label(c.summary_title, "label"))
        col.addWidget(_selectable(Label(data.summary, "body", wrap=True)))
        col.addSpacing(SPACE.xs)
        col.addWidget(divider())
    if any(is_outside_data(m) for m in data.messages):
        slot = BannerSlot()
        slot.show_banner("warn", c.outside_what, c.outside_why, c.outside_todo)
        col.addWidget(slot)
    if not data.messages:
        col.addWidget(Label(c.no_messages, "help", wrap=True))
    for i, m in enumerate(data.messages):
        if i and not (is_outside_data(m) or is_outside_data(data.messages[i - 1])):
            col.addWidget(divider())
        col.addWidget(message_block(m))
    if data.total_messages > len(data.messages):
        col.addWidget(Label(c.list_cut_note.format(n=len(data.messages)), "help", wrap=True))
    col.addStretch(1)
    return page
