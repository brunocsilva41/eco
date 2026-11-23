"""Terminal integrado x cérebro em nuvem (ACP): o agente de exemplo (tests/fake_acp_agent.py) pede comandos pelo MCP em loopback.
Provas: sem consentimento a ferramenta nem aparece; com consentimento TODO comando pede confirmação com o NOME do agente (até no modo
livre armado); comando perigoso é recusado sem perguntar; negar = nada roda; desligado = invisível.

Rodar: python tests/test_terminal_cloud.py
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jarvis import config as cfgmod                   # noqa: E402
from jarvis.brain.acp.cloud import CloudBrain         # noqa: E402
from jarvis.core.cancel import CancelToken            # noqa: E402
from jarvis.core.events import EventBus               # noqa: E402
from jarvis.terminal import runner as term            # noqa: E402
from jarvis.tools import catalog                      # noqa: E402
from jarvis.tools.registry import Decision, ToolRegistry   # noqa: E402

FAKE = [sys.executable, "-I", str(ROOT / "tests" / "fake_acp_agent.py")]
TMP = Path(tempfile.mkdtemp(prefix="jarvis_term_cloud_"))
WORK = TMP / "work"
WORK.mkdir()
(TMP / "data").mkdir()


def _brain(mode: str, command: str, *, consent=("opencode",), answer=True, action_modes=None):
    base = cfgmod.Config()
    cfg = dataclasses.replace(
        base, paths=dataclasses.replace(base.paths, data=TMP / "data"),
        terminal=dataclasses.replace(base.terminal, mode=mode, roots=(str(WORK),)),
        brain=dataclasses.replace(base.brain, kind="cloud", agent="opencode", request_timeout_s=40, startup_timeout_s=15,
                                  consent_terminal=tuple(consent), action_modes=dict(action_modes or {})))
    bus = EventBus()
    asked: list[str] = []

    class _Conf:                                           # o confirmador DO REGISTRO (o que pergunta ao usuário)
        def ask(self, text, risk, cancel):
            asked.append(text)
            return Decision(answer, "test")

    reg = ToolRegistry(cfg, bus, _Conf())
    catalog.register_everything(reg, cfg)
    if term._MANAGER is not None:
        term._MANAGER.close()
        term._MANAGER = None
    mgr = term.get_manager(cfg, bus, start_poller=False)
    os.environ["FAKE_MODE"], os.environ["FAKE_HTTP"], os.environ["FAKE_CMD"] = "term", "1", command
    cb = CloudBrain(cfg, reg, bus, lambda text, risk, cancel: answer, work_dir=TMP / "cwd")
    return cb, asked, mgr


class CloudTerminalTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch("jarvis.brain.acp.agents.command_for", return_value=FAKE)
        p.start()
        self.addCleanup(p.stop)

    def _ask(self, cb):
        try:
            return cb.ask("rode o comando", CancelToken())
        finally:
            cb.close()

    def test_without_consent_tool_is_invisible(self):
        cb, asked, _ = _brain("confirm", "Write-Output oi", consent=())
        out = self._ask(cb)
        self.assertIn("has=False", out)
        self.assertEqual(asked, [])

    def test_terminal_off_tool_is_invisible_even_with_consent(self):
        cb, asked, _ = _brain("off", "Write-Output oi")
        self.assertIn("has=False", self._ask(cb))
        self.assertEqual(asked, [])

    def test_consent_runs_only_after_strong_confirmation_with_agent_name(self):
        cb, asked, mgr = _brain("confirm", "Write-Output 'veio da nuvem'")
        out = self._ask(cb)
        self.assertIn("has=True", out)
        self.assertIn("veio da nuvem", out)
        self.assertEqual(len(asked), 1)
        self.assertIn("OpenCode", asked[0])
        self.assertIn("Write-Output 'veio da nuvem'", asked[0])
        self.assertIn(str(WORK.resolve()), asked[0])

    def test_denied_confirmation_runs_nothing(self):
        cb, asked, mgr = _brain("confirm", "Set-Content marca.txt 'x'", answer=False)
        out = self._ask(cb)
        self.assertEqual(len(asked), 1)
        self.assertFalse((WORK / "marca.txt").exists(), "negado: o comando NÃO pode ter rodado")
        self.assertNotIn("Terminou com código 0", out)
        self.assertFalse(mgr.runs(5))

    def test_free_mode_armed_still_asks_for_cloud(self):
        cb, asked, mgr = _brain("free", "Write-Output 'livre mas nuvem'")
        mgr.arm_free(5)
        out = self._ask(cb)
        self.assertEqual(len(asked), 1, "nuvem sempre pergunta, mesmo com o modo livre liberado")
        self.assertIn("livre mas nuvem", out)

    def test_allowlist_mode_cloud_still_asks(self):
        cb, asked, _ = _brain("allowlist", "dir")
        self._ask(cb)
        self.assertEqual(len(asked), 1, "dir está na lista permitida, mas pedido da nuvem pergunta")

    def test_blocked_command_refused_without_asking(self):
        cb, asked, mgr = _brain("confirm", "Stop-Computer")
        out = self._ask(cb)
        self.assertIn("ok=False", out)
        self.assertIn("bloqueado", out.lower())
        self.assertEqual(asked, [], "perigoso: nem pergunta")
        self.assertFalse(mgr.runs(5))

    def test_action_mode_deny_removes_terminal(self):
        cb, asked, _ = _brain("confirm", "Write-Output oi", action_modes={"opencode": "deny"})
        self.assertIn("has=False", self._ask(cb))


def tearDownModule():
    if term._MANAGER is not None:
        term._MANAGER.close()
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
