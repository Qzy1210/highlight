#!/usr/bin/env python3
"""篮框 ROI 标定工具。

交互方式：在选定帧上框出篮框外接矩形，脚本会换算中心点与半径并写回配置文件。
"""

import argparse
import json
from pathlib import Path

import cv2


def load_config(path: Path) -> dict:
    """读取配置文件。

    Args:
        path: 配置文件路径。

    Returns:
        配置字典。
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(path: Path, data: dict) -> None:
    """保存配置文件。

    Args:
        path: 配置文件路径。
        data: 要写入的配置字典。
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> None:
    """命令行入口。

    Returns:
        无显式返回；更新配置文件并打印新 `hoop` 参数。
    """
    parser = argparse.ArgumentParser(description="Calibrate hoop ROI and write to config")
    parser.add_argument("--video", required=True, help="input video path")
    parser.add_argument("--config", required=True, help="pipeline config json path")
    parser.add_argument("--frame-ratio", type=float, default=0.5, help="pick frame at ratio [0,1], default 0.5")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    cfg = load_config(cfg_path)

    # 取视频中段（默认 0.5）做标定，通常比首帧更稳定。
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {args.video}")

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ratio = min(1.0, max(0.0, args.frame_ratio))
    target = int(total * ratio)
    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("failed to read frame for ROI selection")

    win = "Select Hoop ROI (press ENTER to confirm, c to cancel)"
    # 交互式框选篮框外接矩形，再换算为中心点+半径。
    rect = cv2.selectROI(win, frame, fromCenter=False, showCrosshair=True)
    cv2.destroyAllWindows()

    x, y, w, h = map(int, rect)
    if w <= 0 or h <= 0:
        raise RuntimeError("no ROI selected")

    cx = x + w // 2
    cy = y + h // 2
    # 半径取外接框长边的一半，并设置下限防止 ROI 过小。
    r = max(12, int(max(w, h) * 0.5))

    cfg.setdefault("hoop", {})
    cfg["hoop"]["cx"] = cx
    cfg["hoop"]["cy"] = cy
    cfg["hoop"]["r"] = r
    save_config(cfg_path, cfg)

    print(json.dumps({"hoop": cfg["hoop"], "config": str(cfg_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
