#!/usr/bin/env python3
"""篮球进球检测主脚本。

该脚本提供两种模式：
1. 自动检测模式：基于 OpenCV 在 ROI 内识别球轨迹并结合篮网运动确认事件。
2. 手工模式：直接使用外部传入的时间点，跳过视频检测。

输入通常来自 Go 服务层；输出 `goals.json` 与调试产物目录。
"""

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# OpenCV 依赖按需加载：手工模式不强依赖 cv2/numpy，避免不必要的启动失败。
cv2 = None
np = None


@dataclass
class Rect:
    """矩形区域（像素坐标）。

    Attributes:
        x1: 左边界（包含）。
        y1: 上边界（包含）。
        x2: 右边界（切片右开，不包含）。
        y2: 下边界（切片右开，不包含）。
    """

    x1: int
    y1: int
    x2: int
    y2: int

    def clip(self, width: int, height: int) -> "Rect":
        """将矩形裁剪到画面边界内。

        Args:
            width: 视频宽度（像素）。
            height: 视频高度（像素）。

        Returns:
            裁剪后的合法矩形。
        """
        # x2/y2 采用切片语义（右开区间），因此上限允许等于 width/height。
        return Rect(
            x1=max(0, min(self.x1, width - 1)),
            y1=max(0, min(self.y1, height - 1)),
            x2=max(1, min(self.x2, width)),
            y2=max(1, min(self.y2, height)),
        )


@dataclass
class DetectConfig:
    """自动检测相关参数集合。"""
    # 每隔多少帧处理一次，值越大越快但更容易漏检
    frame_skip: int = 3
    # 进球事件冷却时间，防止同一次进球被重复触发
    cooldown_sec: float = 2.0
    # 候选球体的面积范围（像素）
    min_ball_area: int = 30
    max_ball_area: int = 1400
    # 轮廓圆度过滤，越高越严格，能抑制非球体误检
    min_ball_circularity: float = 0.45
    # 轨迹缓存长度（用于判断下落趋势）
    track_len: int = 8
    # 篮网运动确认阈值，越高越严格
    net_motion_threshold: float = 0.035
    # 球穿框后，允许多久内观察篮网晃动（秒）
    net_confirm_window_sec: float = 0.55
    # 事件合并窗口，过近的事件会被去重
    event_merge_window_sec: float = 1.6
    # 背景建模参数，影响运动目标提取稳定性
    bg_history: int = 400
    bg_var_threshold: float = 48.0


@dataclass
class LiteDebugConfig:
    """轻量调试输出控制参数。"""

    enabled: bool = False
    frame_step: int = 12
    max_frames: int = 120


@dataclass
class AutoHoopConfig:
    """自动篮框检测参数。"""

    enabled: bool = False
    model_path: str = ""
    input_size: int = 960
    conf_threshold: float = 0.25
    iou_threshold: float = 0.45
    min_box_area_ratio: float = 0.00003
    max_box_area_ratio: float = 0.08
    max_dets_per_frame: int = 3
    fallback_to_manual: bool = True
    sample_ratios: List[float] = field(default_factory=lambda: [0.15, 0.35, 0.5, 0.65, 0.85])


def parse_manual_goals(raw: str) -> List[float]:
    """解析手工时间点字符串。

    Args:
        raw: 逗号分隔的秒数文本，例如 `"12.5,45.2"`.

    Returns:
        升序的时间点列表（秒）。
    """
    # 手工时间点支持 "12.5,45.2,..."，统一排序后输出。
    if not raw:
        return []
    out: List[float] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        out.append(float(token))
    return sorted(out)


def load_json(path: str) -> Dict:
    """读取 JSON 文件并返回字典。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_detect_config(cfg: Dict) -> DetectConfig:
    """从整份配置中提取 `detect` 参数。

    Args:
        cfg: 完整配置字典（通常来自 `pipeline.run.json`）。

    Returns:
        `DetectConfig`，缺失字段使用默认值。
    """
    # 从配置文件读取 detect 参数，不存在时使用默认值
    d = cfg.get("detect", {})
    c = DetectConfig()
    c.frame_skip = int(d.get("frame_skip", c.frame_skip))
    c.cooldown_sec = float(d.get("cooldown_sec", c.cooldown_sec))
    c.min_ball_area = int(d.get("min_ball_area", c.min_ball_area))
    c.max_ball_area = int(d.get("max_ball_area", c.max_ball_area))
    c.min_ball_circularity = float(d.get("min_ball_circularity", c.min_ball_circularity))
    c.track_len = int(d.get("track_len", c.track_len))
    c.net_motion_threshold = float(d.get("net_motion_threshold", c.net_motion_threshold))
    c.net_confirm_window_sec = float(d.get("net_confirm_window_sec", c.net_confirm_window_sec))
    c.event_merge_window_sec = float(d.get("event_merge_window_sec", c.event_merge_window_sec))
    c.bg_history = int(d.get("bg_history", c.bg_history))
    c.bg_var_threshold = float(d.get("bg_var_threshold", c.bg_var_threshold))
    return c


def load_auto_hoop_config(cfg: Dict) -> AutoHoopConfig:
    """从整份配置中提取 `auto_hoop` 参数。"""
    raw = cfg.get("auto_hoop", {})
    if not isinstance(raw, dict):
        raw = {}
    c = AutoHoopConfig()
    c.enabled = bool(raw.get("enabled", c.enabled))
    c.model_path = str(raw.get("model_path", c.model_path)).strip()
    c.input_size = max(64, int(raw.get("input_size", c.input_size)))
    c.conf_threshold = float(raw.get("conf_threshold", c.conf_threshold))
    c.iou_threshold = float(raw.get("iou_threshold", c.iou_threshold))
    c.min_box_area_ratio = float(raw.get("min_box_area_ratio", c.min_box_area_ratio))
    c.max_box_area_ratio = float(raw.get("max_box_area_ratio", c.max_box_area_ratio))
    c.max_dets_per_frame = max(1, int(raw.get("max_dets_per_frame", c.max_dets_per_frame)))
    c.fallback_to_manual = bool(raw.get("fallback_to_manual", c.fallback_to_manual))

    ratios = raw.get("sample_ratios")
    if isinstance(ratios, list):
        parsed: List[float] = []
        for item in ratios:
            try:
                val = float(item)
            except Exception:
                continue
            if 0.0 <= val <= 1.0:
                parsed.append(val)
        if parsed:
            c.sample_ratios = sorted(set(parsed))
    return c


def _is_valid_hoop(cfg: Dict, width: int, height: int) -> bool:
    """检查 hoop(cx,cy,r) 是否基本有效。"""
    hoop = cfg.get("hoop", {})
    if not isinstance(hoop, dict):
        return False
    try:
        cx = int(hoop.get("cx", -1))
        cy = int(hoop.get("cy", -1))
        r = int(hoop.get("r", -1))
    except Exception:
        return False
    return (0 <= cx < width) and (0 <= cy < height) and (r > 0)


def _discover_default_auto_hoop_model() -> Optional[Path]:
    """尝试发现默认 ONNX 模型路径（latest best.onnx）。"""
    roots: List[Path] = []
    env_root = os.environ.get("BASKETBALL_MVP_ROOT", "").strip()
    if env_root:
        roots.append(Path(env_root))
    # detect_goals.py 位于 engine-py，下一级即项目根目录。
    roots.append(Path(__file__).resolve().parents[1])

    candidates: List[Path] = []
    seen = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        embedded = resolved / "models" / "hoop" / "best.onnx"
        if embedded.is_file():
            candidates.append(embedded)

        run_dir = resolved / "training" / "hoop_detector" / "runs"
        if not run_dir.exists():
            continue
        candidates.extend(run_dir.glob("*/weights/best.onnx"))
    if not candidates:
        return None
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _resolve_auto_hoop_model_path(model_path: str, config_path: str) -> Optional[Path]:
    """解析 auto_hoop 模型路径。"""
    if model_path:
        path = Path(model_path)
        if not path.is_absolute() and config_path:
            path = (Path(config_path).resolve().parent / path).resolve()
        elif not path.is_absolute():
            path = path.resolve()
        if path.is_file():
            return path
    return _discover_default_auto_hoop_model()


def _letterbox_frame(frame, input_size: int):
    """按 YOLO 常用 letterbox 方式缩放并填充图像。"""
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


def _infer_hoop_boxes_with_onnx(frame, net, cfg: AutoHoopConfig) -> List[Dict]:
    """在单帧上执行 ONNX 推理并返回候选框。"""
    src_h, src_w = frame.shape[:2]
    lb, scale, pad_x, pad_y = _letterbox_frame(frame, cfg.input_size)
    blob = cv2.dnn.blobFromImage(lb, 1.0 / 255.0, (cfg.input_size, cfg.input_size), swapRB=True, crop=False)
    net.setInput(blob)
    pred = net.forward()

    arr = np.array(pred)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2:
        return []
    # YOLOv8 ONNX 常见输出：(C, N)，转为 (N, C) 统一处理。
    if arr.shape[0] <= 10 and arr.shape[1] > arr.shape[0]:
        arr = arr.T
    if arr.shape[1] < 5:
        return []

    boxes_xywh: List[List[float]] = []
    scores: List[float] = []
    raw_rows: List[Tuple[float, float, float, float, float]] = []
    for row in arr:
        x, y, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
        if w <= 1e-4 or h <= 1e-4:
            continue
        if len(row) == 5:
            score = float(row[4])
        else:
            obj = float(row[4])
            cls_score = float(np.max(row[5:])) if len(row) > 5 else 1.0
            score = obj * cls_score
        if score < cfg.conf_threshold:
            continue
        x1 = x - w * 0.5
        y1 = y - h * 0.5
        boxes_xywh.append([x1, y1, w, h])
        scores.append(score)
        raw_rows.append((x1, y1, w, h, score))

    if not boxes_xywh:
        return []

    keep = cv2.dnn.NMSBoxes(boxes_xywh, scores, cfg.conf_threshold, cfg.iou_threshold)
    if keep is None or len(keep) == 0:
        return []

    out: List[Dict] = []
    frame_area = float(max(1, src_w * src_h))
    for idx_raw in keep:
        idx = int(idx_raw[0]) if isinstance(idx_raw, (list, tuple, np.ndarray)) else int(idx_raw)
        x1, y1, w, h, score = raw_rows[idx]
        ox1 = max(0.0, min(float(src_w - 1), (x1 - pad_x) / scale))
        oy1 = max(0.0, min(float(src_h - 1), (y1 - pad_y) / scale))
        ox2 = max(0.0, min(float(src_w - 1), (x1 + w - pad_x) / scale))
        oy2 = max(0.0, min(float(src_h - 1), (y1 + h - pad_y) / scale))
        bw = max(1.0, ox2 - ox1)
        bh = max(1.0, oy2 - oy1)
        area_ratio = (bw * bh) / frame_area
        if area_ratio < cfg.min_box_area_ratio or area_ratio > cfg.max_box_area_ratio:
            continue
        out.append({
            "x1": ox1,
            "y1": oy1,
            "x2": ox2,
            "y2": oy2,
            "score": score,
            "area_ratio": area_ratio,
        })
    out.sort(key=lambda d: d["score"], reverse=True)
    return out[:cfg.max_dets_per_frame]


def _cluster_hoop_candidates(candidates: List[Dict]) -> List[Dict]:
    """将跨帧篮框候选聚类并输出稳定候选列表。"""
    if not candidates:
        return []

    clusters: List[Dict] = []
    for cand in sorted(candidates, key=lambda d: d["score"], reverse=True):
        cx = float(cand["cx"])
        cy = float(cand["cy"])
        r = float(cand["r"])
        w = float(max(1e-6, cand["score"]))

        matched = None
        for clu in clusters:
            dx = cx - clu["cx"]
            dy = cy - clu["cy"]
            dist = (dx * dx + dy * dy) ** 0.5
            tol = max(15.0, 0.65 * max(r, clu["r"]))
            if dist <= tol:
                matched = clu
                break
        if matched is None:
            clusters.append({
                "cx": cx,
                "cy": cy,
                "r": r,
                "weight": w,
                "count": 1,
                "best_score": w,
                "best_frame": int(cand.get("frame", -1)),
                "best_box": cand.get("box"),
            })
            continue

        total_w = matched["weight"] + w
        matched["cx"] = (matched["cx"] * matched["weight"] + cx * w) / total_w
        matched["cy"] = (matched["cy"] * matched["weight"] + cy * w) / total_w
        matched["r"] = (matched["r"] * matched["weight"] + r * w) / total_w
        matched["weight"] = total_w
        matched["count"] += 1
        if w > float(matched["best_score"]):
            matched["best_score"] = w
            matched["best_frame"] = int(cand.get("frame", -1))
            matched["best_box"] = cand.get("box")

    out: List[Dict] = []
    for clu in clusters:
        count = int(clu["count"])
        avg_score = float(clu["weight"]) / max(1, count)
        item = {
            "cx": int(round(clu["cx"])),
            "cy": int(round(clu["cy"])),
            "r": max(4, int(round(clu["r"]))),
            "score": round(avg_score, 4),
            "count": count,
            "best_score": round(float(clu["best_score"]), 4),
            "rank_score": float(clu["weight"]) + 0.2 * float(count),
        }
        best_frame = int(clu.get("best_frame", -1))
        if best_frame >= 0:
            item["frame"] = best_frame
        best_box = clu.get("best_box")
        if isinstance(best_box, dict):
            item["box"] = {
                "x1": float(best_box.get("x1", 0.0)),
                "y1": float(best_box.get("y1", 0.0)),
                "x2": float(best_box.get("x2", 0.0)),
                "y2": float(best_box.get("y2", 0.0)),
            }
        out.append(item)
    out.sort(key=lambda d: (d["rank_score"], d["best_score"], d["count"]), reverse=True)
    for i, item in enumerate(out, start=1):
        item["id"] = f"cand-{i}"
    return out


def _select_hoop_from_candidates(candidates: List[Dict]) -> Optional[Dict[str, int]]:
    """从多帧候选中挑选最稳定的篮框框。"""
    clusters = _cluster_hoop_candidates(candidates)
    if not clusters:
        return None
    best = clusters[0]
    return {
        "cx": int(best["cx"]),
        "cy": int(best["cy"]),
        "r": max(4, int(best["r"])),
    }


def _write_hoop_candidates_preview(
    video_path: str,
    sampled_frames: List[int],
    candidates: List[Dict],
    debug_dir: Path,
) -> Optional[str]:
    """输出篮框候选预览图（叠加多个候选圆）。"""
    if not candidates:
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    frame = None
    frame_indices: List[int] = []
    top_frame = int(candidates[0].get("frame", -1))
    if top_frame >= 0:
        frame_indices.append(top_frame)
    frame_indices.extend(sampled_frames)
    for idx in sorted(set(frame_indices)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, img = cap.read()
        if ok and img is not None:
            frame = img
            break
    if frame is None:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, img = cap.read()
        if ok and img is not None:
            frame = img
    cap.release()
    if frame is None:
        return None

    canvas = frame.copy()
    colors = [
        (0, 255, 255),
        (255, 180, 0),
        (0, 200, 255),
        (180, 255, 120),
        (255, 120, 220),
        (120, 220, 255),
    ]
    for i, cand in enumerate(candidates):
        color = colors[i % len(colors)]
        cx = int(cand.get("cx", 0))
        cy = int(cand.get("cy", 0))
        r = int(cand.get("r", 0))
        score = float(cand.get("score", 0.0))
        count = int(cand.get("count", 0))
        cv2.circle(canvas, (cx, cy), max(4, r), color, 2)
        cv2.circle(canvas, (cx, cy), 3, color, -1)
        text = f"#{i + 1} s={score:.3f} c={count}"
        cv2.putText(canvas, text, (max(5, cx - r), max(20, cy - r - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    debug_dir.mkdir(parents=True, exist_ok=True)
    out = debug_dir / "auto_hoop_candidates.jpg"
    cv2.imwrite(str(out), canvas)
    return str(out)


def _draw_hoop_candidate_overlay(canvas, cand: Dict, title: str) -> None:
    """在候选帧截图上绘制篮框圆、检测框与说明文字。"""
    cx = int(cand.get("cx", 0))
    cy = int(cand.get("cy", 0))
    r = max(4, int(cand.get("r", 4)))
    score = float(cand.get("score", 0.0))
    count = int(cand.get("count", 0))
    frame_idx = int(cand.get("frame", -1))

    color = (0, 255, 255)
    cv2.circle(canvas, (cx, cy), r, color, 2)
    cv2.circle(canvas, (cx, cy), 3, color, -1)

    box = cand.get("box")
    if isinstance(box, dict):
        x1 = int(round(float(box.get("x1", 0.0))))
        y1 = int(round(float(box.get("y1", 0.0))))
        x2 = int(round(float(box.get("x2", 0.0))))
        y2 = int(round(float(box.get("y2", 0.0))))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (255, 180, 0), 2)
        cv2.putText(canvas, "det_box", (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 180, 0), 2)

    line1 = f"{title} frame={frame_idx} score={score:.3f} count={count}"
    line2 = f"hoop({cx},{cy},r={r})"
    cv2.putText(canvas, line1, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 3)
    cv2.putText(canvas, line1, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (25, 25, 25), 1)
    cv2.putText(canvas, line2, (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 3)
    cv2.putText(canvas, line2, (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (25, 25, 25), 1)


def _write_hoop_candidate_frame_images(
    video_path: str,
    candidates: List[Dict],
    debug_dir: Path,
    frame_cache: Optional[Dict[int, object]] = None,
) -> None:
    """为每个候选输出“对应检测帧截图”，并回填 `frame_image`。"""
    if not candidates:
        return
    cap = None
    frame_cache = frame_cache or {}
    # 优先使用检测阶段缓存帧，避免某些编码下二次随机 seek 读取失败。
    need_seek = any(int(cand.get("frame", -1)) >= 0 and int(cand.get("frame", -1)) not in frame_cache for cand in candidates)
    if need_seek:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap = None
    debug_dir.mkdir(parents=True, exist_ok=True)
    for i, cand in enumerate(candidates, start=1):
        frame_idx = int(cand.get("frame", -1))
        if frame_idx < 0:
            continue

        frame = None
        cached = frame_cache.get(frame_idx)
        if cached is not None:
            try:
                frame = cached.copy()
            except Exception:
                frame = cached

        if frame is None and cap is not None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, grabbed = cap.read()
            if ok and grabbed is not None:
                frame = grabbed

        # 最后兜底：如果目标帧失败，取最接近的缓存帧，至少保证有可视化结果。
        if frame is None and frame_cache:
            nearest_idx = min(frame_cache.keys(), key=lambda x: abs(int(x) - frame_idx))
            nearest = frame_cache.get(nearest_idx)
            if nearest is not None:
                try:
                    frame = nearest.copy()
                except Exception:
                    frame = nearest
                cand["frame_fallback"] = int(nearest_idx)

        if frame is None:
            continue
        canvas = frame.copy()
        cid = str(cand.get("id", f"cand-{i}"))
        safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in cid)
        _draw_hoop_candidate_overlay(canvas, cand, f"{safe_id}")
        out = debug_dir / f"auto_hoop_{safe_id}_f{frame_idx:06d}.jpg"
        cv2.imwrite(str(out), canvas)
        cand["frame_image"] = str(out)
    if cap is not None:
        cap.release()


def maybe_auto_fill_hoop(
    cap,
    cfg_raw: Dict,
    config_path: str,
    video_path: str,
    debug_dir: Path,
    width: int,
    height: int,
    total_frames: int,
) -> Dict:
    """按 auto_hoop 配置自动识别篮框，并回填到 cfg_raw。"""
    auto_cfg = load_auto_hoop_config(cfg_raw)
    if not auto_cfg.enabled:
        return {"enabled": False, "status": "disabled"}

    require_cv_deps()
    model_path = _resolve_auto_hoop_model_path(auto_cfg.model_path, config_path)
    if model_path is None:
        raise RuntimeError(
            "auto_hoop enabled but model not found. "
            "export best.onnx and ensure it is bundled under models/hoop/best.onnx "
            "or placed under training/hoop_detector/runs/*/weights/"
        )

    net = cv2.dnn.readNetFromONNX(str(model_path))
    sampled_frames: List[int] = []
    if total_frames > 0:
        for ratio in auto_cfg.sample_ratios:
            idx = int(round((total_frames - 1) * ratio))
            sampled_frames.append(max(0, min(total_frames - 1, idx)))
    sampled_frames = sorted(set(sampled_frames))
    if not sampled_frames:
        sampled_frames = [0]

    frame_candidates: List[Dict] = []
    debug_rows: List[Dict] = []
    for frame_idx in sampled_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            debug_rows.append({"frame": frame_idx, "ok": False, "detections": []})
            continue
        dets = _infer_hoop_boxes_with_onnx(frame, net, auto_cfg)
        row = {"frame": frame_idx, "ok": True, "detections": []}
        for det in dets:
            cx = (float(det["x1"]) + float(det["x2"])) * 0.5
            cy = (float(det["y1"]) + float(det["y2"])) * 0.5
            r = max(float(det["x2"]) - float(det["x1"]), float(det["y2"]) - float(det["y1"])) * 0.5
            cand = {
                "frame": frame_idx,
                "score": float(det["score"]),
                "cx": cx,
                "cy": cy,
                "r": r,
                "box": {
                    "x1": float(det["x1"]),
                    "y1": float(det["y1"]),
                    "x2": float(det["x2"]),
                    "y2": float(det["y2"]),
                },
            }
            frame_candidates.append(cand)
            row["detections"].append(cand)
        debug_rows.append(row)

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    selected = _select_hoop_from_candidates(frame_candidates)
    debug_payload = {
        "enabled": True,
        "video": video_path,
        "model_path": str(model_path),
        "sample_frames": sampled_frames,
        "detections": debug_rows,
        "selected_hoop": selected,
    }
    debug_dir.mkdir(parents=True, exist_ok=True)
    auto_debug_path = debug_dir / "auto_hoop_debug.json"
    auto_debug_path.write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if selected is None:
        raise RuntimeError("auto_hoop found no valid hoop candidate")

    selected["cx"] = max(0, min(width - 1, int(selected["cx"])))
    selected["cy"] = max(0, min(height - 1, int(selected["cy"])))
    selected["r"] = max(4, int(selected["r"]))
    cfg_raw["hoop"] = selected

    if config_path:
        cfg_out = Path(config_path)
        cfg_out.write_text(json.dumps(cfg_raw, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "enabled": True,
        "status": "applied",
        "model_path": str(model_path),
        "selected_hoop": selected,
        "debug_json": str(auto_debug_path),
    }


def detect_hoop_candidates(
    video_path: str,
    cfg_raw: Dict,
    config_path: str,
    debug_dir: Path,
) -> Dict:
    """只执行篮框候选检测（用于前端确认流程）。"""
    require_cv_deps()
    auto_cfg = load_auto_hoop_config(cfg_raw)
    model_path = _resolve_auto_hoop_model_path(auto_cfg.model_path, config_path)
    if model_path is None:
        raise RuntimeError(
            "auto hoop model not found. export best.onnx and ensure it is bundled under models/hoop/best.onnx "
            "or placed under training/hoop_detector/runs/*/weights/"
        )

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    net = cv2.dnn.readNetFromONNX(str(model_path))
    sampled_frames: List[int] = []
    if total_frames > 0:
        for ratio in auto_cfg.sample_ratios:
            idx = int(round((total_frames - 1) * ratio))
            sampled_frames.append(max(0, min(total_frames - 1, idx)))
    sampled_frames = sorted(set(sampled_frames))
    if not sampled_frames:
        sampled_frames = [0]

    frame_candidates: List[Dict] = []
    debug_rows: List[Dict] = []
    frame_cache: Dict[int, object] = {}
    for frame_idx in sampled_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            debug_rows.append({"frame": frame_idx, "ok": False, "detections": []})
            continue
        frame_cache[frame_idx] = frame.copy()
        dets = _infer_hoop_boxes_with_onnx(frame, net, auto_cfg)
        row = {"frame": frame_idx, "ok": True, "detections": []}
        for det in dets:
            cx = (float(det["x1"]) + float(det["x2"])) * 0.5
            cy = (float(det["y1"]) + float(det["y2"])) * 0.5
            r = max(float(det["x2"]) - float(det["x1"]), float(det["y2"]) - float(det["y1"])) * 0.5
            cand = {
                "frame": frame_idx,
                "score": float(det["score"]),
                "cx": cx,
                "cy": cy,
                "r": r,
                "box": {
                    "x1": float(det["x1"]),
                    "y1": float(det["y1"]),
                    "x2": float(det["x2"]),
                    "y2": float(det["y2"]),
                },
            }
            frame_candidates.append(cand)
            row["detections"].append(cand)
        debug_rows.append(row)
    cap.release()

    clusters = _cluster_hoop_candidates(frame_candidates)
    candidates_out: List[Dict] = []
    for item in clusters[:8]:
        cx = max(0, min(width - 1, int(item["cx"])))
        cy = max(0, min(height - 1, int(item["cy"])))
        r = max(4, int(item["r"]))
        cand = {
            "id": str(item.get("id", "")),
            "cx": cx,
            "cy": cy,
            "r": r,
            "score": float(item.get("score", 0.0)),
            "count": int(item.get("count", 1)),
        }
        frame_idx = int(item.get("frame", -1))
        if frame_idx >= 0:
            cand["frame"] = frame_idx
        box = item.get("box")
        if isinstance(box, dict):
            cand["box"] = {
                "x1": float(box.get("x1", 0.0)),
                "y1": float(box.get("y1", 0.0)),
                "x2": float(box.get("x2", 0.0)),
                "y2": float(box.get("y2", 0.0)),
            }
        candidates_out.append(cand)

    status = "none"
    if len(candidates_out) == 1:
        status = "single"
    elif len(candidates_out) > 1:
        status = "multiple"

    _write_hoop_candidate_frame_images(
        video_path=video_path,
        candidates=candidates_out,
        debug_dir=debug_dir,
        frame_cache=frame_cache,
    )

    preview_path = ""
    for cand in candidates_out:
        img = str(cand.get("frame_image", "")).strip()
        if img:
            preview_path = img
            break
    if not preview_path:
        preview_path = _write_hoop_candidates_preview(
            video_path=video_path,
            sampled_frames=sampled_frames,
            candidates=candidates_out,
            debug_dir=debug_dir,
        ) or ""
    debug_payload = {
        "video": video_path,
        "model_path": str(model_path),
        "sample_frames": sampled_frames,
        "frame_size": {"width": width, "height": height},
        "status": status,
        "detections": debug_rows,
        "candidates": candidates_out,
        "preview_image": preview_path,
    }
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_json = debug_dir / "auto_hoop_candidates.json"
    debug_json.write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": status,
        "model_path": str(model_path),
        "sample_frames": sampled_frames,
        "frame_size": {"width": width, "height": height},
        "candidates": candidates_out,
        "preview_image": preview_path,
        "debug_json": str(debug_json),
    }


def require_cv_deps() -> None:
    """按需导入 OpenCV 与 NumPy。

    Raises:
        RuntimeError: 自动检测依赖缺失时抛出。
    """
    global cv2, np
    if cv2 is not None and np is not None:
        return
    try:
        import cv2 as _cv2  # type: ignore
        import numpy as _np  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "auto detect mode requires OpenCV and NumPy. "
            "Install with: pip install opencv-python numpy"
        ) from e
    cv2 = _cv2
    np = _np


def setup_regions(cfg: Dict, width: int, height: int) -> Tuple[Rect, Rect, Rect]:
    """根据篮框标定参数派生主要 ROI。

    Args:
        cfg: 配置字典，读取 `hoop.cx/cy/r`。
        width: 视频宽度（像素）。
        height: 视频高度（像素）。

    Returns:
        `(hoop_region, hoop_above_region, detect_region)` 三个区域。
    """
    # 以 hoop(cx,cy,r) 为核心，若未提供则使用保守默认值。
    hoop = cfg.get("hoop", {})
    cx = int(hoop.get("cx", width * 0.5))
    cy = int(hoop.get("cy", height * 0.35))
    r = int(hoop.get("r", max(15, min(width, height) * 0.035)))

    # hoop_region：篮框核心判断区域（当前版本高度较紧，减少误检）。
    hoop_top = cy - int(0.30 * r)
    hoop_bottom = cy + int(0.50 * r)
    hoop_region = Rect(cx - r, hoop_top, cx + r, hoop_bottom).clip(width, height)

    # hoop_above_region：用于判定“球先从框上方来”。
    hoop_above_top = hoop_top - 2 * r
    hoop_above_bottom = hoop_top - max(2, int(0.15 * r))  # 与 hoop_region 保留最小间隙
    hoop_above_region = Rect(cx - 2 * r, hoop_above_top, cx + 2 * r, hoop_above_bottom).clip(width, height)

    # detect_region：找球的大范围 ROI（上边/左右都做过收缩以提升稳定性）。
    detect_top = cy - 3 * r
    detect_top = min(detect_top, hoop_above_top)
    detect_half_width = max(r + 1, int(2.6 * r))
    detect_region = Rect(cx - detect_half_width, detect_top, cx + detect_half_width, cy + 2 * r).clip(width, height)
    return hoop_region, hoop_above_region, detect_region


def crop(frame, rect: Rect):
    """按矩形区域裁剪图像。"""
    return frame[rect.y1:rect.y2, rect.x1:rect.x2]


def find_ball_center(mask, cfg: DetectConfig) -> Optional[Tuple[int, int]]:
    """在前景掩码中寻找最像篮球的轮廓中心。

    Args:
        mask: 二值前景图（255 表示前景）。
        cfg: 检测参数（面积范围、圆度阈值等）。

    Returns:
        `(x, y)` 球心坐标（相对当前 ROI），找不到返回 `None`。
    """
    # 在前景图中找最像“球”的轮廓中心
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1.0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < cfg.min_ball_area or area > cfg.max_ball_area:
            continue
        peri = cv2.arcLength(cnt, True)
        if peri <= 1e-6:
            continue
        circularity = 4.0 * np.pi * area / (peri * peri)
        if circularity < cfg.min_ball_circularity:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        score = area * circularity
        if score > best_score:
            best_score = score
            best = (x + w // 2, y + h // 2)
    return best


def _draw_regions_overlay(
    canvas,
    hoop_region: Rect,
    hoop_above_region: Rect,
    detect_region: Rect,
    net_region: Rect,
) -> None:
    """在图像上绘制检测相关 ROI。"""
    cv2.rectangle(canvas, (detect_region.x1, detect_region.y1), (detect_region.x2, detect_region.y2), (0, 255, 0), 2)
    cv2.putText(canvas, "detect_region", (detect_region.x1, max(15, detect_region.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
    cv2.rectangle(canvas, (hoop_above_region.x1, hoop_above_region.y1), (hoop_above_region.x2, hoop_above_region.y2), (255, 0, 0), 2)
    cv2.putText(canvas, "hoop_above_region", (hoop_above_region.x1, max(15, hoop_above_region.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 0), 2)
    cv2.rectangle(canvas, (hoop_region.x1, hoop_region.y1), (hoop_region.x2, hoop_region.y2), (0, 0, 255), 2)
    cv2.putText(canvas, "hoop_region", (hoop_region.x1, max(15, hoop_region.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
    cv2.rectangle(canvas, (net_region.x1, net_region.y1), (net_region.x2, net_region.y2), (255, 255, 0), 2)
    cv2.putText(canvas, "net_region", (net_region.x1, max(15, net_region.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)


def _draw_hoop_overlay(canvas, hoop_cfg: Dict) -> None:
    """在图像上绘制 hoop 圆与中心点。"""
    if not isinstance(hoop_cfg, dict):
        return
    try:
        cx = int(hoop_cfg.get("cx", -1))
        cy = int(hoop_cfg.get("cy", -1))
        r = int(hoop_cfg.get("r", -1))
    except Exception:
        return
    if r <= 0 or cx < 0 or cy < 0:
        return
    cv2.circle(canvas, (cx, cy), r, (255, 0, 255), 2)
    cv2.circle(canvas, (cx, cy), 3, (255, 0, 255), -1)
    cv2.putText(canvas, f"hoop({cx},{cy},r={r})", (max(5, cx - r), max(20, cy - r - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)


def _draw_goal_event_overlay(canvas, ev: Dict, idx: int) -> None:
    """在事件截图上绘制事件信息（原因、时间、置信度）。"""
    reason = str(ev.get("reason", "unknown"))
    time_sec = float(ev.get("time_sec", 0.0))
    conf = float(ev.get("confidence", 0.0))
    net_motion = ev.get("net_motion", None)
    line1 = f"goal#{idx:03d}  t={time_sec:.2f}s  reason={reason}"
    cv2.putText(canvas, line1, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 3)
    cv2.putText(canvas, line1, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 20, 20), 1)
    line2 = f"confidence={conf:.3f}"
    if net_motion is not None:
        line2 += f"  net_motion={float(net_motion):.4f}"
    cv2.putText(canvas, line2, (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 3)
    cv2.putText(canvas, line2, (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1)


def _write_roi_debug_image(
    output_dir: Path,
    frame,
    hoop_region: Rect,
    hoop_above_region: Rect,
    detect_region: Rect,
    net_region: Rect,
    hoop_cfg: Optional[Dict] = None,
) -> Optional[str]:
    """绘制并保存 ROI 调试图。

    Args:
        output_dir: 调试输出目录。
        frame: 用于绘图的原始帧。
        hoop_region: 篮框核心区域。
        hoop_above_region: 篮框上方区域。
        detect_region: 球检测区域。
        net_region: 篮网运动检测区域。

    Returns:
        生成的图片绝对路径；若 frame 为空返回 `None`。
    """
    if frame is None:
        return None
    canvas = frame.copy()
    _draw_regions_overlay(canvas, hoop_region, hoop_above_region, detect_region, net_region)
    _draw_hoop_overlay(canvas, hoop_cfg or {})

    out = output_dir / "roi_debug.jpg"
    cv2.imwrite(str(out), canvas)
    return str(out)


def _build_tuning_suggestions(
    cfg: DetectConfig,
    candidate_count: int,
    event_count: int,
    ball_only_count: int,
    duration_sec: float,
) -> Dict:
    """根据一次检测统计产出调参建议。

    Args:
        cfg: 当前检测配置。
        candidate_count: 候选穿框事件数量。
        event_count: 最终事件数量（去重后）。
        ball_only_count: 未通过篮网确认的事件数量。
        duration_sec: 处理视频时长（秒）。

    Returns:
        含 `summary` 与 `suggestions` 的字典。
    """
    # 根据本次统计给出下一轮调参建议
    suggestions: List[Dict] = []
    events_per_min = (event_count / max(1.0, duration_sec)) * 60.0

    if event_count == 0:
        suggestions.append({
            "level": "high",
            "message": "未检测到进球，优先检查 hoop(cx,cy,r) 是否准确覆盖篮框。",
            "suggested_changes": {"hoop.cx": "recheck", "hoop.cy": "recheck", "hoop.r": "recheck"},
        })
        suggestions.append({
            "level": "medium",
            "message": "可能漏检，建议将 detect.frame_skip 调到 1，并适度降低 detect.net_motion_threshold。",
            "suggested_changes": {"detect.frame_skip": 1, "detect.net_motion_threshold": round(max(0.01, cfg.net_motion_threshold - 0.008), 4)},
        })

    if candidate_count >= 8 and event_count <= max(1, candidate_count // 5):
        suggestions.append({
            "level": "medium",
            "message": "球候选较多但有效事件较少，篮网确认可能偏严。",
            "suggested_changes": {
                "detect.net_motion_threshold": round(max(0.01, cfg.net_motion_threshold - 0.006), 4),
                "detect.net_confirm_window_sec": round(cfg.net_confirm_window_sec + 0.15, 3),
            },
        })

    if events_per_min > 6.0:
        suggestions.append({
            "level": "medium",
            "message": "事件密度偏高，可能误检偏多，建议提高形状过滤与篮网阈值。",
            "suggested_changes": {
                "detect.min_ball_circularity": round(min(0.8, cfg.min_ball_circularity + 0.08), 3),
                "detect.min_ball_area": int(cfg.min_ball_area * 1.25),
                "detect.net_motion_threshold": round(cfg.net_motion_threshold + 0.01, 4),
            },
        })

    if event_count > 0 and ball_only_count / max(1, event_count) > 0.7:
        suggestions.append({
            "level": "low",
            "message": "多数事件未通过篮网确认，建议检查 net_region 是否偏移。",
            "suggested_changes": {"hoop.cy": "adjust +/- 8~20 px", "hoop.r": "adjust +/- 4~10 px"},
        })

    if not suggestions:
        suggestions.append({
            "level": "info",
            "message": "当前参数表现稳定，可在更多视频上验证再微调。",
            "suggested_changes": {},
        })

    return {
        "summary": {
            "candidate_count": candidate_count,
            "event_count": event_count,
            "ball_cross_only_count": ball_only_count,
            "duration_sec": round(duration_sec, 2),
            "events_per_min": round(events_per_min, 3),
        },
        "suggestions": suggestions,
    }


class ProgressWriter:
    """进度文件写入器（给 Go 侧轮询用）。"""

    def __init__(self, path: Optional[Path]):
        """初始化进度写入器。

        Args:
            path: 进度文件路径；为 `None` 时不写文件。
        """
        self.path = path
        self.last_write = 0.0

    def write(
        self,
        stage: str,
        percent: float,
        processed_frames: int,
        total_frames: int,
        elapsed_sec: float,
        estimated_left_sec: float,
        force: bool = False,
    ) -> None:
        """写入检测进度。

        Args:
            stage: 当前阶段名。
            percent: 当前进度百分比（0~100）。
            processed_frames: 已处理帧数。
            total_frames: 总帧数。
            elapsed_sec: 已耗时（秒）。
            estimated_left_sec: 预计剩余（秒）。
            force: 是否忽略限频，强制写盘。
        """
        # 限频写入进度文件，避免过于频繁的磁盘 IO
        if self.path is None:
            return
        now = time.time()
        if not force and (now - self.last_write) < 0.6:
            return
        payload = {
            "stage": stage,
            "percent": round(max(0.0, min(100.0, percent)), 3),
            "processed_frames": int(max(0, processed_frames)),
            "total_frames": int(max(0, total_frames)),
            "elapsed_sec": round(max(0.0, elapsed_sec), 3),
            "estimated_left_sec": round(max(0.0, estimated_left_sec), 3),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.last_write = now


class LiteDebugWriter:
    """轻量调试产物写入器。"""

    def __init__(self, debug_root: Path, cfg: LiteDebugConfig):
        """初始化轻量调试输出结构。

        Args:
            debug_root: `debug` 根目录。
            cfg: 轻量调试配置。
        """
        # 轻量调试默认关闭，只有显式开关时才会产生额外磁盘输出。
        self.enabled = bool(cfg.enabled)
        self.frame_step = max(1, int(cfg.frame_step))
        self.max_frames = max(0, int(cfg.max_frames))
        self.root_dir = debug_root / "lite_debug"
        self.frames_dir = self.root_dir / "frames"
        self.frame_saved = 0
        self.frame_metrics: List[Dict] = []
        self.candidates: List[Dict] = []
        if self.enabled:
            self.frames_dir.mkdir(parents=True, exist_ok=True)

    def add_candidate(
        self,
        frame_idx: int,
        time_sec: float,
        moving_down: bool,
        above_recently: bool,
        ball_conf: float,
    ) -> None:
        """记录一次候选事件信息。"""
        if not self.enabled:
            return
        self.candidates.append({
            "frame": int(frame_idx),
            "time_sec": round(float(time_sec), 4),
            "moving_down": bool(moving_down),
            "above_recently": bool(above_recently),
            "ball_conf": round(float(ball_conf), 3),
        })

    def record_frame(
        self,
        frame_idx: int,
        fps: float,
        frame,
        detect_region: Rect,
        hoop_above_region: Rect,
        hoop_region: Rect,
        net_region: Rect,
        ball_center: Optional[Tuple[int, int]],
        in_above: bool,
        in_hoop: bool,
        above_recently: bool,
        moving_down: bool,
        net_motion: float,
        cooldown: int,
    ) -> None:
        """记录采样帧指标，并按配置可选保存可视化图片。"""
        if not self.enabled:
            return
        if frame_idx % self.frame_step != 0:
            return

        # 指标记录优先于图片输出：即使达到 max_frames，仍可继续保留数值轨迹。
        metric = {
            "frame": int(frame_idx),
            "time_sec": round(float(frame_idx / max(1e-6, fps)), 4),
            "ball_found": ball_center is not None,
            "ball_x": int(ball_center[0]) if ball_center is not None else None,
            "ball_y": int(ball_center[1]) if ball_center is not None else None,
            "in_above": bool(in_above),
            "in_hoop": bool(in_hoop),
            "above_recently": bool(above_recently),
            "moving_down": bool(moving_down),
            "net_motion": round(float(net_motion), 5),
            "cooldown": int(cooldown),
        }
        self.frame_metrics.append(metric)

        if self.frame_saved >= self.max_frames:
            return
        canvas = frame.copy()
        cv2.rectangle(canvas, (detect_region.x1, detect_region.y1), (detect_region.x2, detect_region.y2), (0, 255, 0), 2)
        cv2.rectangle(canvas, (hoop_above_region.x1, hoop_above_region.y1), (hoop_above_region.x2, hoop_above_region.y2), (255, 0, 0), 2)
        cv2.rectangle(canvas, (hoop_region.x1, hoop_region.y1), (hoop_region.x2, hoop_region.y2), (0, 0, 255), 2)
        cv2.rectangle(canvas, (net_region.x1, net_region.y1), (net_region.x2, net_region.y2), (255, 255, 0), 2)
        if ball_center is not None:
            cv2.circle(canvas, ball_center, 4, (0, 255, 255), -1)
        text = f"f={frame_idx} net={net_motion:.4f} in_above={int(in_above)} in_hoop={int(in_hoop)}"
        cv2.putText(canvas, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

        out_path = self.frames_dir / f"frame_{frame_idx:06d}.jpg"
        cv2.imwrite(str(out_path), canvas)
        self.frame_saved += 1

    def finalize(
        self,
        events: List[Dict],
        dedup: List[Dict],
        regions: Dict,
        cfg: DetectConfig,
        stats: Dict,
    ) -> Optional[str]:
        """落盘轻量调试结果。

        Args:
            events: 去重前事件列表。
            dedup: 去重后事件列表。
            regions: 当前 ROI 参数快照。
            cfg: 本次检测配置。
            stats: 本次统计信息。

        Returns:
            轻量调试目录路径；若调试未开启返回 `None`。
        """
        if not self.enabled:
            return None

        # 输出多份结构化文件，便于脚本化分析与人工排查。
        (self.root_dir / "candidates.json").write_text(
            json.dumps(self.candidates, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (self.root_dir / "events_raw.json").write_text(
            json.dumps(events, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (self.root_dir / "events_dedup.json").write_text(
            json.dumps(dedup, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary = {
            "sampled_frame_count": len(self.frame_metrics),
            "saved_frame_count": self.frame_saved,
            "candidate_count": len(self.candidates),
            "regions": regions,
            "detect_settings": vars(cfg),
            "stats": stats,
        }
        (self.root_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        metrics_path = self.root_dir / "frame_metrics.jsonl"
        with metrics_path.open("w", encoding="utf-8") as f:
            for item in self.frame_metrics:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return str(self.root_dir)


def _save_goal_frames(
    video_path: str,
    output_dir: Path,
    events: List[Dict],
    fps: float,
    hoop_region: Rect,
    hoop_above_region: Rect,
    detect_region: Rect,
    net_region: Rect,
    hoop_cfg: Dict,
) -> Optional[str]:
    """为最终事件保存关键帧截图。

    Args:
        video_path: 输入视频路径。
        output_dir: 调试输出目录（会写入 `goal_frames/`）。
        events: 最终事件列表，会原地补充 `frame_image` 字段。
        fps: 视频帧率。
        hoop_region: 篮框核心区域。
        hoop_above_region: 篮框上方区域。
        detect_region: 球检测区域。
        net_region: 篮网运动检测区域。
        hoop_cfg: hoop(cx,cy,r) 参数，用于绘制篮框位置。

    Returns:
        `goal_evidence.json` 路径；若未生成返回 `None`。
    """
    # 为每个最终事件保存一帧截图，便于人工复核
    if not events:
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    frame_dir = output_dir / "goal_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    evidence_records: List[Dict] = []

    for idx, ev in enumerate(events, start=1):
        target_frame = int(round(float(ev["time_sec"]) * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, frame = cap.read()
        if not ok:
            continue
        out = frame_dir / f"goal_{idx:03d}_{float(ev['time_sec']):.2f}s.jpg"
        canvas = frame.copy()
        _draw_regions_overlay(canvas, hoop_region, hoop_above_region, detect_region, net_region)
        _draw_hoop_overlay(canvas, hoop_cfg)
        _draw_goal_event_overlay(canvas, ev, idx)
        cv2.imwrite(str(out), canvas)
        ev["frame_image"] = str(out)
        evidence_records.append({
            "index": idx,
            "time_sec": round(float(ev.get("time_sec", 0.0)), 4),
            "reason": str(ev.get("reason", "")),
            "confidence": round(float(ev.get("confidence", 0.0)), 3),
            "net_motion": round(float(ev.get("net_motion", 0.0)), 4) if ev.get("net_motion") is not None else None,
            "frame_image": str(out),
        })
    cap.release()
    evidence_path = output_dir / "goal_evidence.json"
    evidence_path.write_text(json.dumps(evidence_records, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(evidence_path)


def detect_goals_auto(
    video_path: str,
    cfg_raw: Dict,
    config_path: str,
    output_dir: Path,
    debug_dir: Path,
    progress: ProgressWriter,
    lite_debug_cfg: Optional[LiteDebugConfig] = None,
) -> Tuple[List[Dict], Dict]:
    """自动检测进球事件。

    Args:
        video_path: 输入视频路径。
        cfg_raw: 完整配置字典。
        config_path: 当前任务配置文件路径（用于回填 hoop）。
        output_dir: 输出目录（用于 goals 与调试文件）。
        debug_dir: 调试目录。
        progress: 进度写入器。
        lite_debug_cfg: 轻量调试配置，`None` 时用默认值。

    Returns:
        `(events, meta)`：
        - events: 最终去重后的事件列表。
        - meta: 本次检测的元信息与调试产物路径。
    """
    require_cv_deps()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 1e-6:
        fps = 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    cfg = load_detect_config(cfg_raw)
    auto_hoop_cfg = load_auto_hoop_config(cfg_raw)
    auto_hoop_meta = {"enabled": auto_hoop_cfg.enabled, "status": "disabled"}
    if auto_hoop_cfg.enabled:
        try:
            auto_hoop_meta = maybe_auto_fill_hoop(
                cap=cap,
                cfg_raw=cfg_raw,
                config_path=config_path,
                video_path=video_path,
                debug_dir=debug_dir,
                width=width,
                height=height,
                total_frames=total_frames,
            )
        except Exception as e:
            if not auto_hoop_cfg.fallback_to_manual:
                cap.release()
                raise
            auto_hoop_meta = {
                "enabled": True,
                "status": "fallback_manual",
                "error": str(e),
            }
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    if not _is_valid_hoop(cfg_raw, width, height):
        cap.release()
        raise RuntimeError("hoop is missing/invalid after auto_hoop. set hoop manually or fix auto_hoop model/config.")

    # 区域由 hoop(cx, cy, r) 推导，避免多个 ROI 需手工分别维护。
    hoop_region, hoop_above_region, detect_region = setup_regions(cfg_raw, width, height)
    hoop_height = max(1, hoop_region.y2 - hoop_region.y1)
    # net_region：在原下扩高度基础上，再向下增加 1/3 高度。
    net_upward_expand = max(2, int(0.2 * hoop_height))
    net_downward_extra = max(1, int(2*hoop_height))
    net_region = Rect(
        hoop_region.x1,
        hoop_region.y2 - net_upward_expand,
        hoop_region.x2,
        hoop_region.y2 + net_downward_extra,
    ).clip(width, height)

    bg = cv2.createBackgroundSubtractorMOG2(history=cfg.bg_history, varThreshold=cfg.bg_var_threshold, detectShadows=False)
    prev_net_gray: Optional[np.ndarray] = None
    track: List[Tuple[int, int, float]] = []
    cooldown_frames = int(cfg.cooldown_sec * fps)
    confirm_window_frames = int(cfg.net_confirm_window_sec * fps)
    merge_window_frames = int(cfg.event_merge_window_sec * fps)
    cooldown = 0
    frame_idx = 0
    started = time.time()
    events: List[Dict] = []
    candidates: List[Dict] = []
    # 按帧记录 net motion，后续候选确认时按窗口直接查值。
    net_motion_by_frame: Dict[int, float] = {}
    first_frame = None
    last_above_frame = -10**9
    debug_dir.mkdir(parents=True, exist_ok=True)
    lite_debug = LiteDebugWriter(debug_dir, lite_debug_cfg or LiteDebugConfig())

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        if first_frame is None:
            first_frame = frame.copy()
        if frame_idx % max(1, cfg.frame_skip) != 0:
            continue
        if cooldown > 0:
            cooldown -= 1

        ball_center: Optional[Tuple[int, int]] = None
        in_above = False
        in_hoop = False
        above_recently = False
        moving_down = False

        det_roi = crop(frame, detect_region)
        # 运动前景提取 + 轮廓过滤，定位当前帧最像“球”的目标中心。
        fg = bg.apply(det_roi)
        _, fg = cv2.threshold(fg, 220, 255, cv2.THRESH_BINARY)
        center_local = find_ball_center(fg, cfg)

        if center_local is not None:
            gx = center_local[0] + detect_region.x1
            gy = center_local[1] + detect_region.y1
            ball_center = (gx, gy)
            track.append((gx, gy, frame_idx / fps))
            if len(track) > cfg.track_len:
                track.pop(0)

            in_above = hoop_above_region.x1 <= gx <= hoop_above_region.x2 and hoop_above_region.y1 <= gy <= hoop_above_region.y2
            in_hoop = hoop_region.x1 <= gx <= hoop_region.x2 and hoop_region.y1 <= gy <= hoop_region.y2
            if in_above:
                last_above_frame = frame_idx

            # 穿框判定采用时间序列逻辑：
            # 先在“框上方”出现，再进入 hoop_region，且轨迹整体向下
            if len(track) >= 3 and in_hoop and cooldown <= 0:
                y0 = track[0][1]
                y2 = track[-1][1]
                moving_down = y2 > y0 + 3
                above_recently = (frame_idx - last_above_frame) <= max(2, int(0.8 * fps))
                if moving_down and above_recently:
                    candidates.append({
                        "frame": frame_idx,
                        "time_sec": frame_idx / fps,
                        "ball_conf": 0.65,
                    })
                    lite_debug.add_candidate(
                        frame_idx=frame_idx,
                        time_sec=frame_idx / fps,
                        moving_down=moving_down,
                        above_recently=above_recently,
                        ball_conf=0.65,
                    )
                    cooldown = cooldown_frames
                    track.clear()

        net_roi = crop(frame, net_region)
        net_gray = cv2.cvtColor(net_roi, cv2.COLOR_BGR2GRAY)
        current_motion = 0.0
        if prev_net_gray is not None:
            diff = cv2.absdiff(prev_net_gray, net_gray)
            _, t = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
            motion_ratio = float(np.count_nonzero(t)) / float(t.size)
            net_motion_by_frame[frame_idx] = motion_ratio
            current_motion = motion_ratio
        prev_net_gray = net_gray

        lite_debug.record_frame(
            frame_idx=frame_idx,
            fps=fps,
            frame=frame,
            detect_region=detect_region,
            hoop_above_region=hoop_above_region,
            hoop_region=hoop_region,
            net_region=net_region,
            ball_center=ball_center,
            in_above=in_above,
            in_hoop=in_hoop,
            above_recently=above_recently,
            moving_down=moving_down,
            net_motion=current_motion,
            cooldown=cooldown,
        )

        progress_pct = (frame_idx / max(1, total_frames)) * 100.0
        elapsed = time.time() - started
        eta = 0.0
        if progress_pct > 0:
            eta = elapsed * (100.0 / progress_pct - 1.0)
        progress.write(
            stage="detecting",
            percent=progress_pct,
            processed_frames=frame_idx,
            total_frames=total_frames,
            elapsed_sec=elapsed,
            estimated_left_sec=eta,
        )

    cap.release()

    for cand in candidates:
        # 候选事件需要在确认窗口内通过 net_motion 二次确认。
        c_frame = cand["frame"]
        lo = c_frame
        hi = c_frame + max(1, confirm_window_frames)
        net_motion = 0.0
        for f in range(lo, hi + 1):
            val = net_motion_by_frame.get(f)
            if val is not None and val > net_motion:
                net_motion = val
        net_pass = net_motion >= cfg.net_motion_threshold
        score = float(cand["ball_conf"] + min(0.35, net_motion * 4.0))
        reason = "ball_cross+net_motion" if net_pass else "ball_cross_only"
        events.append({
            "time_sec": float(cand["time_sec"]),
            "confidence": round(score, 3),
            "reason": reason,
            "net_motion": round(net_motion, 4),
        })

    # 时间排序 + 去重（保留同窗口内置信度更高的事件）
    events.sort(key=lambda x: x["time_sec"])
    dedup: List[Dict] = []
    for ev in events:
        if not dedup:
            dedup.append(ev)
            continue
        if ev["time_sec"] - dedup[-1]["time_sec"] < (merge_window_frames / fps):
            if ev["confidence"] > dedup[-1]["confidence"]:
                dedup[-1] = ev
        else:
            dedup.append(ev)

    roi_debug_path = _write_roi_debug_image(
        debug_dir,
        first_frame,
        hoop_region,
        hoop_above_region,
        detect_region,
        net_region,
        hoop_cfg=cfg_raw.get("hoop", {}),
    )
    ball_only_count = sum(1 for e in dedup if e["reason"] == "ball_cross_only")
    duration_sec = frame_idx / fps if frame_idx > 0 else 0.0
    tuning = _build_tuning_suggestions(cfg, len(candidates), len(dedup), ball_only_count, duration_sec)
    tuning_path = debug_dir / "tuning_suggestions.json"
    tuning_path.write_text(json.dumps(tuning, ensure_ascii=False, indent=2), encoding="utf-8")
    goal_evidence_path = _save_goal_frames(
        video_path=video_path,
        output_dir=debug_dir,
        events=dedup,
        fps=fps,
        hoop_region=hoop_region,
        hoop_above_region=hoop_above_region,
        detect_region=detect_region,
        net_region=net_region,
        hoop_cfg=cfg_raw.get("hoop", {}),
    )
    lite_debug_dir = lite_debug.finalize(
        events=events,
        dedup=dedup,
        regions={
            "hoop_region": vars(hoop_region),
            "hoop_above_region": vars(hoop_above_region),
            "detect_region": vars(detect_region),
            "net_region": vars(net_region),
        },
        cfg=cfg,
        stats={
            "candidate_count": len(candidates),
            "event_count": len(dedup),
            "frame_count": frame_idx,
        },
    )
    elapsed_final = time.time() - started
    progress.write(
        stage="detect_done",
        percent=100.0,
        processed_frames=frame_idx,
        total_frames=total_frames,
        elapsed_sec=elapsed_final,
        estimated_left_sec=0.0,
        force=True,
    )

    meta = {
        "engine": "python-mvp-cv",
        "fps": round(float(fps), 3),
        "frame_size": {"width": width, "height": height},
        "regions": {
            "hoop_region": vars(hoop_region),
            "hoop_above_region": vars(hoop_above_region),
            "detect_region": vars(detect_region),
            "net_region": vars(net_region),
        },
        "settings": vars(cfg),
        "stats": {
            "candidate_count": len(candidates),
            "event_count": len(dedup),
        },
        "debug_artifacts": {
            "roi_debug_image": roi_debug_path,
            "tuning_suggestions_json": str(tuning_path),
            "goal_frames_dir": str(debug_dir / "goal_frames"),
            "goal_evidence_json": goal_evidence_path,
            "lite_debug_dir": lite_debug_dir,
        },
        "auto_hoop": auto_hoop_meta,
        "hoop": cfg_raw.get("hoop", {}),
    }
    return dedup, meta


def main():
    """命令行入口。

    Returns:
        无显式返回；写入 `--output` 指定的 JSON 文件。
    """
    parser = argparse.ArgumentParser(description="Basketball goal detection MVP")
    parser.add_argument("--video", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--debug-dir", default="", help="directory to store debug artifacts")
    parser.add_argument("--manual-goals", default="", help="comma-separated seconds, e.g. 12.5,45.2")
    parser.add_argument("--progress-file", default="", help="path to write progress json")
    parser.add_argument("--lite-debug", action="store_true", help="enable lightweight debug outputs (off by default)")
    parser.add_argument("--lite-debug-frame-step", type=int, default=12, help="save one debug frame/metric every N processed frames")
    parser.add_argument("--lite-debug-max-frames", type=int, default=120, help="max debug frame images to save")
    parser.add_argument("--detect-hoop-only", action="store_true", help="only detect hoop candidates and skip goal detection")
    args = parser.parse_args()

    cfg_raw = load_json(args.config)
    manual = parse_manual_goals(args.manual_goals)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    debug_dir = Path(args.debug_dir) if args.debug_dir else (out_path.parent / "debug")
    lite_debug_cfg = LiteDebugConfig(
        enabled=bool(args.lite_debug),
        frame_step=max(1, int(args.lite_debug_frame_step)),
        max_frames=max(0, int(args.lite_debug_max_frames)),
    )

    if args.detect_hoop_only:
        hoop_detection = detect_hoop_candidates(
            video_path=args.video,
            cfg_raw=cfg_raw,
            config_path=args.config,
            debug_dir=debug_dir,
        )
        payload = {
            "video": args.video,
            "config": args.config,
            "mode": "hoop_only",
            "hoop_detection": hoop_detection,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    progress = ProgressWriter(Path(args.progress_file) if args.progress_file else None)
    started = time.time()
    if manual:
        # 手工模式不走视频检测，直接生成事件并写完成进度。
        events = [{"time_sec": sec, "confidence": 1.0, "reason": "manual_input"} for sec in manual]
        meta = {"engine": "python-mvp-manual"}
        progress.write(
            stage="manual_done",
            percent=100.0,
            processed_frames=0,
            total_frames=0,
            elapsed_sec=time.time() - started,
            estimated_left_sec=0.0,
            force=True,
        )
    else:
        # 自动模式执行完整检测流程并产出调试文件。
        events, meta = detect_goals_auto(
            args.video,
            cfg_raw,
            args.config,
            out_path.parent,
            debug_dir,
            progress,
            lite_debug_cfg=lite_debug_cfg,
        )

    payload = {
        "video": args.video,
        "config": args.config,
        "events": events,
        "meta": meta,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
