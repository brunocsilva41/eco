<#
.SYNOPSIS
  Monta os assets da release a partir do instalador: <Nome>-Setup-<versao>.exe + .sha256 + alias estavel Eco-Setup.exe (+ .sha256),
  conferindo os hashes. O alias permite o link direto /releases/latest/download/Eco-Setup.exe.
#>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Dist, [Parameter(Mandatory)][string]$Version, [Parameter(Mandatory)][string]$Out, [string]$Notes = "")
$ErrorActionPreference = "Stop"
$exe = Get-ChildItem $Dist -Filter "*-Setup-$Version.exe" -File | Select-Object -First 1
if (-not $exe) { throw "instalador *-Setup-$Version.exe nao encontrado em $Dist" }
if ($exe.Name -ne "Eco-Setup-$Version.exe") { throw "nome inesperado do instalador: $($exe.Name) (esperado Eco-Setup-$Version.exe)" }
$shaFile = "$($exe.FullName).sha256"
if (-not (Test-Path $shaFile)) { throw "falta $($exe.Name).sha256" }
$want = ((Get-Content $shaFile -Raw) -split '\s+')[0].ToLower()
$got = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash.ToLower()
if ($want -ne $got) { throw "SHA-256 nao confere (arquivo $want, calculado $got)" }
New-Item -ItemType Directory -Force $Out | Out-Null
Copy-Item $exe.FullName (Join-Path $Out $exe.Name)
Set-Content (Join-Path $Out "$($exe.Name).sha256") "$got *$($exe.Name)" -Encoding ASCII
Copy-Item $exe.FullName (Join-Path $Out "Eco-Setup.exe")
Set-Content (Join-Path $Out "Eco-Setup.exe.sha256") "$got *Eco-Setup.exe" -Encoding ASCII
$alias = (Get-FileHash (Join-Path $Out "Eco-Setup.exe") -Algorithm SHA256).Hash.ToLower()
if ($alias -ne $got) { throw "alias difere do original" }
if ($Notes -and (Test-Path $Notes)) { Copy-Item $Notes (Join-Path $Out "RELEASE-NOTES.md") }
Get-ChildItem $Out | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 2) } } | Format-Table -AutoSize | Out-String | Write-Host
Write-Host "assets prontos em $Out; sha256 $got"
