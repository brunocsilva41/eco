"""Registro de ferramentas: allowlist, validação de argumentos, risco, confirmação, timeout e auditoria.

Contrato para quem escreve ferramentas (módulos em jarvis/tools/*.py):

    def register(registry: ToolRegistry, cfg: Config) -> None:
        registry.register(ToolSpec(name=..., description=..., parameters={...JSON schema...},
                                   risk=Risk.CONTROL, handler=_handler))

    def _handler(ctx: ToolContext, args: dict) -> ToolResult: ...

Fluxo de `execute` (nesta ordem; qualquer etapa pode encerrar com ToolResult de erro):
  1. allowlist + ferramenta ligada na config (`tools.disabled`)  2. validação do schema
  3. `prepare` (opcional): RESOLVE o alvo real (ex.: a janela exata) ANTES de perguntar e devolve o texto da confirmação
  4. confirmação Sim/Não quando necessário (RISKY, `tools.confirm`, conteúdo não confiável na rodada, ou `confirm_if`)
  5. handler, com timeout e cancelamento; 6. auditoria (inclui a decisão e quem aprovou).

Regras:
- Só o que está registrado existe para o modelo. Não há shell livre.
- Depois de qualquer resultado NÃO CONFIÁVEL na mesma rodada (`tainted`), toda ferramenta que age (CONTROL ou RISKY) exige confirmação.
- O handler deve respeitar `ctx.cancel` e nunca bloquear sem limite. Se uma ferramenta estourar o tempo, o efeito é
  DESCONHECIDO (`effect_unknown=True`): o agente não deve repetir a ação sem verificar.
- `audit_args` define o que vai para o log (ex.: tamanho + hash do texto digitado, nunca o conteúdo).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from collections.abc import Collection
from typing import Any, Callable, Protocol

from ..config import Config
from ..core.cancel import CancelToken
from ..core.events import EventBus
from ..core.permissions import YOLO
from ..core.risk import Risk

log = logging.getLogger(__name__)
audit = logging.getLogger("jarvis.audit")

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
MAX_LIVE_TOOL_THREADS = 4          # teto de threads de ferramenta vivas (uma presa em COM/IO não pode se acumular)
PREPARE_TIMEOUT_S = 5.0

__all__ = ["Risk", "ToolResult", "ToolContext", "Prepared", "ToolSpec", "Decision", "Confirmer", "ToolError",
           "ToolRegistry", "validate_args"]


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    message: str                         # curto; vai ao modelo e pode ser falado
    data: dict[str, Any] | None = None
    image: bytes | None = None           # imagem (JPEG/PNG) para o modelo de visão
    image_mime: str = "image/jpeg"
    untrusted: bool = False              # conteúdo vindo da tela/web/notas: nunca é instrução
    effect_unknown: bool = False         # a ação pode ter ocorrido mesmo sem sucesso confirmado
    grant: dict[str, str] | None = None  # recusa por LISTA DE PERMISSÃO que o usuário pode liberar: {"kind","value","text"}


@dataclass(frozen=True)
class Prepared:
    """Resultado da fase `prepare`: o que será perguntado ao Bruno e o estado guardado para o handler."""
    text: str                            # frase da confirmação, já com o alvo REAL (título/processo)
    state: Any = None                    # ex.: hwnd resolvido; chega ao handler em ctx.prepared


@dataclass
class ToolContext:
    cfg: Config
    cancel: CancelToken
    bus: EventBus
    memory: Any = None                   # jarvis.memory.Memory (injetado pelo app)
    prepared: Any = None                 # Prepared.state da fase prepare
    tainted: bool = False                # a rodada já leu conteúdo não confiável


Handler = Callable[[ToolContext, dict[str, Any]], ToolResult]
PrepareFn = Callable[[ToolContext, dict[str, Any]], "Prepared | ToolResult"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]           # JSON Schema (type=object)
    risk: Risk
    handler: Handler
    timeout_s: float | None = None       # None = cfg.safety.tool_timeout_s
    redact: frozenset[str] = frozenset() # argumentos que não vão para o log
    confirm_text: Callable[[dict[str, Any]], str] | None = None   # frase da confirmação (se não houver `prepare`)
    prepare: PrepareFn | None = None
    confirm_if: Callable[[dict[str, Any], bool], bool] | None = None   # (args, tainted) -> exige confirmação?
    audit_args: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    via: str = "none"                    # "voice" | "key" | "text" | "timeout" | "cancel" | "error"
    heard: str | None = None             # transcrição que aprovou (só vai ao log de auditoria)


class Confirmer(Protocol):
    def ask(self, text: str, risk: Risk, cancel: CancelToken) -> Decision:
        """Pede Sim/Não ao Bruno. Deve devolver allowed=False em timeout, cancelamento ou erro."""


class ToolError(Exception):
    pass


# ----------------------------------------------------------------- validação de argumentos (subconjunto de JSON Schema)
_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,),
}


def validate_args(schema: dict[str, Any], args: Any) -> list[str]:
    if not isinstance(args, dict):
        return ["os argumentos devem ser um objeto"]
    errs: list[str] = []
    props: dict[str, Any] = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in args:
            errs.append(f"falta o argumento '{req}'")
    if schema.get("additionalProperties", False) is False:
        for k in args:
            if k not in props:
                errs.append(f"argumento desconhecido '{k}'")
    for k, v in args.items():
        spec = props.get(k)
        if spec is None:
            continue
        t = spec.get("type")
        py = _TYPES.get(t, ())
        if py and (not isinstance(v, py) or (t in ("integer", "number") and isinstance(v, bool))):
            errs.append(f"'{k}' deve ser {t}")
            continue
        if "enum" in spec and not any(v == e and type(v) is type(e) for e in spec["enum"]):
            errs.append(f"'{k}' deve ser um de {spec['enum']}")
        if t == "string" and isinstance(v, str):
            if len(v) < spec.get("minLength", 0):
                errs.append(f"'{k}' curto demais")
            if len(v) > spec.get("maxLength", 10_000):
                errs.append(f"'{k}' longo demais")
        if t in ("integer", "number") and isinstance(v, (int, float)) and not isinstance(v, bool):
            if "minimum" in spec and v < spec["minimum"]:
                errs.append(f"'{k}' abaixo de {spec['minimum']}")
            if "maximum" in spec and v > spec["maximum"]:
                errs.append(f"'{k}' acima de {spec['maximum']}")
    return errs


def _check_schema(name: str, schema: dict[str, Any]) -> None:
    if schema.get("type") != "object" or not isinstance(schema.get("properties", {}), dict):
        raise ToolError(f"{name}: parameters deve ser um JSON Schema type=object")
    for k, v in schema.get("properties", {}).items():
        if v.get("type") not in _TYPES:
            raise ToolError(f"{name}.{k}: tipo não suportado ({v.get('type')!r}); use string/integer/number/boolean")


# ----------------------------------------------------------------- registro
class ToolRegistry:
    """Contrato de threads: `register` só na partida; `execute`/`openai_tools`/`reconfigure` são seguros entre threads."""

    _grant_appliers: dict[str, Callable[[str], None]]
    _grant_persist: Callable[[dict[str, str]], None] | None = None

    def __init__(self, cfg: Config, bus: EventBus, confirmer: Confirmer | None = None) -> None:
        self._grant_appliers = {}
        self._cfg = cfg
        self._bus = bus
        self._confirmer = confirmer
        self._tools: dict[str, ToolSpec] = {}
        self._lock = threading.Lock()
        self._live = 0                                   # threads de ferramenta ainda vivas
        self._blocked: str | None = None                 # motivo do bloqueio de ações (ex.: tecla de emergência morta)

    def set_confirmer(self, confirmer: Confirmer) -> None:
        self._confirmer = confirmer

    # ------------------------------------------------------------- permissões por lista (liberar na hora)
    def add_grant_applier(self, kind: str, fn: Callable[[str], None]) -> None:
        """A ferramenta registra como aplicar, na hora, uma liberação do tipo `kind` (ex.: 'typing_process')."""
        self._grant_appliers[kind] = fn

    def set_grant_persist(self, fn: Callable[[dict[str, str]], None]) -> None:
        """Quem guarda a liberação no config.toml (o app)."""
        self._grant_persist = fn

    def _grant_flow(self, grant: dict[str, str], parent: CancelToken, origin: str, tool: str) -> bool:
        """Recusa por lista de permissão: PERGUNTA (Ilha, voz ou tecla). Sim = libera, lembra e a ação segue. True se liberou."""
        applier = self._grant_appliers.get(grant.get("kind", ""))
        if applier is None or self._blocked:
            return False
        text = grant.get("text", "Permitir esta ação?")
        if YOLO.active():                                               # YOLO: libera só para a sessão, sem lembrar e sem perguntar
            applier(grant["value"])
            audit.info(json.dumps({"origin": origin, "tool": tool, "grant": grant.get("kind"), "via": "yolo"}, ensure_ascii=False))
            return True
        decision = self._confirm(text, Risk.CONTROL, parent)
        audit.info(json.dumps({"origin": origin, "tool": tool, "grant": grant.get("kind"),
                               "confirmation": {"allowed": decision.allowed, "via": decision.via}}, ensure_ascii=False))
        if not decision.allowed:
            return False
        applier(grant["value"])
        if self._grant_persist is not None:
            try:
                self._grant_persist(grant)
            except Exception:  # noqa: BLE001 - liberou para a sessão mesmo que não consiga gravar
                log.exception("não consegui gravar a liberação %s", grant.get("kind"))
        return True

    def block_actions(self, reason: str) -> None:
        """Só ferramentas de leitura passam a rodar (usado quando a tecla de emergência deixa de funcionar)."""
        with self._lock:
            self._blocked = reason
        log.error("ações no PC BLOQUEADAS: %s", reason)

    def unblock_actions(self) -> None:
        with self._lock:
            if self._blocked:
                log.warning("ações no PC liberadas de novo")
            self._blocked = None

    def reconfigure(self, cfg: Config) -> None:
        """Aplica uma nova configuração sem reiniciar (tools.disabled/confirm, timeouts)."""
        with self._lock:
            self._cfg = cfg

    def register(self, spec: ToolSpec) -> None:
        if not _NAME.match(spec.name):
            raise ToolError(f"nome de ferramenta inválido: {spec.name!r}")
        _check_schema(spec.name, spec.parameters)
        with self._lock:
            if spec.name in self._tools:
                raise ToolError(f"ferramenta duplicada: {spec.name}")
            self._tools[spec.name] = spec

    def names(self) -> list[str]:
        """Todas as ferramentas registradas (ligadas ou não)."""
        with self._lock:
            return sorted(self._tools)

    def enabled_names(self) -> list[str]:
        with self._lock:
            off = set(self._cfg.tools.disabled)
            return sorted(n for n in self._tools if n not in off)

    def get(self, name: str) -> ToolSpec | None:
        with self._lock:
            return self._tools.get(name)

    def openai_tools(self, only: "Collection[str] | None" = None) -> list[dict[str, Any]]:
        """Schemas das ferramentas LIGADAS (as desligadas o modelo nem vê). `only` restringe aos nomes dados (roteamento),
        sempre na ordem de registro, para o prefixo do prompt ser idêntico entre pedidos do mesmo tipo."""
        with self._lock:
            off = set(self._cfg.tools.disabled)
            specs = [s for n, s in self._tools.items() if n not in off and (only is None or n in only)]
            if isinstance(only, (list, tuple)):                           # ordem pedida (prefixo do prompt idêntico entre pedidos)
                order = {n: i for i, n in enumerate(only)}
                specs.sort(key=lambda s: order[s.name])
        return [{"type": "function", "function": {
            "name": s.name, "description": s.description, "parameters": s.parameters}} for s in specs]

    # ------------------------------------------------------------- execução
    def execute(self, name: str, raw_args: Any, parent_cancel: CancelToken, memory: Any = None,
                origin: str = "agent", tainted: bool = False) -> ToolResult:
        """Executa uma ferramenta pedida pelo modelo. Nunca levanta: sempre devolve ToolResult."""
        started = time.monotonic()
        with self._lock:
            spec = self._tools.get(name)
            cfg = self._cfg
            blocked = self._blocked
        if spec is None or name in cfg.tools.disabled:
            audit.warning(_line(origin, name, None, "recusada: ferramenta inexistente ou desligada"))
            return ToolResult(False, f"A ferramenta '{name}' não está disponível.")
        if blocked and spec.risk >= Risk.CONTROL:
            audit.warning(_line(origin, name, None, f"recusada: ações bloqueadas ({blocked})"))
            return ToolResult(False, "Estou sem a tecla de emergência funcionando; só posso consultar, não agir no PC.")

        args = _parse_args(raw_args)
        if args is None:
            return ToolResult(False, "Argumentos ilegíveis (JSON inválido).")
        shown = _audited(spec, args)
        errs = validate_args(spec.parameters, args)
        if errs:
            audit.warning(_line(origin, name, shown, "recusada: " + "; ".join(errs)))
            return ToolResult(False, "Argumentos inválidos: " + "; ".join(errs))
        if parent_cancel.cancelled:
            return ToolResult(False, "Cancelado.")

        ctx_cancel = parent_cancel.child()
        ctx = ToolContext(cfg=cfg, cancel=ctx_cancel, bus=self._bus, memory=memory, tainted=tainted)
        try:
            return self._execute_inner(spec, cfg, args, shown, ctx, parent_cancel, origin, started)
        finally:
            ctx_cancel.release()

    def _execute_inner(self, spec: ToolSpec, cfg: Config, args: dict[str, Any], shown: dict[str, Any],
                       ctx: ToolContext, parent: CancelToken, origin: str, started: float) -> ToolResult:
        name = spec.name
        try:
            step = spec.confirm_text(args) if spec.confirm_text else spec.description
        except Exception:  # noqa: BLE001 - a promessa de `execute` é nunca levantar
            log.exception("confirm_text de %s falhou", name)
            step = spec.description
        if spec.prepare is not None:                                    # 3. resolver o alvo REAL antes de perguntar
            outcome = self._call(spec.prepare, ctx, args, PREPARE_TIMEOUT_S, parent, name + ".prepare")
            if isinstance(outcome, ToolResult) and outcome.grant and self._grant_flow(outcome.grant, parent, origin, name):
                outcome = self._call(spec.prepare, ctx, args, PREPARE_TIMEOUT_S, parent, name + ".prepare")   # liberado: tenta de novo
            if isinstance(outcome, ToolResult):
                why = "[conteúdo omitido]" if (outcome.untrusted or spec.audit_args is not None) else outcome.message[:120]
                audit.info(_line(origin, name, shown, f"preparo falhou: {why}"))   # nunca grava títulos/nomes de fora
                self._bus.publish("action_step", tool=name, text=step, status="error", risk=int(spec.risk),
                                  result=("" if outcome.untrusted else outcome.message[:200]))      # a Ilha mostra POR QUE foi recusada
                return outcome
            ctx.prepared = outcome.state
            step = outcome.text

        try:
            tool_wants = bool(spec.confirm_if and spec.confirm_if(args, ctx.tainted))
        except Exception:  # noqa: BLE001 - erro na regra = pergunta por segurança
            log.exception("confirm_if de %s falhou; vou pedir confirmação", name)
            tool_wants = True
        # confirmação FORTE por voz ("confirmo"/"autorizo"): ação arriscada, rodada contaminada ou regra da própria ferramenta
        # "equilibrado": rodada contaminada só endurece o que a própria ferramenta pede (confirm_if); "estrito" endurece tudo que age
        taint_hardens = ctx.tainted and spec.risk >= Risk.CONTROL and cfg.safety.permission_mode == "strict"
        strong = spec.risk >= Risk.RISKY or taint_hardens or tool_wants
        need_confirm = strong or name in cfg.tools.confirm
        if need_confirm and YOLO.active():                              # ação MANUAL do Bruno: sem confirmações (travas duras seguem nos handlers)
            audit.info(json.dumps({"origin": origin, "tool": name, "args": shown,
                                   "confirmation": {"allowed": True, "via": "yolo"}}, ensure_ascii=False))
            need_confirm = False
        self._bus.publish("action_step", tool=name, text=step, status="start", risk=int(spec.risk))
        if need_confirm:
            decision = self._confirm(step, Risk.RISKY if strong else Risk.CONTROL, parent)
            audit.info(json.dumps({"origin": origin, "tool": name, "args": shown,
                                   "asked": step[:120] if spec.audit_args is None else None,   # com audit_args o texto pode ter dado sensível
                                   "confirmation": {"allowed": decision.allowed, "via": decision.via,
                                                    "heard": (decision.heard or "")[:80] or None}}, ensure_ascii=False))
            if not decision.allowed:
                self._bus.publish("action_step", tool=name, text=step, status="denied", risk=int(spec.risk))
                return ToolResult(False, "Ação não confirmada; não fiz nada.")

        timeout = spec.timeout_s or cfg.safety.tool_timeout_s
        result = self._call(spec.handler, ctx, args, timeout, parent, name)
        if not isinstance(result, ToolResult):
            result = ToolResult(False, f"{name} devolveu um resultado inválido.")
        elapsed = time.monotonic() - started
        outcome_txt = "ok" if result.ok else ("erro/efeito desconhecido" if result.effect_unknown else "erro")
        if result.untrusted:
            msg = f"[conteúdo não confiável omitido: {len(result.message)} caracteres]"
        else:                                                           # com audit_args a mensagem pode citar títulos/nomes: curta
            msg = result.message[:60 if spec.audit_args is not None else 200]
        audit.info(_line(origin, name, shown, f"{outcome_txt} {elapsed:.2f}s: {msg}"))
        self._bus.publish("action_step", tool=name, text=step, status="ok" if result.ok else "error",
                          risk=int(spec.risk), result=("" if result.untrusted else result.message[:200]))
        return result

    def _confirm(self, text: str, risk: Risk, parent: CancelToken) -> Decision:
        if self._confirmer is None:
            return Decision(False, "error")
        try:
            decision = self._confirmer.ask(text, risk, parent)
        except Exception:  # noqa: BLE001
            log.exception("confirmador falhou")
            return Decision(False, "error")
        return decision if isinstance(decision, Decision) else Decision(bool(decision), "legacy")

    def _call(self, fn: Callable[[ToolContext, dict[str, Any]], Any], ctx: ToolContext, args: dict[str, Any],
              timeout: float, parent: CancelToken, label: str) -> Any:
        """Roda `fn` numa thread descartável com timeout real e cancelamento. Devolve o retorno de `fn` ou um ToolResult de falha."""
        with self._lock:
            if self._live >= MAX_LIVE_TOOL_THREADS:
                log.error("há %d threads de ferramenta presas; recusando %s", self._live, label)
                return ToolResult(False, "Há ações anteriores ainda travadas; não vou iniciar outra agora.")
            self._live += 1
        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["r"] = fn(ctx, args)
            except Exception as exc:  # noqa: BLE001 - fronteira: nada pode escapar da ferramenta
                log.exception("ferramenta %s falhou", label)
                box["r"] = ToolResult(False, f"Erro ao executar {label}: {type(exc).__name__}", effect_unknown=True)
            finally:
                with self._lock:
                    self._live -= 1

        t = threading.Thread(target=work, name=f"tool-{label}", daemon=True)
        t.start()
        deadline = time.monotonic() + timeout
        while t.is_alive():
            if parent.cancelled:
                ctx.cancel.cancel(parent.reason)
                t.join(1.0)
                return ToolResult(False, "Cancelado. A ação pode ter sido executada parcialmente.", effect_unknown=True)
            if time.monotonic() >= deadline:
                ctx.cancel.cancel("timeout")
                t.join(1.0)
                return ToolResult(False, f"{label} passou de {timeout:.0f}s; o resultado é desconhecido e a ação "
                                  "pode ter acontecido. Não repita sem verificar.", effect_unknown=True)
            t.join(0.05)
        return box.get("r")


# ----------------------------------------------------------------- utilidades
def _parse_args(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return val if isinstance(val, dict) else None
    return None


def _audited(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    if spec.audit_args is not None:
        try:
            return spec.audit_args(args)
        except Exception:  # noqa: BLE001
            log.exception("audit_args de %s falhou", spec.name)
            return {"_": "args omitidos"}
    return {k: ("***" if k in spec.redact else v) for k, v in args.items()}


def _line(origin: str, tool: str, args: dict[str, Any] | None, outcome: str) -> str:
    return json.dumps({"origin": origin, "tool": tool, "args": args, "outcome": outcome}, ensure_ascii=False)
