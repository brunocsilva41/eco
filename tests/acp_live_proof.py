"""Prova ao vivo do cérebro em nuvem: usa o agente REAL escolhido (padrão: opencode) com o ToolRegistry real.

Uso: python -I tests/acp_live_proof.py [agente] [pedido...]
O confirmador é simulado (registra o que seria perguntado e responde NÃO a tudo que age no PC), então nada é alterado.
"""
import dataclasses
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jarvis import config as cfgmod                                    # noqa: E402
from jarvis.brain.acp.cloud import CloudBrain, CloudUnavailable       # noqa: E402
from jarvis.core.cancel import CancelToken                            # noqa: E402
from jarvis.core.events import EventBus                               # noqa: E402
from jarvis.tools import catalog                                      # noqa: E402
from jarvis.tools.registry import Decision, ToolRegistry              # noqa: E402

agent = sys.argv[1] if len(sys.argv) > 1 else "opencode"
prompts = sys.argv[2:] or ["Que horas são agora? Use a ferramenta."]
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
audit_lines: list[str] = []


class _H(logging.Handler):
    def emit(self, record):
        audit_lines.append(record.getMessage())


logging.getLogger("jarvis.audit").addHandler(_H())

base = cfgmod.load()
cfg = dataclasses.replace(base, brain=dataclasses.replace(base.brain, kind="cloud", agent=agent, request_timeout_s=120))
bus = EventBus()
events = []
bus.subscribe(lambda ev: events.append((ev.kind, dict(ev.data))))
asked: list[str] = []


class Asker:
    def ask(self, text, risk, cancel):
        asked.append(text)
        return Decision(False, "test")


reg = ToolRegistry(cfg, bus, Asker())
catalog.register_everything(reg, cfg)
cloud = CloudBrain(cfg, reg, bus, lambda t, r, c: (asked.append(t), False)[1])
try:
    for p in prompts:
        t0 = time.monotonic()
        try:
            ans = cloud.ask(p, CancelToken())
            print(f"\n>> {p}\n<< {ans}\n   ({time.monotonic() - t0:.1f}s)")
        except CloudUnavailable as exc:
            print("\nNUVEM INDISPONIVEL:", exc.reason)
finally:
    cloud.close()
time.sleep(0.5)
print("\nConfirmações pedidas ao usuário:", asked)
print("Eventos da Ilha (action_step):", [e[1].get("tool") + ":" + e[1].get("status", "") for e in events if e[0] == "action_step"])
print("Auditoria (sem conteúdo):")
for l in audit_lines:
    print("  ", l[:300])
