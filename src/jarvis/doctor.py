"""`jarvis doctor`: confere o ambiente sem abrir o microfone, tocar som nem subir o modelo."""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from pathlib import Path

from .audio.checks import CheckResult, check_audio
from .config import Config
from .core.events import EventBus
from .llm.server import health_ok
from .tools import builtin, notes
from .tools.registry import ToolRegistry
from .win.hotkeys import HotkeyError, HotkeyListener


def _file(name: str, path: Path | None, required: bool = True) -> CheckResult:
    if path is None:
        return CheckResult(name, True, "não configurado (opcional)")
    if Path(path).is_file():
        return CheckResult(name, True, f"{path} ({Path(path).stat().st_size / 1e6:.0f} MB)")
    return CheckResult(name, not required, f"NÃO ENCONTRADO: {path}")


def _check_python() -> CheckResult:
    v = sys.version_info
    return CheckResult("Python", v >= (3, 11), f"{v.major}.{v.minor}.{v.micro}")


def _check_disk(cfg: Config) -> CheckResult:
    free = shutil.disk_usage(cfg.paths.root).free / 1e9
    return CheckResult("disco", free > 2.0, f"{free:.1f} GB livres em {cfg.paths.root.anchor}")


def _check_ram() -> CheckResult:
    try:
        import psutil
    except ImportError:
        return CheckResult("RAM", True, "psutil ausente (não medi)")
    vm = psutil.virtual_memory()
    return CheckResult("RAM", vm.available > 3e9, f"{vm.available / 1e9:.1f} GB livres de {vm.total / 1e9:.1f} GB")


def _check_gpu(cfg: Config) -> CheckResult:
    exe = cfg.paths.llama_bin / "llama-server.exe"
    if not exe.is_file():
        return CheckResult("GPU Vulkan", False, f"llama-server ausente: {exe}")
    try:
        out = subprocess.run([str(exe), "--list-devices"], capture_output=True, text=True, timeout=30,
                             cwd=str(exe.parent), creationflags=0x08000000)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("GPU Vulkan", False, f"não consegui listar dispositivos: {exc}")
    text = (out.stdout + out.stderr)
    lines = [ln.strip() for ln in text.splitlines() if "Vulkan" in ln and ("MiB" in ln or "AMD" in ln)]
    return CheckResult("GPU Vulkan", bool(lines), lines[0] if lines else "nenhuma GPU Vulkan encontrada")


def _check_port(cfg: Config) -> CheckResult:
    host, port = cfg.llm.host, cfg.llm.port
    if health_ok(host, port):
        return CheckResult("porta do LLM", True, f"{host}:{port} já tem um llama-server saudável (será reutilizado)")
    with socket.socket() as s:
        s.settimeout(0.5)
        busy = s.connect_ex((host, port)) == 0
    return CheckResult("porta do LLM", not busy, f"{host}:{port} " + ("OCUPADA por outro programa" if busy else "livre"))


def _check_hotkeys(cfg: Config) -> list[CheckResult]:
    s = cfg.safety
    out: list[CheckResult] = []
    listener = HotkeyListener()
    try:
        listener.start()
        for label, combo in (("emergência", s.emergency_hotkey), ("mudo", s.mute_hotkey),
                             ("confirmar sim", s.confirm_yes_hotkey), ("confirmar não", s.confirm_no_hotkey)):
            try:
                listener.add(combo, lambda: None)
                out.append(CheckResult(f"atalho {label}", True, combo))
            except HotkeyError as exc:
                out.append(CheckResult(f"atalho {label}", label != "emergência", str(exc)))
    except HotkeyError as exc:
        out.append(CheckResult("atalhos", False, str(exc)))
    finally:
        listener.stop()
    return out


def _check_tools(cfg: Config) -> CheckResult:
    reg = ToolRegistry(cfg, EventBus())
    builtin.register_all(reg, cfg)
    notes.register(reg, cfg)
    names = reg.names()
    return CheckResult("ferramentas", len(names) >= 10, f"{len(names)} registradas: {', '.join(names)}")


def run_doctor(cfg: Config) -> list[CheckResult]:
    results: list[CheckResult] = [_check_python(), _check_disk(cfg), _check_ram(),
                                  _file("llama-server", cfg.paths.llama_bin / "llama-server.exe"),
                                  _file("modelo LLM", cfg.llm.model), _file("mmproj (visão)", cfg.llm.mmproj, required=False),
                                  _check_gpu(cfg), _check_port(cfg)]
    results += check_audio(cfg)
    results += _check_hotkeys(cfg)
    results.append(_check_tools(cfg))
    return results
