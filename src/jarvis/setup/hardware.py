"""Checagem de requisitos e hardware para o assistente. Só LÊ: nunca instala nem atualiza driver."""
from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import ROOT, PathsCfg

MIN_BUILD = 19044            # Windows 10 21H2
MIN_RAM_GB = 12.0
GOOD_RAM_GB = 16.0
MIN_VRAM_MB = 4000
_NOWIN = 0x08000000


@dataclass(frozen=True)
class Check:
    key: str
    title: str
    status: str              # ok | warn | fail
    detail: str
    hint: str = ""


def check_os() -> Check:
    try:
        v = sys.getwindowsversion()
    except AttributeError:
        return Check("os", "Windows", "fail", "este assistente roda só no Windows", "Use um PC com Windows 10 ou 11.")
    name = "Windows 11" if v.build >= 22000 else "Windows 10"
    label = f"{name} (compilação {v.build})"
    if v.build < MIN_BUILD:
        return Check("os", "Windows", "fail", label, "Precisa do Windows 10 21H2 (19044) ou mais novo. Atualize pelo Windows Update.")
    return Check("os", "Windows", "ok", label)


def check_arch() -> Check:
    m = platform.machine().upper()
    if m in ("AMD64", "X86_64"):
        return Check("arch", "Processador", "ok", f"64 bits ({m})")
    return Check("arch", "Processador", "fail", f"arquitetura {m}", "O Jarvis precisa de Windows x64.")


def check_ram() -> Check:
    try:
        import psutil
        total = psutil.virtual_memory().total / 1024 ** 3
    except Exception as exc:  # noqa: BLE001
        return Check("ram", "Memória (RAM)", "warn", f"não consegui medir ({exc})")
    detail = f"{total:.1f} GB instalados"
    if total < MIN_RAM_GB - 0.6:             # 12 GB físicos aparecem como ~11,9
        return Check("ram", "Memória (RAM)", "warn", detail,
                     f"O recomendado é {GOOD_RAM_GB:.0f} GB (mínimo {MIN_RAM_GB:.0f}). O Jarvis pode ficar lento ou travar.")
    return Check("ram", "Memória (RAM)", "ok", detail + (" (ótimo)" if total >= GOOD_RAM_GB - 0.6 else ""))


def check_disk(root: Path = ROOT, need_gb: float = 0.0) -> Check:
    p = root
    while not p.exists() and p != p.parent:
        p = p.parent
    free = shutil.disk_usage(p).free / 1e9
    detail = f"{free:.1f} GB livres em {p.anchor}"
    if need_gb and free < need_gb + 0.3:
        return Check("disk", "Espaço em disco", "fail", detail, f"Faltam {need_gb + 0.3 - free:.1f} GB para os modelos escolhidos. Libere espaço.")
    if free < 2.0:
        return Check("disk", "Espaço em disco", "warn", detail, "Pouco espaço livre.")
    return Check("disk", "Espaço em disco", "ok", detail)


def _gpu_wmi() -> list[dict]:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                              "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,DriverDate | ConvertTo-Json -Compress"],
                             capture_output=True, text=True, timeout=25, creationflags=_NOWIN)
        data = json.loads(out.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    return data if isinstance(data, list) else [data]


def _driver_age_years(item: dict) -> float | None:
    m = re.search(r"/Date\((\d+)\)/", str(item.get("DriverDate", "")))
    if not m:
        return None
    return (time.time() - int(m.group(1)) / 1000) / (365.25 * 86400)


def check_gpu(llama_bin: Path | None = None) -> list[Check]:
    """GPU + Vulkan. O que vale é o que o llama-server enxerga (é ele que vai usar). Driver antigo só gera aviso."""
    llama_bin = llama_bin or PathsCfg().llama_bin
    out: list[Check] = []
    vk_dll = Path(r"C:\Windows\System32\vulkan-1.dll")
    exe = llama_bin / "llama-server.exe"
    lines: list[str] = []
    err = ""
    if exe.is_file():
        try:
            r = subprocess.run([str(exe), "--list-devices"], capture_output=True, text=True, timeout=40,
                               cwd=str(exe.parent), creationflags=_NOWIN)
            lines = [ln.strip() for ln in (r.stdout + r.stderr).splitlines() if "Vulkan" in ln and "MiB" in ln]
        except (OSError, subprocess.TimeoutExpired) as exc:
            err = str(exc)
    else:
        err = f"llama-server ausente em {exe}"
    if lines:
        m = re.search(r"Vulkan\d+:\s*(.+?)\s*\((\d+) MiB", lines[0])
        name, vram = (m.group(1), int(m.group(2))) if m else (lines[0], 0)
        status = "ok" if vram >= MIN_VRAM_MB else "warn"
        hint = "" if status == "ok" else "Pouca memória de vídeo: o modelo pode rodar parte na CPU, mais devagar."
        out.append(Check("gpu", "Placa de vídeo (Vulkan)", status, f"{name}, {vram / 1024:.1f} GB de memória de vídeo", hint))
    else:
        why = err or "nenhuma GPU com Vulkan encontrada"
        hint = ("Sem Vulkan o Jarvis cai para a CPU (bem mais lento). Instale o driver de vídeo mais recente do fabricante "
                "(AMD, NVIDIA ou Intel) pelo site oficial; este assistente não mexe em drivers.")
        if not vk_dll.is_file():
            hint = "vulkan-1.dll não está no Windows: " + hint
        out.append(Check("gpu", "Placa de vídeo (Vulkan)", "warn", why, hint))
    for item in _gpu_wmi():
        age = _driver_age_years(item)
        if age is not None and age > 3 and item.get("Name"):
            out.append(Check("driver", "Driver de vídeo", "warn", f"{item.get('Name')}: versão {item.get('DriverVersion')} com {age:.0f} anos",
                             "Só um aviso: um driver mais novo pode melhorar a velocidade. Atualize você mesmo pelo site do fabricante."))
    return out


def check_audio() -> list[Check]:
    try:
        from ..audio.devices import list_devices
        devs = list_devices()
    except Exception as exc:  # noqa: BLE001
        return [Check("mic", "Microfone", "warn", f"não consegui listar os dispositivos de áudio ({exc})",
                      "Confira se o serviço 'Áudio do Windows' está rodando."),
                Check("spk", "Alto-falante", "warn", "não verificado")]
    ins = [d for d in devs if d.is_default_input]
    outs = [d for d in devs if d.is_default_output]
    res = []
    if ins:
        res.append(Check("mic", "Microfone", "ok", f"padrão do Windows: {ins[0].name}"))
    else:
        any_in = [d for d in devs if d.max_input_channels > 0]
        res.append(Check("mic", "Microfone", "fail" if not any_in else "warn",
                         "nenhum microfone padrão" if any_in else "nenhum microfone encontrado",
                         "Conecte um microfone e defina como padrão em Configurações do Windows > Sistema > Som."))
    if outs:
        res.append(Check("spk", "Alto-falante", "ok", f"padrão do Windows: {outs[0].name}"))
    else:
        res.append(Check("spk", "Alto-falante", "warn", "nenhuma saída de áudio padrão", "Conecte caixas ou fones."))
    return res


def check_display() -> Check:
    try:
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return Check("dpi", "Tela", "ok", "sem tela (modo sem janela)")
        g = scr.geometry()
        scale = round(scr.devicePixelRatio() * 100)
        n = len(QGuiApplication.screens())
        return Check("dpi", "Tela", "ok", f"{g.width()}x{g.height()} lógicos, escala {scale}%" + (f", {n} monitores" if n > 1 else ""))
    except Exception as exc:  # noqa: BLE001
        return Check("dpi", "Tela", "warn", f"não consegui medir ({exc})")


def check_runtime() -> Check:
    """O Python embutido: confirma que o Jarvis roda sem depender do Python do sistema."""
    exe = Path(sys.executable)
    own = (ROOT / "runtime").exists() and str(exe).lower().startswith(str(ROOT).lower())
    return Check("runtime", "Programa", "ok", f"Python {platform.python_version()} " + ("embutido na instalação" if own else "do ambiente de desenvolvimento"))


def run_all(root: Path = ROOT, need_gb: float = 0.0, with_gpu: bool = True) -> list[Check]:
    res = [check_os(), check_arch(), check_ram(), check_disk(root, need_gb)]
    if with_gpu:
        res += check_gpu()
    res += check_audio()
    res.append(check_display())
    return res
