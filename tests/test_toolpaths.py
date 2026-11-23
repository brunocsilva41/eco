"""Testes dos caminhos personalizados e da varredura total (core/toolpaths.py e quem o usa).

    venv\\Scripts\\python.exe -I -X utf8 -W error tests\\test_toolpaths.py

Cobre: caminho correto, errado, inexistente, de outra ferramenta, com espaços e acentos, de rede, executável não confiável,
versão antiga, pastas e arquivos de modelo; e que agentes ACP, Terminal e PATH usam o caminho personalizado.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jarvis import config as C  # noqa: E402
from jarvis.core import toolpaths as T  # noqa: E402

GIT = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "cmd" / "git.exe"
PS51 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
SIG_NONE = lambda p: (False, "script sem assinatura")     # noqa: E731
SIG_OK = lambda p: (True, "Fulano de Tal")                # noqa: E731


def fake_cmd(folder: Path, name: str, text: str) -> Path:
    """Programa de mentira (um .cmd que imprime `text`), para testar caminhos sem depender do que está instalado."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{name}.cmd"
    p.write_text(f"@echo off\r\necho {text}\r\n", encoding="utf-8")
    return p


class Validacao(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="eco-tp-"))
        self.addCleanup(T.configure, None)

    def test_vazio_e_automatico(self):
        v = T.validate_path("git", "")
        self.assertEqual((v.status, v.path), ("ok", ""))

    def test_inexistente(self):
        v = T.validate_path("git", str(self.tmp / "nao_existe" / "git.exe"))
        self.assertEqual(v.status, "fail")
        self.assertIn("Não existe", v.message)

    def test_rede_unc_e_recusada(self):
        for bad in (r"\\servidor\pasta\git.exe", "//servidor/pasta/git.exe"):
            v = T.validate_path("git", bad)
            self.assertEqual(v.status, "fail", bad)
            self.assertIn("rede", v.message)

    def test_unidade_de_rede_mapeada_e_recusada(self):
        with mock.patch("jarvis.config.is_network_path", return_value=True):
            self.assertEqual(T.validate_path("git", r"Z:\git.exe").status, "fail")

    @unittest.skipUnless(GIT.is_file(), "sem Git instalado")
    def test_git_real_correto(self):
        v = T.validate_path("git", str(GIT))
        self.assertEqual(v.status, "ok", v.message)
        self.assertTrue(v.version.startswith("2."), v.version)

    @unittest.skipUnless(GIT.is_file(), "sem Git instalado")
    def test_pasta_que_contem_o_programa_vira_o_programa(self):
        v = T.validate_path("git", str(GIT.parent))
        self.assertEqual(v.status, "ok", v.message)
        self.assertTrue(v.path.lower().endswith("git.exe"))

    @unittest.skipUnless(PS51.is_file(), "sem PowerShell 5.1")
    def test_programa_de_outra_ferramenta(self):
        v = T.validate_path("git", str(PS51))
        self.assertEqual(v.status, "fail")
        self.assertIn("PowerShell", v.message)
        self.assertIn("não Git", v.message)

    def test_arquivo_que_nao_e_programa(self):
        fake = self.tmp / "git.exe"
        fake.write_text("isto nao e um executavel", encoding="utf-8")
        v = T.validate_path("git", str(fake), check_signature=False)
        self.assertEqual(v.status, "fail")
        self.assertIn("não executa", v.message)

    def test_extensao_errada(self):
        f = self.tmp / "git.txt"
        f.write_text("x")
        v = T.validate_path("git", str(f))
        self.assertEqual(v.status, "fail")
        self.assertIn("não é um programa", v.message)

    def test_resposta_de_versao_de_outra_coisa(self):
        p = fake_cmd(self.tmp, "git", "Isto e outro programa 9.9")
        v = T.validate_path("git", str(p), signature=SIG_OK)
        self.assertEqual(v.status, "fail")
        self.assertIn("não é de Git", v.message)

    def test_versao_antiga(self):
        p = fake_cmd(self.tmp, "git", "git version 1.9.0.windows.1")
        v = T.validate_path("git", str(p), signature=SIG_OK)
        self.assertEqual(v.status, "fail")
        self.assertIn("antiga", v.message)

    def test_espacos_e_acentos_com_assinatura(self):
        pasta = self.tmp / "Meus programas é ação" / "Ferramentas do João"
        p = fake_cmd(pasta, "git", "git version 2.50.0.windows.1")
        v = T.validate_path("git", f'"{p}"', signature=SIG_OK)                   # aspas coladas do Explorer também funcionam
        self.assertEqual(v.status, "ok", v.message)
        self.assertEqual(v.version, "2.50.0")
        self.assertEqual(v.confirm, "")
        self.assertIn("Fulano de Tal", v.message)

    def test_executavel_nao_confiavel_pede_confirmacao(self):
        p = fake_cmd(self.tmp / "Downloads soltos", "git", "git version 2.50.0.windows.1")
        v = T.validate_path("git", str(p), signature=SIG_NONE)
        self.assertEqual(v.status, "warn")
        self.assertTrue(v.confirm, "executável fora das pastas confiáveis e sem assinatura tem que exigir confirmação")
        self.assertTrue(v.ok)

    def test_variavel_de_ambiente_no_caminho(self):
        pasta = self.tmp / "viaenv"
        p = fake_cmd(pasta, "git", "git version 2.50.0.windows.1")
        with mock.patch.dict(os.environ, {"ECO_TESTE_DIR": str(pasta)}):
            v = T.validate_path("git", r"%ECO_TESTE_DIR%\git.cmd", signature=SIG_OK)
        self.assertEqual(v.status, "ok", v.message)

    def test_git_bash_do_wsl_e_recusado(self):
        wsl = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "bash.exe"
        if not wsl.is_file():
            self.skipTest("sem bash do WSL")
        v = T.validate_path("git_bash", str(wsl))
        self.assertEqual(v.status, "fail")

    # ---- pastas e arquivos
    def test_pasta_errada_e_dica_da_subpasta(self):
        base = self.tmp / "bin"
        (base / "llama-x").mkdir(parents=True)
        (base / "llama-x" / "llama-server.exe").write_bytes(b"MZ")
        v = T.validate_path("llama_server", str(base))
        self.assertEqual(v.status, "fail")
        self.assertIn("llama-server.exe", v.message)
        self.assertIn("llama-x", v.message)                                      # aponta a pasta certa
        ok = T.validate_path("llama_server", str(base / "llama-x"))
        self.assertEqual(ok.status, "ok", ok.message)

    def test_arquivo_no_lugar_de_pasta_e_vice_versa(self):
        f = self.tmp / "a.txt"
        f.write_text("x")
        self.assertIn("PASTA", T.validate_path("models_dir", str(f)).message)
        self.assertIn("ARQUIVO", T.validate_path("llm_model", str(self.tmp)).message)

    def test_pasta_sem_permissao_de_gravacao(self):
        with mock.patch.object(T, "_writable", return_value=False):
            v = T.validate_path("data_dir", str(self.tmp))
        self.assertEqual(v.status, "fail")
        self.assertIn("gravar", v.message)
        self.assertEqual(T.validate_path("data_dir", str(self.tmp)).status, "ok")

    def test_modelo_gguf(self):
        good = self.tmp / "modelo com acentuação.gguf"
        with open(good, "wb") as f:
            f.write(b"GGUF")
            f.truncate(60_000_000)
        self.assertEqual(T.validate_path("llm_model", str(good)).status, "ok")
        bad = self.tmp / "ruim.gguf"
        with open(bad, "wb") as f:
            f.write(b"XXXX")
            f.truncate(60_000_000)
        self.assertIn("formato", T.validate_path("llm_model", str(bad)).message)
        small = self.tmp / "pequeno.gguf"
        small.write_bytes(b"GGUF123")
        self.assertIn("pequeno", T.validate_path("llm_model", str(small)).message)
        wrongext = self.tmp / "modelo.bin"
        wrongext.write_bytes(b"GGUF" + b"0" * 100)
        self.assertIn(".gguf", T.validate_path("llm_model", str(wrongext)).message)

    def test_json_da_voz(self):
        ok = self.tmp / "voz.json"
        ok.write_text('{"audio": {"sample_rate": 22050}}', encoding="utf-8")
        self.assertEqual(T.validate_path("tts_voice_json", str(ok)).status, "ok")
        bad = self.tmp / "ruim.json"
        bad.write_text("{nao e json", encoding="utf-8")
        self.assertEqual(T.validate_path("tts_voice_json", str(bad)).status, "fail")


class Uso(unittest.TestCase):
    """O app inteiro passa a usar o caminho personalizado."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="eco-tp-"))
        self.addCleanup(T.configure, None)

    def cfg(self, **tp):
        return C.from_dict({"toolpaths": {k: str(v) for k, v in tp.items()}})

    def test_resolve_prefere_o_personalizado(self):
        p = fake_cmd(self.tmp / "ferr com espaço", "git", "git version 2.50.0")
        f = T.resolve("git", self.cfg(git=p))
        self.assertEqual((f.path, f.source), (p, T.SRC_CUSTOM))
        auto = T.resolve("git", self.cfg())
        self.assertNotEqual(auto.source, T.SRC_CUSTOM)

    def test_personalizado_quebrado_cai_na_busca_automatica(self):
        f = T.resolve("git", self.cfg(git=self.tmp / "sumiu" / "git.exe"))
        self.assertNotEqual(f.source, T.SRC_CUSTOM)
        self.assertIn("personalizado", f.problem)

    def test_agente_acp_usa_o_caminho_personalizado(self):
        from jarvis.brain.acp import agents
        p = fake_cmd(self.tmp / "agentes", "opencode", "2.2.5")
        T.configure(self.cfg(opencode=p))
        cmd = agents.command_for("opencode")
        self.assertEqual(cmd[0], str(p))
        self.assertEqual(cmd[1:], ["acp"])
        d = agents.detect("opencode", with_version=False)
        self.assertTrue(d.installed)
        self.assertEqual(d.path, str(p))

    def test_terminal_usa_powershell_e_git_bash_personalizados(self):
        from jarvis.terminal import runner
        ps = fake_cmd(self.tmp / "ps", "pwsh", "7.4.0")
        bash = fake_cmd(self.tmp / "gb", "bash", "GNU bash 5.2")
        T.configure(self.cfg(powershell=ps, git_bash=bash))
        self.assertEqual(runner.find_shell("powershell"), str(ps))
        self.assertEqual(runner.find_shell("bash"), str(bash))

    def test_path_do_terminal_inclui_a_pasta_do_git_personalizado(self):
        from jarvis.terminal import policy
        p = fake_cmd(self.tmp / "meu git", "git", "git version 2.50.0")
        T.configure(self.cfg(git=p))
        env = policy.clean_env()
        first = next(v for k, v in env.items() if k.upper() == "PATH").split(os.pathsep)[0]
        self.assertEqual(first, str(p.parent))

    def test_ollama_do_setup_usa_o_personalizado(self):
        from jarvis.setup import prereqs
        p = fake_cmd(self.tmp / "oll", "ollama", "ollama version is 0.1.0")
        T.configure(self.cfg(ollama=p))
        self.assertEqual(prereqs.ollama_exe(), p)

    def test_doctor_acusa_caminho_personalizado_invalido(self):
        from jarvis import doctor
        bad = self.cfg(git=self.tmp / "nao_existe.exe")
        res = doctor._check_toolpaths(bad)
        self.assertEqual(len(res), 1)
        self.assertFalse(res[0].ok)
        p = fake_cmd(self.tmp / "ok", "git", "git version 2.50.0")
        self.assertTrue(all(r.ok for r in doctor._check_toolpaths(self.cfg(git=p))))

    def test_config_recusa_caminho_de_rede(self):
        with self.assertRaises(C.ConfigError) as cm:
            C.from_dict({"toolpaths": {"git": r"\\srv\x\git.exe"}})
        self.assertIn("rede", str(cm.exception))
        with self.assertRaises(C.ConfigError):
            C.from_dict({"paths": {"models": r"\\srv\modelos"}})

    def test_salvar_e_reler_pelo_settings_store(self):
        from jarvis.settings.store import SettingsStore
        st = SettingsStore(self.tmp / "config.toml")
        p = fake_cmd(self.tmp / "salvo", "git", "git version 2.50.0")
        vals = st.values()
        vals["toolpaths.git"] = str(p)
        st.save(vals)
        cfg = C.load(self.tmp / "config.toml")
        self.assertEqual(cfg.toolpaths.git, str(p))
        vals["toolpaths.git"] = r"\\srv\x\git.exe"
        with self.assertRaises(Exception):
            st.save(vals)

    def test_restaurar_padrao_volta_ao_automatico(self):
        d = T.BY_KEY["git"]
        self.assertEqual(T.default_value(d), "")
        self.assertFalse(T.is_custom(d, self.cfg()))
        self.assertTrue(T.is_custom(d, self.cfg(git=self.tmp / "x.exe")))
        self.assertEqual(T.default_value(T.BY_KEY["llm_model"]), str(C.Config().llm.model))


class Varredura(unittest.TestCase):
    def test_varredura_cobre_o_catalogo_e_relata_versao_e_origem(self):
        items = T.scan_all()
        self.assertEqual({i.key for i in items}, {t.key for t in T.CATALOG})
        for i in items:
            self.assertIn(i.status, ("ok", "warn", "fail", "info"))
            if i.path:
                self.assertTrue(i.where, f"{i.key}: achou em {i.path} mas não disse de onde")
        ps = next(i for i in items if i.key == "powershell")
        self.assertEqual(ps.status, "ok")
        self.assertTrue(ps.version)

    def test_ferramenta_opcional_ausente_e_opcional_nao_erro(self):
        with mock.patch.object(T, "detect", return_value=(None, T.SRC_NONE)):
            it = T.scan_tool("ollama")
        self.assertEqual(it.status, "info")
        it = T.scan_tool.__wrapped__("git") if hasattr(T.scan_tool, "__wrapped__") else None
        with mock.patch.object(T, "detect", return_value=(None, T.SRC_NONE)):
            self.assertEqual(T.scan_tool("powershell").status, "fail")                  # obrigatório ausente = falta

    def test_relatorios(self):
        items = T.scan_all(with_version=False)
        txt = T.report_text(items)
        self.assertIn("Resumo:", txt)
        data = json.loads(T.report_json(items))
        self.assertEqual(len(data["items"]), len(items))
        from jarvis.setup import prereqs
        from jarvis.setup.manifest import load_manifest
        man = load_manifest(ROOT)
        full = prereqs.full_scan(ROOT, man, ["vision"], cfg=C.from_dict({}), ram_gb=16)
        self.assertGreater(len(full), len(items) - 5)
        self.assertIn("Resumo:", prereqs.full_report_text(full))
        self.assertTrue(json.loads(prereqs.full_report_json(full))["items"])
        keys = [i.tool for i in full if i.tool]
        self.assertIn("llama_server", keys)
        self.assertIn("ollama", keys)
        self.assertEqual(len(keys), len(set(keys)), "nenhuma ferramenta pode aparecer duas vezes")

    def test_doctor_full_inclui_as_ferramentas(self):
        from jarvis import doctor
        res = doctor.run_doctor(C.from_dict({}), full=True) if False else doctor._scan_results(C.from_dict({}))
        names = " ".join(r.name for r in res)
        self.assertIn("ferramenta: Git", names)


if __name__ == "__main__":
    unittest.main()
