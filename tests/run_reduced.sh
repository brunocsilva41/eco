P=F:/Jarvis/venv/Scripts/python.exe
B="$P -I F:/Jarvis/src/f2/stt_bench.py --audio-dir F:/Jarvis/tests/audio_piper --tag piper --limit 6"
$B --model small --threads 8 --beams 1 --vads 0
$B --model small --threads 12 --beams 1 5 --vads 0 1
$B --model small --threads 24 --beams 1 --vads 0
$B --model large-v3-turbo --threads 12 --beams 1 5 --vads 0 1
$B --model large-v3-turbo --threads 8 --beams 1 --vads 0
$B --model large-v3-turbo --threads 24 --beams 1 --vads 0
$B --model medium --threads 12 --beams 1 --vads 0
$B --model medium --threads 24 --beams 1 --vads 0
