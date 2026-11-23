<#
  Compila o whisper.cpp v1.9.5 com backend Vulkan (so para quem quer recompilar o pacote de dependencias do instalador).
  Exige: Visual Studio Build Tools (C++ e CMake) e o Vulkan SDK (variavel de ambiente VULKAN_SDK).
  Uso: pwsh -File src\build_whispercpp.ps1 [-Work <pasta de trabalho>] [-BuildTools <pasta do Build Tools>]
#>
param(
  [string]$Work = (Join-Path (Split-Path -Parent $PSScriptRoot) 'work'),
  [string]$BuildTools = (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\18\BuildTools')
)
$ErrorActionPreference = 'Stop'
if (-not $env:VULKAN_SDK) { throw 'Defina a variavel VULKAN_SDK (pasta do Vulkan SDK).' }
$vcvars = Join-Path $BuildTools 'VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path $vcvars)) { throw "vcvars64.bat nao encontrado em $BuildTools" }
$cmakeBin = Join-Path $BuildTools 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin'
$ninja    = Join-Path $BuildTools 'Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja'
New-Item -ItemType Directory -Force $Work | Out-Null
$src = Join-Path $Work 'whispercpp'
if (-not (Test-Path $src)) { git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp $src }
$cmd = "`"$vcvars`" && set PATH=%PATH%;$($env:VULKAN_SDK)\Bin;$cmakeBin;$ninja && cd /d `"$src`" && " +
       'cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl -DGGML_VULKAN=1 -DWHISPER_BUILD_TESTS=OFF && ' +
       'cmake --build build -j 2 --target whisper-cli whisper-bench'
cmd /c $cmd
exit $LASTEXITCODE