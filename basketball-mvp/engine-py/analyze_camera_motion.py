#!/usr/bin/env python3
"""相机运动分析预检工具。

用途:
  - 在跑进球检测之前,先用它量化一条视频的“晃动等级”,并探测是否内嵌
    陀螺仪/加速度计/GPS 等运动元数据。
  - 输出直接指导后续技术路线:
      * 带陀螺仪元数据 + 高晃动  -> 优先走 Gyroflow 稳定化(检测层)。
      * 无陀螺仪元数据 + 高晃动  -> 需要做视觉运动补偿 / 篮框跟随检测。
      * 低晃动                     -> 现有固定机位检测链路可直接用。

不改动任何现有流程,纯只读分析。

用法:
  python3 engine-py/analyze_camera_motion.py --input /abs/path/video.mp4
  可选:
    --max-samples 800   帧间对比最大采样对数量(按时间均匀抽样)
    --json out.json     把结构化结果写到文件
    --verbose           打印匹配中间信息
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    sys.stderr.write("缺少依赖:需要 opencv-python 与 numpy(python3 -m pip install opencv-python numpy)\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 1) 元数据探测(ffprobe)
# ---------------------------------------------------------------------------

# 手机相机把陀螺仪等 IMU 数据包成 GPMF/GPMD 轨道,或在容器 tag 里留下线索。
_IMU_TAG_KEYWORDS = (
    "gyro", "accelerometer", "accel", "motion", "imu",
    "camera-motion", "camera_motion", "gpmf", "gpmd", "mvt",
)
_GPS_TAG_KEYWORDS = ("gps", "location", "coordinate", "com.apple.quicktime.location")
_IMU_STREAM_HINTS = ("motion", "imuf", "gpmd", "meta", "stereo/meta")


def _probe_json(video_path: str) -> Dict:
    """用 ffprobe 读容器的 format 与 streams 元数据。"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_format", "-show_streams",
        "-of", "json",
        video_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def probe_motion_metadata(video_path: str) -> Dict:
    """探测视频是否带陀螺仪/加速度计/GPS 等运动元数据。

    返回字段:
      - gyro:        是否发现陀螺仪线索
      - accelerometer: 是否发现加速度计线索
      - gps:          是否发现 GPS/位置线索
      - imu_stream:   是否存在专门存放 IMU 的数据流
      - hint_keys:    命中的元数据 key(便于人工核对)
    """
    data = _probe_json(video_path)
    result = {
        "gyro": False,
        "accelerometer": False,
        "gps": False,
        "imu_stream": False,
        "hint_keys": [],
    }

    fmt_tags = (data.get("format") or {}).get("tags") or {}
    streams = data.get("streams") or []
    all_tags: List[Dict] = [fmt_tags]
    for s in streams:
        all_tags.append(s.get("tags") or {})
        codec_name = (s.get("codec_name") or "").lower()
        codec_type = (s.get("codec_type") or "").lower()
        stream_id = f"{codec_type}/{codec_name}".lower()
        if codec_type in ("data", "unknown") or any(h in stream_id for h in _IMU_STREAM_HINTS):
            result["imu_stream"] = True

    seen = set()
    for tags in all_tags:
        for k, v in tags.items():
            low_k = k.lower()
            low_v = str(v).lower()
            if low_k in seen:
                continue
            if any(w in low_k for w in _IMU_TAG_KEYWORDS):
                result["gyro"] = result["gyro"] or ("gyro" in low_k or "imu" in low_k or "motion" in low_k)
                result["accelerometer"] = result["accelerometer"] or ("accel" in low_k)
                seen.add(low_k)
                result["hint_keys"].append(f"{k}={str(v)[:60]}")
            if any(w in low_k for w in _GPS_TAG_KEYWORDS) or any(w in low_v for w in _GPS_TAG_KEYWORDS):
                if low_k not in seen:
                    result["gps"] = True
                    seen.add(low_k)
                    result["hint_keys"].append(f"{k}={str(v)[:60]}")

    return result


# ---------------------------------------------------------------------------
# 2) 视觉晃动等级估计(ORB 匹配 + 仿射变换)
# ---------------------------------------------------------------------------


def _draw_debug_preview(frame, src_pts, dst_pts, path: str) -> None:
    """画一张可视化采样帧+匹配点,便于肉眼核对运动估计是否可靠。"""
    canvas = frame.copy()
    for (x1, y1), (x2, y2) in zip(src_pts, dst_pts):
        cv2.circle(canvas, (int(x1), int(y1)), 3, (0, 200, 255), -1)
        cv2.line(canvas, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 200), 1)
    cv2.imwrite(path, canvas)


def _relative_motion(frame_a, frame_b, orb, matcher, max_pts: int = 200):
    """估计第 b 帧相对第 a 帧的刚体运动。

    返回 (dx, dy, rot_deg, match_count),估计失败返回 None。
    """
    kp_a, des_a = orb.detectAndCompute(frame_a, None)
    kp_b, des_b = orb.detectAndCompute(frame_b, None)
    if des_a is None or des_b is None or len(kp_a) < 8 or len(kp_b) < 8:
        return None
    if len(des_a) > max_pts:
        des_a, kp_a = des_a[:max_pts], kp_a[:max_pts]
    if len(des_b) > max_pts:
        des_b, kp_b = des_b[:max_pts], kp_b[:max_pts]

    matches = matcher.knnMatch(des_a, des_b, k=2)
    good: List = []
    for pair in matches:
        # knnMatch 可能返回长度 <2 的项,需防御。
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:
            good.append(m)
    if len(good) < 8:
        return None

    src = np.float32([kp_a[m.queryIdx].pt for m in good])
    dst = np.float32([kp_b[m.trainIdx].pt for m in good])
    mtx, inliers = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0
    )
    if mtx is None:
        return None
    dx = float(mtx[0, 2])
    dy = float(mtx[1, 2])
    rot_deg = float(math.degrees(math.atan2(mtx[1, 0], mtx[0, 0])))  # 相似变换旋转角
    return dx, dy, rot_deg, len(good)


def analyze_visual_motion(
    video_path: str,
    max_samples: int = 800,
    verbose: bool = False,
) -> Dict:
    """对整个视频做帧间运动估计,输出晃动统计。

    采样策略:按时间均匀抽帧,相邻两个采样帧求一次相对运动。
    这样既能感知中低频平移(pan/手持),也能感知高频抖动(roll)。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # 每两个采样帧之间的步长:默认 0.25s,保证样本数可控。
    step = max(1, int(round(fps * 0.25)))
    # 如果视频太长,按 max_samples 目标放大步长。
    est_samples = max(1, total // step)
    if est_samples > max_samples:
        step = max(1, int(round(total / max_samples)))

    orb = cv2.ORB_create(nfeatures=3000, fastThreshold=12)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    deltas_dx: List[float] = []
    deltas_dy: List[float] = []
    deltas_deg: List[float] = []
    match_counts: List[int] = []
    debug_path: Optional[str] = None

    prev_gray = None
    frame_count = 0
    sampled_count = 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        frame_count += 1
        if frame_count % step != 0:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_gray is not None:
            motion = _relative_motion(prev_gray, gray, orb, matcher)
            if motion is not None:
                dx, dy, deg, n = motion
                deltas_dx.append(dx)
                deltas_dy.append(dy)
                deltas_deg.append(deg)
                match_counts.append(n)
                sampled_count += 1
                if verbose and debug_path is None:
                    # 只存第一对样本的可视化,便于肉眼核对。
                    try:
                        kp_a, des_a = orb.detectAndCompute(prev_gray, None)
                        kp_b, des_b = orb.detectAndCompute(gray, None)
                        if des_a is not None and des_b is not None and kp_a and kp_b:
                            matches = matcher.knnMatch(des_a[:200], des_b[:200], k=2)
                            good = [pair[0] for pair in matches if len(pair) >= 2 and pair[0].distance < 0.75 * pair[1].distance][:40]
                            if good:
                                src = np.float32([kp_a[m.queryIdx].pt for m in good])
                                dst = np.float32([kp_b[m.trainIdx].pt for m in good])
                                debug_path = os.path.join(
                                    os.path.dirname(os.path.abspath(video_path)),
                                    "_motion_match_debug.jpg",
                                )
                                _draw_debug_preview(frame, src, dst, debug_path)
                    except Exception:
                        pass
        prev_gray = gray

    cap.release()

    if sampled_count == 0:
        raise RuntimeError("无法从视频中估计任何运动(帧数太少或特征点不足)")

    dx = np.asarray(deltas_dx, dtype=np.float64)
    dy = np.asarray(deltas_dy, dtype=np.float64)
    deg = np.asarray(deltas_deg, dtype=np.float64)
    d_len = np.hypot(dx, dy)

    # 晃动指标(用视频高度归一化,避免分辨率差异):
    #  - 单帧位移中位数:反映整体抖动幅度
    #  - 位移标准差:反映抖动离散度
    #  - 累计路径:反映是否存在大范围 pan
    #  - 旋转标准差:反映 roll 抖动(手持最常见)
    disp_median = float(np.median(d_len))
    disp_std = float(np.std(d_len))
    disp_mean = float(np.mean(d_len))
    rot_std = float(np.std(deg))
    path_total = float(np.sum(d_len))

    disp_pct = disp_median / height * 100.0
    rot_abs_median = float(np.median(np.abs(deg)))

    if disp_pct < 1.0 and rot_std < 0.6:
        shake = "low"
    elif disp_pct < 4.0 and rot_std < 2.0:
        shake = "medium"
    else:
        shake = "high"

    # “平滑度”:相邻样本位移之差的中位数。低平滑度=高频抖动,高=平滑移动。
    if sampled_count >= 3:
        d = np.diff(d_len)
        smoothness = float(np.median(np.abs(d)))
    else:
        smoothness = 0.0
    smooth_rel = smoothness / height * 100.0

    return {
        "fps": fps,
        "width": width,
        "height": height,
        "sampled_pairs": sampled_count,
        "translation_px": {
            "dx_median": float(np.median(dx)),
            "dy_median": float(np.median(dy)),
            "disp_median": disp_median,
            "disp_mean": disp_mean,
            "disp_std": disp_std,
            "disp_pct_of_height": disp_pct,
        },
        "rotation_deg": {
            "rot_std": rot_std,
            "abs_median": rot_abs_median,
        },
        "path_px_total": path_total,
        "smoothness_pct_of_height": smooth_rel,
        "match_counts_median": int(np.median(match_counts)) if match_counts else 0,
        "shake_level": shake,
        "debug_preview": debug_path,
    }


# ---------------------------------------------------------------------------
# 3) 汇总判定
# ---------------------------------------------------------------------------

def build_verdict(meta: Dict, visual: Dict) -> Dict:
    """根据元数据 + 视觉晃动给出技术路线建议。"""
    gyro = meta.get("gyro") or meta.get("imu_stream") or meta.get("accelerometer")
    shake = visual.get("shake_level")

    if gyro:
        route = "gyro_stabilize"
        note = "检测到陀螺仪/IMU 元数据,优先用 Gyroflow 做检测层稳定化,回原始视频剪辑。"
    elif shake in ("high", "medium"):
        route = "visual_compensation"
        note = "无陀螺仪元数据且晃动明显,需在检测层做运动补偿或篮框跟随。"
    else:
        route = "fixed_camera"
        note = "晃动低,可直接使用现有固定机位检测链路。"

    return {
        "route": route,
        "route_note": note,
        "recommend_gyroflow": bool(gyro),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="相机运动分析预检")
    parser.add_argument("--input", required=True, help="输入视频绝对路径")
    parser.add_argument("--max-samples", type=int, default=800, help="帧间对比最大采样对数量")
    parser.add_argument("--json", help="结构化结果输出到 JSON 文件")
    parser.add_argument("--verbose", action="store_true", help="打印中间信息并输出匹配可视化")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: 文件不存在: {args.input}")
        return 2

    print(f"== 元数据探测: {args.input}")
    meta = probe_motion_metadata(args.input)
    print(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"\n== 视觉晃动估计(max_samples={args.max_samples}):")
    visual = analyze_visual_motion(args.input, max_samples=args.max_samples, verbose=args.verbose)
    print(json.dumps(visual, ensure_ascii=False, indent=2))

    verdict = build_verdict(meta, visual)
    print(f"\n== 综合判定 ==\n路线: {verdict['route']}\n说明: {verdict['route_note']}")

    if args.json:
        result = {
            "input": args.input,
            "metadata": meta,
            "visual_motion": visual,
            "verdict": verdict,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n已写入: {os.path.abspath(args.json)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())