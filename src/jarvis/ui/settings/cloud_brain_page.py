"""Painel "Cérebro em nuvem" das Configurações: widget autocontido (kit + tokens), no contrato de `blocks.external_panel`
(classe `*Panel` construída com `(controller)` ou sem argumentos; `ensure_loaded()` monta o conteúdo ao abrir a página).

O que ele mostra, por agente (OpenCode, Antigravity, Claude Code, Codex, Copilot): situação real (instalado, login, conta/cota),
botão **Testar** (inicia o agente e faz UM pedido mínimo: prova login, conta e modelo), botão **Como entrar** (o comando exato
que só a pessoa pode rodar), o **modo das ações no PC** (Negar / Confirmar sempre / Permissões normais) e o que o agente pode
ver (tela, memória, arquivos). Os campos continuam sendo do schema (`brain.*`); o painel só os edita de forma mais clara.

Integração:
    CloudBrainPanel(controller)       # com SettingsController: lê/grava via `controller.model.current` e `controller.edit`
    CloudBrainPanel()                 # autônomo: `values()`, `set_values(dict)` e sinal `changed` (sem controller)
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QVBoxLayout, QWidget

from ...brain.acp import agents
from ...brain.acp.cloud import probe_deep
from ..kit.base import Label, set_a11y
from ..kit.buttons import Button
from ..kit.feedback import InlineBanner
from ..kit.fields import ComboField
from ..kit.layout import Card
from ..kit.status import StatusChip
from ..theme import SPACE

log = logging.getLogger(__name__)

KEYS = ("brain.kind", "brain.agent", "brain.fallback_local", "brain.use_tools", "brain.builtin_tools", "brain.consent_screen",
        "brain.consent_memory", "brain.consent_files", "brain.action_modes", "brain.models", "brain.request_timeout_s",
        "brain.startup_timeout_s")
_DEFAULTS: dict[str, Any] = {"brain.kind": "local", "brain.agent": "opencode", "brain.fallback_local": True, "brain.use_tools": True,
                             "brain.builtin_tools": "deny", "brain.consent_screen": [], "brain.consent_memory": [],
                             "brain.consent_files": [], "brain.action_modes": {}, "brain.models": {},
                             "brain.request_timeout_s": 90.0, "brain.startup_timeout_s": 45.0}
MODES = (("Negar: só consultas, nada que aja no PC", "deny"), ("Confirmar sempre (recomendado)", "confirm"),
         ("Permissões normais do Eco", "normal"))
INTRO = ("Na nuvem, só o TEXTO do que você pede vai ao agente, que usa o login dele (o Eco nunca vê sua senha). "
         "A Ilha avisa a cada uso e, se a nuvem falhar, o modelo local assume.")


class _Bridge(QObject):
    detected = Signal(list)
    probed = Signal(str, dict)


class _AgentCard(Card):
    """Um agente: situação, Testar, Como entrar, modo das ações e o que ele pode ver."""

    def __init__(self, agent: agents.AgentDef, owner: "CloudBrainPanel") -> None:
        super().__init__()
        self.agent = agent
        head = QHBoxLayout()
        head.setSpacing(SPACE.md)
        self.title = Label(agent.label, "label")
        self.chip = StatusChip("neutral", "verificando…")
        self.use = Button("Usar este", variant="secondary")
        self.use.clicked.connect(lambda: owner._choose(agent.id))
        self.test = Button("Testar", variant="secondary", icon_name="refresh")
        self.test.setToolTip("Inicia o agente e faz um pedido mínimo (\"Diga apenas: ok\") para provar login, conta e modelo. "
                             "Pode levar até 1 minuto.")
        self.test.clicked.connect(lambda: owner._test(agent.id))
        self.how = Button("Como entrar", variant="text")
        self.how.clicked.connect(lambda: owner._how(agent.id))
        head.addWidget(self.title)
        head.addWidget(self.chip)
        head.addStretch(1)
        self.body.addLayout(head)
        buttons = QHBoxLayout()                                    # botões em linha própria: cabem em janela estreita (100%/150%)
        buttons.setSpacing(SPACE.sm)
        for w in (self.use, self.test, self.how):
            buttons.addWidget(w)
        buttons.addStretch(1)
        self.body.addLayout(buttons)
        self.detail = Label("", "help", wrap=True)
        self.body.addWidget(self.detail)
        self.slot = QVBoxLayout()                                  # banner de resultado do teste / como entrar
        self.slot.setContentsMargins(0, 0, 0, 0)
        self.body.addLayout(self.slot)

        row = QHBoxLayout()
        row.setSpacing(SPACE.md)
        row.addWidget(Label("Ações no PC", "help"))
        self.mode = ComboField(list(MODES))
        self.mode.valueChanged.connect(lambda _v: owner._edit_modes())
        set_a11y(self.mode, f"Ações no PC pedidas por {agent.label}")
        row.addWidget(self.mode, 1)
        self.body.addLayout(row)
        see = QVBoxLayout()
        see.setSpacing(SPACE.xs)
        see.addWidget(Label("Este agente pode usar:", "help"))
        self.screen, self.memory, self.files = (QCheckBox("Ver a tela e as janelas"), QCheckBox("Memória e conversas"),
                                                QCheckBox("Arquivos"))
        for box in (self.screen, self.memory, self.files):
            box.toggled.connect(lambda _c: owner._edit_consents())
            see.addWidget(box)
        self.body.addLayout(see)

    def show_banner(self, banner: QWidget | None) -> None:
        while self.slot.count():
            it = self.slot.takeAt(0)
            w = it.widget() if it is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if banner is not None:
            self.slot.addWidget(banner)


class CloudBrainPanel(QWidget):
    changed = Signal()

    def __init__(self, controller: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctl = controller
        self._local: dict[str, Any] = dict(_DEFAULTS)
        self._loading = False
        self._built = False
        self._cards: dict[str, _AgentCard] = {}
        self._bridge = _Bridge()
        self._bridge.detected.connect(self._on_detected)
        self._bridge.probed.connect(self._on_probed)
        self._detected: dict[str, agents.Detected] = {}
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(SPACE.md)
        if controller is not None:
            controller.valuesReplaced.connect(self._reload)

    # ------------------------------------------------------------------ valores (controller ou autônomo)
    def _get(self, key: str) -> Any:
        if self._ctl is not None:
            return self._ctl.model.current.get(key, _DEFAULTS[key])
        return self._local.get(key, _DEFAULTS[key])

    def _set(self, key: str, value: Any) -> None:
        if self._loading:
            return
        if self._ctl is not None:
            self._ctl.edit(key, value)
        else:
            self._local[key] = value
        self.changed.emit()

    def values(self) -> dict[str, Any]:
        return {k: self._get(k) for k in KEYS}

    def set_values(self, values: dict[str, Any]) -> None:
        self._local.update({k: v for k, v in values.items() if k in KEYS})
        self._reload()

    # ------------------------------------------------------------------ montagem preguiçosa
    def ensure_loaded(self) -> None:
        if self._built:
            return
        self._built = True
        self.col.addWidget(Label(INTRO, "help", wrap=True))
        top = QHBoxLayout()
        self.refresh = Button("Detectar de novo", variant="text", icon_name="refresh")
        self.refresh.clicked.connect(self.refresh_agents)
        top.addWidget(self.refresh)
        top.addStretch(1)
        self.col.addLayout(top)
        for a in agents.CATALOG:
            card = _AgentCard(a, self)
            self._cards[a.id] = card
            self.col.addWidget(card)
        self._reload()
        self.refresh_agents()

    # ------------------------------------------------------------------ estado -> tela
    def _reload(self) -> None:
        if not self._built or self._loading:
            return
        self._loading = True
        try:
            modes = self._get("brain.action_modes") or {}
            current = self._get("brain.agent")
            for aid, card in self._cards.items():
                card.mode.set_value(modes.get(aid, "confirm"))
                card.screen.setChecked(aid in (self._get("brain.consent_screen") or []))
                card.memory.setChecked(aid in (self._get("brain.consent_memory") or []))
                card.files.setChecked(aid in (self._get("brain.consent_files") or []))
                card.use.setText("Em uso" if aid == current else "Usar este")
                card.use.setEnabled(aid != current)
        finally:
            self._loading = False

    def _choose(self, agent_id: str) -> None:
        self._set("brain.agent", agent_id)
        self._reload()
        self._sync_rows()

    def _edit_modes(self) -> None:
        if self._loading:
            return
        modes = {aid: c.mode.value() for aid, c in self._cards.items() if c.mode.value() != "confirm"}
        self._set("brain.action_modes", modes)
        self._sync_rows()

    def _edit_consents(self) -> None:
        if self._loading:
            return
        for key, attr in (("brain.consent_screen", "screen"), ("brain.consent_memory", "memory"), ("brain.consent_files", "files")):
            self._set(key, [aid for aid, c in self._cards.items() if getattr(c, attr).isChecked()])
        self._sync_rows()

    def _sync_rows(self) -> None:
        """Mantém os campos avançados do schema (listas/tabela) em dia com o que foi mudado aqui."""
        if self._ctl is not None:
            self._loading = True                         # nosso próprio _reload não precisa rodar
            try:
                self._ctl.valuesReplaced.emit()
            finally:
                self._loading = False

    # ------------------------------------------------------------------ detecção e teste (em thread)
    def refresh_agents(self) -> None:
        if not self._built:
            return
        self.refresh.setEnabled(False)
        for c in self._cards.values():
            c.chip.set_state("neutral", "verificando…")

        def work() -> None:
            try:
                found = agents.detect_all(with_version=True)
            except Exception:  # noqa: BLE001
                log.exception("detecção de agentes falhou")
                found = []
            self._bridge.detected.emit(found)

        threading.Thread(target=work, name="cloud-detect", daemon=True).start()

    def _on_detected(self, found: list) -> None:
        self.refresh.setEnabled(True)
        self._detected = {d.id: d for d in found}
        for aid, card in self._cards.items():
            d = self._detected.get(aid)
            if d is None:
                card.chip.set_state("warn", "não consegui verificar")
                card.test.setEnabled(False)
            elif not d.installed:
                card.chip.set_state("error", "não instalado")
                card.detail.setText(f"{d.label} não foi encontrado neste computador.")
                card.test.setEnabled(False)
            else:
                login = {"provável": "login provável", "sem login": "login não encontrado", "desconhecido": "login não verificado"}.get(
                    d.login, d.login)
                card.chip.set_state("neutral", "instalado")
                card.detail.setText(f"{d.version} · {login}. Use «Testar» para confirmar conta e modelo.".strip(" ·"))
                card.test.setEnabled(True)

    def _test(self, agent_id: str) -> None:
        card = self._cards[agent_id]
        card.test.setEnabled(False)
        card.chip.set_state("neutral", "testando…")
        card.show_banner(None)

        def work() -> None:
            try:
                result = probe_deep(agent_id, None, 90.0)
            except Exception as exc:  # noqa: BLE001
                log.exception("teste do agente falhou")
                result = {"state": "erro", "detail": type(exc).__name__, "model": "", "seconds": 0.0,
                          "login_help": agents.BY_ID[agent_id].login_help}
            self._bridge.probed.emit(agent_id, result)

        threading.Thread(target=work, name="cloud-probe", daemon=True).start()

    def _on_probed(self, agent_id: str, result: dict) -> None:
        self.apply_probe_result(agent_id, result)

    def apply_probe_result(self, agent_id: str, result: dict) -> None:
        """Mostra o resultado de um teste (também usado pelos testes de interface com resultados simulados)."""
        card = self._cards[agent_id]
        card.test.setEnabled(True)
        state, detail = result.get("state"), str(result.get("detail", ""))
        secs, model = float(result.get("seconds", 0) or 0), result.get("model", "")
        label = agents.BY_ID[agent_id].label
        card.detail.setText("")
        if state == "pronto":
            card.chip.set_state("ok", "pronto")
            card.detail.setText(f"Respondeu em {secs:.0f} s" + (f" · modelo {model}" if model else "") + ".")
            card.show_banner(None)
        elif state == "sem login":
            card.chip.set_state("error", "sem login")
            card.show_banner(self._how_banner(agent_id, f"{label} está sem login."))
        elif state == "sem cota":
            card.chip.set_state("warn", "sem cota")
            card.show_banner(InlineBanner("warn", f"A conta do {label} atingiu o limite de uso.",
                                          "O agente está instalado e com login, mas a assinatura ou os créditos acabaram.",
                                          "Espere a renovação, troque de plano ou use outro agente. Enquanto isso o Eco "
                                          "responde com o modelo local."))
        elif state == "modelo":
            card.chip.set_state("warn", "modelo indisponível")
            card.show_banner(InlineBanner("warn", f"{label} não tem um modelo disponível nesta conta.", detail,
                                          "Escolha outro modelo em «Modelo por agente» ou use outro agente."))
        elif state == "nao instalado":
            card.chip.set_state("error", "não instalado")
        else:
            card.chip.set_state("error", "não respondeu")
            card.show_banner(InlineBanner("error", f"{label} não respondeu.", detail or "Erro desconhecido.",
                                          "Tente de novo. Se persistir, abra o agente no terminal para ver o erro."))

    # ------------------------------------------------------------------ Como entrar
    def _how_banner(self, agent_id: str, what: str) -> InlineBanner:
        a = agents.BY_ID[agent_id]
        banner = InlineBanner("warn", what, "Quem entra na conta é o próprio agente; o Eco não pede nem guarda senha.",
                              f"Abra um terminal e rode:  {a.login_help}", action_text="Copiar comando")
        banner.actionTriggered.connect(lambda: self._copy(agents.login_command(agent_id)))
        return banner

    def _how(self, agent_id: str) -> None:
        self._cards[agent_id].show_banner(self._how_banner(agent_id, f"Como entrar no {agents.BY_ID[agent_id].label}"))

    @staticmethod
    def _copy(text: str) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text)

    def shutdown(self) -> None:
        pass


CloudBrainPage = CloudBrainPanel          # nome antigo (compatibilidade)
