$ErrorActionPreference = 'Stop'

param(
  [ValidateSet('amd64','arm64')]
  [string]$Arch = 'amd64',
  [switch]$RequireRuntime
)

$Root = Split-Path -Parent $PSScriptRoot
$AppGo = Join-Path $Root 'app-go'
$Dist = Join-Path $Root ("dist/windows-" + $Arch)
$ResProject = Join-Path $Dist 'resources/project'

if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
New-Item -ItemType Directory -Force -Path $ResProject | Out-Null

Push-Location $AppGo
$env:GOOS = 'windows'
$env:GOARCH = $Arch
go build -o (Join-Path $Dist 'basketball_mvp_server.exe') ./cmd/app
go build -o (Join-Path $Dist 'BasketballMVP.exe') ./cmd/desktop
Pop-Location

Copy-Item -Recurse -Force (Join-Path $Root 'engine-py') (Join-Path $ResProject 'engine-py')
Copy-Item -Recurse -Force (Join-Path $Root 'configs') (Join-Path $ResProject 'configs')
New-Item -ItemType Directory -Force -Path (Join-Path $ResProject 'app-go') | Out-Null
Copy-Item -Recurse -Force (Join-Path $Root 'app-go/web') (Join-Path $ResProject 'app-go/web')

$runtimeSrc = Join-Path $Root ("runtime/windows-" + $Arch)
$runtimeDst = Join-Path $ResProject 'runtime'
if (Test-Path $runtimeSrc) {
  New-Item -ItemType Directory -Force -Path $runtimeDst | Out-Null
  Copy-Item -Recurse -Force (Join-Path $runtimeSrc '*') $runtimeDst
  Write-Host "Bundled runtime from: $runtimeSrc"
} else {
  if ($RequireRuntime) {
    throw "Runtime bundle not found: $runtimeSrc"
  }
  Write-Warning "Runtime bundle not found: $runtimeSrc . Package will fallback to system Python/FFmpeg."
}

@'
@echo off
setlocal
set BASKETBALL_MVP_ROOT=%~dp0resources\project
set BASKETBALL_MVP_DATA=%APPDATA%\BasketballMVP\workspace
if exist "%~dp0resources\project\runtime\python\python.exe" set BASKETBALL_MVP_PYTHON=%~dp0resources\project\runtime\python\python.exe
if exist "%~dp0resources\project\runtime\bin\ffmpeg.exe" set BASKETBALL_MVP_FFMPEG=%~dp0resources\project\runtime\bin\ffmpeg.exe
start "" "%~dp0BasketballMVP.exe"
'@ | Set-Content -Encoding ascii (Join-Path $Dist 'run.bat')

Write-Host "Built Windows package: $Dist"
