"""Grava as 20 frases de F:\\Jarvis\\tests\\frases_pt.txt com a voz do usuário (para o WER real).
Usa o dispositivo de entrada padrao (o microfone padrão do Windows). Salva 16 kHz mono em tests\\audio_usuario\\NN.wav.
Uso: venv\\Scripts\\python.exe -I src\\f2\\record_usuario.py [--device N] [--seconds 12] [--from 1]
Por frase: ENTER inicia; ENTER de novo para; depois ENTER aceita ou 'r' regrava; 'q' sai.
"""
import argparse
import threading
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(r"F:\Eco")
OUT = ROOT / "tests" / "audio_usuario"
SR = 16000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--seconds", type=float, default=12, help="limite maximo por frase")
    ap.add_argument("--from", dest="start", type=int, default=1)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    frases = [l.strip() for l in (ROOT / "tests" / "frases_pt.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    dev = a.device if a.device is not None else sd.default.device[0]
    print("Microfone:", sd.query_devices(dev)["name"])
    i = a.start
    while i <= len(frases):
        print(f"\n[{i}/{len(frases)}]  Diga:  {frases[i-1]}")
        if input("ENTER = comecar a gravar (q = sair): ").strip().lower() == "q":
            break
        chunks = []
        stop = threading.Event()

        def waiter():
            input("Gravando... ENTER para parar. ")
            stop.set()

        with sd.InputStream(samplerate=SR, channels=1, dtype="int16", device=dev,
                            callback=lambda d, f, t, s: chunks.append(d.copy())):
            threading.Thread(target=waiter, daemon=True).start()
            stop.wait(a.seconds)
        audio = np.concatenate(chunks) if chunks else np.zeros((0, 1), "int16")
        peak = int(np.abs(audio).max()) if audio.size else 0
        print(f"duracao {len(audio)/SR:.1f}s, pico {peak}/32767" + ("  (MUITO BAIXO!)" if peak < 1500 else ""))
        if input("ENTER = aceitar, r = regravar: ").strip().lower() == "r":
            continue
        with wave.open(str(OUT / f"{i:02d}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(audio.tobytes())
        i += 1
    print("Fim. Rode: stt_bench.py --grid --audio-dir tests\\audio_usuario --tag bruno")


if __name__ == "__main__":
    main()
