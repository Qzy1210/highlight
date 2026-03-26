#!/usr/bin/env python3
"""篮球进球检测主脚本。

该脚本提供两种模式：
1. 自动检测模式：基于 OpenCV 在 ROI 内识别球轨迹并结合篮网运动确认事件。
2. 手工模式：直接使用外部传入的时间点，跳过视频检测。

输入通常来自 Go 服务层；输出 `goals.json` 与调试产物目录。
"""

import argparse
import json
import time
from dataclasses import dataclass
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


def _write_roi_debug_image(
    output_dir: Path,
    frame,
    hoop_region: Rect,
    hoop_above_region: Rect,
    detect_region: Rect,
    net_region: Rect,
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
    cv2.rectangle(canvas, (detect_region.x1, detect_region.y1), (detect_region.x2, detect_region.y2), (0, 255, 0), 2)
    cv2.putText(canvas, "detect_region", (detect_region.x1, max(15, detect_region.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
    cv2.rectangle(canvas, (hoop_above_region.x1, hoop_above_region.y1), (hoop_above_region.x2, hoop_above_region.y2), (255, 0, 0), 2)
    cv2.putText(canvas, "hoop_above_region", (hoop_above_region.x1, max(15, hoop_above_region.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 0), 2)
    cv2.rectangle(canvas, (hoop_region.x1, hoop_region.y1), (hoop_region.x2, hoop_region.y2), (0, 0, 255), 2)
    cv2.putText(canvas, "hoop_region", (hoop_region.x1, max(15, hoop_region.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
    cv2.rectangle(canvas, (net_region.x1, net_region.y1), (net_region.x2, net_region.y2), (255, 255, 0), 2)
    cv2.putText(canvas, "net_region", (net_region.x1, max(15, net_region.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)

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


def _save_goal_frames(video_path: str, output_dir: Path, events: List[Dict], fps: float) -> None:
    """为最终事件保存关键帧截图。

    Args:
        video_path: 输入视频路径。
        output_dir: 调试输出目录（会写入 `goal_frames/`）。
        events: 最终事件列表，会原地补充 `frame_image` 字段。
        fps: 视频帧率。
    """
    # 为每个最终事件保存一帧截图，便于人工复核
    if not events:
        return
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return
    frame_dir = output_dir / "goal_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)

    for idx, ev in enumerate(events, start=1):
        target_frame = int(round(float(ev["time_sec"]) * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, frame = cap.read()
        if not ok:
            continue
        out = frame_dir / f"goal_{idx:03d}_{float(ev['time_sec']):.2f}s.jpg"
        cv2.imwrite(str(out), frame)
        ev["frame_image"] = str(out)
    cap.release()


def detect_goals_auto(
    video_path: str,
    cfg_raw: Dict,
    output_dir: Path,
    debug_dir: Path,
    progress: ProgressWriter,
    lite_debug_cfg: Optional[LiteDebugConfig] = None,
) -> Tuple[List[Dict], Dict]:
    """自动检测进球事件。

    Args:
        video_path: 输入视频路径。
        cfg_raw: 完整配置字典。
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

    roi_debug_path = _write_roi_debug_image(debug_dir, first_frame, hoop_region, hoop_above_region, detect_region, net_region)
    ball_only_count = sum(1 for e in dedup if e["reason"] == "ball_cross_only")
    duration_sec = frame_idx / fps if frame_idx > 0 else 0.0
    tuning = _build_tuning_suggestions(cfg, len(candidates), len(dedup), ball_only_count, duration_sec)
    tuning_path = debug_dir / "tuning_suggestions.json"
    tuning_path.write_text(json.dumps(tuning, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_goal_frames(video_path, debug_dir, dedup, fps)
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
            "lite_debug_dir": lite_debug_dir,
        },
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
