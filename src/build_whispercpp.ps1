$ErrorActionPreference='Continue'
$log='F:\Jarvis\logs\whispercpp-build.log'
"início $(Get-Date)" | Out-File $log
Set-Location F:\Jarvis\work
if(-not (Test-Path whispercpp)){ git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp whispercpp *>> $log }
$vs='C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat'
$cmake='C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$cmd = "`"$vs`" && set `"VULKAN_SDK=E:\vulkan`" && set PATH=%PATH%;E:\vulkan\Bin;" + (Split-Path $cmake) + ";" + 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja' + " && cd /d F:\Jarvis\work\whispercpp && cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=1 -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=ON && cmake --build build -j 2 --target whisper-cli whisper-bench"
cmd /c $cmd *>> $log
"fim $(Get-Date) exit=$LASTEXITCODE" | Out-File $log -Append

