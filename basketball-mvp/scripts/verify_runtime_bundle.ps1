$ErrorActionPreference = 'Stop'

param(
  [Parameter(Mandatory = $true)]
  [string]$RuntimeDir
)

if (-not (Test-Path $RuntimeDir)) {
  throw "runtime dir not found: $RuntimeDir"
}

$pythonCandidates = @(
  (Join-Path $RuntimeDir 'python\python.exe'),
  (Join-Path $RuntimeDir 'python\Scripts\python.exe'),
  (Join-Path $RuntimeDir 'python\bin\python3'),
  (Join-Path $RuntimeDir 'python\bin\python')
)

$python = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
  throw "python binary not found under $RuntimeDir\python"
}

$ffmpegCandidates = @(
  (Join-Path $RuntimeDir 'bin\ffmpeg.exe'),
  (Join-Path $RuntimeDir 'bin\ffmpeg')
)

$ffmpeg = $ffmpegCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ffmpeg) {
  throw "ffmpeg binary not found under $RuntimeDir\bin"
}

Write-Host "python: $python"
& $python -c "import cv2, numpy; print('python deps ok')"

Write-Host "ffmpeg: $ffmpeg"
& $ffmpeg -version | Select-Object -First 1

Write-Host "runtime bundle verification passed"
