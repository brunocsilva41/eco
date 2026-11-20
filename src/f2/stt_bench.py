"""Benchmark faster-whisper (CPU, int8) em pt-BR.

Uso (um modelo/threads por processo, para RAM de pico confiavel):
  venv\\Scripts\\python.exe -I src\\f2\\stt_bench.py --model small --threads 12 --audio-dir tests\\audio_sapi --tag sapi
Grade completa (cada combinacao modelo x threads em subprocesso):
  venv\\Scripts\\python.exe -I src\\f2\\stt_bench.py --grid --audio-dir tests\\audio_sapi --tag sapi
Resultados: JSON-lines em tests\\stt_results_<tag>.jsonl
Sempre CPU (device='cpu'); a GPU fica reservada ao LLM.
Modelos baixados por src\\f2\\dl_whisper.py em models\\whisper\\hf_<nome>.
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"F:\Jarvis")
MODELS_DIR = ROOT / "models" / "whisper"
FRASES = ROOT / "tests" / "frases_pt.txt"


def norm(t: str) -> list[str]:
    t = t.lower().replace("%", " por cento ")
    t = "".join(c if (c.isalnum() or c.isspace()) else " " for c in t)
    return t.split()


def wer_counts(ref: list[str], hyp: list[str]) -> tuple[int, int]:
    """Distancia de edicao de palavras (Levenshtein). Retorna (erros, n_ref)."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1], len(ref)


def load_refs() -> list[str]:
    return [l.strip() for l in FRASES.read_text(encoding="utf-8").splitlines() if l.strip()]


def model_path(name: str) -> str:
    base = MODELS_DIR / f"hf_{name}"
    snaps = list(base.glob("models--*/snapshots/*"))
    if not snaps:
        raise SystemExit(f"modelo {name} nao encontrado em {base}")
    return str(snaps[0])


def load_audio(path):
    """Decodifica para float32 mono 16 kHz com PyAV. (faster-whisper 1.2.1 chama av.open(metadata_errors=...),
    incompativel com av 19 deste venv; por isso decodificamos aqui e passamos o array.)"""
    import av
    import numpy as np
    res = av.AudioResampler(format="s16", layout="mono", rate=16000)
    parts = []
    with av.open(str(path)) as c:
        for fr in c.decode(audio=0):
            for r in res.resample(fr):
                parts.append(r.to_ndarray().reshape(-1))
        for r in res.resample(None):
            parts.append(r.to_ndarray().reshape(-1))
    return np.concatenate(parts).astype("float32") / 32768.0


def run_one(args):
    import psutil
    from faster_whisper import WhisperModel
    proc = psutil.Process()
    refs = load_refs()
    files = sorted(Path(args.audio_dir).glob("*.wav"))[: args.limit]
    t0 = time.perf_counter()
    model = WhisperModel(model_path(args.model), device="cpu", compute_type="int8",
                         cpu_threads=args.threads, num_workers=1)
    load_s = time.perf_counter() - t0
    rss_load = proc.memory_info().rss / 2**20
    segs, _ = model.transcribe(load_audio(files[0]), language="pt", beam_size=1)  # aquecimento, nao contado
    list(segs)
    out = Path(args.out or ROOT / "tests" / f"stt_results_{args.tag}.jsonl")
    for beam in args.beams:
        for vad in args.vads:
            times, rtfs, errs, nref, hyps = [], [], 0, 0, []
            for k, f in enumerate(files):
                audio = load_audio(f)  # decodificacao fora da medicao
                t = time.perf_counter()
                segs, info = model.transcribe(audio, language="pt", beam_size=beam,
                                              vad_filter=bool(vad), condition_on_previous_text=False)
                text = " ".join(s.text.strip() for s in segs)
                dt = time.perf_counter() - t
                times.append(dt)
                rtfs.append(dt / max(info.duration, 1e-6))
                hyps.append(text)
                if k < len(refs):
                    e, n = wer_counts(norm(refs[k]), norm(text))
                    errs += e
                    nref += n
            mi = proc.memory_info()
            rec = dict(tag=args.tag, model=args.model, threads=args.threads, beam=beam, vad=vad,
                       n=len(files), load_s=round(load_s, 2),
                       mean_s=round(sum(times) / len(times), 3), min_s=round(min(times), 3),
                       max_s=round(max(times), 3), rtf=round(sum(rtfs) / len(rtfs), 3),
                       rss_after_load_mb=round(rss_load), rss_now_mb=round(mi.rss / 2**20),
                       peak_wset_mb=round(mi.peak_wset / 2**20),
                       wer=round(errs / max(nref, 1), 4), hyps=hyps,
                       when=time.strftime("%Y-%m-%d %H:%M:%S"))
            with open(out, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print({k: v for k, v in rec.items() if k != "hyps"}, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small")
    ap.add_argument("--threads", type=int, default=12)
    ap.add_argument("--beams", type=int, nargs="+", default=[1, 5])
    ap.add_argument("--vads", type=int, nargs="+", default=[0, 1])
    ap.add_argument("--audio-dir", default=str(ROOT / "tests" / "audio_sapi"))
    ap.add_argument("--tag", default="sapi")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--grid-models", nargs="+", default=["small", "medium", "large-v3-turbo"])
    ap.add_argument("--grid-threads", type=int, nargs="+", default=[8, 12, 24])
    a = ap.parse_args()
    if a.grid:
        for m in a.grid_models:
            for th in a.grid_threads:
                subprocess.run([sys.executable, "-I", __file__, "--model", m, "--threads", str(th),
                                "--audio-dir", a.audio_dir, "--tag", a.tag, "--limit", str(a.limit),
                                "--beams", *map(str, a.beams), "--vads", *map(str, a.vads)], check=False)
    else:
        run_one(a)


if __name__ == "__main__":
    main()
