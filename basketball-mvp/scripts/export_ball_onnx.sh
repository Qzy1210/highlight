#!/usr/bin/env bash
set -euo pipefail

# 把训练好的 ball 检测 .pt 导出成 ONNX(供 cv2.dnn / onnxruntime 部署)。
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

MODEL="${MODEL:-$ROOT_DIR/training/ball_detector/runs/ball_v1_n/weights/best.pt}"
IMGSZ="${IMGSZ:-640}"
OUT="${OUT:-$(dirname "$MODEL")/best.onnx}"

if [[ ! -f "$MODEL" ]]; then
  echo "ERROR: model not found: $MODEL"
  exit 1
fi

# 注意:不能用 nms=True。engine-py/ball_detector.py 的 OnnxDnnBackend
# 解析的是“未内置 NMS”的裸输出 (N, 4+nc),自行用 cv2.dnn.NMSBoxes 做 NMS。
./venv/bin/yolo export model="$MODEL" format=onnx imgsz="$IMGSZ" nms=False opset=12 simplify=False
# ultralytics 默认导出到同目录
EXPECTED="${MODEL%.pt}.onnx"
echo ""
echo "==> 导出完成: $EXPECTED"
echo "    若需拷贝: cp \"$EXPECTED\" \"$OUT\""
