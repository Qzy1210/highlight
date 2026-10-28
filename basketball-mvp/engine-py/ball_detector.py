#!/usr/bin/env python3
"""球检测 + 跟踪模块(模型可插拔)。

背景:
  现有进球检测依赖 MOG2 背景差分 + 固定 ROI,对手持/移动机位失效。
  本模块用“目标检测 + 多帧跟踪”替代背景差分,对相机运动更鲁棒,
  并同时适用于固定机位与手持视频。

设计要点:
  - 模型可插拔:`.pt` 走 ultralytics(开发态),`.onnx` 走 cv2.dnn(部署态,
    无需 torch)。两条路径输出统一为 (x1,y1,x2,y2,conf,cls)。
  - 类别可过滤:COCO 模型可取 `sports ball`(class 32);专用微调模型单类可传 -1。
  - 跟踪器自实现(IOU + 中心距离,容忍漏检),不依赖 ultralytics 的 tracker,
    保证部署态零额外依赖。
  - 输出“漏斗统计”:采样帧 -> 有检测帧 -> 轨迹数 -> 可用轨迹数,
    用于量化每一层过滤后的剩余量,作为换模型前后的对比基线。

只读输入视频,不改动现有流程。

用法:
  python3 engine-py/ball_detector.py \
    --input /abs/video.mp4 --model yolov8n.pt \
    --class-id 32 --output /abs/tracking.json --debug-dir /abs/debug
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    sys.stderr.write("缺少依赖:需要 opencv-python 与 numpy\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class DetectorConfig:
    """检测与跟踪参数。"""
    # 模型路径:.pt 用 ultralytics;.onnx 用 cv2.dnn
    model_path: str = "yolov8n.pt"
    # 目标类别 id;-1 表示不过滤(取所有类别中置信度最高者)
    class_id: int = 32  # COCO sports ball
    # 置信度阈值
    conf_threshold: float = 0.15
    # NMS IoU 阈值(ONNX 路径使用)
    iou_threshold: float = 0.45
    # 推理输入尺寸
    input_size: int = 960
    # 每隔多少帧推理一次(1=每帧)
    frame_skip: int = 2
    # 处理最大帧数(<=0 表示全片)
    max_frames: int = 0
    # 跟踪:允许连续漏检多少帧后判定轨迹结束(容忍零样本漏检)
    max_misses: int = 12
    # 跟踪:新检测与既有轨迹匹配的最大中心距离(像素)
    match_max_dist: float = 140.0
    # 判定“可用轨迹”的最少命中帧数
    min_hits: int = 5


# ---------------------------------------------------------------------------
# 推理后端
# ---------------------------------------------------------------------------

def _letterbox(frame, input_size: int):
    """缩放+填充到正方形,返回 (canvas, scale, pad_x, pad_y)。"""
    src_h, src_w = frame.shape[:2]
    scale = min(float(input_size) / float(src_w), float(input_size) / float(src_h))
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_w = input_size - new_w
    pad_h = input_size - new_h
    left = pad_w // 2
    top = pad_h // 2
    canvas = np.full((input_size, input_size, 3), 114, dtype=np.uint8)
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas, scale, left, top


class UltralyticsBackend:
    """基于 ultralytics 的推理后端(支持 .pt / .onnx)。"""

    def __init__(self, cfg: DetectorConfig):
        from ultralytics import YOLO  # 延迟导入:部署态可不装 torch
        self.model = YOLO(cfg.model_path)
        self.cfg = cfg

    def predict(self, frame) -> List[Tuple[float, float, float, float, float, int]]:
        res = self.model.predict(
            frame, verbose=False,
            conf=self.cfg.conf_threshold,
            iou=self.cfg.iou_threshold,
            imgsz=self.cfg.input_size,
        )[0]
        out: List[Tuple[float, float, float, float, float, int]] = []
        boxes = getattr(res, "boxes", None)
        if boxes is None:
            return out
        xyxy = boxes.xyxy.cpu().numpy()
        conf = boxes.conf.cpu().numpy()
        cls = boxes.cls.cpu().numpy().astype(int)
        for (x1, y1, x2, y2), c, k in zip(xyxy, conf, cls):
            # 与 ONNX 路径保持一致:按目标类别过滤(COCO 球=32)。
            if self.cfg.class_id >= 0 and int(k) != self.cfg.class_id:
                continue
            out.append((float(x1), float(y1), float(x2), float(y2), float(c), int(k)))
        return out


class OnnxDnnBackend:
    """基于 cv2.dnn 的 ONNX 推理后端(部署态,无 torch 依赖)。"""

    def __init__(self, cfg: DetectorConfig):
        self.net = cv2.dnn.readNetFromONNX(cfg.model_path)
        self.cfg = cfg

    def predict(self, frame) -> List[Tuple[float, float, float, float, float, int]]:
        src_h, src_w = frame.shape[:2]
        lb, scale, pad_x, pad_y = _letterbox(frame, self.cfg.input_size)
        blob = cv2.dnn.blobFromImage(
            lb, 1.0 / 255.0, (self.cfg.input_size, self.cfg.input_size), swapRB=True, crop=False
        )
        self.net.setInput(blob)
        pred = np.array(self.net.forward())
        if pred.ndim == 3:
            pred = pred[0]
        if pred.ndim != 2:
            return []
        # YOLOv8 ONNX 输出常为 (4+nc, N),转成 (N, 4+nc)。
        if pred.shape[0] <= 256 and pred.shape[1] > pred.shape[0]:
            pred = pred.T
        if pred.shape[1] < 5:
            return []

        boxes_xywh: List[List[float]] = []
        scores: List[float] = []
        rows: List[Tuple[float, float, float, float, float, int]] = []
        for row in pred:
            cx, cy, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            if w <= 1e-4 or h <= 1e-4:
                continue
            if len(row) == 5:
                score = float(row[4])
                cls_id = 0
            else:
                cls_scores = row[4:]
                cls_id = int(np.argmax(cls_scores))
                score = float(cls_scores[cls_id])
            if score < self.cfg.conf_threshold:
                continue
            if self.cfg.class_id >= 0 and cls_id != self.cfg.class_id:
                continue
            x1 = cx - w * 0.5
            y1 = cy - h * 0.5
            boxes_xywh.append([x1, y1, w, h])
            scores.append(score)
            rows.append((x1, y1, w, h, score, cls_id))

        if not boxes_xywh:
            return []
        keep = cv2.dnn.NMSBoxes(boxes_xywh, scores, self.cfg.conf_threshold, self.cfg.iou_threshold)
        if keep is None or len(keep) == 0:
            return []

        out: List[Tuple[float, float, float, float, float, int]] = []
        for raw in keep:
            idx = int(raw[0]) if isinstance(raw, (list, tuple, np.ndarray)) else int(raw)
            x1, y1, w, h, score, cls_id = rows[idx]
            ox1 = max(0.0, min(float(src_w - 1), (x1 - pad_x) / scale))
            oy1 = max(0.0, min(float(src_h - 1), (y1 - pad_y) / scale))
            ox2 = max(0.0, min(float(src_w - 1), (x1 + w - pad_x) / scale))
            oy2 = max(0.0, min(float(src_h - 1), (y1 + h - pad_y) / scale))
            out.append((ox1, oy1, ox2, oy2, score, cls_id))
        return out


def build_backend(cfg: DetectorConfig):
    """按模型扩展名选择推理后端。"""
    if cfg.model_path.lower().endswith(".onnx"):
        return OnnxDnnBackend(cfg)
    return UltralyticsBackend(cfg)


# ---------------------------------------------------------------------------
# 跟踪器
# ---------------------------------------------------------------------------

@dataclass
class Track:
    """一条球轨迹。"""
    id: int
    box: Tuple[float, float, float, float]
    last_frame: int
    hits: int = 1
    misses: int = 0
    points: List[Dict] = field(default_factory=list)

    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.box
        return (x1 + x2) * 0.5, (y1 + y2) * 0.5


def _center_dist(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax, ay = (a[0] + a[2]) * 0.5, (a[1] + a[3]) * 0.5
    bx, by = (b[0] + b[2]) * 0.5, (b[1] + b[3]) * 0.5
    return math.hypot(ax - bx, ay - by)


class BallTracker:
    """基于中心距离贪心匹配的轻量跟踪器。

    不依赖卡尔曼滤波,容忍漏检(max_misses)。对“球”这类单目标、轨迹
    连续的场景足够,且无额外依赖。
    """

    def __init__(self, cfg: DetectorConfig):
        self.cfg = cfg
        self.tracks: Dict[int, Track] = {}
        self._next_id = 1
        self.finished: List[Track] = []

    def update(self, frame_idx: int, dets: List[Tuple[float, float, float, float, float, int]]) -> List[Track]:
        """用当前帧检测更新轨迹,返回仍在活跃的轨迹。"""
        boxes = [(d[0], d[1], d[2], d[3]) for d in dets]
        confs = [d[4] for d in dets]

        # 贪心匹配:对每个检测找最近的、距离在阈值内的活跃轨迹。
        assigned: Dict[int, int] = {}  # track_id -> det index
        used_dets = set()
        candidates: List[Tuple[float, int, int]] = []
        for tid, tr in self.tracks.items():
            for di, box in enumerate(boxes):
                dist = _center_dist(tr.box, box)
                if dist <= self.cfg.match_max_dist:
                    candidates.append((dist, tid, di))
        candidates.sort(key=lambda x: x[0])
        for dist, tid, di in candidates:
            if tid in assigned or di in used_dets:
                continue
            assigned[tid] = di
            used_dets.add(di)

        for tid, tr in self.tracks.items():
            if tid in assigned:
                di = assigned[tid]
                tr.box = boxes[di]
                tr.last_frame = frame_idx
                tr.hits += 1
                tr.misses = 0
                tr.points.append({
                    "frame": frame_idx,
                    "cx": round((boxes[di][0] + boxes[di][2]) * 0.5, 1),
                    "cy": round((boxes[di][1] + boxes[di][3]) * 0.5, 1),
                    "conf": round(confs[di], 3),
                })
            else:
                tr.misses += 1

        # 未匹配的检测 -> 新轨迹
        for di, box in enumerate(boxes):
            if di in used_dets:
                continue
            tr = Track(id=self._next_id, box=box, last_frame=frame_idx)
            tr.points.append({
                "frame": frame_idx,
                "cx": round((box[0] + box[2]) * 0.5, 1),
                "cy": round((box[1] + box[3]) * 0.5, 1),
                "conf": round(confs[di], 3),
            })
            self.tracks[self._next_id] = tr
            self._next_id += 1

        # 连续漏检超限 -> 结束轨迹
        for tid in [t for t, tr in self.tracks.items() if tr.misses > self.cfg.max_misses]:
            self.finished.append(self.tracks.pop(tid))

        return list(self.tracks.values())

    def flush(self) -> List[Track]:
        """视频结束时收尾所有剩余轨迹。"""
        self.finished.extend(self.tracks.values())
        self.tracks.clear()
        return self.finished


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _track_summary(tr: Track, fps: float) -> Dict:
    """汇总单条轨迹的统计信息。"""
    pts = tr.points
    path_px = 0.0
    for a, b in zip(pts, pts[1:]):
        path_px += math.hypot(b["cx"] - a["cx"], b["cy"] - a["cy"])
    if pts:
        f0, f1 = pts[0]["frame"], pts[-1]["frame"]
        duration = (f1 - f0) / fps if fps > 0 else 0.0
    else:
        duration = 0.0
    return {
        "id": tr.id,
        "hits": tr.hits,
        "misses": tr.misses,
        "start_frame": pts[0]["frame"] if pts else -1,
        "end_frame": pts[-1]["frame"] if pts else -1,
        "duration_sec": round(duration, 2),
        "path_px": round(path_px, 1),
        "avg_conf": round(sum(p["conf"] for p in pts) / len(pts), 3) if pts else 0.0,
        "points": pts,
    }


def detect_ball_tracks(
    video_path: str,
    cfg: DetectorConfig,
    debug_dir: Optional[str] = None,
) -> Dict:
    """对整条视频执行球检测 + 跟踪,输出结构化结果与漏斗统计。"""
    backend = build_backend(cfg)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    tracker = BallTracker(cfg)
    frame_idx = 0
    processed = 0
    frames_with_det = 0
    det_total = 0
    shots: List[Tuple[int, List]] = []

    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        frame_idx += 1
        if cfg.max_frames > 0 and frame_idx > cfg.max_frames:
            break
        if frame_idx % max(1, cfg.frame_skip) != 0:
            continue
        processed += 1

        dets = backend.predict(frame)
        if dets:
            frames_with_det += 1
            det_total += len(dets)
            shots.append((frame_idx, dets))
        tracker.update(frame_idx, dets)

    cap.release()
    tracks = tracker.flush()
    summaries = [_track_summary(tr, fps) for tr in tracks]
    summaries.sort(key=lambda s: s["hits"], reverse=True)
    usable = [s for s in summaries if s["hits"] >= cfg.min_hits]

    # 可视化:画出轨迹与检测框
    debug_image = ""
    if debug_dir and shots:
        debug_image = _write_track_overlay(video_path, shots, usable, debug_dir)

    return {
        "video": video_path,
        "model": cfg.model_path,
        "class_id": cfg.class_id,
        "fps": fps,
        "width": width,
        "height": height,
        "total_frames": total,
        "frames_processed": processed,
        "funnel": {
            "frames_processed": processed,
            "frames_with_detection": frames_with_det,
            "detection_frame_ratio": round(frames_with_det / max(1, processed), 3),
            "detections_total": det_total,
            "tracks_total": len(summaries),
            "tracks_usable": len(usable),
            "usable_tracks": len(usable),
        },
        "tracks": summaries[:50],
        "debug_image": debug_image,
    }


def _write_track_overlay(video_path, shots, usable, debug_dir: str) -> str:
    """把检测框与轨迹中心画到采样帧上,便于人工核对。"""
    usable_ids = {s["id"] for s in usable}
    cap = cv2.VideoCapture(video_path)
    # 取中间一帧作为底图
    mid = shots[len(shots) // 2][0]
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, mid - 1))
    ok, canvas = cap.read()
    cap.release()
    if not ok or canvas is None:
        return ""
    for s in usable:
        color = (0, 200, 255) if s["id"] in usable_ids else (120, 120, 120)
        pts = [(int(p["cx"]), int(p["cy"])) for p in s["points"]]
        for a, b in zip(pts, pts[1:]):
            cv2.line(canvas, a, b, color, 2)
        if pts:
            cv2.putText(canvas, f"#{s['id']}", pts[0], cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    out_path = os.path.join(debug_dir, "ball_tracks_overlay.jpg")
    cv2.imwrite(out_path, canvas)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="球检测 + 跟踪(模型可插拔)")
    parser.add_argument("--input", required=True, help="输入视频绝对路径")
    parser.add_argument("--model", default="yolov8n.pt", help="模型路径(.pt 或 .onnx)")
    parser.add_argument("--class-id", type=int, default=32, help="目标类别 id(-1 不过滤;COCO 球=32)")
    parser.add_argument("--conf", type=float, default=0.15, help="置信度阈值")
    parser.add_argument("--imgsz", type=int, default=960, help="推理输入尺寸")
    parser.add_argument("--frame-skip", type=int, default=2, help="帧跳过")
    parser.add_argument("--max-frames", type=int, default=0, help="最大处理帧数(0=全片)")
    parser.add_argument("--max-misses", type=int, default=12, help="容忍漏检帧数")
    parser.add_argument("--min-hits", type=int, default=5, help="可用轨迹最少命中数")
    parser.add_argument("--output", help="结果 JSON 输出路径")
    parser.add_argument("--debug-dir", help="调试产物目录")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: 文件不存在: {args.input}")
        return 2

    cfg = DetectorConfig(
        model_path=args.model,
        class_id=args.class_id,
        conf_threshold=args.conf,
        input_size=args.imgsz,
        frame_skip=args.frame_skip,
        max_frames=args.max_frames,
        max_misses=args.max_misses,
        min_hits=args.min_hits,
    )
    result = detect_ball_tracks(args.input, cfg, debug_dir=args.debug_dir)
    print(json.dumps(result["funnel"], ensure_ascii=False, indent=2))
    print(f"\n轨迹数: {result['funnel']['tracks_total']}, 可用轨迹: {result['funnel']['tracks_usable']}")
    if result["debug_image"]:
        print(f"可视化: {result['debug_image']}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"已写入: {os.path.abspath(args.output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())