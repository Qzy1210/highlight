$ErrorActionPreference = 'Stop'

param(
  [ValidateSet('amd64','arm64')]
  [string]$Arch = 'amd64',
  [string]$PythonSeries = '3.11',
  [string[]]$PipPackages = @('numpy','opencv-python-headless'),
  [switch]$SkipPip,
  [switch]$ForceClean
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RuntimeDir = Join-Path $Root ("runtime/windows-" + $Arch)

if ($ForceClean -and (Test-Path $RuntimeDir)) {
  Remove-Item -Recurse -Force $RuntimeDir
}
New-Item -ItemType Directory -Force -Path (Join-Path $RuntimeDir 'bin') | Out-Null

switch ($Arch) {
  'amd64' {
    $targetTriple = 'x86_64-pc-windows-msvc'
    $ffmpegAsset = 'ffmpeg-win32-x64.gz'
  }
  'arm64' {
    $targetTriple = 'aarch64-pc-windows-msvc'
    Write-Warning 'ffmpeg-static currently has no win-arm64 asset; falling back to x64 ffmpeg binary.'
    $ffmpegAsset = 'ffmpeg-win32-x64.gz'
  }
}

function Get-LatestRelease {
  param([string]$Repo)
  $api = "https://api.github.com/repos/$Repo/releases/latest"
  return Invoke-RestMethod -Uri $api -Headers @{ 'User-Agent' = 'basketball-mvp-runtime-prep' }
}

function Download-AssetByRegex {
  param(
    [string]$Repo,
    [string]$NameRegex,
    [string]$OutputPath
  )
  $release = Get-LatestRelease -Repo $Repo
  $matches = @($release.assets | Where-Object { $_.name -match $NameRegex })
  if ($matches.Count -ne 1) {
    $names = ($release.assets | Select-Object -ExpandProperty name | Select-Object -First 80) -join "`n"
    throw "asset match failed repo=$Repo regex=$NameRegex matches=$($matches.Count)`n$names"
  }
  $asset = $matches[0]
  Write-Host "download: $($asset.name)"
  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $OutputPath
}

function Expand-GzipFile {
  param(
    [string]$GzipPath,
    [string]$OutputPath
  )
  $inStream = [System.IO.File]::OpenRead($GzipPath)
  try {
    $gzip = New-Object System.IO.Compression.GZipStream($inStream, [System.IO.Compression.CompressionMode]::Decompress)
    try {
      $outStream = [System.IO.File]::Create($OutputPath)
      try {
        $gzip.CopyTo($outStream)
      } finally {
        $outStream.Dispose()
      }
    } finally {
      $gzip.Dispose()
    }
  } finally {
    $inStream.Dispose()
  }
}

$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("basketball-mvp-runtime-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
try {
  $seriesPattern = [Regex]::Escape($PythonSeries)
  $pythonRegex = '^cpython-' + $seriesPattern + '\..*-' + [Regex]::Escape($targetTriple) + '-install_only\.tar\.gz$'
  $pythonArchive = Join-Path $tmpDir 'python-install.tar.gz'
  Download-AssetByRegex -Repo 'astral-sh/python-build-standalone' -NameRegex $pythonRegex -OutputPath $pythonArchive

  if (Test-Path (Join-Path $RuntimeDir 'python')) {
    Remove-Item -Recurse -Force (Join-Path $RuntimeDir 'python')
  }
  tar -xzf $pythonArchive -C $RuntimeDir

  $ffmpegGz = Join-Path $tmpDir 'ffmpeg.gz'
  Download-AssetByRegex -Repo 'eugeneware/ffmpeg-static' -NameRegex ('^' + [Regex]::Escape($ffmpegAsset) + '$') -OutputPath $ffmpegGz
  Expand-GzipFile -GzipPath $ffmpegGz -OutputPath (Join-Path $RuntimeDir 'bin\ffmpeg.exe')

  $pythonExe = Join-Path $RuntimeDir 'python\python.exe'
  if (-not (Test-Path $pythonExe)) {
    throw "python executable not found: $pythonExe"
  }

  if (-not $SkipPip) {
    Write-Host 'install pip packages into runtime\python ...'
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install --no-cache-dir @PipPackages
  } else {
    Write-Host 'skip pip install by -SkipPip'
  }

  $meta = @(
    "platform=windows"
    "arch=$Arch"
    "python_series=$PythonSeries"
    "pip_packages=$($PipPackages -join ' ')"
    "generated_at=$([DateTime]::UtcNow.ToString('s'))Z"
  )
  Set-Content -Path (Join-Path $RuntimeDir 'RUNTIME_INFO.txt') -Value $meta -Encoding UTF8

  Write-Host "Prepared runtime: $RuntimeDir"
  Write-Host "Python: $pythonExe"
  Write-Host "FFmpeg: $(Join-Path $RuntimeDir 'bin\ffmpeg.exe')"
}
finally {
  if (Test-Path $tmpDir) {
    Remove-Item -Recurse -Force $tmpDir
  }
}
