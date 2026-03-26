#!/usr/bin/env python3
"""从视频中抽帧，生成篮框标注用图片集（按视频级别划分 train/val/test）。

用法示例：
    python3 scripts/extract_hoop_label_frames.py \
      --input /abs/path/videos \
      --output-root training/hoop_detector/datasets/hoop_v1/images \
      --interval-sec 0.8 \
      --max-frames-per-video 220
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".wmv"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="extract frames for hoop labeling")
    parser.add_argument("--input", required=True, help="video file or directory")
    parser.add_argument("--output-root", default="training/hoop_detector/datasets/hoop_v1/images", help="output images root")
    parser.add_argument("--interval-sec", type=float, default=0.8, help="sample interval in seconds")
    parser.add_argument("--max-frames-per-video", type=int, default=220, help="max saved frames per video")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="train split ratio")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="val split ratio")
    parser.add_argument("--test-ratio", type=float, default=0.1, help="test split ratio")
    parser.add_argument("--min-sharpness", type=float, default=0.0, help="optional blur filter threshold (0 disables)")
    parser.add_argument("--recursive", action="store_true", help="search input dir recursively")
    return parser.parse_args()


def iter_videos(path: Path, recursive: bool) -> Iterable[Path]:
    if path.is_file() and path.suffix.lower() in VIDEO_EXTS:
        yield path
        return
    if not path.is_dir():
        return
    pattern = "**/*" if recursive else "*"
    for p in sorted(path.glob(pattern)):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            yield p


def split_for_video(video_path: Path, train_ratio: float, val_ratio: float) -> str:
    # 视频级别稳定划分：同一个视频始终分到同一集合，避免相邻帧泄漏。
    digest = hashlib.md5(str(video_path).encode("utf-8")).hexdigest()  # nosec B324
    value = int(digest[:8], 16) / 0xFFFFFFFF
    if value < train_ratio:
        return "train"
    if value < train_ratio + val_ratio:
        return "val"
    return "test"


def laplacian_sharpness(cv2, frame) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def sanitize_name(name: str) -> str:
    out = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_") or "video"


def extract_one(
    cv2,
    video_path: Path,
    out_dir: Path,
    interval_sec: float,
    max_frames: int,
    min_sharpness: float,
) -> Dict:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"video": str(video_path), "saved": 0, "error": "open failed"}

    fps = float(cap.get(cv2.CAP_PROP_FPS))
    if fps <= 1e-6:
        fps = 30.0
    step = max(1, int(round(fps * max(0.05, interval_sec))))

    saved = 0
    frame_idx = 0
    video_key = sanitize_name(video_path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step != 0:
            frame_idx += 1
            continue
        if min_sharpness > 0 and laplacian_sharpness(cv2, frame) < min_sharpness:
            frame_idx += 1
            continue

        out_name = f"{video_key}_f{frame_idx:07d}.jpg"
        out_path = out_dir / out_name
        cv2.imwrite(str(out_path), frame)
        saved += 1
        frame_idx += 1
        if saved >= max_frames:
            break

    cap.release()
    return {
        "video": str(video_path),
        "saved": saved,
        "fps": round(fps, 3),
        "step_frames": step,
    }


def main() -> None:
    args = parse_args()
    if args.train_ratio <= 0 or args.val_ratio < 0 or args.test_ratio < 0:
        raise ValueError("split ratios must be non-negative and train_ratio > 0")
    ratio_sum = args.train_ratio + args.val_ratio + args.test_ratio
    if abs(ratio_sum - 1.0) > 1e-6:
        raise ValueError("train_ratio + val_ratio + test_ratio must equal 1.0")

    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise RuntimeError("OpenCV is required: pip install opencv-python") from exc

    input_path = Path(args.input).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    videos: List[Path] = list(iter_videos(input_path, args.recursive))
    if not videos:
        raise RuntimeError(f"no video files found in: {input_path}")

    summary = {
        "input": str(input_path),
        "output_root": str(output_root),
        "interval_sec": args.interval_sec,
        "max_frames_per_video": args.max_frames_per_video,
        "min_sharpness": args.min_sharpness,
        "videos": [],
        "totals": {"train": 0, "val": 0, "test": 0},
    }

    for video in videos:
        split = split_for_video(video, args.train_ratio, args.val_ratio)
        split_out = output_root / split
        item = extract_one(
            cv2=cv2,
            video_path=video,
            out_dir=split_out,
            interval_sec=args.interval_sec,
            max_frames=args.max_frames_per_video,
            min_sharpness=args.min_sharpness,
        )
        item["split"] = split
        summary["videos"].append(item)
        summary["totals"][split] += int(item.get("saved", 0))

    summary_path = output_root.parent / "frame_extract_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "video_count": len(videos),
        "totals": summary["totals"],
        "summary_json": str(summary_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
