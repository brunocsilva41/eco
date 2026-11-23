<#
.SYNOPSIS
  Teste-fumaca do instalador: confere o SHA-256, instala em silencio numa pasta temporaria, roda os comandos do launcher
  (tools, config, doctor) sem tela, desinstala e confere a limpeza. Nunca toca a instalacao do usuario.
.PARAMETER Installer  Caminho do *-Setup-<versao>.exe (o .sha256 ao lado e obrigatorio).
.PARAMETER Version    Versao esperada (ex.: 0.2.0).
#>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Installer, [Parameter(Mandatory)][string]$Version, [string]$Report = "")
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$rows = New-Object System.Collections.Generic.List[object]
$failed = 0
function Check($name, [scriptblock]$body) {
  $t0 = Get-Date
  try { $r = & $body; $rows.Add([pscustomobject]@{ Etapa = $name; Resultado = "ok"; Detalhe = "$r" }) }
  catch { $script:failed++; $rows.Add([pscustomobject]@{ Etapa = $name; Resultado = "FALHOU"; Detalhe = $_.Exception.Message }); Write-Host "FALHOU: $name :: $($_.Exception.Message)" -ForegroundColor Red }
  Write-Host ("[{0}] {1} ({2:n1}s)" -f $rows[$rows.Count - 1].Resultado, $name, ((Get-Date) - $t0).TotalSeconds)
}
$Installer = (Resolve-Path $Installer).Path
$dir = Join-Path ([IO.Path]::GetTempPath()) ("eco-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$log = Join-Path ([IO.Path]::GetTempPath()) "eco-smoke-install.log"
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONUTF8 = "1"

Check "sha256 do instalador confere com o .sha256" {
  $want = ((Get-Content "$Installer.sha256" -Raw) -split '\s+')[0].ToLower()
  $got = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLower()
  if ($want -ne $got) { throw "esperado $want, veio $got" }
  $got.Substring(0, 16) + "..."
}
Check "instalacao silenciosa (/VERYSILENT) em pasta temporaria" {
  $p = Start-Process -FilePath $Installer -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/DIR=`"$dir`"", "/LOG=`"$log`"", "/TASKS=`"`"") -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "instalador saiu com codigo $($p.ExitCode); veja $log" }
  "codigo 0"
}
$launcher = $null
Check "arquivos essenciais instalados" {
  $launcher = Get-ChildItem $dir -Filter "*.cmd" -File | Where-Object { $_.Name -match '^(Eco|Eco)\.cmd$' } | Select-Object -First 1
  if (-not $launcher) { throw "launcher .cmd nao encontrado" }
  $script:launcher = $launcher.FullName
  foreach ($f in "runtime\python\python.exe", "VERSION", "THIRD-PARTY.txt", "manifest.json") { if (-not (Test-Path (Join-Path $dir $f))) { throw "falta $f" } }
  $v = (Get-Content (Join-Path $dir "VERSION") -Raw).Trim()
  if ($v -ne $Version) { throw "VERSION instalada ($v) difere da esperada ($Version)" }
  "launcher $($launcher.Name), VERSION $v"
}
function Run-Launcher($arguments, $timeoutSec) {
  $o = Join-Path ([IO.Path]::GetTempPath()) ("eco-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 6) + ".txt")
  # cmd /c exige aspas externas quando o comando inteiro comeca com aspas: /c ""caminho" args > "saida" 2>&1"
  $cmdline = '/c ""' + $script:launcher + '" ' + $arguments + ' > "' + $o + '" 2>&1"'
  $p = Start-Process -FilePath "cmd.exe" -ArgumentList $cmdline -WorkingDirectory $dir -PassThru -WindowStyle Hidden
  if (-not $p.WaitForExit($timeoutSec * 1000)) { try { & taskkill /PID $p.Id /T /F | Out-Null } catch {}; throw "tempo esgotado ($timeoutSec s) em '$arguments'" }
  $txt = if (Test-Path $o) { Get-Content $o -Raw -Encoding UTF8 } else { "" }
  Remove-Item $o -Force -ErrorAction SilentlyContinue
  return [pscustomobject]@{ Code = $p.ExitCode; Text = $txt }
}
Check "launcher: tools lista as ferramentas" {
  $r = Run-Launcher "tools" 120
  if ($r.Code -ne 0) { throw "codigo $($r.Code): $($r.Text.Substring(0, [Math]::Min(300, $r.Text.Length)))" }
  if ($r.Text.Length -lt 200) { throw "saida curta demais" }
  "$($r.Text.Split("`n").Count) linhas"
}
Check "launcher: config mostra a configuracao" {
  $r = Run-Launcher "config" 120
  if ($r.Code -ne 0) { throw "codigo $($r.Code): $($r.Text.Substring(0, [Math]::Min(300, $r.Text.Length)))" }
  "$($r.Text.Split("`n").Count) linhas"
}
Check "launcher: doctor roda (sem modelos e sem GPU no runner, avisos esperados)" {
  $r = Run-Launcher "doctor" 180
  if ($r.Text -match 'Traceback \(most recent call last\)') { throw "excecao Python no doctor: $($r.Text.Substring(0, [Math]::Min(300, $r.Text.Length)))" }
  "codigo $($r.Code) (informativo)"
}
Check "desinstalacao silenciosa remove programa e atalhos" {
  $unins = Get-ChildItem $dir -Filter "unins*.exe" | Select-Object -First 1
  if (-not $unins) { throw "desinstalador nao encontrado" }
  $p = Start-Process -FilePath $unins.FullName -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/PURGEDATA=1") -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "desinstalador saiu com codigo $($p.ExitCode)" }
  Start-Sleep -Seconds 3
  $left = @(Get-ChildItem $dir -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { -not $_.PSIsContainer }).Count
  if ($left -gt 0) { throw "$left arquivo(s) restaram em $dir" }
  "pasta limpa"
}
Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue

$md = @("### Teste-fumaca do instalador $Version", "", "| Etapa | Resultado | Detalhe |", "|---|---|---|")
$md += $rows | ForEach-Object { "| $($_.Etapa) | $($_.Resultado) | $(($_.Detalhe -replace '\|', '/') -replace "`r?`n", ' ') |" }
if ($Report) { $md | Set-Content $Report -Encoding UTF8 }
if ($env:GITHUB_STEP_SUMMARY) { $md | Add-Content $env:GITHUB_STEP_SUMMARY -Encoding UTF8 }
if ($failed -gt 0) { Write-Host "$failed etapa(s) falharam" -ForegroundColor Red; exit 1 }
Write-Host "fumaca ok" -ForegroundColor Green
