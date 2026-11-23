"""Painel Terminal: mostra o que o terminal integrado do Eco está fazendo e deixa o usuário agir à mão.

O painel é OUTRO processo: lê `data/terminal/state.json` e os logs `runs/<id>.log` (já com segredos redigidos) a cada 0,4 s e
fala com o Eco por pedidos ASSINADOS (`runner.send_request`): rodar, parar, limpar e liberar/desligar o modo livre.
Liberar o modo livre exige o clique do usuário e uma confirmação; nada por voz, ferramenta ou nuvem chega até aqui.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter, QVBoxLayout,
                               QWidget)

from ...config import Config
from ...terminal import runner as term
from ..kit.base import ElidedLabel, Label, set_a11y, watch_theme
from ..kit.buttons import Button
from ..kit.dialogs import ConfirmDialog
from ..kit.feedback import InlineBanner, Toast
from ..kit.fields import ComboField, TextField
from ..kit.status import StatusChip
from ..theme import RADIUS, SIZE, SPACE, TYPE, ThemeManager, pal

log = logging.getLogger(__name__)

TITLE = "Terminal do Eco"
STALE_S = 6.0
POLL_MS = 400
MIN_SIZE = (860, 560)
OPEN_SIZE = (1040, 680)
_MARK = {"running": "●", "ok": "✓", "error": "✕", "timeout": "⏱", "killed": "■", "blocked": "⛔"}
_STATUS_TXT = {"running": "rodando", "ok": "ok", "error": "erro", "timeout": "tempo esgotado", "killed": "parado", "blocked": "bloqueado"}
_MODE_TXT = {"off": ("neutral", "Terminal desligado"), "confirm": ("ok", "Confirmar sempre"), "allowlist": ("ok", "Lista permitida"),
             "free": ("neutral", "Livre (não liberado)")}


def _dur(run: dict) -> str:
    end = run.get("ended") or time.time()
    s = max(0.0, end - float(run.get("started") or end))
    return (f"{s:.1f}".replace(".", ",") + " s") if s < 90 else f"{int(s // 60)} min {int(s % 60)} s"


def _mono() -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    for fam in ("Cascadia Mono", "Consolas", "Courier New"):
        if fam in QFontDatabase.families():
            f.setFamily(fam)
            break
    f.setPointSizeF(TYPE.body * 72.0 / 96.0)
    return f


class TerminalPanel(QWidget):
    """Janela do terminal. `data_dir` = pasta de dados do Eco (a mesma do `config.toml`)."""

    def __init__(self, data_dir: Path, parent: QWidget | None = None, *, cfg_loader: Callable[[], Config] | None = None) -> None:
        super().__init__(parent)
        self._dir = Path(data_dir)
        self._cfg_loader = cfg_loader
        self._state: dict | None = None
        self._runs: list[dict] = []
        self._shown_id = ""                       # run mostrado na saída
        self._follow = True                       # acompanha o comando mais novo até o usuário escolher outro
        self._log_pos = 0
        self._connected = False
        self._banner: InlineBanner | None = None
        self.setWindowTitle(TITLE)
        self._build()
        watch_theme(self, self._restyle)
        self._restyle()
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # ------------------------------------------------------------ montagem
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.xl, SPACE.lg, SPACE.xl, SPACE.lg)
        root.setSpacing(SPACE.md)

        head = QHBoxLayout()
        head.setSpacing(SPACE.md)
        self.title = Label(TITLE, "title")
        self.chip_mode = StatusChip("neutral", "Terminal desligado")
        self.chip_link = StatusChip("warn", "Eco fechado")
        head.addWidget(self.title)
        head.addWidget(self.chip_mode)
        head.addWidget(self.chip_link)
        head.addStretch(1)
        self.btn_free = Button("Liberar modo livre…", variant="secondary", icon_name="shield")
        self.btn_free.clicked.connect(self._ask_free)
        self.btn_unfree = Button("Desligar modo livre", variant="danger")
        self.btn_unfree.clicked.connect(lambda: self._send("disarm_free", {}, "Modo livre desligado."))
        head.addWidget(self.btn_free)
        head.addWidget(self.btn_unfree)
        root.addLayout(head)

        self.cwd_label = ElidedLabel("", "help")
        set_a11y(self.cwd_label, "Pasta atual do terminal")
        root.addWidget(self.cwd_label)
        self.banner_host = QVBoxLayout()
        self.banner_host.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self.banner_host)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self.history = QListWidget()
        self.history.setMinimumWidth(240)
        self.history.setUniformItemSizes(False)
        self.history.setWordWrap(True)
        self.history.setIconSize(QSize(1, 1))
        set_a11y(self.history, "Histórico de comandos")
        self.history.currentRowChanged.connect(self._on_pick)
        split.addWidget(self.history)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(SPACE.sm)
        bar = QHBoxLayout()
        bar.setSpacing(SPACE.sm)
        self.run_title = ElidedLabel("Nenhum comando ainda", "label")
        self.run_title.setProperty("kind", "label")
        bar.addWidget(self.run_title, 1)
        self.btn_stop = Button("Parar", variant="danger", icon_name="stop")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_copy = Button("Copiar saída", icon_name="copy")
        self.btn_copy.clicked.connect(self._copy_output)
        self.btn_copy_cmd = Button("Copiar comando", variant="text")
        self.btn_copy_cmd.clicked.connect(self._copy_command)
        self.btn_clear = Button("Limpar", variant="text", icon_name="trash")
        self.btn_clear.clicked.connect(self._clear)
        for b in (self.btn_stop, self.btn_copy, self.btn_copy_cmd, self.btn_clear):
            bar.addWidget(b)
        rl.addLayout(bar)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(_mono())
        self.out.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.out.setMaximumBlockCount(20000)
        set_a11y(self.out, "Saída do comando")
        rl.addWidget(self.out, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 700])
        root.addWidget(split, 1)

        row = QHBoxLayout()
        row.setSpacing(SPACE.sm)
        self.shell = ComboField([("PowerShell", "powershell"), ("Prompt de Comando", "cmd"), ("Git Bash", "bash")])
        set_a11y(self.shell, "Terminal a usar")
        self.shell.setFixedWidth(SIZE.nav_width - SPACE.xl)
        self.input = TextField("", placeholder="Digite um comando e aperte Enter (roda na pasta atual, com as mesmas travas)",
                               accessible_name="Comando")
        self.input.returnPressed.connect(self._run)
        self.btn_run = Button("Executar", variant="primary", icon_name="play")
        self.btn_run.clicked.connect(self._run)
        row.addWidget(self.shell)
        row.addWidget(self.input, 1)
        row.addWidget(self.btn_run)
        root.addLayout(row)

        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._clear)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self._copy_output)
        QShortcut(QKeySequence("Ctrl+C"), self.out, activated=self._copy_selection_or_stop)

    def _restyle(self) -> None:
        p = pal()
        self.out.setStyleSheet(
            f"QPlainTextEdit {{ background: {p.bg}; color: {p.text}; border: {SIZE.border}px solid {p.border_strong}; "
            f"border-radius: {RADIUS.md}px; padding: {SPACE.sm}px; selection-background-color: {p.accent}; selection-color: {p.on_accent}; }}")
        self.history.setStyleSheet(
            f"QListWidget {{ background: {p.surface}; color: {p.text}; border: {SIZE.border}px solid {p.border}; border-radius: {RADIUS.md}px; "
            f"outline: 0; padding: {SPACE.xs}px; }}"
            f"QListWidget::item {{ padding: {SPACE.sm}px {SPACE.md}px; border-radius: {RADIUS.sm}px; }}"
            f"QListWidget::item:hover {{ background: {p.hover}; }}"
            f"QListWidget::item:selected {{ background: {p.raised}; color: {p.text}; border: {SIZE.border}px solid {p.accent_ink}; }}")

    # ------------------------------------------------------------ leitura do estado
    def refresh(self) -> None:
        st = term.read_state(self._dir)
        self._state = st
        now = time.time()
        self._connected = bool(st and now - float(st.get("updated", 0)) <= STALE_S)
        mode = (st or {}).get("mode", "off")
        free_left = max(0.0, float((st or {}).get("free_until", 0)) - now) if self._connected else 0.0
        self.chip_link.set_state("ok" if self._connected else "warn", "Eco conectado" if self._connected else "Eco fechado")
        kind, text = _MODE_TXT.get(mode, ("neutral", mode))
        if mode == "free" and free_left > 0:
            kind, text = "warn", f"Livre: {int(free_left // 60)} min {int(free_left % 60):02d} s"
        self.chip_mode.set_state(kind, text)
        armed = mode == "free" and free_left > 0
        self.btn_free.setVisible(mode == "free" and not armed)
        self.btn_unfree.setVisible(armed)
        self.btn_free.setEnabled(self._connected)
        cwd = (st or {}).get("cwd") or ""
        shell = (st or {}).get("shell") or ""
        self.cwd_label.set_full_text(f"Pasta atual: {cwd or '(ainda nenhuma)'}   ·   Terminal padrão: {term.SHELL_LABEL.get(shell, shell) or '—'}")
        self._sync_banner(mode)
        runs = (st or {}).get("runs", [])
        if [r["id"] + r["status"] for r in runs] != [r["id"] + r["status"] for r in self._runs]:
            self._runs = runs
            self._rebuild_history()
        else:
            self._runs = runs
        cur = self._current_run()
        self._pump_output(cur)                                  # primeiro a saída: os botões abaixo dependem de haver texto
        running = bool(st and st.get("running"))
        self.btn_stop.setEnabled(self._connected and running)
        can_run = self._connected and mode != "off" and not running
        self.btn_run.setEnabled(can_run)
        self.input.setEnabled(self._connected and mode != "off")
        self.input.setPlaceholderText("Digite um comando e aperte Enter (roda na pasta atual, com as mesmas travas)" if can_run else
                                      ("Um comando está rodando; espere ou aperte Parar" if running else "Comandos manuais indisponíveis agora"))
        self.btn_copy.setEnabled(bool(self.out.toPlainText()))
        self.btn_copy_cmd.setEnabled(cur is not None)
        self.btn_clear.setEnabled(self._connected and bool(self._runs))

    def _sync_banner(self, mode: str) -> None:
        want: tuple[str, str, str, str] | None = None
        if not self._connected:
            want = ("warn", "O Eco não está rodando", "Sem ele o painel só mostra o que já foi gravado.", "Abra o Eco para usar o terminal.")
        elif mode == "off":
            want = ("warn", "O terminal integrado está desligado",
                    "O Eco não roda comandos enquanto estiver assim.", "Ligue em Configurações, página Terminal.")
        key = want[1] if want else ""
        if (self._banner.property("key") if self._banner else "") == key:
            return
        if self._banner is not None:
            self._banner.setParent(None)
            self._banner.deleteLater()
            self._banner = None
        if want:
            self._banner = InlineBanner(*want[:1], *want[1:])
            self._banner.setProperty("key", key)
            self.banner_host.addWidget(self._banner)

    def _rebuild_history(self) -> None:
        self.history.blockSignals(True)
        self.history.clear()
        for r in reversed(self._runs):                           # o mais novo em cima
            mark = _MARK.get(r["status"], "•")
            code = "" if r.get("exit") is None else f" · código {r['exit']}"
            origin = {"manual": "à mão", "agent": "Eco"}.get(r.get("origin", ""), "nuvem" if str(r.get("origin", "")).startswith("cloud") else r.get("origin", ""))
            item = QListWidgetItem(f"{mark} {r['command'][:90]}\n{_STATUS_TXT.get(r['status'], r['status'])}{code} · {_dur(r)} · {origin}")
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            item.setToolTip(f"{r['command']}\n{r.get('cwd', '')}")
            self.history.addItem(item)
        sel = self._shown_id if (self._shown_id and not self._follow) else (self._runs[-1]["id"] if self._runs else "")
        for i in range(self.history.count()):
            if self.history.item(i).data(Qt.ItemDataRole.UserRole) == sel:
                self.history.setCurrentRow(i)
                break
        self.history.blockSignals(False)

    def _current_run(self) -> dict | None:
        want = self._shown_id if not self._follow else (self._runs[-1]["id"] if self._runs else "")
        return next((r for r in self._runs if r["id"] == want), None)

    def _on_pick(self, row: int) -> None:
        item = self.history.item(row)
        if item is None:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        self._follow = bool(self._runs and rid == self._runs[-1]["id"])
        self._load_run(rid)                                     # recarrega a saída do comando escolhido
        self._pump_output(self._current_run())                  # e já mostra (sem esperar o próximo ciclo)
        self.btn_copy.setEnabled(bool(self.out.toPlainText()))

    def _load_run(self, rid: str) -> None:
        self.out.clear()
        self._log_pos = 0
        self._shown_id = rid

    def _pump_output(self, cur: dict | None) -> None:
        if cur is None:
            if self._shown_id:
                self._shown_id = ""
                self.out.clear()
            self.run_title.set_full_text("Nenhum comando ainda")
            return
        if cur["id"] != self._shown_id:
            self._load_run(cur["id"])
        mark = _MARK.get(cur["status"], "•")
        code = "" if cur.get("exit") is None else f" · código {cur['exit']}"
        self.run_title.set_full_text(f"{mark} {cur['command']}   —   {_STATUS_TXT.get(cur['status'], cur['status'])}{code} · {_dur(cur)} · {cur.get('cwd', '')}")
        path = self._dir / "terminal" / "runs" / (cur.get("log") or "")
        try:
            with open(path, "rb") as fh:
                fh.seek(self._log_pos)
                data = fh.read()
                self._log_pos = fh.tell()
        except OSError:
            data = b""
        if data:
            bar = self.out.verticalScrollBar()
            at_end = bar.value() >= bar.maximum() - 4
            self.out.moveCursor(self.out.textCursor().MoveOperation.End)
            self.out.insertPlainText(data.decode("utf-8", "replace"))
            if at_end:
                bar.setValue(bar.maximum())
        if cur["status"] == "blocked" and not self.out.toPlainText():
            self.out.setPlainText(cur.get("reason") or "Comando bloqueado.")

    # ------------------------------------------------------------ ações
    def _send(self, action: str, args: dict, toast: str = "") -> None:
        try:
            term.send_request(self._dir, action, args)
        except OSError as exc:
            Toast.show_message(self, "error", "Não consegui falar com o Eco", str(exc))
            return
        if toast:
            Toast.show_message(self, "ok", toast)

    def _run(self) -> None:
        cmd = self.input.value().strip()
        if not cmd or not self.btn_run.isEnabled():
            return
        self._follow = True
        self._send("run", {"command": cmd, "shell": self.shell.value()})
        self.input.set_value("")

    def _stop(self) -> None:
        run = (self._state or {}).get("running")
        if run:
            self._send("stop", {"run": run}, "Pedi para parar o comando.")

    def _copy_output(self) -> None:
        text = self.out.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            Toast.show_message(self, "ok", "Saída copiada")

    def _copy_command(self) -> None:
        cur = self._current_run()
        if cur:
            QApplication.clipboard().setText(cur["command"])
            Toast.show_message(self, "ok", "Comando copiado")

    def _copy_selection_or_stop(self) -> None:
        if self.out.textCursor().hasSelection():
            self.out.copy()
        elif self.btn_stop.isEnabled():
            self._stop()

    def _clear(self) -> None:
        if not self.btn_clear.isEnabled():
            return
        self._send("clear", {}, "Histórico limpo.")
        self.out.clear()
        self._log_pos = 0
        self._shown_id = ""

    def _ask_free(self) -> None:
        minutes = 15
        if self._cfg_loader is not None:
            try:
                minutes = self._cfg_loader().terminal.free_minutes
            except Exception:  # noqa: BLE001
                pass
        ok = ConfirmDialog.ask(
            self, title="Liberar o modo livre",
            message=(f"Por {minutes} minutos o Eco roda comandos pedidos por você SEM perguntar antes. Os comandos perigosos continuam bloqueados "
                     "e o que sair das pastas permitidas ainda pergunta. Pedidos vindos da nuvem ou depois de ler conteúdo de fora também continuam "
                     "perguntando. Desliga sozinho, ao reiniciar o Eco e na parada de emergência."),
            confirm_text="Liberar", destructive=True)
        if ok:
            self._send("arm_free", {"minutes": minutes}, "Modo livre liberado.")

    def closeEvent(self, e) -> None:  # type: ignore[no-untyped-def]
        self._timer.stop()
        super().closeEvent(e)


# ---------------------------------------------------------------- janela própria
_window: TerminalPanel | None = None


def _load_cfg() -> Config:
    from ... import config as cfgmod
    try:
        return cfgmod.load()
    except Exception:  # noqa: BLE001
        log.warning("config.toml ilegível; o painel usa os padrões", exc_info=True)
        return Config()


def open_terminal(data_dir: Path | None = None, parent: QWidget | None = None) -> TerminalPanel:
    global _window
    if QApplication.instance() is None:
        raise RuntimeError("open_terminal precisa de um QApplication; use main_terminal()")
    if _window is not None:
        try:
            if _window.isVisible():
                _window.raise_()
                _window.activateWindow()
                return _window
        except RuntimeError:
            _window = None
    data = Path(data_dir) if data_dir else Path(_load_cfg().paths.data)
    w = TerminalPanel(data, parent, cfg_loader=_load_cfg)
    w.setWindowFlag(Qt.WindowType.Window, True)
    w.setAutoFillBackground(True)
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    w.setMinimumSize(*MIN_SIZE)
    w.resize(*OPEN_SIZE)
    _window = w
    w.show()
    w.raise_()
    w.activateWindow()
    w.input.setFocus()
    return w


_mutex = None


def _another_instance_running() -> bool:
    global _mutex
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, "Local\\JarvisTerminalSingleton")
    if ctypes.get_last_error() == 183:
        hwnd = u32.FindWindowW(None, TITLE)
        if hwnd:
            u32.ShowWindow(ctypes.c_void_p(hwnd), 9)
            u32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        return True
    _mutex = handle
    return False


def main_terminal() -> int:
    if QApplication.instance() is None and _another_instance_running():
        return 0
    app = QApplication.instance()
    owns = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    if owns:
        try:
            from ..settings.prefs import UiPrefs
            UiPrefs().apply_saved_theme()
        except Exception:  # noqa: BLE001
            log.debug("tema salvo indisponível", exc_info=True)
        ThemeManager.instance().apply(app)  # type: ignore[arg-type]
    try:
        open_terminal()
    except Exception:  # noqa: BLE001
        log.exception("não consegui abrir o painel Terminal")
        return 1
    return int(app.exec()) if owns else 0
