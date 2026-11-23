"""Prova ponta a ponta do fluxo de voz com o cérebro em nuvem, medindo a latência de CADA etapa:

    áudio sintético pt-BR (Piper)  ->  STT local (faster-whisper, CPU)  ->  texto  ->  agente ACP (nuvem)  ->  resposta  ->  TTS local (Piper)

Só o TEXTO da transcrição vai ao agente. Sem microfone: o áudio de entrada é gerado pelo próprio Piper (a captura real não é testada aqui).
Uso:  python -I tests\\e2e_cloud_voice.py <agente> [--approve] [--json saida.json]
  --approve: o confirmador simulado responde SIM (a ação do Bloco de Notas roda de verdade e o processo novo é fechado por PID);
  sem a flag responde NÃO (nada é alterado).  Pedidos: hora (consulta) e abrir o Bloco de Notas (ação confirmável).
"""
import dataclasses
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jarvis import config as cfgmod                                    # noqa: E402
from jarvis.audio.stt import Transcriber                               # noqa: E402
from jarvis.audio.tts import Synthesizer                               # noqa: E402
from jarvis.brain.acp.cloud import CloudBrain, CloudUnavailable        # noqa: E402
from jarvis.core.cancel import CancelToken                             # noqa: E402
from jarvis.core.events import EventBus                                # noqa: E402
from jarvis.tools import catalog                                       # noqa: E402
from jarvis.tools.registry import Decision, ToolRegistry               # noqa: E402

agent = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "antigravity"
approve = "--approve" in sys.argv
out_json = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
PHRASES = ["Eco, que horas são agora?", "Eco, abra o bloco de notas."]


def resample16k(pcm16: np.ndarray, sr: int) -> np.ndarray:
    x = pcm16.astype(np.float32) / 32768.0
    if sr == 16000:
        return x
    n = int(len(x) * 16000 / sr)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def notepad_pids() -> set[int]:
    """PIDs de janelas do Bloco de Notas (o app da Store pode rodar com outro nome de processo)."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-Process | ? { $_.MainWindowTitle -match 'Bloco de Notas|Notepad' }).Id"],
                         capture_output=True, text=True).stdout
    return {int(x) for x in out.split() if x.isdigit()}


base = cfgmod.load()
cfg = dataclasses.replace(base, stt=dataclasses.replace(base.stt, device="cpu"), tts=dataclasses.replace(base.tts, device="cpu"),
                          brain=dataclasses.replace(base.brain, kind="cloud", agent=agent, request_timeout_s=150))
bus = EventBus()
steps: list[str] = []
bus.subscribe(lambda ev: steps.append(f"{ev.data.get('tool')}:{ev.data.get('status')}"), kind="action_step")
asked: list[str] = []


class Asker:
    def ask(self, text, risk, cancel):
        asked.append(text)
        return Decision(approve, "test")


reg = ToolRegistry(cfg, bus, Asker())
catalog.register_everything(reg, cfg)
cloud = CloudBrain(cfg, reg, bus, lambda t, r, c: (asked.append(t), approve)[1])
tts, stt = Synthesizer(cfg.tts), Transcriber(cfg.stt)
report = {"agent": agent, "approve": approve, "turns": []}
before = notepad_pids()
try:
    t = time.perf_counter()
    tts.preload()
    stt.preload()
    report["load_models_s"] = round(time.perf_counter() - t, 2)
    for phrase in PHRASES:
        row: dict = {"phrase": phrase}
        t = time.perf_counter()
        chunks = list(tts.synthesize(phrase))
        pcm = np.concatenate([c.pcm_int16 for c in chunks])
        sr = chunks[0].sample_rate
        row["tts_in_s"] = round(time.perf_counter() - t, 2)
        row["audio_s"] = round(len(pcm) / sr, 2)
        audio = resample16k(pcm, sr)
        t = time.perf_counter()
        tr = stt.transcribe(audio)
        row["stt_s"] = round(time.perf_counter() - t, 2)
        row["heard"] = tr.text
        t = time.perf_counter()
        try:
            answer = cloud.ask(tr.text, CancelToken())
            row["cloud_s"] = round(time.perf_counter() - t, 2)
            row["cloud_split"] = dict(cloud.last_timing)
            row["model"] = cloud.last_model
            row["answer"] = answer
            t = time.perf_counter()
            first = None
            n = 0
            for ch in tts.synthesize(answer):
                if first is None:
                    first = time.perf_counter() - t
                n += len(ch.pcm_int16)
            row["tts_first_s"] = round(first or 0, 2)
            row["tts_total_s"] = round(time.perf_counter() - t, 2)
            row["total_s"] = round(row["stt_s"] + row["cloud_s"] + row["tts_first_s"], 2)
        except CloudUnavailable as exc:
            row["cloud_s"] = round(time.perf_counter() - t, 2)
            row["unavailable"] = {"kind": exc.kind, "reason": exc.reason, "login_help": exc.login_help}
        report["turns"].append(row)
finally:
    cloud.close()
    stt.close()
    tts.close()
    new = notepad_pids() - before
    for pid in new:                                                         # só o Bloco de Notas que ESTE teste abriu
        subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True)
    report["notepad_opened_and_closed"] = sorted(new)
report["confirmations_asked"] = asked
report["island_events"] = steps
print(json.dumps(report, ensure_ascii=False, indent=1))
if out_json:
    Path(out_json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
