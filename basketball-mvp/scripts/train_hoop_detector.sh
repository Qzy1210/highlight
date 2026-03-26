#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

DATASET="${DATASET:-$ROOT_DIR/training/hoop_detector/dataset.yaml}"
BASE_MODEL="${BASE_MODEL:-yolov8n.pt}"
EPOCHS="${EPOCHS:-120}"
IMGSZ="${IMGSZ:-960}"
BATCH="${BATCH:-16}"
DEVICE="${DEVICE:-0}"
WORKERS="${WORKERS:-8}"
PROJECT="${PROJECT:-$ROOT_DIR/training/hoop_detector/runs}"
RUN_NAME="${RUN_NAME:-hoop_v1_n}"

if ! command -v yolo >/dev/null 2>&1; then
  echo "ERROR: 'yolo' command not found. Install with: pip install ultralytics"
  exit 1
fi

if [[ ! -f "$DATASET" ]]; then
  echo "ERROR: dataset yaml not found: $DATASET"
  echo "Hint: copy training/hoop_detector/dataset.yaml.template to dataset.yaml and edit paths."
  exit 1
fi

mkdir -p "$PROJECT"

echo "==> Train hoop detector"
echo "DATASET=$DATASET"
echo "BASE_MODEL=$BASE_MODEL"
echo "EPOCHS=$EPOCHS IMGSZ=$IMGSZ BATCH=$BATCH DEVICE=$DEVICE"
echo "PROJECT=$PROJECT RUN_NAME=$RUN_NAME"

yolo detect train \
  data="$DATASET" \
  model="$BASE_MODEL" \
  epochs="$EPOCHS" \
  imgsz="$IMGSZ" \
  batch="$BATCH" \
  device="$DEVICE" \
  workers="$WORKERS" \
  project="$PROJECT" \
  name="$RUN_NAME"

echo "==> Done. Check results in: $PROJECT/$RUN_NAME"
