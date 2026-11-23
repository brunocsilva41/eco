"""Testes da atualização automática (sem rede): versões, hash, download com retomada, estado e agenda.

Rodar: python tests/test_updates.py   (ou pytest)."""
from __future__ import annotations

import dataclasses
import hashlib
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jarvis import config as cfgmod                    # noqa: E402
from jarvis.core import updater, updates                 # noqa: E402
from jarvis.core.updates import Asset, UpdateInfo        # noqa: E402
from jarvis.settings import schema                       # noqa: E402

PAYLOAD = bytes(range(256)) * 4096                      # 1 MiB
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _info(**kw) -> UpdateInfo:
    base = dict(current="0.1.0", latest="0.2.0", available=True, via="public",
                installer=Asset("Eco-Setup-0.2.0.exe", len(PAYLOAD), "https://api.github.com/x", "https://github.com/x"),
                body_sha256=SHA)
    base.update(kw)
    return UpdateInfo(**base)


def test_versions():
    assert updates.is_newer("0.2.0", "0.1.9") and updates.is_newer("v1.0.0", "0.9.9")
    assert not updates.is_newer("0.1.4", "0.1.4")
    assert updates.is_newer("0.2.0", "0.2.0-rc1") and not updates.is_newer("0.2.0-rc1", "0.2.0")
    assert updates.is_newer("0.10.0", "0.9.0")


def test_hash_sources_must_agree():
    assert updater.expected_sha256(_info()) == SHA
    try:
        updater.expected_sha256(_info(installer=Asset("Eco-Setup-0.2.0.exe", 1, "", "https://x", "sha256:" + "0" * 64)))
    except updater.UpdateError as e:
        assert "não concordam" in str(e)
    else:
        raise AssertionError("hashes divergentes deveriam ser recusados")
    try:
        updater.expected_sha256(_info(body_sha256=""))
    except updater.UpdateError as e:
        assert "SHA-256" in str(e)
    else:
        raise AssertionError("sem hash publicado deveria recusar")


def _fake_stream(payload: bytes, stop_at: int | None = None):
    def stream(asset, info, start, cancel):
        data = payload[start:]
        step = 100_000
        sent = 0
        for i in range(0, len(data), step):
            if stop_at is not None and start + sent >= stop_at:
                raise updater.UpdateError("sem conexão com a internet (o download pode ser retomado depois)")
            chunk = data[i:i + step]
            sent += len(chunk)
            yield chunk
    return stream


def test_download_resume_and_verify():
    orig = updater._stream
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        try:
            updater._stream = _fake_stream(PAYLOAD, stop_at=300_000)
            try:
                updater.download(_info(), d)
            except updater.UpdateError:
                pass
            part = d / "Eco-Setup-0.2.0.exe.part"
            assert 0 < part.stat().st_size < len(PAYLOAD)
            seen: list[int] = []
            updater._stream = _fake_stream(PAYLOAD)
            out = updater.download(_info(), d, lambda a, b: seen.append(a))
            assert out.read_bytes() == PAYLOAD and not part.exists() and seen and seen[0] > 300_000
            # segunda chamada reaproveita o arquivo já verificado
            assert updater.download(_info(), d) == out
        finally:
            updater._stream = orig


def test_download_bad_hash_is_discarded():
    orig = updater._stream
    with tempfile.TemporaryDirectory() as d:
        try:
            updater._stream = _fake_stream(PAYLOAD[:-1] + b"X")
            try:
                updater.download(_info(), Path(d))
            except updater.UpdateError as e:
                assert "NÃO confere" in str(e)
            else:
                raise AssertionError("arquivo adulterado foi aceito")
            assert not list(Path(d).glob("*.exe")) and not list(Path(d).glob("*.part"))
        finally:
            updater._stream = orig


def test_http_refused_and_no_install_without_hash():
    bad = _info(installer=Asset("Eco-Setup-0.2.0.exe", 1, "http://insecure", "http://insecure"))
    try:
        updater.download(bad, Path(tempfile.gettempdir()) / "x_jarvis_upd")
    except updater.UpdateError as e:
        assert "HTTPS" in str(e)
    else:
        raise AssertionError
    try:
        updates.open_https("http://example.com")
    except ValueError:
        pass
    else:
        raise AssertionError("http deveria ser recusado")
    with tempfile.TemporaryDirectory() as d:
        exe = Path(d) / "a.exe"
        exe.write_bytes(b"not the installer")
        try:
            updater.install(exe, _info(), Path(d), target_dir=Path(d), dry_run=True)
        except updater.UpdateError as e:
            assert "não confere" in str(e)
        else:
            raise AssertionError("instalador com hash errado não pode rodar")


def test_state_snooze_ignore():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        info = _info()
        st = updater.load_state(d)
        assert updater.should_notify(info, st, now=1000.0)
        updater.snooze(d, 24, now=1000.0)
        assert not updater.should_notify(info, updater.load_state(d), now=1000.0 + 3600)
        assert updater.should_notify(info, updater.load_state(d), now=1000.0 + 25 * 3600)
        updater.ignore_version(d, "0.2.0")
        assert not updater.should_notify(info, updater.load_state(d), now=10 ** 9)
        assert updater.should_notify(_info(latest="0.3.0"), updater.load_state(d), now=10 ** 9)


def test_schedule_and_config():
    cfg = cfgmod.Config()
    st = updater.UpdateState(last_check=1000.0)
    assert updater.should_check_now(cfg, st, startup=True)
    assert not updater.should_check_now(cfg, st, startup=False, now=1000.0 + 3600)
    assert updater.should_check_now(cfg, st, startup=False, now=1000.0 + 13 * 3600)
    off = dataclasses.replace(cfg, updates=dataclasses.replace(cfg.updates, enabled=False))
    assert not updater.should_check_now(off, st, startup=True)
    assert not cfgmod.validate(cfg)
    bad = dataclasses.replace(cfg, updates=dataclasses.replace(cfg.updates, channel="x", interval_hours=0))
    assert len(cfgmod.validate(bad)) == 2
    assert schema.uncovered_fields() == []


def test_dev_tree_refused():
    with tempfile.TemporaryDirectory() as d:
        exe = Path(d) / "a.exe"
        exe.write_bytes(PAYLOAD)
        try:
            updater.install(exe, _info(), Path(d), target_dir=Path(d))
        except updater.UpdateError as e:
            assert "parece uma instalação" in str(e) and "administrador" not in str(e)
        else:
            raise AssertionError


def _fake_install(d: Path) -> Path:
    t = d / "inst"
    (t / "runtime" / "python").mkdir(parents=True)
    (t / "runtime" / "python" / "pythonw.exe").write_bytes(b"x")
    return t


def test_elevation_detection_and_uac_declined():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        t = _fake_install(d)
        exe = d / "Eco-Setup-0.2.0.exe"
        exe.write_bytes(PAYLOAD)
        assert not updater.needs_elevation(t)
        orig_w, orig_r = updater.can_write, updater.shell_runas
        calls = []
        try:
            updater.can_write = lambda p: False                  # simula Program Files
            assert updater.needs_elevation(t)
            r = updater.install(exe, _info(), d, target_dir=t, dry_run=True)
            assert r["elevated"] and "/VERYSILENT" in r["script"] and "/NORESTART" in r["script"]
            assert "runas" not in " ".join(r["cmd"])
            updater.shell_runas = lambda f, p: calls.append((f, p)) or 5       # UAC recusado (acesso negado)
            quit_called = []
            try:
                updater.install(exe, _info(), d, target_dir=t, quit_cb=lambda: quit_called.append(1))
            except updater.UacDeclined as e:
                assert "Tentar de novo" in str(e)
            else:
                raise AssertionError("UAC recusado deveria falhar")
            assert calls and calls[0][0] == "powershell.exe" and not quit_called    # Eco NÃO fechou
            assert exe.read_bytes() == PAYLOAD                                         # download preservado
        finally:
            updater.can_write, updater.shell_runas = orig_w, orig_r


def test_hash_changed_between_steps_and_script_content():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        t = _fake_install(d)
        exe = d / "Eco-Setup-0.2.0.exe"
        exe.write_bytes(PAYLOAD)
        r = updater.install(exe, _info(), d, target_dir=t, dry_run=True, elevate=True)
        # o script embute o hash esperado e o confere ANTES e DEPOIS da cópia elevada
        assert r["script"].count("-ne $Sha.ToLower()") == 2 and SHA in r["script"] and "explorer.exe" in r["script"]
        assert "Bearer" not in r["script"] and "Authorization" not in r["script"] and "gh_" not in r["script"]
        exe.write_bytes(PAYLOAD[:-1] + b"Z")                     # arquivo muda antes da elevação
        try:
            updater.install(exe, _info(), d, target_dir=t, dry_run=True, elevate=True)
        except updater.UpdateError as e:
            assert "não confere" in str(e)
        else:
            raise AssertionError("arquivo alterado deveria ser recusado")


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
            print("ok", name)
    print(f"{n} testes passaram")
