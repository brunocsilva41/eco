"""Seção «Atualizações» das Configurações: versão atual, verificar agora, notas, baixar/instalar e acesso ao repositório privado.

Widget autocontido (kit + tokens), no contrato `PageLike` da janela (`key`, `filter`, `ensure_loaded`, `shutdown`, `scroll_to`).
A navegação/integração é feita por quem monta a janela:

    page = UpdatesPage(parent=None, cfg_loader=None)       # cfg_loader: () -> Config (padrão: jarvis.config.load)
    stack.addWidget(page); page.key == "updates"

Os campos da config (`updates.*`) são do schema (`G_UPD`); esta página cuida do que NÃO é campo: estado, ações e o token
somente-leitura (guardado no Cofre de Credenciais do Windows, nunca no config.toml).
"""
from __future__ import annotations

import logging
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QTextBrowser, QVBoxLayout, QWidget

from ...core import credstore, updates
from ...core.updates import UpdateInfo
from ..kit.base import Label, set_a11y
from ..kit.buttons import Button
from ..kit.feedback import InlineBanner
from ..kit.fields import TextField
from ..kit.layout import Card, FieldRow
from ..kit.meters import ProgressBar
from ..kit.status import StatusChip
from ..theme import SIZE, SPACE
from ..update_flow import UpdateSession
from .searching import matches

log = logging.getLogger(__name__)

TITLE = "Atualizações"
SUBTITLE = "Veja a versão instalada, procure novas versões e instale por cima sem perder dados."
_SEARCH = ("Atualizações versão atualizar verificar baixar instalar token repositório privado GitHub canal estável "
           "pré-lançamento intervalo SHA-256 ignorar lembrar")


def _mb(n: int) -> str:
    return f"{n / (1 << 20):.0f} MB"


class UpdatesPanel(QWidget):
    """Conteudo da secao: estado, notas, download/instalacao e token. Sem titulo nem rolagem propria, para entrar num cartao
    das Configuracoes (``ensure_loaded()`` monta o conteudo na primeira vez que a pagina abre)."""

    def __init__(self, parent: QWidget | None = None, *, cfg_loader=None, session: UpdateSession | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self._session = session or UpdateSession(self, cfg_loader=cfg_loader)
        self._built = False
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(SPACE.md)

    def ensure_loaded(self) -> None:
        if self._built:
            return
        self._built = True
        self._build()

    def shutdown(self) -> None:
        self._session.cancel()

    @property
    def session(self) -> UpdateSession:
        return self._session
    # ------------------------------------------------------------ montagem
    def _build(self) -> None:
        s = self._session
        card = Card("Esta versão")
        self._chip_row = QHBoxLayout()
        self._version = Label(f"Eco {updates.current_version()}", "heading")
        self._chip = StatusChip("neutral", "Ainda não verificado")
        self._chip_row.addWidget(self._version)
        self._chip_row.addWidget(self._chip)
        self._chip_row.addStretch(1)
        card.body.addLayout(self._chip_row)
        self._status = Label("", "help", wrap=True)
        card.add(self._status)
        self._check_btn = Button("Verificar agora", variant="primary", icon_name="refresh")
        self._check_btn.clicked.connect(lambda: s.check(manual=True))
        row = QHBoxLayout()
        row.addWidget(self._check_btn)
        row.addStretch(1)
        card.body.addLayout(row)
        self.col.addWidget(card)

        self._banner_host = QVBoxLayout()
        self.col.addLayout(self._banner_host)

        self._avail = Card("Nova versão")
        self._avail_title = Label("", "label", wrap=True)
        self._notes = QTextBrowser()
        self._notes.setOpenLinks(False)
        self._notes.setMinimumHeight(SIZE.target * 4)
        set_a11y(self._notes, "Notas da nova versão")
        self._bar = ProgressBar()
        self._bar.setVisible(False)
        self._bar_text = Label("", "help")
        self._bar_text.setVisible(False)
        self._avail.add(self._avail_title)
        self._avail.add(self._notes)
        self._avail.add(self._bar)
        self._avail.add(self._bar_text)
        self._b_dl = Button("Baixar")
        self._b_auto = Button("Instalar automaticamente", variant="primary")
        self._b_later = Button("Lembrar depois", variant="text")
        self._b_ignore = Button("Ignorar esta versão", variant="text")
        self._b_open = Button("Abrir página da versão", variant="text")
        for widgets in ((self._b_auto, self._b_dl), (self._b_later, self._b_ignore, self._b_open)):
            b = QHBoxLayout()
            b.setSpacing(SPACE.sm)
            for w in widgets:
                b.addWidget(w)
            b.addStretch(1)
            self._avail.body.addLayout(b)
        self._avail.setVisible(False)
        self.col.addWidget(self._avail)
        self._b_dl.clicked.connect(lambda: s.download(then_install=False))
        self._b_auto.clicked.connect(self._auto)
        self._b_later.clicked.connect(self._later)
        self._b_ignore.clicked.connect(self._ignore)
        self._b_open.clicked.connect(self._open_release)

        acc = Card("Acesso ao repositório privado")
        acc.add(Label("Se o repositório de versões for privado, o Eco usa um token do GitHub SOMENTE-LEITURA guardado no "
                      "Cofre de Credenciais do Windows (nunca no config.toml nem em logs) ou o GitHub CLI (`gh`) já "
                      "logado neste computador. Repositório público não precisa de nada.", "help", wrap=True))
        self._token = TextField(placeholder="Cole o token aqui (permissão: Contents e Metadata, somente leitura)",
                                accessible_name="Token somente-leitura do GitHub")
        self._token.setEchoMode(TextField.EchoMode.Password)
        acc.add(FieldRow("Token do GitHub", self._token, stacked=True))
        r = QHBoxLayout()
        self._b_save = Button("Guardar no cofre do Windows")
        self._b_clear = Button("Remover token", variant="text")
        r.addWidget(self._b_save)
        r.addWidget(self._b_clear)
        r.addStretch(1)
        acc.body.addLayout(r)
        self._acc_state = Label("", "help", wrap=True)
        acc.add(self._acc_state)
        self.col.addWidget(acc)
        self.col.addStretch(1)
        self._b_save.clicked.connect(self._save_token)
        self._b_clear.clicked.connect(self._clear_token)
        self._refresh_access()

        s.checked.connect(self._on_checked)
        s.progress.connect(self._on_progress)
        s.ready.connect(self._on_ready)
        s.failed.connect(self._on_failed)
        s.installing.connect(lambda: self._status.setText("Instalando: o Eco vai fechar, atualizar e abrir de novo."))
        s.state_changed.connect(lambda _s: self._sync())
        self._sync()

    # ------------------------------------------------------------ estado
    def _banner(self, state: str, what: str, why: str = "", todo: str = "") -> None:
        while self._banner_host.count():
            it = self._banner_host.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        if what:
            self._banner_host.addWidget(InlineBanner(state, what, why, todo))

    def _sync(self) -> None:
        st = self._session.state
        busy = st in ("checking", "downloading", "installing")
        ok, why = self._session.can_install()
        self._check_btn.setEnabled(not busy)
        self._check_btn.setText("Verificando…" if st == "checking" else "Verificar agora")
        ready = st == "ready"
        self._b_dl.setEnabled(not busy and not ready)
        self._b_dl.setText("Baixado" if ready else "Baixar")
        self._b_auto.setEnabled(not busy and ok)
        self._b_auto.setText(("Tentar de novo" if self._session.retry else "Instalar agora") if ready else "Instalar automaticamente")
        self._b_auto.setToolTip(why)
        for w in (self._b_later, self._b_ignore):
            w.setEnabled(not busy)

    def _on_checked(self, info: UpdateInfo, _manual: bool) -> None:
        self._banner("", "")
        self._bar.setVisible(False)
        self._bar_text.setVisible(False)
        if info.error:
            self._replace_chip("error", "Não consegui verificar")
            self._avail.setVisible(False)
            self._banner("error", "Não consegui verificar as atualizações", info.error, info.hint)
            self._status.setText("")
            return
        if info.available:
            self._avail_title.setText(f"Eco {info.latest} está disponível (você tem {info.current}).")
            self._notes.setMarkdown(info.notes or "Sem notas para esta versão.")
            self._avail.setVisible(True)
            self._status.setText(f"Consultado via {_VIA.get(info.via, info.via)}.")
            ok, why = self._session.can_install()
            if not ok:
                self._banner("warn", "Instalação automática indisponível", why)
        else:
            self._avail.setVisible(False)
            self._status.setText(f"Você já está na versão mais recente ({info.current}). Consultado via {_VIA.get(info.via, info.via)}.")
        self._replace_chip("warn" if info.available else "ok", "Nova versão" if info.available else "Atualizado")

    def _replace_chip(self, state: str, text: str) -> None:
        self._chip_row.removeWidget(self._chip)
        self._chip.deleteLater()
        self._chip = StatusChip(state, text)  # type: ignore[arg-type]
        self._chip_row.insertWidget(1, self._chip)

    def _on_progress(self, got: int, total: int) -> None:
        self._bar.setVisible(True)
        self._bar_text.setVisible(True)
        self._bar.set_progress(got, max(total, 1))
        self._bar_text.setText(f"{_mb(got)} de {_mb(total)}" if total else _mb(got))

    def _on_ready(self, _p: str) -> None:
        self._bar.setVisible(False)
        self._bar_text.setVisible(False)
        self._banner("ok", "Download concluído", "O SHA-256 do instalador bate com o publicado na versão.",
                     "Clique em «Instalar agora» para atualizar por cima (seus dados ficam).")

    def _on_failed(self, msg: str) -> None:
        self._bar.setVisible(False)
        self._bar_text.setVisible(False)
        self._banner("error", "A atualização não foi concluída", msg)
        self._sync()

    # ------------------------------------------------------------ ações
    def _auto(self) -> None:
        if self._session.state == "ready":
            self._session.install()
        else:
            self._session.download(then_install=True)

    def _later(self) -> None:
        self._session.remind_later(24.0)
        self._banner("ok", "Combinado", "O aviso automático volta em 24 horas.")

    def _ignore(self) -> None:
        self._session.ignore()
        self._avail.setVisible(False)
        self._banner("ok", "Versão ignorada", "Só avisarei de uma versão mais nova que esta. Você ainda pode verificar à mão.")

    def _open_release(self) -> None:
        info = self._session.info
        if info and info.url.startswith("https://"):
            webbrowser.open(info.url)

    def _refresh_access(self) -> None:
        has = credstore.has_token()
        gh = bool(updates.gh_path())
        self._b_clear.setEnabled(has)
        bits = ["Token guardado no cofre do Windows." if has else "Nenhum token guardado.",
                "GitHub CLI encontrado." if gh else "GitHub CLI (`gh`) não encontrado."]
        self._acc_state.setText(" ".join(bits))

    def _save_token(self) -> None:
        tok = self._token.text().strip()
        self._token.clear()                                   # nunca deixa o segredo na tela
        if not tok:
            return
        ok = credstore.set_token(tok)
        self._refresh_access()
        self._banner("ok" if ok else "error", "Token guardado no cofre do Windows" if ok else "O cofre do Windows recusou o token")

    def _clear_token(self) -> None:
        credstore.clear_token()
        self._refresh_access()
        self._banner("ok", "Token removido do cofre do Windows")


_VIA = {"public": "a API pública do GitHub", "token": "o token guardado", "gh": "o GitHub CLI", "": "o GitHub"}


class UpdatesPage(QScrollArea):
    """Pagina completa (titulo + painel), para quem a usa fora das Configuracoes. Contrato ``PageLike``."""
    key = "updates"

    def __init__(self, parent: QWidget | None = None, *, cfg_loader=None, session: UpdateSession | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.title, self.subtitle = TITLE, SUBTITLE
        self.panel = UpdatesPanel(None, cfg_loader=cfg_loader, session=session)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        column = QWidget()
        column.setMaximumWidth(SIZE.reading_width)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.md)
        col.addWidget(Label(TITLE, "title"))
        col.addWidget(Label(SUBTITLE, "help", wrap=True))
        col.addWidget(self.panel)
        host = QWidget()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(SPACE.xl, SPACE.xl, SPACE.xl, SPACE.xxl)
        lay.addWidget(column, 100)
        lay.addStretch(1)
        self.setWidget(host)
        set_a11y(self, TITLE, SUBTITLE)

    def search_text(self) -> str:
        return f"{TITLE} {SUBTITLE} {_SEARCH}"

    def filter(self, query: str) -> int:
        return 1 if matches(query, self.search_text()) else 0

    def ensure_loaded(self) -> None:
        self.panel.ensure_loaded()

    def shutdown(self) -> None:
        self.panel.shutdown()

    def scroll_to(self, key: str) -> None:
        return None

def build(parent: QWidget | None = None, cfg_loader=None) -> UpdatesPage:  # type: ignore[no-untyped-def]
    """Atalho para quem monta a janela."""
    return UpdatesPage(parent, cfg_loader=cfg_loader)

