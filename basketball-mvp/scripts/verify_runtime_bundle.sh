#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/verify_runtime_bundle.sh --runtime-dir <dir>

Example:
  ./scripts/verify_runtime_bundle.sh --runtime-dir ./runtime/macos-arm64
EOF
}

RUNTIME_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-dir)
      RUNTIME_DIR="${2:-}"
      shift 2
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

if [[ -z "$RUNTIME_DIR" ]]; then
  usage
  exit 1
fi

if [[ ! -d "$RUNTIME_DIR" ]]; then
  echo "runtime dir not found: $RUNTIME_DIR" >&2
  exit 1
fi

PY_CANDIDATES=(
  "$RUNTIME_DIR/python/bin/python3"
  "$RUNTIME_DIR/python/bin/python"
  "$RUNTIME_DIR/python/python.exe"
)

PY_BIN=""
for p in "${PY_CANDIDATES[@]}"; do
  if [[ -f "$p" ]]; then
    PY_BIN="$p"
    break
  fi
done

if [[ -z "$PY_BIN" ]]; then
  echo "python binary not found under $RUNTIME_DIR/python" >&2
  exit 1
fi

FFMPEG_CANDIDATES=(
  "$RUNTIME_DIR/bin/ffmpeg"
  "$RUNTIME_DIR/bin/ffmpeg.exe"
)

FFMPEG_BIN=""
for p in "${FFMPEG_CANDIDATES[@]}"; do
  if [[ -f "$p" ]]; then
    FFMPEG_BIN="$p"
    break
  fi
done

if [[ -z "$FFMPEG_BIN" ]]; then
  echo "ffmpeg binary not found under $RUNTIME_DIR/bin" >&2
  exit 1
fi

echo "python: $PY_BIN"
"$PY_BIN" -c "import cv2, numpy; print('python deps ok')"

echo "ffmpeg: $FFMPEG_BIN"
"$FFMPEG_BIN" -version | head -n 1

echo "runtime bundle verification passed"
