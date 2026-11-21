"""Validação do whisper.cpp (Vulkan) contra o faster-whisper (CPU): WER em clipes limpos de texto conhecido e
diferença de tempo por palavra (sincronia). Resultados em F:\\Jarvis\\work\\bench\\validate.json.
Uso: venv\\Scripts\\python.exe -I src\\bench_validate.py
"""
import difflib, json, statistics, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, r"F:\Jarvis\src\f2")
from stt_bench import load_audio, load_refs, model_path, norm, wer_counts
from faster_whisper import WhisperModel

CLI = r"C:\Users\Bruno Silva\OpenBot\Shared\triade\estudio-br\bin\whispercpp-vulkan\whisper-cli.exe"
MODEL = r"C:\Users\Bruno Silva\OpenBot\Shared\triade\estudio-br\bin\whispercpp-vulkan\ggml-small.bin"
OUT = Path(r"F:\Jarvis\work\bench"); OUT.mkdir(parents=True, exist_ok=True)


def wcpp(wav: str, tag: str) -> list[dict]:
    base = OUT / f"v_{tag}"
    subprocess.run([CLI, "-m", MODEL, "-f", wav, "-l", "pt", "-bs", "1", "-bo", "1", "-ojf", "-of", str(base)],
                   capture_output=True, timeout=600)
    data = json.loads(Path(f"{base}.json").read_text(encoding="utf-8"))
    words = []
    for seg in data["transcription"]:
        for t in seg.get("tokens", []):
            txt = t.get("text", "")
            if txt.startswith("[_") or not txt.strip():
                continue
            o = t["offsets"]
            if txt.startswith(" ") or not words:
                words.append({"w": txt.strip(), "s": o["from"] / 1000, "e": o["to"] / 1000})
            else:
                words[-1]["w"] += txt; words[-1]["e"] = max(words[-1]["e"], o["to"] / 1000)
    return words


def main() -> None:
    refs = load_refs()
    fw = WhisperModel(model_path("small"), device="cpu", compute_type="int8", cpu_threads=12)

    def fwords(audio) -> list[dict]:
        segs, _ = fw.transcribe(audio, language="pt", vad_filter=True, beam_size=1, condition_on_previous_text=False,
                                word_timestamps=True)
        return [{"w": w.word.strip(), "s": w.start, "e": w.end} for s in segs for w in (s.words or [])]

    res = {"clips": [], "tot": {"wcpp": [0, 0], "fw": [0, 0]}}
    deltas: list[float] = []
    for voice in ("piper", "sapi"):
        for i, ref in enumerate(refs, 1):
            wav = rf"F:\Jarvis\tests\audio_{voice}\{i:02d}.wav"
            if not Path(wav).exists():
                continue
            audio = load_audio(wav)
            a, b = wcpp(wav, f"{voice}{i:02d}"), fwords(audio)
            row = {"voice": voice, "n": i}
            for name, ws in (("wcpp", a), ("fw", b)):
                e, n = wer_counts(norm(ref), norm(" ".join(w["w"] for w in ws)))
                row[name] = {"err": e, "n": n}
                res["tot"][name][0] += e; res["tot"][name][1] += n
            # sincronia: palavras casadas entre os motores
            ta, tb = [norm(w["w"]) for w in a], [norm(w["w"]) for w in b]
            fa, fb = [" ".join(x) for x in ta], [" ".join(x) for x in tb]
            sm = difflib.SequenceMatcher(None, fa, fb, autojunk=False)
            for blk in sm.get_matching_blocks():
                for k in range(blk.size):
                    if fa[blk.a + k]:
                        deltas.append(abs(a[blk.a + k]["s"] - b[blk.b + k]["s"]))
            res["clips"].append(row)
            print(voice, i, row["wcpp"], row["fw"], flush=True)
    for name in ("wcpp", "fw"):
        e, n = res["tot"][name]
        res["tot"][name].append(round(e / n, 4) if n else None)
    if deltas:
        deltas.sort()
        res["sync"] = {"palavras_casadas": len(deltas), "mediana_s": round(statistics.median(deltas), 3),
                       "p90_s": round(deltas[int(len(deltas) * 0.9)], 3), "max_s": round(deltas[-1], 3)}
    (OUT / "validate.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("FIM", res["tot"], res.get("sync"))


if __name__ == "__main__":
    main()
