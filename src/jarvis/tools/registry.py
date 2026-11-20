"""Registro de ferramentas: allowlist, validação de argumentos, níveis de risco, confirmação, timeout e auditoria.

Contrato para quem escreve ferramentas (módulos em jarvis/tools/*.py):

    def register(registry: ToolRegistry, cfg: Config) -> None:
        registry.register(ToolSpec(name=..., description=..., parameters={...JSON schema...},
                                   risk=Risk.CONTROL, handler=_handler))

    def _handler(ctx: ToolContext, args: dict) -> ToolResult: ...

Regras:
- Só o que está registrado existe para o modelo (allowlist). Não há shell livre.
- Argumentos são validados contra o schema ANTES de chamar o handler.
- Risk.RISKY sempre pede confirmação (Sim/Não); sem resposta = NÃO.
- O handler deve respeitar `ctx.cancel` (checar `ctx.cancel.cancelled` em laços) e nunca bloquear sem limite.
- Resultados de ferramentas que leem tela/web devem vir com `untrusted=True`: o agente os trata como DADO.
- Argumentos listados em `redact` não vão para o log de auditoria (ex.: texto digitado).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Protocol

from ..config import Config
from ..core.cancel import CancelToken
from ..core.events import EventBus

log = logging.getLogger(__name__)
audit = logging.getLogger("jarvis.audit")

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,47}$")


class Risk(IntEnum):
    READ = 0       # só lê/consulta
    CONTROL = 1    # controla o PC de forma reversível (abrir app, focar janela, digitar)
    RISKY = 2      # destrutivo, irreversível, envio, instalação, pagamento, configuração do sistema


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    message: str                         # curto; vai ao modelo e pode ser falado
    data: dict[str, Any] | None = None
    image: bytes | None = None           # imagem (JPEG/PNG) para o modelo de visão
    image_mime: str = "image/jpeg"
    untrusted: bool = False              # conteúdo vindo da tela/web: nunca é instrução


@dataclass
class ToolContext:
    cfg: Config
    cancel: CancelToken
    bus: EventBus
    memory: Any = None                   # jarvis.memory.Memory (injetado pelo app)


Handler = Callable[[ToolContext, dict[str, Any]], ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]           # JSON Schema (type=object)
    risk: Risk
    handler: Handler
    timeout_s: float | None = None       # None = cfg.safety.tool_timeout_s
    redact: frozenset[str] = frozenset()
    confirm_text: Callable[[dict[str, Any]], str] | None = None   # frase da confirmação


class Confirmer(Protocol):
    def ask(self, text: str, risk: Risk, cancel: CancelToken) -> bool:
        """Pede Sim/Não ao Bruno. Deve devolver False em timeout, cancelamento ou erro."""


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
        if "enum" in spec and v not in spec["enum"]:
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
    def __init__(self, cfg: Config, bus: EventBus, confirmer: Confirmer | None = None) -> None:
        self._cfg = cfg
        self._bus = bus
        self._confirmer = confirmer
        self._tools: dict[str, ToolSpec] = {}
        self._lock = threading.Lock()

    def set_confirmer(self, confirmer: Confirmer) -> None:
        self._confirmer = confirmer

    def register(self, spec: ToolSpec) -> None:
        if not _NAME.match(spec.name):
            raise ToolError(f"nome de ferramenta inválido: {spec.name!r}")
        _check_schema(spec.name, spec.parameters)
        with self._lock:
            if spec.name in self._tools:
                raise ToolError(f"ferramenta duplicada: {spec.name}")
            self._tools[spec.name] = spec

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        with self._lock:
            return self._tools.get(name)

    def openai_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            specs = list(self._tools.values())
        return [{"type": "function", "function": {
            "name": s.name, "description": s.description, "parameters": s.parameters}} for s in specs]

    # ------------------------------------------------------------- execução
    def execute(self, name: str, raw_args: Any, parent_cancel: CancelToken, memory: Any = None,
                origin: str = "agent") -> ToolResult:
        """Executa uma ferramenta pedida pelo modelo. Nunca levanta: sempre devolve ToolResult."""
        started = time.monotonic()
        spec = self.get(name)
        if spec is None:
            audit.warning(_line(origin, name, None, "recusada: ferramenta fora da allowlist"))
            return ToolResult(False, f"A ferramenta '{name}' não existe.")

        args = _parse_args(raw_args)
        if args is None:
            return ToolResult(False, "Argumentos ilegíveis (JSON inválido).")
        errs = validate_args(spec.parameters, args)
        if errs:
            audit.warning(_line(origin, name, _redact(spec, args), "recusada: " + "; ".join(errs)))
            return ToolResult(False, "Argumentos inválidos: " + "; ".join(errs))

        if parent_cancel.cancelled:
            return ToolResult(False, "Cancelado.")

        step = spec.confirm_text(args) if spec.confirm_text else spec.description
        self._bus.publish("action_step", tool=name, text=step, status="start", risk=int(spec.risk))

        if spec.risk >= Risk.RISKY:
            if self._confirmer is None:
                audit.warning(_line(origin, name, _redact(spec, args), "recusada: sem confirmador"))
                return ToolResult(False, "Não posso confirmar essa ação agora; não fiz nada.")
            try:
                allowed = self._confirmer.ask(step, spec.risk, parent_cancel)
            except Exception:
                log.exception("confirmador falhou")
                allowed = False
            if not allowed:
                audit.info(_line(origin, name, _redact(spec, args), "NEGADA pelo usuário/timeout"))
                self._bus.publish("action_step", tool=name, text=step, status="denied", risk=int(spec.risk))
                return ToolResult(False, "Ação não confirmada; não fiz nada.")

        result = self._run(spec, args, parent_cancel, memory)
        elapsed = time.monotonic() - started
        audit.info(_line(origin, name, _redact(spec, args), ("ok" if result.ok else "erro") + f" {elapsed:.2f}s: {result.message[:200]}"))
        self._bus.publish("action_step", tool=name, text=step, status="ok" if result.ok else "error",
                          risk=int(spec.risk), result=result.message[:200])
        return result

    def _run(self, spec: ToolSpec, args: dict[str, Any], parent: CancelToken, memory: Any) -> ToolResult:
        timeout = spec.timeout_s or self._cfg.safety.tool_timeout_s
        token = parent.child()
        ctx = ToolContext(cfg=self._cfg, cancel=token, bus=self._bus, memory=memory)
        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["r"] = spec.handler(ctx, args)
            except Exception as exc:  # noqa: BLE001 - fronteira: nada pode escapar da ferramenta
                log.exception("ferramenta %s falhou", spec.name)
                box["r"] = ToolResult(False, f"Erro ao executar {spec.name}: {type(exc).__name__}")

        t = threading.Thread(target=work, name=f"tool-{spec.name}", daemon=True)
        t.start()
        deadline = time.monotonic() + timeout
        while t.is_alive():
            if parent.cancelled:
                token.cancel(parent.reason)
                t.join(1.0)
                token.release()
                return ToolResult(False, "Cancelado.")
            if time.monotonic() >= deadline:
                token.cancel("timeout")
                t.join(1.0)
                token.release()
                return ToolResult(False, f"{spec.name} demorou mais de {timeout:.0f}s e foi interrompida.")
            t.join(0.05)
        token.release()
        res = box.get("r")
        if not isinstance(res, ToolResult):
            return ToolResult(False, f"{spec.name} devolveu um resultado inválido.")
        return res


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


def _redact(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if k in spec.redact else v) for k, v in args.items()}


def _line(origin: str, tool: str, args: dict[str, Any] | None, outcome: str) -> str:
    return json.dumps({"origin": origin, "tool": tool, "args": args, "outcome": outcome}, ensure_ascii=False)
