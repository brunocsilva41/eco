import sys, time, glob, json
sys.path.insert(0, r"F:\Jarvis\src\f2")
from stt_bench import load_audio, model_path
from faster_whisper import WhisperModel
a = load_audio(r"F:\Jarvis\work\bench\clip.wav")
beam = int(sys.argv[1])
t=time.time(); m = WhisperModel(model_path("small"), device="cpu", compute_type="int8", cpu_threads=12); tl=time.time()-t
t=time.time(); segs,_ = m.transcribe(a, language="pt", beam_size=beam, word_timestamps=True)
words=[w for s in segs for w in s.words]; tt=time.time()-t
open(rf"F:\Jarvis\work\bench\fw_beam{beam}.txt","w",encoding="utf-8").write(" ".join(w.word.strip() for w in words))
print(f"faster-whisper small int8 CPU beam{beam}: carga {tl:.1f}s, transcricao {tt:.1f}s, palavras {len(words)}")
