"""Verificações de áudio para o comando ``doctor``.

Só consulta: não abre o microfone, não abre stream de saída, não toca som e não carrega modelos
(apenas confere arquivos, tamanhos e a presença dos pacotes). Cada verificação é independente e
nunca levanta exceção: falhas viram ``CheckResult(ok=False)``.
"""
from __future__ import annotations

import importlib.util
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from .devices import DeviceError, resolve_input_device, resolve_output_device
from .service import AUDIO_SERVICES, query_service
from .stt import find_local_model
from .vad import VadError, default_model_path, validate_model_file

log = logging.getLogger(__name__)

_MIN_VOICE_BYTES = 1_000_000
_PACKAGES = ("sounddevice", "numpy", "onnxruntime", "faster_whisper", "piper")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _mb(size: int) -> str:
    return f"{size / 2**20:.1f} MB"


def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.iterdir() if p.is_file())


def _check_packages() -> CheckResult:
    missing = [name for name in _PACKAGES if importlib.util.find_spec(name) is None]
    if missing:
        return CheckResult("pacotes de áudio", False, "ausentes: " + ", ".join(missing))
    return CheckResult("pacotes de áudio", True, ", ".join(_PACKAGES))


def _check_device(name: str, resolver: Callable[[], object]) -> CheckResult:
    try:
        device = resolver()
    except DeviceError as exc:
        return CheckResult(name, False, str(exc))
    return CheckResult(name, True, getattr(device, "label", str(device)))


def _check_whisper(cfg: Config) -> CheckResult:
    name = "modelo Whisper"
    local = find_local_model(cfg.stt.model_dir)
    if local is None:
        return CheckResult(name, False, f"sem model.bin em {cfg.stt.model_dir} (o modelo {cfg.stt.model_name!r} "
                                        "teria de ser baixado para essa pasta)")
    try:
        return CheckResult(name, True, f"{cfg.stt.model_name}: {_mb(_dir_size(local))} em {local}, "
                                       f"{cfg.stt.compute_type}, {cfg.stt.cpu_threads} threads")
    except OSError as exc:
        return CheckResult(name, False, f"não consegui ler {local}: {exc}")


def _check_piper(cfg: Config) -> CheckResult:
    name = "voz Piper"
    onnx, conf = cfg.tts.voice_onnx, cfg.tts.voice_json
    problems = [f"ausente: {p}" for p in (onnx, conf) if not p.is_file()]
    if problems:
        return CheckResult(name, False, "; ".join(problems))
    try:
        size = onnx.stat().st_size
        if size < _MIN_VOICE_BYTES:
            return CheckResult(name, False, f"{onnx.name} com {size} bytes: parece truncado")
        rate = json.loads(conf.read_text(encoding="utf-8"))["audio"]["sample_rate"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return CheckResult(name, False, f"configuração da voz ilegível ({conf.name}): {exc}")
    return CheckResult(name, True, f"{onnx.name}: {_mb(size)}, {rate} Hz")


def _check_vad(cfg: Config) -> CheckResult:
    name = "VAD Silero"
    # mesmo caminho e mesma validação do runtime (Microphone(models_dir=cfg.paths.models) -> SileroVAD)
    path = default_model_path(cfg.paths.models)
    try:
        size = validate_model_file(path)
    except VadError as exc:
        return CheckResult(name, False, str(exc))
    return CheckResult(name, True, f"{path} ({_mb(size)})")


def _check_audio_services() -> CheckResult:
    """Estado REAL dos serviços de áudio do Windows (Service Control Manager)."""
    states = [query_service(n) for n in AUDIO_SERVICES]
    detail = ", ".join(f"{s.name}: {s.text}" for s in states)
    return CheckResult("serviços de áudio do Windows", all(s.running for s in states), detail)


def _check_host_apis() -> CheckResult:
    """APIs de áudio que o PortAudio enxerga e quantos dispositivos cada uma tem. Só WDM-KS = algo errado com o áudio."""
    from collections import Counter

    from .devices import list_devices
    inputs: Counter[str] = Counter()
    outputs: Counter[str] = Counter()
    for d in list_devices():
        if d.max_input_channels > 0:
            inputs[d.hostapi] += 1
        if d.max_output_channels > 0:
            outputs[d.hostapi] += 1
    apis = sorted(set(inputs) | set(outputs))
    detail = "; ".join(f"{a}: {inputs[a]} entrada(s), {outputs[a]} saída(s)" for a in apis) or "nenhuma"
    if not [a for a in apis if "wdm" not in a.lower()]:
        return CheckResult("APIs de áudio", False,
                           f"só aparecem APIs WDM-KS ({detail}). O Jarvis prefere MME/WASAPI/DirectSound: reinicie o "
                           "programa e confira o serviço 'Áudio do Windows' no item acima")
    return CheckResult("APIs de áudio", True, detail)


def check_audio(cfg: Config) -> list[CheckResult]:
    """Roda todas as verificações de áudio (sem abrir microfone nem tocar som)."""
    checks: list[tuple[str, Callable[[], CheckResult]]] = [
        ("pacotes de áudio", _check_packages),
        ("serviços de áudio do Windows", _check_audio_services),
        ("APIs de áudio", _check_host_apis),
        ("microfone", lambda: _check_device("microfone", lambda: resolve_input_device(cfg.audio))),
        ("alto-falante", lambda: _check_device("alto-falante", lambda: resolve_output_device(cfg.audio))),
        ("modelo Whisper", lambda: _check_whisper(cfg)),
        ("voz Piper", lambda: _check_piper(cfg)),
        ("VAD Silero", lambda: _check_vad(cfg)),
    ]
    results: list[CheckResult] = []
    for name, check in checks:
        try:
            results.append(check())
        except Exception as exc:  # o doctor nunca pode quebrar por uma verificação
            log.exception("verificação de áudio %r falhou de forma inesperada", name)
            results.append(CheckResult(name, False, f"erro inesperado: {exc}"))
    return results
