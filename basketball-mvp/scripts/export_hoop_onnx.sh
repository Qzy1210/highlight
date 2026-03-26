#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

MODEL="${MODEL:-$ROOT_DIR/training/hoop_detector/runs/hoop_v1_n/weights/best.pt}"
IMGSZ="${IMGSZ:-960}"
OPSET="${OPSET:-12}"
DYNAMIC="${DYNAMIC:-false}"
SIMPLIFY="${SIMPLIFY:-true}"

if ! command -v yolo >/dev/null 2>&1; then
  echo "ERROR: 'yolo' command not found. Install with: pip install ultralytics"
  exit 1
fi

if [[ ! -f "$MODEL" ]]; then
  echo "ERROR: model file not found: $MODEL"
  exit 1
fi

echo "==> Export ONNX"
echo "MODEL=$MODEL IMGSZ=$IMGSZ OPSET=$OPSET DYNAMIC=$DYNAMIC SIMPLIFY=$SIMPLIFY"

yolo export \
  model="$MODEL" \
  format=onnx \
  imgsz="$IMGSZ" \
  opset="$OPSET" \
  dynamic="$DYNAMIC" \
  simplify="$SIMPLIFY"

echo "==> Done. ONNX is generated near the input model path."
