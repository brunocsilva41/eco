"""Testes da etapa "Preparar o computador" (setup/prereqs.py + setup/pages_prepare.py). Sem rede e sem instalar nada.

    venv\\Scripts\\python.exe -I -X utf8 -W error tests\\test_prepare.py
O download REAL do Visual C++ da Microsoft e a assinatura real ficam em tests\\prepare_live_proof.py.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["JARVIS_TEST_INSTANCE"] = "-prep"

from jarvis.setup import prereqs as P  # noqa: E402
from jarvis.setup.manifest import FileEntry, Manifest, Package, Component  # noqa: E402


class FakeResp:
    def __init__(self, data: bytes, status: int = 200, total: int | None = None, start: int = 0) -> None:
        self._b = io.BytesIO(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}
        if status == 206:
            self.headers["Content-Range"] = f"bytes {start}-{start + len(data) - 1}/{total}"

    def read(self, n=-1):
        return self._b.read(n)

    def close(self):
        pass


def make_opener(blob: bytes, honor_range=True, fail_first=0, record=None):
    state = {"calls": 0}

    def opener(url, hosts, headers, timeout=30.0):
        state["calls"] += 1
        if record is not None:
            record.append(dict(headers))
        if state["calls"] <= fail_first:
            raise urllib.error.URLError("falha de rede simulada")
        rng = headers.get("Range")
        if rng and honor_range:
            start = int(rng.split("=")[1].split("-")[0])
            return FakeResp(blob[start:], 206, len(blob), start)
        return FakeResp(blob)
    return opener


class Checks(unittest.TestCase):
    def test_vcruntime_ausente_e_presente(self):
        with tempfile.TemporaryDirectory() as d:
            s = Path(d)
            it = P.check_vcruntime(s)
            self.assertEqual((it.status, it.action), ("fail", "install_vcredist"))
            for n in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
                (s / n).write_bytes(b"x")
            it = P.check_vcruntime(s)
            self.assertEqual((it.status, it.action), ("ok", ""))

    def test_internet_total_parcial_ok(self):
        ok = lambda h: (True, "")                       # noqa: E731
        bad = lambda h: (False, "sem rota")             # noqa: E731
        self.assertEqual(P.check_internet(["a.com", "b.com"], ok).status, "ok")
        self.assertEqual(P.check_internet(["a.com", "b.com"], bad).status, "fail")
        mix = lambda h: (h == "a.com", "falhou")        # noqa: E731
        self.assertEqual(P.check_internet(["a.com", "b.com"], mix).status, "warn")

    def test_pastas_sem_permissao(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(P.check_folders(Path(d)).status, "ok")
            with mock.patch.object(Path, "mkdir", side_effect=PermissionError(13, "Acesso negado")):
                it = P.check_folders(Path(d) / "novo")
            self.assertEqual(it.status, "fail")

    def test_modelos_faltando(self):
        with tempfile.TemporaryDirectory() as d:
            entry = FileEntry("models/x/a.bin", 10, "0" * 64, ("https://huggingface.co/x",))
            pkg = Package("p", "P", "MIT", "", "", (entry,))
            man = Manifest({"c": Component("c", "C", "d", ("p",))}, {"p": pkg}, ())
            it = P.check_models(man, ["c"], Path(d))
            self.assertEqual((it.status, it.action), ("fail", "download_models"))
            (Path(d) / "models" / "x").mkdir(parents=True)
            (Path(d) / "models" / "x" / "a.bin").write_bytes(b"0123456789")
            self.assertEqual(P.check_models(man, ["c"], Path(d)).status, "ok")

    def test_sugestoes_ollama_por_memoria(self):
        self.assertEqual([m.tag for m in P.suggest_ollama_models(8192, 16)][-1], "llama3.1:8b")      # 8 GB de vídeo: cabe até 8B Q4
        self.assertEqual(P.recommended_ollama_model(8192, 16).tag, "gemma3:4b")                      # recomendado = equilibrado, com folga
        self.assertEqual(P.recommended_ollama_model(4096, 16).tag, "llama3.2:3b")
        self.assertEqual([m.tag for m in P.suggest_ollama_models(4096, 16)], ["llama3.2:3b", "gemma3:4b"])
        self.assertEqual([m.tag for m in P.suggest_ollama_models(0, 8)], ["llama3.2:3b"])             # sem GPU: poucos GB de RAM
        self.assertTrue(all(m.approx_gb <= 8192 / 1024 * 0.85 for m in P.suggest_ollama_models(8192, 16)))

    def test_vram_do_item(self):
        it = P.Item("gpu", "x", "ok", "AMD Radeon RX 580, 8.0 GB de memória de vídeo")
        self.assertEqual(P.vram_from_items([it]), 8192)

    def test_driver_url(self):
        self.assertIn("amd.com", P.gpu_driver_url("AMD Radeon RX 580"))
        self.assertIn("nvidia.com", P.gpu_driver_url("NVIDIA GeForce GTX 1060"))
        self.assertIn("intel.com", P.gpu_driver_url("Intel(R) UHD Graphics"))

    def test_relatorio(self):
        with tempfile.TemporaryDirectory() as d:
            p = P.write_report(Path(d), [P.Item("a", "A", "ok", "d")], ["evento"])
            self.assertTrue(p.is_file())
            self.assertIn("evento", p.read_text(encoding="utf-8"))


class Download(unittest.TestCase):
    spec = P.Official("t", "Teste", "https://aka.ms/x.exe", ("aka.ms",), "x.exe", "Microsoft", (), False, 10)
    blob = bytes(range(256)) * 4096                                              # 1 MiB

    def test_lista_de_hosts_e_https(self):
        for url, kind in (("http://aka.ms/x", "https"), ("https://evil.example/x", "host")):
            with self.assertRaises(P.PrepError) as cm:
                P._open(url, ("aka.ms",), {})
            self.assertEqual(cm.exception.kind, kind)
        self.assertTrue(P.host_allowed("download.microsoft.com", ("microsoft.com",)))
        self.assertFalse(P.host_allowed("evilmicrosoft.com", ("microsoft.com",)))

    def test_redirecionamento_para_host_ruim_e_recusado(self):
        h = P._AllowRedirect(("aka.ms",))
        with self.assertRaises(P.PrepError) as cm:
            h.redirect_request(mock.Mock(), None, 302, "x", {}, "https://evil.example/a.exe")
        self.assertEqual(cm.exception.kind, "host")
        with self.assertRaises(P.PrepError) as cm:
            h.redirect_request(mock.Mock(), None, 302, "x", {}, "http://aka.ms/a.exe")
        self.assertEqual(cm.exception.kind, "https")

    def test_download_completo(self):
        with tempfile.TemporaryDirectory() as d:
            got = []
            path = P.download_official(self.spec, Path(d), lambda a, b: got.append((a, b)), opener=make_opener(self.blob))
            self.assertEqual(path.read_bytes(), self.blob)
            self.assertFalse((Path(d) / "x.exe.part").exists())
            self.assertEqual(got[-1][0], len(self.blob))

    def test_retomada_com_range(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.exe.part").write_bytes(self.blob[:300_000])
            rec: list[dict] = []
            path = P.download_official(self.spec, Path(d), opener=make_opener(self.blob, record=rec))
            self.assertEqual(path.read_bytes(), self.blob)
            self.assertEqual(rec[0].get("Range"), "bytes=300000-")

    def test_servidor_que_ignora_range_recomeca(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.exe.part").write_bytes(b"lixo" * 1000)
            path = P.download_official(self.spec, Path(d), opener=make_opener(self.blob, honor_range=False))
            self.assertEqual(path.read_bytes(), self.blob)

    def test_falha_de_rede_tenta_de_novo(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("time.sleep"):
            path = P.download_official(self.spec, Path(d), opener=make_opener(self.blob, fail_first=2))
            self.assertEqual(path.read_bytes(), self.blob)
        with tempfile.TemporaryDirectory() as d, mock.patch("time.sleep"):
            with self.assertRaises(P.PrepError) as cm:
                P.download_official(self.spec, Path(d), opener=make_opener(self.blob, fail_first=99))
            self.assertEqual(cm.exception.kind, "net")

    def test_cancelar_guarda_o_parcial(self):
        with tempfile.TemporaryDirectory() as d:
            ev = threading.Event()
            ev.set()
            with self.assertRaises(P.PrepError) as cm:
                P.download_official(self.spec, Path(d), cancel=ev, opener=make_opener(self.blob))
            self.assertEqual(cm.exception.kind, "cancelled")

    def test_assinatura_invalida_apaga_o_arquivo(self):
        with tempfile.TemporaryDirectory() as d:
            bad = P.Signature(False, "HashMismatch", "CN=X", "", "")
            with mock.patch.object(P, "verify_authenticode", return_value=bad):
                with self.assertRaises(P.PrepError) as cm:
                    P.fetch_verified(self.spec, Path(d), opener=make_opener(self.blob))
            self.assertEqual(cm.exception.kind, "signature")
            self.assertFalse((Path(d) / "x.exe").exists(), "instalador sem assinatura válida precisa ser apagado")

    def test_assinatura_valida_devolve_o_arquivo(self):
        with tempfile.TemporaryDirectory() as d:
            ok = P.Signature(True, "Valid", "CN=Microsoft Corporation", "AB", "")
            with mock.patch.object(P, "verify_authenticode", return_value=ok):
                path, sig = P.fetch_verified(self.spec, Path(d), opener=make_opener(self.blob))
            self.assertTrue(path.is_file() and sig.valid)

    def test_assinatura_real_do_windows(self):
        nb = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
        if not nb.is_file():
            self.skipTest("sem notepad.exe")
        self.assertTrue(P.verify_authenticode(nb, "Microsoft").valid)
        self.assertFalse(P.verify_authenticode(nb, "Fabricante Qualquer").valid)
        with tempfile.TemporaryDirectory() as d:
            txt = Path(d) / "a.exe"
            txt.write_bytes(b"MZ nao assinado")
            self.assertFalse(P.verify_authenticode(txt).valid)


class OllamaPull(unittest.TestCase):
    def test_nome_de_modelo_invalido(self):
        for bad in ("", "a b", "x/../y", 'a"b', "x" * 100):
            with self.assertRaises(P.PrepError):
                P.ollama_pull(bad)


class Interface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from jarvis.ui.theme import ThemeManager
        ThemeManager.instance().apply(cls.app)

    def _page(self, items, confirm: bool, runner=None):
        from jarvis.setup.pages_prepare import PreparePage
        from jarvis.setup.wizard import build_ctx
        ctx = build_ctx(False, demo=True)
        if runner:
            ctx.extra["prep_run_installer"] = runner
        page = PreparePage(ctx)
        page.setProperty("autoconfirm", confirm)
        page.show()
        page.show_items(items)
        return page

    def _pump(self, page, cond, secs=8.0):
        t = time.monotonic()
        while time.monotonic() - t < secs and not cond():
            self.app.processEvents()
            time.sleep(0.01)

    def _click(self, btn):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(btn.width() // 2, btn.height() // 2))

    ITEMS = [P.Item("vcruntime", "Biblioteca do Visual C++", "fail", "faltam", "", "install_vcredist", "Baixar e instalar"),
             P.Item("ollama", "Ollama (opcional)", "info", "não instalado", "", "install_ollama", "Baixar do site oficial", True)]

    def test_linhas_e_botoes(self):
        page = self._page(self.ITEMS, True)
        from jarvis.setup.pages_prepare import PrepRow
        rows = page.findChildren(PrepRow)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.button is not None for r in rows))
        self.assertTrue(page.btn_all.isEnabled())                 # há item com erro
        page.show_items([P.Item("a", "A", "ok", "bem")])
        self.assertFalse(page.btn_all.isEnabled())

    def test_instalar_com_confirmacao_roda_o_instalador_oficial(self):
        calls = []
        tmp = Path(tempfile.mkdtemp()) / "vc_redist.x64.exe"
        tmp.write_bytes(b"MZ")
        ok = P.Signature(True, "Valid", "CN=Microsoft Windows, O=Microsoft Corporation", "AB", "")
        page = self._page(self.ITEMS, True, runner=lambda path, args, elevate: calls.append((path, args, elevate)) or 0)
        with mock.patch.object(P, "fetch_verified", return_value=(tmp, ok)), mock.patch.object(page, "recheck") as rc:
            from jarvis.setup.pages_prepare import PrepRow
            row = [r for r in page.findChildren(PrepRow) if r.item.key == "vcruntime"][0]
            self._click(row.button)
            self._pump(page, lambda: bool(calls))
            self._pump(page, lambda: rc.called)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], tmp)
        self.assertTrue(calls[0][2], "o Visual C++ exige administrador (UAC)")
        self.assertIn("/quiet", calls[0][1])

    def test_recusar_a_confirmacao_nao_baixa_nem_instala(self):
        calls = []
        page = self._page(self.ITEMS, False, runner=lambda *a, **k: calls.append(1) or 0)
        from jarvis.setup.pages_prepare import PrepRow
        with mock.patch.object(P, "fetch_verified") as fv:
            self._click([r for r in page.findChildren(PrepRow) if r.item.key == "vcruntime"][0].button)
            self._pump(page, lambda: False, 0.4)
            fv.assert_not_called()
        self.assertEqual(calls, [])

    def test_assinatura_invalida_mostra_erro_e_nao_instala(self):
        calls = []
        page = self._page(self.ITEMS, True, runner=lambda *a, **k: calls.append(1) or 0)
        from jarvis.setup.pages_prepare import PrepRow
        err = P.PrepError("signature", "A assinatura digital do instalador NÃO é válida (HashMismatch).")
        with mock.patch.object(P, "fetch_verified", side_effect=err):
            self._click([r for r in page.findChildren(PrepRow) if r.item.key == "vcruntime"][0].button)
            self._pump(page, lambda: not page._busy and page.msg_host.count() > 0)
        self.assertEqual(calls, [])
        from jarvis.ui.kit.feedback import InlineBanner
        banners = page.findChildren(InlineBanner)
        self.assertTrue(banners, "deveria mostrar o aviso de assinatura inválida")
        self.assertFalse(page._busy)

    def test_uac_negado_vira_aviso(self):
        tmp = Path(tempfile.mkdtemp()) / "vc.exe"
        tmp.write_bytes(b"MZ")
        ok = P.Signature(True, "Valid", "CN=Microsoft Corporation", "AB", "")

        def deny(*a, **k):
            raise P.PrepError("cancelled", "Você não deu a permissão do Windows. Nada foi instalado.")
        page = self._page(self.ITEMS, True, runner=deny)
        from jarvis.setup.pages_prepare import PrepRow
        with mock.patch.object(P, "fetch_verified", return_value=(tmp, ok)):
            self._click([r for r in page.findChildren(PrepRow) if r.item.key == "vcruntime"][0].button)
            self._pump(page, lambda: any("permissão" in (getattr(w, "text", lambda: "")() or "") for w in page.findChildren(type(page.prog_title))))
        self.assertFalse(page._busy)

    def test_sair_com_pendencia_pede_confirmacao(self):
        page = self._page(self.ITEMS, False)
        self.assertFalse(page.on_leave(True))                      # recusou: não sai
        page.setProperty("autoconfirm", True)
        self.assertTrue(page.on_leave(True))
        page.show_items([P.Item("models", "Modelos", "fail", "faltam", "", "download_models", "Baixar")])
        page.setProperty("autoconfirm", False)
        self.assertTrue(page.on_leave(True), "modelos faltando têm a própria etapa: não bloqueia aqui")

    def test_etapa_registrada_no_assistente(self):
        from jarvis.setup.state import STEPS
        from jarvis.setup import strings as S
        self.assertEqual(STEPS.index("prepare"), STEPS.index("hardware") + 1)
        self.assertIn("prepare", S.STEP_TITLES)
        self.assertIn("prepare", S.STEP_SUBTITLES)


if __name__ == "__main__":
    unittest.main()
