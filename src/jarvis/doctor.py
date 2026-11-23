"""`eco doctor`: confere o ambiente sem abrir o microfone, tocar som nem subir o modelo."""
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
from .tools import catalog
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
        return CheckResult("porta do LLM", False,
                           f"{host}:{port} já tem um servidor de modelo rodando que o Eco não iniciou; ele NÃO o usa. "
                           "Feche-o ou mude llm.port")
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


_CORE_TOOLS = frozenset({
    "abrir_app", "listar_apps_permitidos", "listar_janelas", "janela_ativa", "focar_janela", "fechar_janela",
    "digitar_texto", "apertar_atalho", "ver_tela", "listar_controles", "clicar_controle", "hora_atual",
    "ajustar_volume", "abrir_pasta"})


def _check_tools(cfg: Config) -> CheckResult:
    reg = ToolRegistry(cfg, EventBus())
    failed = catalog.register_everything(reg, cfg)
    names = set(reg.names())
    missing = sorted(_CORE_TOOLS - names)
    ok = not failed and not missing
    detail = f"{len(names)} registradas"
    if missing:
        detail += f"; FALTAM: {', '.join(missing)}"
    if failed:
        detail += f"; módulos com falha: {', '.join(failed)}"
    return CheckResult("ferramentas", ok, detail)


def _check_where(cfg: Config) -> list[CheckResult]:
    """Onde cada serviço RODA (GPU ou CPU), conforme a configuração e o que está disponível de verdade."""
    out: list[CheckResult] = []
    gpu = _check_gpu(cfg)
    gpu_name = gpu.detail.split(":", 1)[-1].strip() if gpu.ok else ""
    gpu_ok = gpu.ok
    llm_dev = "CPU (escolha do usuário)" if cfg.llm.device == "cpu" else (
        f"GPU: {gpu_name}, {cfg.llm.ngl} camadas" if gpu_ok else "CPU (nenhuma GPU Vulkan encontrada: o modo auto cai para a CPU)")
    out.append(CheckResult("onde: modelo de linguagem", True, llm_dev))
    mm = "CPU (escolha do usuário: ~5x mais lento)" if (cfg.llm.mmproj_device == "cpu" or cfg.llm.device == "cpu" or not gpu_ok) else "GPU (junto do modelo)"
    out.append(CheckResult("onde: visão (mmproj)", cfg.llm.mmproj is not None, mm if cfg.llm.mmproj is not None else "desligada"))
    # escuta: testa de verdade (carrega o motor GPU e transcreve 1 s de silêncio)
    from .audio.stt import Transcriber
    import numpy as np
    stt_detail, stt_ok = "", True
    if cfg.stt.device == "cpu":
        stt_detail = f"CPU (faster-whisper, {cfg.stt.model_dir.name}, {cfg.stt.cpu_threads} threads, escolha do usuário)"
    else:
        tr = Transcriber(cfg.stt)
        try:
            tr.preload()
            tr.transcribe(np.zeros(16000, dtype=np.float32))
            stt_detail = ("GPU (whisper.cpp Vulkan, " + cfg.stt.gpu_model.name + ")") if tr.engine == "gpu" else (
                f"CPU (faster-whisper {cfg.stt.model_dir.name}); a GPU não carregou, veja os avisos do log")
        except Exception as exc:  # noqa: BLE001
            stt_ok, stt_detail = False, f"falhou: {exc}"
        finally:
            tr.close()
    out.append(CheckResult("onde: escuta (STT)", stt_ok, stt_detail))
    out.append(CheckResult("onde: voz (Piper)", True, "CPU (onnxruntime; medido mais rápido que DirectML)"))
    out.append(CheckResult("onde: detector de voz (VAD)", True, "CPU, 1 thread (~0,9% de 1 núcleo)"))
    out.append(CheckResult("onde: captura de tela", True, "CPU (GDI, ~49 ms; DXGI ganha 33 ms mas exige OpenCV)"))
    out.append(CheckResult("onde: Ilha e janelas (Qt)", True, "CPU, renderização por software; ~0% escondida"))
    return out


def _check_toolpaths(cfg: Config) -> list[CheckResult]:
    """Caminhos PERSONALIZADOS (Configurações > Caminhos dos programas) precisam valer; senão o Eco usa a busca automática."""
    from .core import toolpaths
    out: list[CheckResult] = []
    for d in toolpaths.CATALOG:
        if not toolpaths.is_custom(d, cfg):
            continue
        v = toolpaths.validate_path(d.key, toolpaths.configured_value(d, cfg), run_version=True, check_signature=False)
        out.append(CheckResult(f"caminho personalizado: {d.title}", v.ok, v.message))
    return out


def _scan_results(cfg: Config) -> list[CheckResult]:
    """Varredura TOTAL das ferramentas (versão, onde foi achada, o que fazer). FALTA em item obrigatório = falha."""
    from .core import toolpaths
    txt = {"ok": "OK", "warn": "AVISO", "fail": "FALTA", "info": "opcional"}
    out: list[CheckResult] = []
    for it in toolpaths.scan_all(cfg):
        parts = [txt.get(it.status, it.status)]
        if it.version:
            parts.append(f"versão {it.version}")
        if it.path:
            parts.append(f"{it.path} ({it.where})")
        if it.detail and it.detail != "encontrado":
            parts.append(it.detail)
        if it.status in ("fail", "warn") and it.hint:
            parts.append("fazer: " + it.hint)
        out.append(CheckResult(f"ferramenta: {it.title}", it.status != "fail", " · ".join(parts)))
    return out


def run_doctor(cfg: Config, full: bool = False) -> list[CheckResult]:
    results: list[CheckResult] = [_check_python(), _check_disk(cfg), _check_ram(),
                                  _file("llama-server", cfg.paths.llama_bin / "llama-server.exe"),
                                  _file("modelo LLM", cfg.llm.model), _file("mmproj (visão)", cfg.llm.mmproj, required=False),
                                  _check_gpu(cfg), _check_port(cfg)]
    results += check_audio(cfg)
    results += _check_where(cfg)
    results += _check_hotkeys(cfg)
    results.append(_check_tools(cfg))
    results += _check_toolpaths(cfg)
    if full:
        results += _scan_results(cfg)
    return results
