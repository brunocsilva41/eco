"""Gravação das escolhas do assistente no config.toml (pelo mesmo `SettingsStore` das Configurações) e Iniciar com o Windows."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..config import CONFIG_FILE, ROOT, Config, load
from ..settings.store import SettingsStore
from .manifest import Manifest

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "Jarvis"


def store() -> SettingsStore:
    return SettingsStore(CONFIG_FILE)


def current_config() -> Config:
    return load(CONFIG_FILE)


def save_values(updates: dict[str, Any]) -> Config:
    """Mescla `updates` ({'secao.campo': valor}) no config atual, valida e grava (atômico, com backup)."""
    st = store()
    values = st.values()
    values.update(updates)
    return st.save(values).config


def stt_dir_for(components: list[str], manifest: Manifest) -> str | None:
    for key in components:
        comp = manifest.components.get(key)
        if comp and comp.stt_dir:
            return comp.stt_dir
    return None


def apply_stt_choice(components: list[str], manifest: Manifest) -> None:
    d = stt_dir_for(components, manifest)
    if d:
        updates = {"stt.model_dir": d}
        # sem o modelo ggml (opção "base, leve") a escuta fica na CPU; com o "small" o padrão "auto" usa a placa de vídeo
        chosen = {pk for key in components for pk in (manifest.components[key].packages if key in manifest.components else ())}
        if "whisper-small-ggml" not in chosen:
            updates["stt.device"] = "cpu"
        save_values(updates)


# ---------------------------------------------------------------- Iniciar com o Windows (HKCU\...\Run)
def launcher_command(root: Path = ROOT) -> str | None:
    pyw = root / "Jarvis.pyw"
    if not pyw.is_file():
        return None
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.is_file():
        return None
    return f'"{pythonw}" -I -X utf8 "{pyw}"'


def autostart_available(root: Path = ROOT) -> bool:
    return launcher_command(root) is not None


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _RUN_NAME)
            return True
    except (OSError, ImportError):
        return False


def set_autostart(on: bool, root: Path = ROOT) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            cmd = launcher_command(root)
            if cmd is None:
                raise OSError("launcher do Jarvis não encontrado")
            winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, _RUN_NAME)
            except FileNotFoundError:
                pass
