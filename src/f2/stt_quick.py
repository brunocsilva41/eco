import sys, time, glob
sys.path.insert(0, r"F:\Jarvis\src\f2")
from stt_bench import load_audio, load_refs, norm, wer_counts, model_path
from faster_whisper import WhisperModel
name, thr = sys.argv[1], int(sys.argv[2])
try: p = model_path(name)
except SystemExit: p = name
t=time.time(); m = WhisperModel(p, device="cpu", compute_type="int8", cpu_threads=thr, download_root=r"F:\Jarvis\models\whisper\hf_"+name); print("carga", round(time.time()-t,1))
refs = load_refs(); E=N=0; ts=[]
for i in range(6):
    a = load_audio(rf"F:\Jarvis\tests\audio_piper\{i+1:02d}.wav")
    t=time.time(); segs,_ = m.transcribe(a, language="pt", beam_size=1, vad_filter=False); txt=" ".join(s.text for s in segs); dt=time.time()-t
    if i>0: ts.append(dt)
    e,n = wer_counts(norm(refs[i]), norm(txt)); E+=e; N+=n
    print(i+1, round(dt,2), txt)
print(name, thr, "media", round(sum(ts)/len(ts),2), "WER6", round(E/N,3))
