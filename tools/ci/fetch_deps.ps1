<#
.SYNOPSIS
  Baixa os binarios nativos pre-compilados (whisper.cpp Vulkan) da release de deps do repositorio e confere o SHA-256
  de tools\ci\deps.lock.json. Somente HTTPS; nao grava nada se o hash nao bater.
.PARAMETER Repo
  dono/repo (padrao: $env:GITHUB_REPOSITORY).
.PARAMETER LocalZip
  Usa este zip local em vez de baixar (testes locais); o hash continua sendo conferido.
#>
[CmdletBinding()]
param([string]$Repo = $env:GITHUB_REPOSITORY, [string]$LocalZip = "")
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$lock = (Get-Content (Join-Path $PSScriptRoot "deps.lock.json") -Raw -Encoding UTF8 | ConvertFrom-Json).whispercpp
$dest = Join-Path $Root ($lock.dest -replace '/', '\')
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("eco-deps-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $tmp | Out-Null
$zip = Join-Path $tmp $lock.asset
try {
  if ($LocalZip) { Copy-Item $LocalZip $zip }
  else {
    if (-not $Repo -or $Repo -notmatch '^[\w.-]+/[\w.-]+$') { throw "informe -Repo dono/repo (ou GITHUB_REPOSITORY)" }
    $url = "https://github.com/$Repo/releases/download/$($lock.release_tag)/$($lock.asset)"
    Write-Host "baixando $url"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
  }
  $h = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
  if ($h -ne $lock.sha256) { throw "SHA-256 do pacote de deps NAO confere (esperado $($lock.sha256), veio $h). Nada foi gravado." }
  Write-Host "SHA-256 ok: $h"
  New-Item -ItemType Directory -Force $dest | Out-Null
  Expand-Archive $zip -DestinationPath $dest -Force
  foreach ($f in "jarvis_whisper.dll", "whisper.dll", "ggml.dll", "ggml-vulkan.dll", "ggml-base.dll", "ggml-cpu.dll") {
    if (-not (Test-Path (Join-Path $dest $f))) { throw "pacote de deps incompleto: falta $f" }
  }
  Write-Host "deps prontas em $dest"
} finally { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
