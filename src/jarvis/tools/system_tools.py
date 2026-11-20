"""Ferramentas de sistema: hora, volume e pastas conhecidas."""
from __future__ import annotations

import ctypes
import logging
import os
import uuid
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from ..config import Config
from ..win import input as win_input
from .registry import Risk, ToolContext, ToolRegistry, ToolResult, ToolSpec

log = logging.getLogger(__name__)

VK_VOLUME_MUTE: Final = 0xAD
VK_VOLUME_DOWN: Final = 0xAE
VK_VOLUME_UP: Final = 0xAF
_VOLUME_STEP_PAUSE_S: Final = 0.03

_WEEKDAYS: Final = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                    "sexta-feira", "sábado", "domingo")
_MONTHS: Final = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
                  "agosto", "setembro", "outubro", "novembro", "dezembro")


def _spoken_time(now: datetime) -> str:
    """Ex.: 'São 14h35, quinta-feira, 20 de novembro.' (hora 1 e 13 pedem 'É')."""
    verb = "É" if now.hour % 12 == 1 else "São"
    clock = f"{now.hour}h" if now.minute == 0 else f"{now.hour}h{now.minute:02d}"
    return f"{verb} {clock}, {_WEEKDAYS[now.weekday()]}, {now.day} de {_MONTHS[now.month - 1]}."


# ----------------------------------------------------------------- pastas conhecidas
class _GUID(ctypes.Structure):
    _fields_ = (("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8))


def _guid(text: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


_shell32 = ctypes.WinDLL("shell32")
_ole32 = ctypes.WinDLL("ole32")
_shell32.SHGetKnownFolderPath.argtypes = (
    ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p))
_shell32.SHGetKnownFolderPath.restype = ctypes.c_long
_ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
_ole32.CoTaskMemFree.restype = None

# chave do schema -> (rótulo falado, FOLDERID, nome da pasta no perfil como plano B)
_FOLDERS: Final[dict[str, tuple[str, str, str]]] = {
    "downloads": ("Downloads", "374DE290-123F-4565-9164-39C4925E467B", "Downloads"),
    "documentos": ("Documentos", "FDD39AD0-238F-46AF-ADB4-6C85480369C7", "Documents"),
    "area_de_trabalho": ("Área de Trabalho", "B4BFCC3A-DB2C-424C-B029-7FE99A87C641", "Desktop"),
    "imagens": ("Imagens", "33E28130-4E1E-4676-835A-98395C3BC3BB", "Pictures"),
}


def _known_folder(folder_id: str) -> Path | None:
    out = ctypes.c_void_p()
    try:
        hr = _shell32.SHGetKnownFolderPath(ctypes.byref(_guid(folder_id)), 0, None, ctypes.byref(out))
        if hr != 0 or not out.value:
            return None
        return Path(ctypes.wstring_at(out.value))
    finally:
        _ole32.CoTaskMemFree(out)       # seguro com NULL


def _resolve_folder(key: str) -> Path | None:
    _label, folder_id, fallback = _FOLDERS[key]
    for candidate in (_known_folder(folder_id), Path.home() / fallback):
        if candidate is not None and candidate.is_dir():
            return candidate
    return None


def register(registry: ToolRegistry, cfg: Config) -> None:
    def hora_atual(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        now = datetime.now().astimezone()
        return ToolResult(True, _spoken_time(now), data={"iso": now.isoformat(timespec="seconds")})

    def ajustar_volume(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        action = str(args["acao"])
        steps = int(args.get("passos", 1))
        try:
            if action == "mudo":
                win_input.tap_key(VK_VOLUME_MUTE)
                return ToolResult(True, "Alternei o mudo.")
            vk = VK_VOLUME_UP if action == "aumentar" else VK_VOLUME_DOWN
            done = 0
            for _ in range(steps):
                if ctx.cancel.cancelled:
                    break
                win_input.tap_key(vk)
                done += 1
                ctx.cancel.wait(_VOLUME_STEP_PAUSE_S)
        except win_input.InputBlockedError as exc:
            return ToolResult(False, str(exc))
        if done == 0:
            return ToolResult(False, "Cancelado.")
        verb = "Aumentei" if action == "aumentar" else "Diminuí"
        return ToolResult(True, f"{verb} o volume em {done} passo{'s' if done > 1 else ''}.")

    def abrir_pasta(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        key = str(args["pasta"])
        if key not in _FOLDERS:                       # o enum já barra; defesa extra
            return ToolResult(False, "Pasta não permitida.")
        label = _FOLDERS[key][0]
        path = _resolve_folder(key)
        if path is None:
            return ToolResult(False, f"Não encontrei a pasta {label}.")
        if ctx.cancel.cancelled:
            return ToolResult(False, "Cancelado.")
        try:
            os.startfile(path)  # noqa: S606 - caminho vindo do Windows, nunca do modelo
        except OSError as exc:
            log.warning("falha ao abrir a pasta %s: %s", path, exc)
            return ToolResult(False, f"Não consegui abrir a pasta {label}.")
        return ToolResult(True, f"Abri a pasta {label}.")

    registry.register(ToolSpec(
        name="hora_atual",
        description="Diz a hora, o dia da semana e a data de agora. Use para perguntas como 'que horas são?'.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        risk=Risk.READ,
        handler=hora_atual,
    ))
    registry.register(ToolSpec(
        name="ajustar_volume",
        description=("Muda o volume do computador: 'aumentar', 'diminuir' ou 'mudo' (liga/desliga o som). "
                     "'passos' é quantas vezes apertar (1 a 10, cada passo é cerca de 2%)."),
        parameters={
            "type": "object",
            "properties": {
                "acao": {"type": "string", "enum": ["aumentar", "diminuir", "mudo"]},
                "passos": {"type": "integer", "minimum": 1, "maximum": 10,
                           "description": "Quantidade de passos; padrão 1."},
            },
            "required": ["acao"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=ajustar_volume,
        confirm_text=lambda a: f"Ajustar o volume ({a.get('acao', '')})",
    ))
    registry.register(ToolSpec(
        name="abrir_pasta",
        description="Abre no Explorador de Arquivos uma pasta comum: downloads, documentos, área de trabalho ou imagens.",
        parameters={
            "type": "object",
            "properties": {"pasta": {"type": "string", "enum": list(_FOLDERS)}},
            "required": ["pasta"],
            "additionalProperties": False,
        },
        risk=Risk.CONTROL,
        handler=abrir_pasta,
        confirm_text=lambda a: f"Abrir a pasta {a.get('pasta', '')}",
    ))
