#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ARCH_INPUT="host"
PYTHON_SERIES="${PYTHON_SERIES:-3.11}"
PIP_PACKAGES="${PIP_PACKAGES:-numpy opencv-python-headless}"
SKIP_PIP="0"
FORCE_CLEAN="0"
OUTPUT_ROOT="$ROOT_DIR/runtime"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/prepare_runtime_macos.sh [--arch host|arm64|amd64] [--python-series 3.11] [--skip-pip] [--force-clean]

Env:
  PYTHON_SERIES     Python major.minor line (default: 3.11)
  PIP_PACKAGES      Packages installed into runtime python (default: "numpy opencv-python-headless")

Output:
  runtime/macos-<arch>/
    python/...
    bin/ffmpeg
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch)
      ARCH_INPUT="${2:-}"
      shift 2
      ;;
    --python-series)
      PYTHON_SERIES="${2:-}"
      shift 2
      ;;
    --skip-pip)
      SKIP_PIP="1"
      shift
      ;;
    --force-clean)
      FORCE_CLEAN="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

normalize_arch() {
  case "$1" in
    arm64|aarch64) echo "arm64" ;;
    amd64|x86_64) echo "amd64" ;;
    host|"") normalize_arch "$(uname -m)" ;;
    *)
      echo "unsupported architecture: $1" >&2
      exit 1
      ;;
  esac
}

download_asset_by_regex() {
  local repo="$1"
  local regex="$2"
  local output="$3"
  python3 - "$repo" "$regex" "$output" <<'PY'
import json
import re
import sys
import urllib.request

repo, pattern, output = sys.argv[1], sys.argv[2], sys.argv[3]
api = f"https://api.github.com/repos/{repo}/releases/latest"
with urllib.request.urlopen(api, timeout=60) as resp:
    data = json.load(resp)
assets = data.get("assets", [])
matched = [a for a in assets if re.match(pattern, a.get("name", ""))]
if len(matched) != 1:
    names = [a.get("name", "") for a in assets]
    raise SystemExit(
        f"asset match failed for repo={repo}, regex={pattern}, matches={len(matched)}\n"
        + "\n".join(names[:80])
    )
url = matched[0]["browser_download_url"]
print(f"download: {matched[0]['name']}")
urllib.request.urlretrieve(url, output)
PY
}

ARCH="$(normalize_arch "$ARCH_INPUT")"
TARGET_TRIPLE=""
FFMPEG_ASSET=""
case "$ARCH" in
  arm64)
    TARGET_TRIPLE="aarch64-apple-darwin"
    FFMPEG_ASSET="ffmpeg-darwin-arm64.gz"
    ;;
  amd64)
    TARGET_TRIPLE="x86_64-apple-darwin"
    FFMPEG_ASSET="ffmpeg-darwin-x64.gz"
    ;;
esac

RUNTIME_DIR="$OUTPUT_ROOT/macos-$ARCH"
if [[ "$FORCE_CLEAN" == "1" ]]; then
  rm -rf "$RUNTIME_DIR"
fi
mkdir -p "$RUNTIME_DIR/bin"

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

py_series_regex="${PYTHON_SERIES//./\\.}"
py_regex="^cpython-${py_series_regex}\\..*-${TARGET_TRIPLE}-install_only\\.tar\\.gz$"
py_archive="$tmpdir/python-install.tar.gz"
download_asset_by_regex "astral-sh/python-build-standalone" "$py_regex" "$py_archive"

rm -rf "$RUNTIME_DIR/python"
tar -xzf "$py_archive" -C "$RUNTIME_DIR"

download_asset_by_regex "eugeneware/ffmpeg-static" "^${FFMPEG_ASSET}$" "$tmpdir/ffmpeg.gz"
gzip -dc "$tmpdir/ffmpeg.gz" > "$RUNTIME_DIR/bin/ffmpeg"
chmod +x "$RUNTIME_DIR/bin/ffmpeg"

PY_BIN="$RUNTIME_DIR/python/bin/python3"
if [[ ! -x "$PY_BIN" ]]; then
  echo "python executable not found: $PY_BIN" >&2
  exit 1
fi

if [[ "$SKIP_PIP" == "0" ]]; then
  echo "install pip packages into runtime/python ..."
  "$PY_BIN" -m pip install --upgrade pip
  read -r -a pkg_array <<< "$PIP_PACKAGES"
  "$PY_BIN" -m pip install --no-cache-dir "${pkg_array[@]}"
else
  echo "skip pip install by --skip-pip"
fi

cat > "$RUNTIME_DIR/RUNTIME_INFO.txt" <<EOF
platform=macos
arch=$ARCH
python_series=$PYTHON_SERIES
pip_packages=$PIP_PACKAGES
generated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF

echo "Prepared runtime: $RUNTIME_DIR"
echo "Python: $PY_BIN"
echo "FFmpeg: $RUNTIME_DIR/bin/ffmpeg"
