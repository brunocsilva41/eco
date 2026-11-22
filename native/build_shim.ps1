# Compila o shim jarvis_whisper.dll (precisa do Visual Studio Build Tools e do código do whisper.cpp já compilado em work\whispercpp).
# Uso: pwsh native\build_shim.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vs = 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat'
$wc = Join-Path $root 'work\whispercpp'
$out = Join-Path $root 'bin\whispercpp-vulkan'
New-Item -ItemType Directory -Force $out | Out-Null
$cl = "`"$vs`" >nul && cd /d `"$PSScriptRoot`" && cl /nologo /O2 /LD /MD jarvis_whisper.c /I`"$wc\include`" /I`"$wc\ggml\include`" `"$wc\build\src\whisper.lib`" `"$wc\build\ggml\src\ggml-base.lib`" /Fe:`"$out\jarvis_whisper.dll`" /Fo:`"$env:TEMP\\`" /link /nologo"
cmd /c $cl
if ($LASTEXITCODE -ne 0) { throw "cl falhou ($LASTEXITCODE)" }
foreach ($f in 'whisper.dll', 'ggml.dll', 'ggml-base.dll', 'ggml-cpu.dll', 'ggml-vulkan.dll') {
    Copy-Item (Join-Path $wc "build\bin\$f") $out -Force
}
Copy-Item (Join-Path $wc 'LICENSE') (Join-Path $out 'LICENSE-whisper.cpp.txt') -Force
Remove-Item "$out\jarvis_whisper.lib", "$out\jarvis_whisper.exp" -ErrorAction SilentlyContinue
Get-ChildItem $out | Select-Object Name, Length
