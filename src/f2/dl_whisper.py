import sys
from faster_whisper.utils import download_model
for n in sys.argv[1:]:
    p = download_model(n, cache_dir=r"F:\Jarvis\models\whisper\hf_cache_"+n) if False else download_model(n, cache_dir=r"F:\Jarvis\models\whisper\hf_"+n)
    print(n, p, flush=True)
