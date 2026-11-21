"""Sincronia contra o áudio: início real da fala (energia) x primeira palavra, fim real x última palavra, por motor.
Verdade-base = onde o sinal passa do limiar (clipes limpos, sintéticos, silêncio nas pontas)."""
import json, statistics, sys, wave
from pathlib import Path
import numpy as np

sys.path.insert(0, r"F:\Jarvis\src\f2")
from stt_bench import load_audio, model_path
from faster_whisper import WhisperModel

OUT = Path(r"F:\Jarvis\work\bench")


def edges(wav: str) -> tuple[float, float]:
    with wave.open(wav, "rb") as w:
        sr = w.getframerate(); x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    hop = int(sr * 0.01); n = len(x) // hop
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1))
    thr = max(0.02 * rms.max(), 0.004)
    idx = np.where(rms > thr)[0]
    return idx[0] * 0.01, (idx[-1] + 1) * 0.01


def wcpp_words(tag: str) -> list[dict]:
    data = json.loads((OUT / f"v_{tag}.json").read_text(encoding="utf-8"))
    ws = []
    for seg in data["transcription"]:
        for t in seg.get("tokens", []):
            txt = t.get("text", "")
            if txt.startswith("[_") or not txt.strip():
                continue
            o = t["offsets"]
            if txt.startswith(" ") or not ws:
                ws.append({"s": o["from"] / 1000, "e": o["to"] / 1000})
            else:
                ws[-1]["e"] = max(ws[-1]["e"], o["to"] / 1000)
    return ws


def main() -> None:
    fw = WhisperModel(model_path("small"), device="cpu", compute_type="int8", cpu_threads=12)
    st = {"wcpp": {"ini": [], "fim": []}, "fw": {"ini": [], "fim": []}}
    for voice in ("piper", "sapi"):
        for i in range(1, 21):
            wav = rf"F:\Jarvis\tests\audio_{voice}\{i:02d}.wav"
            if not Path(wav).exists() or not (OUT / f"v_{voice}{i:02d}.json").exists():
                continue
            t0, t1 = edges(wav)
            segs, _ = fw.transcribe(load_audio(wav), language="pt", vad_filter=True, beam_size=1,
                                    condition_on_previous_text=False, word_timestamps=True)
            b = [{"s": w.start, "e": w.end} for s in segs for w in (s.words or [])]
            a = wcpp_words(f"{voice}{i:02d}")
            for name, ws in (("wcpp", a), ("fw", b)):
                if ws:
                    st[name]["ini"].append(ws[0]["s"] - t0)
                    st[name]["fim"].append(ws[-1]["e"] - t1)
    res = {}
    for name, d in st.items():
        res[name] = {}
        for k, v in d.items():
            av = [abs(x) for x in v]
            res[name][k] = {"n": len(v), "vies_medio_s": round(statistics.mean(v), 3), "mediana_abs_s": round(statistics.median(av), 3),
                            "p90_abs_s": round(sorted(av)[int(len(av) * 0.9)], 3), "max_abs_s": round(max(av), 3)}
    (OUT / "edges.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("FIM", json.dumps(res))


if __name__ == "__main__":
    main()
