"""Tela de Configurações do Jarvis ("triple A": lógica no ``SettingsStore``, aqui só apresentação e fluxo).

Uso::

    from jarvis.ui.settings_window import open_settings, main_settings
    main_settings()                      # programa próprio (cria o QApplication)
    open_settings(cfg, parent=janela)    # dentro de um app Qt já em execução

Para ligar outros painéis: ``collect_values(window)`` / ``apply_values(window, valores)`` e ``window.set_memory_widget(w)``.
Nada aqui lê/escreve o config.toml diretamente: tudo passa por ``SettingsStore`` (validação, gravação atômica, .bak) e
por ``settings.control`` (conversa com o Jarvis em execução). Não existe campo de senha, token ou PIN.
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from ..config import Config, ConfigError
from ..settings import control, schema
from ..settings.schema import FieldSpec
from ..settings.store import Problem, SaveResult, SettingsError, SettingsStore
from . import theme
from .settings_widgets import (FieldEditor, FieldRow, ToolsFacet, ToolsPanel, limits_hint, make_editor)

log = logging.getLogger(__name__)

VALIDATE_DELAY_MS: Final = 250
DISK_POLL_MS: Final = 2000
VOICE_PAGE: Final = "Minha voz"
MEMORY_PAGE: Final = "O que o Jarvis sabe de mim"
_MAX_LISTED: Final = 8


# ============================================================================ utilidades puras
def _norm(spec: FieldSpec, value: Any) -> Any:
    """Forma comparável de um valor (None e '' iguais, listas de ferramentas sem ordem, floats sem ruído)."""
    if value is None:
        return ""
    if spec.kind == schema.TOOLS:
        return tuple(sorted(str(v) for v in value))
    if isinstance(value, dict):
        return tuple(sorted((str(k), str(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(value)
    if isinstance(value, float):
        return round(value, 9)
    return value


def _label(key: str) -> str:
    spec = schema.BY_KEY.get(key)
    return spec.label if spec else key


def _summarize(keys: list[str]) -> str:
    names = [_label(k) for k in keys]
    shown = ", ".join(names[:_MAX_LISTED])
    return shown + (f" e mais {len(names) - _MAX_LISTED}" if len(names) > _MAX_LISTED else "")


def _friendly(problem: Problem) -> str:
    """Troca o nome técnico 'secao.campo' no início da mensagem pelo rótulo do campo."""
    spec = schema.BY_KEY.get(problem.key)
    msg = problem.message
    if spec and msg.startswith(problem.key):
        msg = f"{spec.label}{msg[len(problem.key):]}"
    return msg


@dataclass
class _Binding:
    spec: FieldSpec
    editor: FieldEditor | ToolsFacet
    row: FieldRow


class _Banner(QFrame):
    """Faixa de aviso com texto e botões (estado ok/warn/error pela cor da borda E pelo texto)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("banner")
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(theme.SP1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SP2, theme.SP1, theme.SP2, theme.SP1)
        lay.addWidget(self.text, 1)
        lay.addLayout(self.buttons)
        self.setVisible(False)

    def add_button(self, text: str, slot: Callable[[], None], variant: str = "") -> QPushButton:
        btn = QPushButton(text)
        if variant:
            btn.setProperty("variant", variant)
        btn.clicked.connect(slot)
        self.buttons.addWidget(btn)
        return btn

    def show_message(self, message: str, state: str = "ok") -> None:
        self.text.setText(message)
        self.setProperty("state", state)
        theme.repolish(self)
        self.setVisible(True)


class _MemoryPlaceholder(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("plain")
        lay = QVBoxLayout(self)
        title = QLabel(MEMORY_PAGE)
        title.setProperty("role", "section")
        note = QLabel("Disponível em breve.")
        note.setProperty("role", "muted")
        lay.addWidget(title)
        lay.addWidget(note)
        lay.addStretch(1)


# ============================================================================ janela
class SettingsWindow(QWidget):
    """Janela de Configurações. Sinal ``saved(SaveResult)`` após gravar (ou restaurar padrões) com sucesso."""

    saved = Signal(object)

    def __init__(self, cfg: Config | None = None, parent: QWidget | None = None, store: SettingsStore | None = None) -> None:
        super().__init__(parent)
        self._store = store or SettingsStore()
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle("Jarvis - Configurações")
        self.setStyleSheet(theme.build_stylesheet() + theme.build_settings_stylesheet())
        self.resize(1120, 780)
        self.setMinimumSize(920, 620)

        self._bindings: dict[str, _Binding] = {}
        self._rows: list[FieldRow] = []
        self._group_keys: dict[str, list[str]] = {g: [] for g in schema.GROUPS}
        self._page_editors: dict[int, list[FieldEditor]] = {}
        self._page_scroll: dict[int, QScrollArea] = {}
        self._errors: dict[str, list[str]] = {}
        self._general_errors: list[str] = []
        self._baseline: dict[str, Any] = {}
        self._force_dirty = False
        self._busy = False
        self._last_result: SaveResult | None = None
        self._disk_mtime = 0.0
        self._dismissed_mtime: float | None = None
        self._first_error_key = ""

        load_error = ""
        if cfg is None:
            try:
                cfg = self._store.load()
            except ConfigError as exc:
                log.warning("config.toml com erro; a tela abre com os padrões: %s", exc)
                load_error = str(exc)
                cfg = self._store.defaults()
        self._cfg: Config = cfg

        self._build_ui()
        self._load_baseline(self._cfg)
        self._disk_mtime = control.config_mtime(self._store.path)
        if load_error:
            self._force_dirty = True
            self._load_banner.show_message(
                "O config.toml atual tem erros e não pôde ser lido:\n" + load_error +
                "\nA tela mostra os padrões. Ao salvar, o arquivo é substituído (a cópia anterior fica em config.toml.bak).", "error")

        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(VALIDATE_DELAY_MS)
        self._validate_timer.timeout.connect(self._revalidate)
        self._disk_timer = QTimer(self)
        self._disk_timer.setInterval(DISK_POLL_MS)
        self._disk_timer.timeout.connect(self._check_disk)
        self._disk_timer.start()
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)       # type: ignore[attr-defined]

        self._revalidate()
        self._nav.setCurrentRow(0)

    # ------------------------------------------------------------------ construção da interface
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(0)
        nav_frame = QFrame()
        nav_frame.setObjectName("nav")
        nav_lay = QVBoxLayout(nav_frame)
        nav_lay.setContentsMargins(theme.SP2, theme.SP2, theme.SP2, theme.SP2)
        title = QLabel("Configurações")
        title.setProperty("role", "title")
        nav_lay.addWidget(title)
        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        self._nav.setAccessibleName("Seções das configurações")
        self._nav.setFixedWidth(270)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._nav.setWordWrap(True)
        self._nav.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        nav_lay.addWidget(self._nav, 1)
        body.addWidget(nav_frame)

        self._stack = QStackedWidget()
        body.addWidget(self._stack, 1)
        root.addLayout(body, 1)

        for group in schema.GROUPS:
            self._add_group_page(group)
        self._add_voice_page()
        self._add_memory_page()
        self._nav.currentRowChanged.connect(self._on_nav)

        # --- faixas de aviso (acima do rodapé)
        self._load_banner = _Banner()
        self._disk_banner = _Banner()
        self._disk_banner.add_button("Recarregar do disco", self._reload_from_disk)
        self._disk_banner.add_button("Manter minhas edições", self._keep_mine, "ghost")
        self._result_banner = _Banner()
        self._apply_btn = self._result_banner.add_button("Aplicar agora", self._apply_now, "primary")
        self._restart_btn = self._result_banner.add_button("Reiniciar o Jarvis", self._restart_jarvis)
        self._result_banner.add_button("Fechar aviso", lambda: self._result_banner.setVisible(False), "ghost")
        banners = QVBoxLayout()
        banners.setContentsMargins(theme.SP2, theme.SP1, theme.SP2, theme.SP1)
        banners.setSpacing(theme.SP1)
        for b in (self._load_banner, self._disk_banner, self._result_banner):
            banners.addWidget(b)
        root.addLayout(banners)

        # --- rodapé
        footer = QFrame()
        footer.setObjectName("footer")
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(theme.SP2, theme.SP1 + 2, theme.SP2, theme.SP1 + 2)
        fv.setSpacing(theme.SP1)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setAccessibleName("Resumo das alterações e erros")
        fv.addWidget(self._summary)
        flay = QHBoxLayout()
        flay.setSpacing(theme.SP1)
        self._goto_btn = QPushButton("Ir ao primeiro erro")
        self._goto_btn.clicked.connect(self._goto_first_error)
        self._goto_btn.setVisible(False)
        self._reset_btn = QPushButton("Restaurar padrões")
        self._reset_btn.clicked.connect(self._restore_defaults)
        self._discard_btn = QPushButton("Descartar alterações")
        self._discard_btn.clicked.connect(self._discard)
        self._save_btn = QPushButton("Salvar")
        self._save_btn.setProperty("variant", "primary")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save)
        flay.addWidget(self._reset_btn)
        flay.addStretch(1)
        for w in (self._goto_btn, self._discard_btn, self._save_btn):
            flay.addWidget(w)
        fv.addLayout(flay)
        root.addWidget(footer)

    def _new_page(self, title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout, QScrollArea]:
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(theme.SP3, theme.SP3, theme.SP3, theme.SP3)
        lay.setSpacing(theme.SP2)
        head = QLabel(title)
        head.setProperty("role", "section")
        head.setAccessibleName(title)
        lay.addWidget(head)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setProperty("role", "muted")
            sub.setWordWrap(True)
            lay.addWidget(sub)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAccessibleName(title)
        return page, lay, scroll

    def _add_nav(self, text: str, page: QWidget) -> int:
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, text)
        self._nav.addItem(item)
        index = self._stack.addWidget(page)
        return index

    def _add_group_page(self, group: str) -> None:
        specs = schema.fields_by_group()[group]
        count = len(specs)
        _page, lay, scroll = self._new_page(group, f"{count} opç{'ão' if count == 1 else 'ões'} nesta seção.")
        index = self._add_nav(group, scroll)
        self._page_scroll[index] = scroll
        editors: list[FieldEditor] = []
        panel: ToolsPanel | None = None
        for spec in specs:
            self._group_keys[group].append(spec.key)
            if spec.kind == schema.TOOLS:
                if panel is None:
                    panel = ToolsPanel(spec, self._describe_tools)
                    panel.changed.connect(lambda: self._on_edit())
                    keys = tuple(s.key for s in specs if s.kind == schema.TOOLS)
                    row = FieldRow("Ferramentas", "Escolha o que o Jarvis pode usar e o que sempre pede confirmação. "
                                   "Desligadas não aparecem para o modelo.", schema.LIVE, panel, panel.focus_widget(), keys=keys)
                    self._rows.append(row)
                    lay.addWidget(row)
                    editors.append(panel)
                    self._tools_row = row
                self._bindings[spec.key] = _Binding(spec, ToolsFacet(panel, spec), self._tools_row)
                continue
            editor = make_editor(spec)
            editor.changed.connect(lambda: self._on_edit())
            help_text = " ".join(t for t in (spec.help, limits_hint(spec)) if t)
            row = FieldRow(spec.label, help_text, spec.apply, editor, editor.focus_widget(), locked=spec.locked, keys=(spec.key,))
            self._bindings[spec.key] = _Binding(spec, editor, row)
            self._rows.append(row)
            editors.append(editor)
            lay.addWidget(row)
        lay.addStretch(1)
        self._page_editors[index] = editors

    def _add_voice_page(self) -> None:
        _page, lay, scroll = self._new_page(VOICE_PAGE, "Grave suas frases e amostras da palavra de ativação para o Jarvis aprender a sua voz.")
        card = QFrame()
        card.setObjectName("card")
        clay = QVBoxLayout(card)
        clay.setContentsMargins(theme.SP2, theme.SP2, theme.SP2, theme.SP2)
        clay.setSpacing(theme.SP1)
        text = QLabel("As gravações abrem o gravador 'Minha voz'. O microfone só é usado quando você clicar em gravar lá dentro, "
                      "e as amostras ficam só neste computador.")
        text.setWordWrap(True)
        clay.addWidget(text)
        row = QHBoxLayout()
        self._phrases_btn = QPushButton("Gravar minhas frases")
        self._phrases_btn.setProperty("variant", "primary")
        self._phrases_btn.clicked.connect(lambda: self._open_recorder(0))
        self._wake_btn = QPushButton("Amostras da palavra Jarvis")
        self._wake_btn.clicked.connect(lambda: self._open_recorder(1))
        row.addWidget(self._phrases_btn)
        row.addWidget(self._wake_btn)
        row.addStretch(1)
        clay.addLayout(row)
        self._voice_status = QLabel("")
        self._voice_status.setProperty("state", "error")
        self._voice_status.setWordWrap(True)
        clay.addWidget(self._voice_status)
        lay.addWidget(card)
        lay.addStretch(1)
        self._add_nav(VOICE_PAGE, scroll)

    def _add_memory_page(self) -> None:
        page, lay, scroll = self._new_page(MEMORY_PAGE)
        self._memory_layout = lay
        self._memory_placeholder: QWidget | None = _MemoryPlaceholder()
        lay.insertWidget(1, self._memory_placeholder)
        lay.addStretch(1)
        self._add_nav(MEMORY_PAGE, scroll)

    # ------------------------------------------------------------------ API pública
    def collect_values(self) -> dict[str, Any]:
        """{'secao.campo': valor} do que está na tela agora (o mesmo formato de ``SettingsStore.validate/save``)."""
        return {key: b.editor.value() for key, b in self._bindings.items()}

    def apply_values(self, values: dict[str, Any]) -> None:
        """Coloca valores nos campos (chaves desconhecidas são ignoradas). Aparecem como 'alterados' se diferirem do salvo."""
        for key, val in values.items():
            b = self._bindings.get(key)
            if b is not None:
                b.editor.set_value(val)
        self._on_edit()

    def change_count(self) -> int:
        return len(self._changed_keys())

    def has_pending_changes(self) -> bool:
        return self.change_count() > 0 or self._force_dirty

    def set_memory_widget(self, widget: QWidget) -> None:
        """Troca o espaço reservado 'O que o Jarvis sabe de mim' pelo painel real."""
        if self._memory_placeholder is not None:
            self._memory_layout.removeWidget(self._memory_placeholder)
            self._memory_placeholder.deleteLater()
        self._memory_placeholder = widget
        self._memory_layout.insertWidget(1, widget)

    def _ensure_memory_panel(self) -> None:
        """Cria o painel de memória na primeira vez que a seção é aberta (e só se ninguém o trocou antes)."""
        if not isinstance(self._memory_placeholder, _MemoryPlaceholder):
            return
        try:
            from .memory_panel import MemoryPanel          # import tardio: só carrega a memória se a seção for aberta
            self.set_memory_widget(MemoryPanel(self._cfg))
        except Exception as exc:  # noqa: BLE001 - a tela de configurações nunca cai por causa deste painel
            log.exception("não consegui abrir o painel de memória")
            note = QLabel(f"Erro: não consegui abrir o painel de memória: {exc}")
            note.setProperty("state", "error")
            note.setWordWrap(True)
            self.set_memory_widget(note)

    # ------------------------------------------------------------------ valores e alterações
    def _describe_tools(self) -> list[Any]:
        from ..tools.catalog import describe_tools      # import tardio e em thread: registra as ferramentas sem travar a janela
        return describe_tools(self._cfg)

    def _load_baseline(self, cfg: Config) -> None:
        self._baseline = schema.current_values(cfg)
        for key, b in self._bindings.items():
            b.editor.set_value(self._baseline.get(key))
        self._force_dirty = False
        self._refresh_marks()

    def _changed_keys(self) -> list[str]:
        out: list[str] = []
        for key, b in self._bindings.items():
            if _norm(b.spec, b.editor.value()) != _norm(b.spec, self._baseline.get(key)):
                out.append(key)
        return out

    def _refresh_marks(self) -> None:
        changed = set(self._changed_keys())
        for row in self._rows:
            row.set_changed(any(k in changed for k in row.keys))
        for i, group in enumerate(schema.GROUPS):
            n_ch = sum(1 for k in self._group_keys[group] if k in changed)
            n_err = sum(1 for k in self._group_keys[group] if self._errors.get(k))
            item = self._nav.item(i)
            text = group
            tip = group
            if n_err:
                text += f"    ▲ {n_err}"
                tip += f" - {n_err} erro(s) a corrigir"
            elif n_ch:
                text += f"    ● {n_ch}"
                tip += f" - {n_ch} alteração(ões) não salva(s)"
            item.setText(text)
            item.setToolTip(tip)
        self._update_footer(len(changed))

    def _on_edit(self) -> None:
        self._refresh_marks()
        self._validate_timer.start()

    # ------------------------------------------------------------------ validação ao vivo
    def _revalidate(self) -> None:
        values = self.collect_values()
        errors: dict[str, list[str]] = {}
        general: list[str] = []
        for key, b in self._bindings.items():
            msg = b.editor.local_error()
            if msg:
                errors.setdefault(key, []).append(msg)
        try:
            problems = self._store.validate(values)
        except Exception as exc:  # noqa: BLE001 - validação nunca pode derrubar a tela
            log.exception("falha inesperada ao validar")
            problems = [Problem("", f"falha inesperada ao validar: {exc}")]
        for p in problems:
            if p.key in self._bindings:
                if p.key not in errors:                    # o erro local (forma) já explica; evita mensagem dupla
                    errors[p.key] = [_friendly(p)]
            else:
                general.append(_friendly(p))
        self._errors, self._general_errors = errors, general
        by_row: dict[int, list[str]] = {}
        for key, msgs in errors.items():
            by_row.setdefault(id(self._bindings[key].row), []).extend(msgs)
        for row in self._rows:
            row.set_errors(by_row.get(id(row), []))
        self._first_error_key = next(iter(errors), "")
        self._refresh_marks()

    def _update_footer(self, n_changes: int) -> None:
        err_keys = [k for k, m in self._errors.items() if m]
        n_err = len(err_keys) + len(self._general_errors)
        if n_err:
            names = _summarize(err_keys)
            extra = "; ".join(self._general_errors[:2])
            text = f"{n_err} erro(s) a corrigir antes de salvar" + (f": {names}" if names else "") + (f". {extra}" if extra else "") + "."
            state = "error"
        elif n_changes:
            text = f"{n_changes} alteraç{'ão' if n_changes == 1 else 'ões'} não salva{'' if n_changes == 1 else 's'}."
            state = "warn"
        elif self._force_dirty:
            text = "O arquivo atual tem erros; salve para substituí-lo pelos valores da tela."
            state = "warn"
        else:
            text = "Nenhuma alteração."
            state = "ok"
        self._summary.setText(text)
        self._summary.setProperty("state", state)
        theme.repolish(self._summary)
        self._goto_btn.setVisible(bool(n_err and self._first_error_key))
        self._save_btn.setEnabled(not n_err and (n_changes > 0 or self._force_dirty) and not self._busy)
        self._discard_btn.setEnabled(n_changes > 0 and not self._busy)
        self._reset_btn.setEnabled(not self._busy)

    def _goto_first_error(self) -> None:
        b = self._bindings.get(self._first_error_key)
        if b is None:
            return
        self._nav.setCurrentRow(schema.GROUPS.index(b.spec.group))
        target = b.editor.focus_widget() if isinstance(b.editor, FieldEditor) else b.row
        target.setFocus()

    # ------------------------------------------------------------------ navegação
    def _on_nav(self, row: int) -> None:
        if row < 0:
            return
        self._stack.setCurrentIndex(row)
        item = self._nav.item(row)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == MEMORY_PAGE:
            self._ensure_memory_panel()
        for ed in self._page_editors.get(row, []):
            ed.ensure_loaded()                           # dispositivos/ferramentas: sob demanda, em segundo plano (idempotente)

    def _on_focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        if new is None or not self.isAncestorOf(new):
            return
        scroll = self._page_scroll.get(self._stack.currentIndex())
        if scroll is not None and scroll.widget() is not None and scroll.widget().isAncestorOf(new):
            scroll.ensureWidgetVisible(new, 0, theme.SP4)

    # ------------------------------------------------------------------ diálogos
    def _ask(self, title: str, text: str, yes: str, no: str = "Cancelar", destructive: bool = False) -> bool:
        box = QMessageBox(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question, title, text, parent=self)
        yes_btn = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
        no_btn = box.addButton(no, QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no_btn)
        box.setEscapeButton(no_btn)
        box.exec()
        return box.clickedButton() is yes_btn

    # ------------------------------------------------------------------ salvar, descartar, restaurar
    def _save(self) -> bool:
        if self._busy:
            return False
        self._busy = True
        self._update_footer(self.change_count())
        try:
            result = self._store.save(self.collect_values())
        except SettingsError as exc:
            self._apply_problems(exc.problems)
            QMessageBox.warning(self, "Não foi possível salvar", "Corrija os campos marcados em vermelho e tente de novo.")
            return False
        except OSError as exc:
            self._write_failed(exc)
            return False
        except Exception as exc:  # noqa: BLE001
            log.exception("falha inesperada ao salvar as configurações")
            self._write_failed(exc)
            return False
        finally:
            self._busy = False
            self._update_footer(self.change_count())
        self._after_write(result, "Configurações salvas.")
        return True

    def _apply_problems(self, problems: list[Problem]) -> None:
        errors: dict[str, list[str]] = {}
        for p in problems:
            if p.key in self._bindings:
                errors.setdefault(p.key, []).append(_friendly(p))
        self._errors = errors
        self._general_errors = [_friendly(p) for p in problems if p.key not in self._bindings]
        for row in self._rows:
            row.set_errors([m for k in row.keys for m in errors.get(k, [])])
        self._first_error_key = next(iter(errors), "")
        self._refresh_marks()

    def _write_failed(self, exc: BaseException) -> None:
        log.error("não consegui gravar as configurações: %s", exc)
        if isinstance(exc, PermissionError):
            why = "Sem permissão para gravar o config.toml (arquivo somente leitura ou aberto em outro programa)."
        elif isinstance(exc, OSError):
            why = f"Erro de disco ao gravar o config.toml: {exc.strerror or exc}."
        else:
            why = f"Erro inesperado ao gravar: {exc}."
        self._result_banner.show_message(f"{why}\nNada foi perdido: suas edições continuam na tela. Corrija o problema e salve de novo.", "error")
        self._apply_btn.setVisible(False)
        self._restart_btn.setVisible(False)
        QMessageBox.critical(self, "Não consegui salvar", why + "\n\nSuas alterações continuam na tela.")

    def _after_write(self, result: SaveResult, title: str) -> None:
        self._last_result = result
        self._cfg = result.config
        self._load_baseline(result.config)
        self._disk_mtime = control.config_mtime(self._store.path)
        self._dismissed_mtime = None
        self._disk_banner.setVisible(False)
        self._load_banner.setVisible(False)
        self._show_result(result, title)
        self._revalidate()
        self.saved.emit(result)

    def _show_result(self, result: SaveResult, title: str) -> None:
        ch = result.changes
        lines = [title]
        if not ch.any:
            lines.append("Nada mudou em relação ao que já estava gravado.")
        if ch.live:
            lines.append("Aplicam na hora (quando o Jarvis recarregar): " + _summarize(list(ch.live)) + ".")
        if ch.restart:
            lines.append("EXIGEM reiniciar o Jarvis: " + _summarize(list(ch.restart)) + ".")
        rt = None
        try:
            rt = control.read_runtime(self._cfg.paths.data)
        except Exception:  # noqa: BLE001 - estado do Jarvis é informativo
            log.exception("não consegui ler o estado do Jarvis em execução")
        if rt is not None:
            lines.append(f"O Jarvis está rodando (processo {rt.pid}).")
            if rt.pending_restart:
                lines.append("Já aguardando reinício nele: " + _summarize(list(rt.pending_restart)) + ".")
        else:
            lines.append("O Jarvis não está rodando agora: tudo valerá na próxima vez que ele iniciar.")
        running = rt is not None
        self._apply_btn.setVisible(running)
        self._apply_btn.setEnabled(bool(ch.live))
        self._restart_btn.setVisible(running)
        self._result_banner.show_message("\n".join(lines), "warn" if ch.restart else "ok")

    def _apply_now(self) -> None:
        try:
            control.request(self._cfg.paths.data, "reload")
        except (OSError, ValueError) as exc:
            log.error("não consegui pedir o reload: %s", exc)
            self._result_banner.show_message(f"Não consegui avisar o Jarvis: {exc}", "error")
            return
        log.info("pedido de reload enviado ao Jarvis")
        self._apply_btn.setEnabled(False)
        self._result_banner.text.setText(self._result_banner.text.text() + "\nPedido enviado: o Jarvis recarrega em instantes (até 1 s).")

    def _restart_jarvis(self) -> None:
        if not self._ask("Reiniciar o Jarvis",
                         "O Jarvis vai fechar e abrir de novo. Qualquer fala ou ação em andamento será interrompida.\n\nReiniciar agora?",
                         "Reiniciar o Jarvis", destructive=True):
            return
        try:
            control.request(self._cfg.paths.data, "restart")
        except (OSError, ValueError) as exc:
            log.error("não consegui pedir o reinício: %s", exc)
            self._result_banner.show_message(f"Não consegui avisar o Jarvis: {exc}", "error")
            return
        log.info("pedido de reinício enviado ao Jarvis")
        self._restart_btn.setEnabled(False)
        self._result_banner.text.setText(self._result_banner.text.text() + "\nPedido de reinício enviado. (Só reabre sozinho se o Jarvis foi iniciado pelo Jarvis.cmd.)")

    def _discard(self) -> None:
        n = self.change_count()
        if n and not self._ask("Descartar alterações", f"Descartar as {n} alteração(ões) não salva(s) e voltar aos valores gravados?",
                               "Descartar", destructive=True):
            return
        self._load_baseline(self._cfg)
        self._revalidate()

    def _restore_defaults(self) -> None:
        extra = f"\n\nAs {self.change_count()} alteração(ões) não salvas também serão perdidas." if self.change_count() else ""
        if not self._ask("Restaurar padrões",
                         "Isto apaga TODAS as suas personalizações e volta cada opção ao valor de fábrica. "
                         "O arquivo anterior fica guardado em config.toml.bak." + extra +
                         "\n\nDeseja restaurar os padrões?", "Restaurar padrões", destructive=True):
            return
        self._busy = True
        try:
            result = self._store.reset_defaults()
        except OSError as exc:
            self._write_failed(exc)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("falha ao restaurar os padrões")
            self._write_failed(exc)
            return
        finally:
            self._busy = False
        self._after_write(result, "Padrões restaurados.")

    # ------------------------------------------------------------------ config.toml mudou em disco
    def _check_disk(self) -> None:
        mtime = control.config_mtime(self._store.path)
        if mtime == self._disk_mtime or mtime == self._dismissed_mtime:
            return
        self._disk_banner.show_message(
            "O config.toml mudou no disco desde que esta tela abriu (outro programa ou edição manual). "
            "Recarregar descarta o que está na tela; manter e salvar sobrescreve o arquivo.", "warn")

    def _reload_from_disk(self) -> None:
        if self.change_count() and not self._ask("Recarregar do disco", "Recarregar descarta suas alterações não salvas. Continuar?",
                                                 "Recarregar", destructive=True):
            return
        try:
            cfg = self._store.load()
        except ConfigError as exc:
            log.warning("config.toml em disco inválido: %s", exc)
            self._disk_banner.show_message(f"O config.toml em disco tem erros e não pôde ser lido: {exc}\nSuas edições foram mantidas.", "error")
            self._dismissed_mtime = control.config_mtime(self._store.path)
            return
        self._cfg = cfg
        self._disk_mtime = control.config_mtime(self._store.path)
        self._disk_banner.setVisible(False)
        self._load_baseline(cfg)
        self._revalidate()

    def _keep_mine(self) -> None:
        self._dismissed_mtime = control.config_mtime(self._store.path)
        self._disk_banner.setVisible(False)

    # ------------------------------------------------------------------ Minha voz
    def _open_recorder(self, index: int) -> None:
        self._voice_status.setText("")
        try:
            from .recorder_window import open_recorder        # import tardio: carrega áudio/numpy só se for usado
            window = open_recorder(self._cfg, self)
            chooser = getattr(window, "_on_set_chosen", None)
            if callable(chooser):
                chooser(index)
        except Exception as exc:  # noqa: BLE001
            log.exception("não consegui abrir o gravador")
            self._voice_status.setText(f"Erro: não consegui abrir o gravador: {exc}")

    # ------------------------------------------------------------------ ciclo de vida
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.has_pending_changes() and self.isVisible():
            box = QMessageBox(QMessageBox.Icon.Question, "Alterações não salvas",
                              f"Há {self.change_count()} alteração(ões) não salva(s). O que deseja fazer?", parent=self)
            save = box.addButton("Salvar e fechar", QMessageBox.ButtonRole.AcceptRole)
            drop = box.addButton("Descartar e fechar", QMessageBox.ButtonRole.DestructiveRole)
            stay = box.addButton("Continuar editando", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(stay)
            box.setEscapeButton(stay)
            box.exec()
            clicked = box.clickedButton()
            if clicked is save:
                if not (not self._errors and not self._general_errors and self._save()):
                    event.ignore()
                    return
            elif clicked is not drop:
                event.ignore()
                return
        self._disk_timer.stop()
        self._validate_timer.stop()
        app = QApplication.instance()
        if app is not None:
            try:
                app.focusChanged.disconnect(self._on_focus_changed)      # type: ignore[attr-defined]
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)


# ============================================================================ funções de módulo
def collect_values(window: SettingsWindow) -> dict[str, Any]:
    """Valores atuais da tela como {'secao.campo': valor}."""
    return window.collect_values()


def apply_values(window: SettingsWindow, values: dict[str, Any]) -> None:
    """Preenche a tela com {'secao.campo': valor}; o que diferir do salvo aparece como alterado."""
    window.apply_values(values)


_instance: SettingsWindow | None = None


def open_settings(cfg: Config | None = None, parent: QWidget | None = None) -> SettingsWindow:
    """Abre (ou traz à frente) a tela de Configurações. Exige um ``QApplication`` ativo."""
    global _instance
    if QApplication.instance() is None:
        raise RuntimeError("open_settings precisa de um QApplication; use main_settings() fora da interface")
    existing = _instance
    if existing is not None:
        try:
            if existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return existing
        except RuntimeError:                                   # objeto Qt já destruído
            _instance = None
    window = SettingsWindow(cfg, parent)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    _instance = window
    window.show()
    window.raise_()
    window.activateWindow()
    return window


def main_settings() -> int:
    """Executa a tela como programa próprio (cria o ``QApplication`` se preciso). Devolve o código de saída."""
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    if owns_app:
        theme.apply_theme(app)      # type: ignore[arg-type]
    try:
        window = open_settings()
    except Exception:  # noqa: BLE001
        log.exception("não consegui abrir as configurações")
        return 1
    if not owns_app:
        return 0
    return int(app.exec()) if window is not None else 1
