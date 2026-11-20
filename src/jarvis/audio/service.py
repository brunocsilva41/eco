"""Estado dos serviços de áudio do Windows, consultado no Service Control Manager (sem subprocess e sem alterar nada)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_STATUS = 0x0004
_SC_STATUS_PROCESS_INFO = 0
_STATES = {1: "parado", 2: "iniciando", 3: "parando", 4: "em execução", 5: "retomando", 6: "pausando", 7: "pausado"}
RUNNING = 4

AUDIO_SERVICES = ("Audiosrv", "AudioEndpointBuilder")

_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_adv.OpenSCManagerW.restype = wt.HANDLE
_adv.OpenSCManagerW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.DWORD]
_adv.OpenServiceW.restype = wt.HANDLE
_adv.OpenServiceW.argtypes = [wt.HANDLE, wt.LPCWSTR, wt.DWORD]
_adv.QueryServiceStatusEx.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
_adv.CloseServiceHandle.argtypes = [wt.HANDLE]


class _STATUS(ctypes.Structure):
    _fields_ = [("dwServiceType", wt.DWORD), ("dwCurrentState", wt.DWORD), ("dwControlsAccepted", wt.DWORD),
                ("dwWin32ExitCode", wt.DWORD), ("dwServiceSpecificExitCode", wt.DWORD), ("dwCheckPoint", wt.DWORD),
                ("dwWaitHint", wt.DWORD), ("dwProcessId", wt.DWORD), ("dwServiceFlags", wt.DWORD)]


@dataclass(frozen=True)
class ServiceState:
    name: str
    code: int | None            # SERVICE_* do Windows; None se não deu para consultar
    error: str = ""

    @property
    def running(self) -> bool:
        return self.code == RUNNING

    @property
    def text(self) -> str:
        if self.code is None:
            return f"não consegui consultar ({self.error})"
        return _STATES.get(self.code, f"estado {self.code}")


def query_service(name: str) -> ServiceState:
    """Consulta o estado real do serviço no SCM. Nunca levanta exceção."""
    scm = _adv.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
    if not scm:
        return ServiceState(name, None, f"OpenSCManager erro {ctypes.get_last_error()}")
    try:
        svc = _adv.OpenServiceW(scm, name, _SERVICE_QUERY_STATUS)
        if not svc:
            return ServiceState(name, None, f"OpenService erro {ctypes.get_last_error()}")
        try:
            st, needed = _STATUS(), wt.DWORD()
            if not _adv.QueryServiceStatusEx(svc, _SC_STATUS_PROCESS_INFO, ctypes.byref(st), ctypes.sizeof(st), ctypes.byref(needed)):
                return ServiceState(name, None, f"QueryServiceStatusEx erro {ctypes.get_last_error()}")
            return ServiceState(name, int(st.dwCurrentState))
        finally:
            _adv.CloseServiceHandle(svc)
    finally:
        _adv.CloseServiceHandle(scm)
