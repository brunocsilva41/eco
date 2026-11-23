"""Testes do cérebro em nuvem (ACP) com um agente de exemplo local (tests/fake_acp_agent.py). Sem rede, sem GPU, sem credenciais.

Rodar:  venv\\Scripts\\python.exe -I -W error tests\\test_cloud_brain.py
"""
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jarvis import config as cfgmod                                          # noqa: E402
from jarvis.agent import Agent                                               # noqa: E402
from jarvis.brain.acp import client as acpclient, policy                    # noqa: E402
from jarvis.brain.acp.client import AcpAuthRequired, AcpCancelled, AcpClient, AcpError, AcpTimeout   # noqa: E402
from jarvis.brain.acp.cloud import CloudBrain, CloudUnavailable             # noqa: E402
from jarvis.brain.acp.mcp_server import LoopbackMcpServer, McpTool, McpToolResult   # noqa: E402
from jarvis.core.cancel import Cancelled, CancelToken                        # noqa: E402
from jarvis.core.events import EventBus                                      # noqa: E402
from jarvis.core.risk import Risk                                            # noqa: E402
from jarvis.settings import schema                                           # noqa: E402
from jarvis.tools import catalog                                             # noqa: E402
from jarvis.tools.registry import Decision, ToolContext, ToolRegistry, ToolResult, ToolSpec   # noqa: E402

FAKE = [sys.executable, "-I", str(ROOT / "tests" / "fake_acp_agent.py")]
TMP = Path(tempfile.mkdtemp(prefix="jarvis_acp_test_"))


def _client(mode: str, **kw) -> AcpClient:
    return AcpClient(FAKE, TMP, env={"FAKE_MODE": mode, **kw.pop("env", {})}, **kw)


def _started(mode: str, **kw) -> AcpClient:
    c = _client(mode, **kw)
    c.start()
    c.initialize(10)
    c.new_session(TMP, [], 10)
    return c


class ClientTests(unittest.TestCase):
    def test_prompt_streams_text(self):
        c = _started("ok")
        try:
            r = c.prompt("oi", CancelToken(), 10)
            self.assertEqual(r.text, "Olá, mundo.")
            self.assertEqual(r.stop_reason, "end_turn")
        finally:
            c.close()

    def test_fs_and_terminal_are_denied(self):
        c = _started("fs")
        try:
            self.assertEqual(c.prompt("x", CancelToken(), 10).text, "fs=erro")
        finally:
            c.close()

    def test_capabilities_announce_no_fs_no_terminal(self):
        sent = {}
        c = _client("ok")
        orig = c._send
        c._send = lambda o: (sent.setdefault(o.get("method"), o), orig(o))[1]
        c.start()
        try:
            c.initialize(10)
        finally:
            c.close()
        caps = sent["initialize"]["params"]["clientCapabilities"]
        self.assertEqual(caps, {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False})

    def test_auth_required(self):
        c = _client("auth")
        c.start()
        try:
            c.initialize(10)
            with self.assertRaises(AcpAuthRequired):
                c.new_session(TMP, [], 10)
        finally:
            c.close()

    def test_timeout_sends_cancel(self):
        c = _started("hang")
        try:
            t0 = time.monotonic()
            with self.assertRaises(AcpTimeout):
                c.prompt("x", CancelToken(), 0.6)
            self.assertLess(time.monotonic() - t0, 4)
        finally:
            c.close()

    def test_cancel_cooperative(self):
        c = _started("hang")
        tok = CancelToken()
        threading.Timer(0.4, lambda: tok.cancel("parar")).start()
        try:
            with self.assertRaises(AcpCancelled):
                c.prompt("x", tok, 30)
        finally:
            c.close()

    def test_cancel_ignored_kills_process(self):
        c = _started("hang_ignore")
        tok = CancelToken()
        threading.Timer(0.3, lambda: tok.cancel("parar")).start()
        with mock.patch.object(acpclient, "CANCEL_GRACE_S", 1.0):
            with self.assertRaises(AcpCancelled):
                c.prompt("x", tok, 30)
        self.assertFalse(c.alive)

    def test_process_death(self):
        c = _started("die")
        try:
            with self.assertRaises(AcpError):
                c.prompt("x", CancelToken(), 10)
            self.assertFalse(c.alive)
        finally:
            c.close()


def _perm(mode, builtin="deny", confirm=True):
    asked = []
    log = []
    tok = CancelToken()
    handler = lambda p: policy.decide_permission(                    # noqa: E731
        p, label="Teste", builtin_policy=builtin, jarvis_tools={"hora_atual"},
        confirm=lambda text, risk, c: (asked.append((text, risk)), confirm)[1], cancel=tok, audit=lambda e, x: log.append((e, x)))
    c = _started(mode, on_permission=handler)
    try:
        return c.prompt("x", tok, 10).text, asked, log
    finally:
        c.close()


class PermissionTests(unittest.TestCase):
    def test_builtin_denied_by_default(self):
        text, asked, log = _perm("perm")
        self.assertIn('"optionId": "r"', text)
        self.assertEqual(asked, [])
        self.assertEqual(log[0][0], "permission_builtin")

    def test_builtin_ask_goes_to_strong_confirmation(self):
        text, asked, _ = _perm("perm", builtin="ask", confirm=True)
        self.assertIn('"optionId": "a"', text)                      # allow_once, nunca allow_always
        self.assertEqual(asked[0][1], Risk.RISKY)
        self.assertIn("Teste", asked[0][0])
        text, _, _ = _perm("perm", builtin="ask", confirm=False)
        self.assertIn('"optionId": "r"', text)

    def test_jarvis_tool_allowed_once_without_double_ask(self):
        text, asked, _ = _perm("perm_jarvis")
        self.assertIn('"optionId": "a"', text)
        self.assertEqual(asked, [])

    def test_title_spoofing_is_not_jarvis(self):
        self.assertFalse(policy.is_jarvis_tool({"title": "Run bash x_hora_atual"}, {"hora_atual"}))
        self.assertTrue(policy.is_jarvis_tool({"title": "Run mcp_eco_hora_atual"}, {"hora_atual"}))
        self.assertFalse(policy.is_jarvis_tool({"title": "eco_naoexiste"}, {"hora_atual"}))


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.srv = LoopbackMcpServer(lambda: [McpTool("eco", "eco", {"type": "object", "properties": {}})],
                                     lambda n, a: (self.calls.append((n, a)), McpToolResult(True, "feito"))[1])
        self.srv.start()

    def tearDown(self):
        self.srv.stop()

    def _post(self, body, token=True, host=None):
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {self.srv.token}"
        if host:
            h["Host"] = host
        req = urllib.request.Request(self.srv.url, data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_binds_loopback_only(self):
        self.assertEqual(self.srv._httpd.server_address[0], "127.0.0.1")

    def test_requires_token_and_loopback_host(self):
        self.assertEqual(self._post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=False)[0], 401)
        self.assertEqual(self._post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, host="evil.example")[0], 403)
        self.assertEqual(self._post({"jsonrpc": "2.0", "id": 1, "method": "ping"})[0], 200)

    def test_list_call_and_unlisted_tool(self):
        _, body = self._post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(json.loads(body)["result"]["tools"][0]["name"], "eco")
        _, body = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "eco", "arguments": {}}})
        self.assertFalse(json.loads(body)["result"]["isError"])
        _, body = self._post({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "apagar_arquivo", "arguments": {}}})
        self.assertTrue(json.loads(body)["result"]["isError"])
        self.assertEqual(self.calls, [("eco", {})])                  # a ferramenta não listada NUNCA chegou ao executor

    def test_stdio_bridge(self):
        env = {**os.environ, "JARVIS_MCP_URL": self.srv.url, "JARVIS_MCP_TOKEN": self.srv.token}
        out = subprocess.run([sys.executable, "-I", str(ROOT / "src" / "jarvis" / "brain" / "acp" / "mcp_stdio_bridge.py")],
                             input='{"jsonrpc":"2.0","id":7,"method":"tools/list"}\n', capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(json.loads(out.stdout.strip())["result"]["tools"][0]["name"], "eco")
        bad = subprocess.run([sys.executable, "-I", str(ROOT / "src" / "jarvis" / "brain" / "acp" / "mcp_stdio_bridge.py")],
                             input="{}\n", capture_output=True, text=True, timeout=20,
                             env={**os.environ, "JARVIS_MCP_URL": "http://example.com/mcp", "JARVIS_MCP_TOKEN": "x"})
        self.assertEqual(bad.returncode, 2)                          # recusa URL fora de loopback


class ConsentTests(unittest.TestCase):
    def test_default_hides_screen_memory_files_and_memory_writes(self):
        b = cfgmod.BrainCfg()
        names = ["hora_atual", "ver_tela", "listar_janelas", "ler_arquivo", "buscar_memoria", "lembrar", "abrir_app"]
        self.assertEqual(policy.allowed_tools(b, "opencode", names), ["hora_atual", "abrir_app"])

    def test_consent_is_per_agent(self):
        b = cfgmod.BrainCfg(consent_screen=("claude",), consent_files=("claude",), consent_memory=("claude",))
        names = ["ver_tela", "ler_arquivo", "buscar_memoria", "lembrar"]
        self.assertEqual(policy.allowed_tools(b, "claude", names), ["ver_tela", "ler_arquivo", "buscar_memoria"])   # lembrar nunca
        self.assertEqual(policy.allowed_tools(b, "opencode", names), [])


class RegistryCloudTests(unittest.TestCase):
    def test_cloud_action_always_needs_strong_confirmation_with_agent_name(self):
        asked = []

        class Asker:
            def ask(self, text, risk, cancel):
                asked.append((text, risk))
                return Decision(True, "test")

        reg = ToolRegistry(cfgmod.load(), EventBus(), Asker())
        ran = []
        reg.register(ToolSpec("acao_teste", "Faz algo", {"type": "object", "properties": {}}, Risk.CONTROL,
                              lambda ctx, a: (ran.append(1), ToolResult(True, "feito"))[1], confirm_text=lambda a: "Fazer algo"))
        reg.register(ToolSpec("consulta_teste", "Lê algo", {"type": "object", "properties": {}}, Risk.READ,
                              lambda ctx, a: ToolResult(True, "lido")))
        reg.execute("acao_teste", {}, CancelToken())                                       # local, equilibrado: sem pergunta
        self.assertEqual(asked, [])
        reg.execute("acao_teste", {}, CancelToken(), origin="cloud:x", tainted=True, cloud_label="Agente X")
        self.assertEqual(len(asked), 1)
        self.assertIn("Agente X", asked[0][0])
        self.assertEqual(asked[0][1], Risk.RISKY)
        reg.execute("consulta_teste", {}, CancelToken(), origin="cloud:x", cloud_label="Agente X")
        self.assertEqual(len(asked), 1)                                                    # consulta READ segue livre


def _cloud(mode, *, brain=None, http="1", register=True):
    base = cfgmod.load()
    cfg = dataclasses.replace(base, paths=base.paths, brain=dataclasses.replace(
        base.brain, kind="cloud", agent="opencode", request_timeout_s=20, startup_timeout_s=10, **(brain or {})))
    bus = EventBus()
    events = []
    bus.subscribe(lambda ev: events.append((ev.kind, dict(ev.data))))
    asked = []
    reg = ToolRegistry(cfg, bus, None)
    if register:
        catalog.register_everything(reg, cfg)
    os.environ["FAKE_MODE"], os.environ["FAKE_HTTP"] = mode, http
    cb = CloudBrain(cfg, reg, bus, lambda t, r, c: (asked.append(t), True)[1], work_dir=TMP / "cwd")
    return cb, events, asked


class CloudBrainTests(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch("jarvis.brain.acp.agents.command_for", return_value=FAKE)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_ok_and_island_notice(self):
        cb, events, _ = _cloud("ok")
        try:
            self.assertEqual(cb.ask("oi", CancelToken()), "Olá, mundo.")
        finally:
            cb.close()
        steps = [(d["tool"], d["status"]) for k, d in events if k == "action_step"]
        self.assertEqual(steps, [("nuvem", "start"), ("nuvem", "ok")])           # aviso na Ilha a cada uso

    def test_no_login_becomes_unavailable(self):
        cb, _, _ = _cloud("auth")
        try:
            with self.assertRaises(CloudUnavailable) as cm:
                cb.ask("oi", CancelToken())
            self.assertIn("sem login", cm.exception.reason)
        finally:
            cb.close()

    def test_error_text_is_not_spoken(self):
        cb, _, _ = _cloud("err_text")
        try:
            with self.assertRaises(CloudUnavailable):
                cb.ask("oi", CancelToken())
        finally:
            cb.close()

    def test_timeout_then_unavailable(self):
        cb, _, _ = _cloud("hang")
        cb._cfg = dataclasses.replace(cb._cfg, brain=dataclasses.replace(cb._cfg.brain, request_timeout_s=10))
        cb._cfg.brain  # noqa: B018
        try:
            with mock.patch.object(acpclient, "CANCEL_GRACE_S", 1.0):
                tok = CancelToken()
                threading.Timer(0.5, lambda: tok.cancel("parar")).start()
                with self.assertRaises(Cancelled):
                    cb.ask("oi", tok)
        finally:
            cb.close()

    def test_restart_after_crash(self):
        cb, _, _ = _cloud("die")
        try:
            with self.assertRaises(CloudUnavailable):
                cb.ask("oi", CancelToken())
            os.environ["FAKE_MODE"] = "ok"                                       # o próximo processo nasce saudável
            self.assertEqual(cb.ask("oi", CancelToken()), "Olá, mundo.")
        finally:
            cb.close()

    def test_tools_reach_agent_through_mcp_and_audit_has_no_content(self):
        cb, _, asked = _cloud("tool")
        lines = []

        class H:
            level = 0

            def handle(self, rec):
                lines.append(rec.getMessage())
                return True

            def filter(self, rec):
                return True

        import logging
        lg = logging.getLogger("jarvis.audit")
        h = logging.Handler()
        h.emit = lambda rec: lines.append(rec.getMessage())
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        try:
            out = cb.ask("Que horas são? segredo-xyz", CancelToken())
        finally:
            cb.close()
            lg.removeHandler(h)
        self.assertIn("hora=", out)
        self.assertEqual(asked, [])                                               # hora_atual é consulta: sem confirmação
        joined = "\n".join(lines)
        self.assertIn('"event": "prompt"', joined)
        self.assertNotIn("segredo-xyz", joined)                                   # só tamanho e hash curto, nunca o texto

    def test_screen_and_files_hidden_without_consent_and_visible_with(self):
        cb, _, _ = _cloud("tool_screen")
        try:
            self.assertEqual(cb.ask("x", CancelToken()), "ver_tela=False ler_arquivo=False")
        finally:
            cb.close()
        cb, _, _ = _cloud("tool_screen", brain={"consent_screen": ("opencode",), "consent_files": ("opencode",)})
        try:
            self.assertEqual(cb.ask("x", CancelToken()), "ver_tela=True ler_arquivo=True")
        finally:
            cb.close()

    def test_use_tools_off_sends_no_mcp(self):
        cb, _, _ = _cloud("tool", brain={"use_tools": False})
        try:
            self.assertIn("sem mcp http", cb.ask("x", CancelToken()))
        finally:
            cb.close()

    def test_stdio_mcp_config_when_agent_lacks_http(self):
        cb, _, _ = _cloud("ok", http="0")
        try:
            cb.ask("x", CancelToken())
            cfg = cb._mcp_config(cb._client)
            self.assertEqual(cfg[0]["command"], sys.executable)
            self.assertIn("mcp_stdio_bridge.py", cfg[0]["args"][-1])
            self.assertNotIn("headers", cfg[0])
        finally:
            cb.close()


class FailureDetectionTests(unittest.TestCase):
    def test_account_model_and_login_errors_are_failures(self):
        from jarvis.brain.acp.agents import explain_failure as f
        self.assertEqual(f("Info: Remote index: queued x. Error: You have exceeded your monthly quota (Request I")[0], "quota")
        self.assertEqual(f("You've hit your usage limit. Upgrade to Plus to continue using Codex")[0], "quota")
        self.assertEqual(f("Warning: Model metadata for `gpt-6-sol` not found. The 'gpt-6-sol' model is not supported when using Codex with a ChatGPT account.")[0], "model")
        self.assertEqual(f('Error: Execution failed: Model "x" is not available.')[0], "model")
        self.assertEqual(f("Authentication required: provider authentication required")[0], "auth")
        self.assertEqual(f("This request requires more credits, or fewer max_tokens.")[0], "quota")

    def test_real_answers_are_not_failures(self):
        from jarvis.brain.acp.agents import explain_failure as f
        for ok in ("Agora são 20 horas e 41 minutos.", "Ocorreu um erro ao abrir o app, tente de novo.",
                   "Não consegui: o aplicativo não está disponível.", "Pronto, abri a calculadora.", ""):
            self.assertIsNone(f(ok), ok)

    def test_child_env_strips_parent_agent_session_and_points_claude_exe(self):
        from jarvis.brain.acp import agents
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "x", "CLAUDE_AGENT_SDK_VERSION": "9"}):
            env = agents.child_env("claude")
        for k in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_AGENT_SDK_VERSION"):
            self.assertIsNone(env[k])
        self.assertTrue(agents.child_env("opencode")["OPENCODE_CONFIG_CONTENT"].count("deny") >= 4)


class ModelRetryTests(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch("jarvis.brain.acp.agents.command_for", return_value=FAKE)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_model_error_switches_to_alternative_and_remembers(self):
        cb, _, _ = _cloud("model_switch")
        cb._cfg = dataclasses.replace(cb._cfg, paths=dataclasses.replace(cb._cfg.paths, data=TMP / "data1"))
        try:
            self.assertEqual(cb.ask("oi", CancelToken()), "Resposta boa.")
            self.assertEqual(cb.last_model, "opencode/big-pickle")
            self.assertEqual(json.loads((TMP / "data1" / "cloud_models.json").read_text())["opencode"], "opencode/big-pickle")
        finally:
            cb.close()

    def test_quota_error_becomes_unavailable_with_kind(self):
        cb, _, _ = _cloud("quota")
        try:
            with self.assertRaises(CloudUnavailable) as cm:
                cb.ask("oi", CancelToken())
            self.assertEqual(cm.exception.kind, "quota")
            self.assertNotIn("Request ID", cm.exception.reason)                  # o motivo nunca repete trechos do erro
        finally:
            cb.close()

    def test_pinned_model_is_never_replaced(self):
        cb, _, _ = _cloud("model_switch", brain={"models": {"opencode": "bad"}})
        try:
            with self.assertRaises(CloudUnavailable):
                cb.ask("oi", CancelToken())
        finally:
            cb.close()


class ActionModeTests(unittest.TestCase):
    def _brain(self, mode):
        cb, _, asked = _cloud("ok", brain={"action_modes": {"opencode": mode} if mode else {}})
        return cb, asked

    def test_default_is_confirm_and_unknown_falls_back(self):
        cb, _ = self._brain(None)
        self.assertEqual(cb.action_mode(), "confirm")

    def test_deny_hides_action_tools_and_refuses_calls(self):
        cb, asked = self._brain("deny")
        names = {t.name for t in cb._list_tools()}
        self.assertIn("hora_atual", names)
        self.assertNotIn("abrir_app", names)
        cb._cancel = CancelToken()
        res = cb._exec_tool("abrir_app", {"nome": "bloco de notas"})
        self.assertFalse(res.ok)
        self.assertEqual(asked, [])

    def test_confirm_always_asks_with_agent_name(self):
        cb, asked = self._brain("confirm")
        calls = []
        with mock.patch.object(cb._registry, "execute", side_effect=lambda *a, **k: (calls.append(k), ToolResult(True, "ok"))[1]):
            cb._cancel = CancelToken()
            cb._exec_tool("abrir_app", {"nome": "x"})
        self.assertTrue(calls[0]["cloud_force"])
        self.assertTrue(calls[0]["cloud_label"])

    def test_normal_follows_regular_permissions(self):
        cb, _ = self._brain("normal")
        calls = []
        with mock.patch.object(cb._registry, "execute", side_effect=lambda *a, **k: (calls.append(k), ToolResult(True, "ok"))[1]):
            cb._cancel = CancelToken()
            cb._exec_tool("abrir_app", {"nome": "x"})
        self.assertFalse(calls[0]["cloud_force"])
        self.assertTrue(calls[0]["tainted"])                                      # continua marcado como vindo de fora


class AgentFallbackTests(unittest.TestCase):
    def _agent(self, cloud, fallback):
        a = Agent.__new__(Agent)
        base = cfgmod.load()
        a._cfg = dataclasses.replace(base, brain=dataclasses.replace(base.brain, kind="cloud", fallback_local=fallback))
        a._cloud = cloud
        a._bus = EventBus()
        self.notes = []
        a._bus.subscribe(lambda ev: self.notes.append(ev.kind), kind="notice")
        sessions = mock.Mock()
        sessions.ensure_active.return_value = (mock.Mock(id="s"), False)
        a._memory = mock.Mock(sessions=sessions)
        self.sessions = sessions
        return a

    def test_fallback_to_local_when_cloud_fails(self):
        cloud = mock.Mock()
        cloud.ask.side_effect = CloudUnavailable("sem internet")
        a = self._agent(cloud, True)
        self.assertIsNone(a._handle_cloud("oi", CancelToken(), lambda s: None, time.monotonic()))
        time.sleep(0.2)
        self.assertIn("notice", self.notes)

    def test_no_fallback_speaks_a_clear_failure(self):
        cloud = mock.Mock()
        cloud.ask.side_effect = CloudUnavailable("sem internet")
        a = self._agent(cloud, False)
        said = []
        res = a._handle_cloud("oi", CancelToken(), said.append, time.monotonic())
        self.assertIn("plano B local está desligado", res.text)
        self.assertTrue(said)

    def test_success_speaks_and_stores_as_untrusted(self):
        cloud = mock.Mock()
        cloud.ask.return_value = "Tudo certo. Feito."
        a = self._agent(cloud, True)
        said = []
        res = a._handle_cloud("oi", CancelToken(), said.append, time.monotonic())
        self.assertEqual(res.text, "Tudo certo. Feito.")
        self.assertEqual(" ".join(said), "Tudo certo. Feito.")
        self.assertTrue(self.sessions.append.call_args_list[-1].kwargs.get("untrusted"))


class ConfigTests(unittest.TestCase):
    def test_default_is_local_and_schema_covers_brain(self):
        self.assertEqual(cfgmod.load().brain.kind, "local")
        self.assertEqual(schema.uncovered_fields(), [])
        for k in ("kind", "agent", "fallback_local", "use_tools", "builtin_tools", "consent_screen", "consent_memory",
                  "consent_files", "request_timeout_s", "startup_timeout_s"):
            self.assertIn(f"brain.{k}", schema.BY_KEY)

    def test_validation(self):
        for bad in ({"kind": "x"}, {"agent": "x"}, {"builtin_tools": "yes"}, {"request_timeout_s": 1}, {"consent_screen": ["x"]}):
            with self.assertRaises(cfgmod.ConfigError):
                cfgmod.from_dict({"brain": bad})
        cfgmod.from_dict({"brain": {"kind": "cloud", "agent": "claude", "consent_screen": ["claude"]}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
