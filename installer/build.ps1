<#
.SYNOPSIS
  Build reproduzivel do instalador do Eco (Inno Setup 6): Eco-Setup-<versao>.exe + SHA-256 + notas.

.DESCRIPTION
  (a) valida installer\VERSION (semver)   (b) monta installer\staging\app so com o necessario (sem work, logs, data, .git,
  __pycache__, tests, modelos, venv)   (c) prepara o runtime Python (embeddable oficial 3.14.3 + wheels travadas por hash)
  (d) roda o ISCC   (e) gera o .exe, o .sha256 e as notas em installer\dist.

  Tudo fica dentro de F:\Jarvis\installer (cache\, wheels\, staging\, dist\, tools\). Nao altera PATH, registro global, nem
  nada fora dessa pasta. Inno Setup: usa o que ja estiver instalado; se nao houver, baixa o instalador OFICIAL e instala POR USUARIO
  em installer\tools\InnoSetup (sem admin), conferindo a assinatura digital.

  Assinatura de codigo (OPCIONAL, nunca inventamos certificado): defina a variavel de ambiente JARVIS_SIGN_CMD com o comando do
  signtool, usando $f onde vai o arquivo. Ex.: signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f C:\cert.pfx /p SENHA $f
  Sem a variavel o instalador sai SEM assinatura (o Windows SmartScreen vai avisar "editor desconhecido").

.PARAMETER Relock
  Rebaixa as wheels (pip download) e regera requirements.lock.txt com os hashes.
.PARAMETER Fast
  Compressao rapida (testes). O release usa lzma2/max.
.PARAMETER NoWait
  Nao espera a carga da maquina baixar antes do build pesado.
#>
[CmdletBinding()]
param(
  [switch]$Relock,
  [switch]$Fast,
  [switch]$NoWait,
  [string]$OutDir = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Installer = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Split-Path -Parent $Installer
$Cache     = Join-Path $Installer "cache"
$Wheels    = Join-Path $Installer "wheels"
$Staging   = Join-Path $Installer "staging"
$App       = Join-Path $Staging "app"
$Dist      = if ($OutDir) { $OutDir } else { Join-Path $Installer "dist" }
$Tools     = Join-Path $Installer "tools"
$VenvPy    = Join-Path $Root "venv\Scripts\python.exe"
$Manifest  = Get-Content (Join-Path $Installer "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json

function Step($n, $msg) { Write-Host ""; Write-Host "[$n] $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERRO: $msg" -ForegroundColor Red; exit 1 }

# ------------------------------------------------------------------ (a) VERSION
Step "a" "Validando VERSION"
$verFile = Join-Path $Installer "VERSION"
if (-not (Test-Path $verFile)) { Fail "installer\VERSION nao existe" }
$Version = (Get-Content $verFile -Raw).Trim()
if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$') { Fail "VERSION '$Version' nao e semver (MAJOR.MINOR.PATCH[-pre][+build])" }
$VersionNum = "$($Matches[1]).$($Matches[2]).$($Matches[3]).0"
Write-Host "Versao $Version (arquivo $VersionNum)"

# ------------------------------------------------------------------ carga da maquina (producao de video compartilha este PC)
if (-not $NoWait) {
  $busy = Get-Process ffmpeg, blender -ErrorAction SilentlyContinue
  $load = (Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average
  Write-Host ("ffmpeg/blender ativos: {0}; carga de CPU: {1}%" -f @($busy).Count, [int]$load)
  $tries = 0
  while ($load -gt 85 -and $tries -lt 30) {
    Write-Host "carga alta; aguardando 10 s (nao mato processos alheios)..."
    Start-Sleep -Seconds 10
    $load = (Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average
    $tries++
  }
}
# o build roda em prioridade baixa para nao competir com renders
try { (Get-Process -Id $PID).PriorityClass = "BelowNormal" } catch {}

if (-not (Test-Path $VenvPy)) { Fail "venv de desenvolvimento nao encontrado em $VenvPy (usado so para baixar/instalar wheels do mesmo Python 3.14.3)" }
New-Item -ItemType Directory -Force $Cache, $Wheels, $Dist | Out-Null

function Get-Verified($url, $dest, $sha256) {
  if ((Test-Path $dest) -and ((Get-FileHash $dest -Algorithm SHA256).Hash.ToLower() -eq $sha256)) { return }
  Write-Host "baixando $url"
  if ($url -notmatch '^https://') { Fail "somente https: $url" }
  Invoke-WebRequest -Uri $url -OutFile "$dest.part" -UseBasicParsing
  $h = (Get-FileHash "$dest.part" -Algorithm SHA256).Hash.ToLower()
  if ($h -ne $sha256) { Remove-Item "$dest.part" -Force; Fail "SHA-256 de $dest nao confere (esperado $sha256, veio $h)" }
  Move-Item "$dest.part" $dest -Force
}

# ------------------------------------------------------------------ insumos oficiais
Step "b" "Insumos oficiais (cache em installer\cache, SHA-256 do manifest.json)"
$llama = $Manifest.bundled | Where-Object { $_.id -eq "llama.cpp" }
$pyemb = $Manifest.bundled | Where-Object { $_.id -eq "python-embed" }
$llamaZip = Join-Path $Cache "llama-vulkan.zip"
$pyZip    = Join-Path $Cache "python-embed.zip"
Get-Verified $llama.url $llamaZip $llama.sha256
Get-Verified $pyemb.url $pyZip $pyemb.sha256

# ------------------------------------------------------------------ wheels travadas
Step "c" "Wheels (offline, travadas por hash)"
$lock = Join-Path $Installer "requirements.lock.txt"
if ($Relock -or -not (Test-Path $lock)) {
  & $VenvPy -m pip download --only-binary=:all: --no-deps -d $Wheels -r (Join-Path $Installer "requirements.lock.in.txt") | Out-Host
  if ($LASTEXITCODE -ne 0) { Fail "pip download falhou" }
  & $VenvPy -I (Join-Path $Installer "make_lock.py") | Out-Host
  if ($LASTEXITCODE -ne 0) { Fail "make_lock falhou" }
} elseif (-not (Get-ChildItem $Wheels -Filter *.whl -ErrorAction SilentlyContinue)) {
  & $VenvPy -m pip download --only-binary=:all: --no-deps --require-hashes -d $Wheels -r $lock | Out-Host
  if ($LASTEXITCODE -ne 0) { Fail "pip download (com hashes) falhou" }
}

# ------------------------------------------------------------------ staging
Step "d" "Montando staging (so o necessario)"
if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
New-Item -ItemType Directory -Force $App | Out-Null

# codigo: src\jarvis sem __pycache__ nem testes
$rc = robocopy (Join-Path $Root "src\jarvis") (Join-Path $App "src\jarvis") /E /XD __pycache__ tests test .git /XF *.pyc *.pyo /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { Fail "robocopy do codigo falhou ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0

# llama.cpp (Vulkan): so o servidor e as bibliotecas
$llamaDst = Join-Path $App "bin\llama-b12531-vulkan"
Expand-Archive $llamaZip -DestinationPath $llamaDst -Force
Get-ChildItem $llamaDst -Filter *.exe | Where-Object { $_.Name -ne "llama-server.exe" } | Remove-Item -Force

# whisper.cpp (Vulkan) + shim jarvis_whisper.dll: motor de escuta na GPU (compilado aqui por native\build_shim.ps1; MIT)
$wcSrc = Join-Path $Root "bin\whispercpp-vulkan"
if (-not (Test-Path (Join-Path $wcSrc "jarvis_whisper.dll"))) { & pwsh -NoProfile -File (Join-Path $Root "native\build_shim.ps1") | Out-Host }
if (-not (Test-Path (Join-Path $wcSrc "jarvis_whisper.dll"))) { Fail "faltam os binarios do whisper.cpp (bin\whispercpp-vulkan): rode src\build_whispercpp.ps1 e native\build_shim.ps1" }
$wcDst = Join-Path $App "bin\whispercpp-vulkan"
New-Item -ItemType Directory -Force $wcDst | Out-Null
Get-ChildItem $wcSrc -File | Where-Object { $_.Extension -in ".dll", ".txt" } | Copy-Item -Destination $wcDst -Force

# runtime Python embutido
$pyDst = Join-Path $App "runtime\python"
Expand-Archive $pyZip -DestinationPath $pyDst -Force
$pyExe = Join-Path $pyDst "python.exe"
$sig = Get-AuthenticodeSignature $pyExe
if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") {
  Fail "python.exe do embeddable sem assinatura valida da PSF (status $($sig.Status))"
}
$pth = Get-ChildItem $pyDst -Filter "python*._pth" | Select-Object -First 1
$zipName = (Get-ChildItem $pyDst -Filter "python*.zip" | Select-Object -First 1).Name
Set-Content -Path $pth.FullName -Value @($zipName, ".", "Lib\site-packages", "import site") -Encoding ASCII
$site = Join-Path $pyDst "Lib\site-packages"
New-Item -ItemType Directory -Force $site | Out-Null
& $VenvPy -m pip install --no-index --find-links $Wheels --require-hashes --only-binary=:all: --no-deps --target $site -r $lock --disable-pip-version-check | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "pip install --target falhou" }
Remove-Item (Join-Path $site "bin") -Recurse -Force -ErrorAction SilentlyContinue

# DLLs do runtime C++ (implantacao app-local permitida pela Microsoft): so as que faltarem, para PCs sem o VC++ Redistributable
$crt = "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll"
foreach ($d in @($pyDst, $llamaDst, $wcDst)) {
  foreach ($n in $crt) {
    $src = Join-Path $env:SystemRoot "System32\$n"
    if ((Test-Path $src) -and -not (Test-Path (Join-Path $d $n))) { Copy-Item $src $d }
  }
}

# pyc do projeto (primeira partida rapida mesmo em Program Files, onde o usuario nao grava)
& $pyExe -I -X utf8 -m compileall -q -s $App -p "<eco>" (Join-Path $App "src\jarvis") | Out-Null

# arquivos da raiz
foreach ($f in "Eco.cmd", "Eco.pyw", "eco_boot.py") { Copy-Item (Join-Path $Installer "payload\$f") $App }
Copy-Item $verFile (Join-Path $App "VERSION")
Copy-Item (Join-Path $Installer "manifest.json") $App
Copy-Item (Join-Path $Installer "assets\eco.ico") $App
Copy-Item (Join-Path $Installer "LICENSE.pt-BR.txt") $App
Copy-Item (Join-Path $Installer "LICENSE.en.txt") $App
& $VenvPy -I (Join-Path $Installer "make_notices.py") $site (Join-Path $App "THIRD-PARTY.txt") | Out-Host

# conferencia: nada proibido no staging
$bad = Get-ChildItem $App -Recurse -Force -ErrorAction SilentlyContinue | Where-Object {
  ($_.FullName -replace [regex]::Escape($App), "") -match '^\\(work|logs|data|models|venv|\.git|tests)(\\|$)' -or
  ($_.FullName -like "*\src\jarvis\*" -and $_.FullName -like "*\tests\*")
}
if ($bad) { Fail "staging contem itens proibidos: $($bad[0].FullName)" }
if (Test-Path (Join-Path $App "config.toml")) { Fail "staging contem config.toml (o pacote deve usar o padrao)" }
# varredura de privacidade: nada pessoal no codigo/arquivos empacotados (fora de site-packages e binarios)
# 'usuário' como NOME DO DONO em comentarios/prompts do codigo e so aviso (nao e dado pessoal); caminhos de usuario, e-mails e 'Fuxi' reprovam
$warn = @(Get-ChildItem (Join-Path $App "src") -Recurse -File -Include *.py | Select-String -Pattern 'usuário' -List)
if ($warn.Count -gt 0) { Write-Host ("AVISO: 'usuário' aparece em {0} arquivo(s) do codigo (nome do dono em prompts/comentarios); nao e caminho nem dado pessoal." -f $warn.Count) -ForegroundColor Yellow }
$pat = 'C:\\Users\\[A-Za-z]|Fuxi|[A-Za-z0-9._-]+@[A-Za-z0-9-]+\.(com|br|org|net)'
$hits = @(Get-ChildItem (Join-Path $App "src") -Recurse -File -Include *.py,*.json,*.txt,*.md,*.toml | Select-String -Pattern $pat -List)
$hits += @(Get-ChildItem $App -File -Include *.cmd,*.pyw,*.py,*.json,*.txt | Select-String -Pattern $pat -List)
if ($hits.Count -gt 0) { $hits | ForEach-Object { Write-Host ("PESSOAL? {0}:{1}: {2}" -f $_.Path, $_.LineNumber, $_.Line.Trim()) -ForegroundColor Yellow }; Fail "varredura de privacidade encontrou termos pessoais no staging (veja acima)" }
$sizeMB = [math]::Round(((Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB)
Write-Host "staging pronto: $sizeMB MB em $App"

# ------------------------------------------------------------------ Inno Setup
Step "e" "Inno Setup (ISCC)"
function Find-Iscc {
  foreach ($c in @((Join-Path $Tools "InnoSetup\ISCC.exe"),
                   (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
                   (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
                   (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"))) {
    if ($c -and (Test-Path $c)) { return $c }
  }
  return $null
}
$iscc = Find-Iscc
if (-not $iscc) {
  Write-Host "Inno Setup nao encontrado: baixando o instalador OFICIAL (jrsoftware.org) e instalando por usuario em installer\tools\InnoSetup"
  $isExe = Join-Path $Cache "innosetup-6.7.4.exe"
  if (-not (Test-Path $isExe)) { Invoke-WebRequest -Uri "https://files.jrsoftware.org/is/6/innosetup-6.7.4.exe" -OutFile $isExe -UseBasicParsing }
  $isig = Get-AuthenticodeSignature $isExe
  if ($isig.Status -ne "Valid") { Fail "instalador do Inno Setup sem assinatura valida ($($isig.Status)); abortando" }
  New-Item -ItemType Directory -Force (Join-Path $Tools "InnoSetup") | Out-Null
  & $isExe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /NOICONS "/DIR=$(Join-Path $Tools 'InnoSetup')" | Out-Null
  $iscc = Find-Iscc
  if (-not $iscc) { Fail "nao consegui instalar o Inno Setup" }
}
Write-Host "ISCC: $iscc"

$IsccArgs = @("/DAppVersion=$Version", "/DAppVersionNum=$VersionNum", "/DStagingDir=staging\app", "/DOutDir=$Dist")
if ($Fast) { $IsccArgs += "/DFastCompression=1" }
$signNote = "SEM assinatura de codigo"
if ($env:JARVIS_SIGN_CMD) {
  $IsccArgs += "/Sjarvissign=$($env:JARVIS_SIGN_CMD)"
  $IsccArgs += "/DSignTool=jarvissign"
  $signNote = "assinado via JARVIS_SIGN_CMD"
}
$iss = Join-Path $Installer "Eco.iss"
if ($Fast) {
  $tmpIss = Join-Path $Installer "Eco.fast.iss"
  (Get-Content $iss -Raw -Encoding UTF8) -replace 'Compression=lzma2/max', 'Compression=lzma2/fast' | Set-Content $tmpIss -Encoding UTF8
  $iss = $tmpIss
}
$t0 = Get-Date
$log = Join-Path $Dist "iscc.log"
$p = Start-Process -FilePath $iscc -ArgumentList ($IsccArgs + @("`"$iss`"")) -WorkingDirectory $Installer -NoNewWindow -Wait -PassThru -RedirectStandardOutput $log
if ($Fast -and (Test-Path (Join-Path $Installer "Eco.fast.iss"))) { Remove-Item (Join-Path $Installer "Eco.fast.iss") -Force }
if ($p.ExitCode -ne 0) { Get-Content $log -Tail 30 | Out-Host; Fail "ISCC falhou (codigo $($p.ExitCode)); veja $log" }
Write-Host ("compilado em {0:n0} s" -f ((Get-Date) - $t0).TotalSeconds)

# ------------------------------------------------------------------ hash + notas
Step "f" "Hash e notas"
$exe = Join-Path $Dist "Eco-Setup-$Version.exe"
if (-not (Test-Path $exe)) { Fail "saida esperada nao encontrada: $exe" }
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$exe.sha256" -Value "$hash *$(Split-Path -Leaf $exe)" -Encoding ASCII
$commit = ""
try { $commit = (git -C $Root rev-parse --short HEAD 2>$null) } catch {}
$sizeInst = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$sigStatus = (Get-AuthenticodeSignature $exe).Status
$notes = @"
# Eco $Version - notas do instalador

- Arquivo: ``$(Split-Path -Leaf $exe)`` ($sizeInst MB)
- SHA-256: ``$hash``
- Data do build: $(Get-Date -Format "yyyy-MM-dd HH:mm")
- Commit: $commit
- Assinatura de codigo: $signNote (status do Windows: $sigStatus)
- Requisitos: Windows 10 21H2 (19044) ou 11, x64, 12 GB de RAM ou mais (16 GB recomendado), GPU com Vulkan (AMD/NVIDIA/Intel) para velocidade.
- Conteudo: Eco + Python 3.14.3 embutido + llama.cpp b12531 (Vulkan). Os modelos (~3,5 GB) NAO estao no instalador: sao baixados pelo
  assistente de configuracao (HTTPS, SHA-256, retomada) ou importados de um pacote offline (pasta Eco-Modelos ao lado do instalador).
- Instalacao silenciosa: ``Eco-Setup-$Version.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\\Pasta" /LOG="install.log" [/DOWNLOADMODELS=1] [/OFFLINEPACK="C:\\Eco-Modelos"]``
- Desinstalacao silenciosa: ``unins000.exe /VERYSILENT [/PURGEDATA=1] [/KEEPMODELS=1]`` (por padrao MANTEM dados do usuario e remove modelos)

## Modelos (manifest.json)
$((($Manifest.packages | ForEach-Object { "- $($_.name): licenca $($_.license)" }) -join "`n"))
"@
Set-Content -Path (Join-Path $Dist "Eco-Setup-$Version-NOTAS.md") -Value $notes -Encoding UTF8
Write-Host ""
Write-Host "PRONTO: $exe ($sizeInst MB)" -ForegroundColor Green
Write-Host "SHA-256: $hash"
