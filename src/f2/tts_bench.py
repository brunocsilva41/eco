r"""Benchmark de TTS em CPU (Piper; Kokoro opcional). Uso:
  venv\Scripts\python.exe -I src\f2\tts_bench.py piper
  ... tts_bench.py kokoro   (requer pacote kokoro-onnx e modelos na pasta)
Medicoes: ttfa = tempo ate o 1o chunk (1 chunk por sentenca no Piper 1.8.0),
total = sintese completa, rtf = total / duracao do audio. Sem GPU."""
import sys, time, wave, json, statistics as st
from pathlib import Path
import numpy as np

ROOT = Path(r"F:\Eco")
FRASES = ROOT / "tests" / "frases_pt.txt"

def stats(xs):
    return {"media": st.mean(xs), "min": min(xs), "max": max(xs)}

def write_wav(path, pcm16, sr):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm16.tobytes())

def piper_engine():
    from piper import PiperVoice
    d = ROOT / "models" / "piper-faber"
    v = PiperVoice.load(d / "pt_BR-faber-medium.onnx", d / "pt_BR-faber-medium.onnx.json", use_cuda=False)
    sr = v.config.sample_rate
    def gen(text):
        for ch in v.synthesize(text):
            yield ch.audio_int16_array
    return gen, sr, ROOT / "tests" / "audio_piper"

def kokoro_engine():
    from kokoro_onnx import Kokoro
    d = ROOT / "models" / "kokoro"
    k = Kokoro(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))
    sr = 24000
    def gen(text):
        s, _ = k.create(text, voice="pf_dora", speed=1.0, lang="pt-br")
        yield (np.clip(s, -1, 1) * 32767).astype(np.int16)
    return gen, sr, ROOT / "tests" / "audio_kokoro"

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "piper"
    gen, sr, outdir = {"piper": piper_engine, "kokoro": kokoro_engine}[which]()
    outdir.mkdir(parents=True, exist_ok=True)
    frases = [l.strip() for l in FRASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    list(gen("Aquecimento."))  # warm-up fora da medicao
    rows = []
    for i, f in enumerate(frases, 1):
        t0 = time.perf_counter(); first = None; parts = []
        for a in gen(f):
            if first is None: first = time.perf_counter() - t0
            parts.append(a)
        total = time.perf_counter() - t0
        pcm = np.concatenate(parts); dur = len(pcm) / sr
        write_wav(outdir / f"{i:02d}.wav", pcm, sr)
        rows.append({"n": i, "ttfa": first, "total": total, "dur": dur, "rtf": total / dur})
        print(f"{i:02d} ttfa={first:.3f}s total={total:.3f}s dur={dur:.2f}s rtf={total/dur:.3f}  {f}")
    out = {"engine": which, "sr": sr, **{k: stats([r[k] for r in rows]) for k in ("ttfa", "total", "dur", "rtf")}}
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
