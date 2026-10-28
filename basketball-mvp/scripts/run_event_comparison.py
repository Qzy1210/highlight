#!/usr/bin/env python3
"""事件对比编排：自动跑两种检测模式并汇总对比表。

流程:
    truth-dir/*.truth.json  →  对每个视频生成 off/on 两份检出配置  →  调用
    detect_goals.py 分别跑 (off=纯MOG2, on=YOLO+MOG2)  →  汇总 event_comparison.json
    → 打印 MOG2 vs YOLO+MOG2 的 TP/FP/FN/P/R/F1 对比表。

用法:
    python3 scripts/run_event_comparison.py \
        --truth-dir basketball-mvp/workspace/truth \
        --video-dir /path/to/video \
        --out hockey...           (推荐放 basketball-mvp/workspace/event_compare_<date>)
        --python venv/bin/python
        --detect-goals basketball-mvp/engine-py/detect_goals.py
        [--hoop cx,cy,r]          (统一 hoop；缺省取 configs/pipeline.sample.json 里的 hoop)
        [--tolerance 1.0]         (事件匹配容差，秒)
        [--video NAME]            (只跑某个视频 stem，可选)

生成结构:
    <out>/
      configs/off/<stem>.json      检测配置(off)
      configs/on/<stem>.json       检测配置(on)
      detect/<stem>/{off,on}/out.json   检出结果
      goals/<stem>_{off,on}.json   供人工复检的完整事件
      event_comparison.json        汇总
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_TOLERANCE = 1.0


def load_default_hoop(sample_config: Path):
    data = json.loads(sample_config.read_text(encoding="utf-8"))
    h = data.get("hoop", {})
    return int(h.get("cx", 640)), int(h.get("cy", 360)), int(h.get("r", 30))


def find_hoop_model(sample_config: Path):
    """定位可用于按视频自动标定篮框的 ONNX。

    优先项目内 models/hoop/best.onnx，其次打包产物，最后训练 runs。
    """
    root = sample_config.parent.parent  # configs/ -> 项目根
    cands = [root / "models" / "hoop" / "best.onnx"]
    dist_models = root / "dist"
    if dist_models.is_dir():
        cands.extend(dist_models.glob("*/Contents/Resources/project/models/hoop/best.onnx"))
    run_dir = root / "training" / "hoop_detector" / "runs"
    if run_dir.is_dir():
        cands.extend(run_dir.glob("*/weights/best.onnx"))
    for p in cands:
        if p.is_file():
            return p.resolve()
    return None


def detect_hoop_for_video(python, script, video_path, model_path, work_dir: Path):
    """按视频自动检测一个篮框候选，返回 (cx, cy, r) 或 None。

    用 detect_goals.py --detect-hoop-only 一次，取分数最高的候选，
    随后冻结进 off/on 两份配置，保证两种模式使用同一篮框（对比公平）。
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "hoop": {"cx": 640, "cy": 360, "r": 30},
        "auto_hoop": {
            "enabled": True,
            "model_path": str(model_path),
            "input_size": 960,
            "conf_threshold": 0.25,
            "iou_threshold": 0.45,
        },
    }
    cfg_path = work_dir / "hoop_probe.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    out_path = work_dir / "hoop_probe.out.json"
    cmd = [str(python), str(script), "--video", str(video_path),
           "--config", str(cfg_path), "--output", str(out_path),
           "--debug-dir", str(work_dir / "hoop_dbg"), "--detect-hoop-only"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_path.is_file():
        return None, (r.stderr or r.stdout)[-800:]
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    cands = (data.get("hoop_detection") or {}).get("candidates") or []
    if not cands:
        return None, "no hoop candidate"
    best = max(cands, key=lambda c: float(c.get("score", 0.0)))
    return (int(best["cx"]), int(best["cy"]), int(best["r"])), ""


def make_config(hoop, enabled, model_path=""):
    return {
        "pre_seconds": 4.0,
        "post_seconds": 2.0,
        "cooldown_sec": 2.0,
        "hoop": {"cx": hoop[0], "cy": hoop[1], "r": hoop[2]},
        "auto_hoop": {"enabled": False},
        "ball_detector": {
            "enabled": enabled,
            "model_path": model_path,
            "input_size": 640,
            "conf_threshold": 0.15,
            "iou_threshold": 0.45,
            "fallback_to_mog2": True,
        },
        "detect": {
            "frame_skip": 2,
            "cooldown_sec": 2.0,
            "min_ball_area": 30,
            "max_ball_area": 1400,
            "min_ball_circularity": 0.45,
            "track_len": 8,
            "net_motion_threshold": 0.035,
            "net_confirm_window_sec": 0.55,
            "event_merge_window_sec": 1.6,
            "bg_history": 400,
            "bg_var_threshold": 48.0,
        },
    }


def run_detect(python, script, video_path, cfg_path, out_path, debug_root):
    cmd = [
        str(python), str(script),
        "--video", str(video_path),
        "--config", str(cfg_path),
        "--output", str(out_path),
        "--debug-dir", str(debug_root),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout[-2000:], r.stderr[-2000:]


def load_events(json_path):
    if not json_path.is_file():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return sorted(float(e["time_sec"]) for e in data.get("events", []) if float(e["time_sec"]) >= 0)


def match(gt_times, det_times, tol):
    gt_sorted = sorted(gt_times)
    det_sorted = sorted(det_times)
    used_det = set()
    matches = []
    tp = 0
    for gt in gt_sorted:
        best_i, best_dist = -1, tol + 1e-9
        for i, d in enumerate(det_sorted):
            if i in used_det:
                continue
            dist = abs(d - gt)
            if dist < best_dist:
                best_dist, best_i = dist, i
        if best_i >= 0:
            used_det.add(best_i)
            tp += 1
            matches.append((gt, det_sorted[best_i]))
        else:
            matches.append((gt, None))
    fp = len(det_sorted) - tp
    fn = len(gt_sorted) - tp
    return tp, fn, fp, matches


def prf(tp, fn, fp):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def fmt_pct(v):
    return f"{v*100:.1f}%"


def assign_ball_model(sample_config: Path):
    """尝试定位已训练的 ball ONNX（让 on 模式真实启用 YOLO）。"""
    run_dir = sample_config.parent.parent / "training" / "ball_detector" / "runs"
    cands = sorted((run_dir.glob("*/weights/best.onnx")) if run_dir.exists() else [])
    if cands:
        return str(cands[-1].resolve())  # 最近修改的
    return ""


def main():
    parser = argparse.ArgumentParser(description="Run both detection modes and compare against truth")
    parser.add_argument("--truth-dir", required=True)
    parser.add_argument("--video-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--python", default="python3")
    parser.add_argument("--detect-goals", default="engine-py/detect_goals.py")
    parser.add_argument("--sample-config", default="configs/pipeline.sample.json")
    parser.add_argument("--hoop", default="", help="cx,cy,r override (same for all videos)")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    parser.add_argument("--video", default="", help="restrict to one video stem")
    parser.add_argument("--no-auto-hoop", action="store_true", help="skip per-video hoop auto-detection; use --hoop/default")
    args = parser.parse_args()

    truth_dir = Path(args.truth_dir)
    video_dir = Path(args.video_dir)
    out_dir = Path(args.out)
    sample_config = Path(args.sample_config)
    if not truth_dir.is_dir():
        raise SystemExit(f"truth dir not found: {truth_dir}")
    if not video_dir.is_dir():
        raise SystemExit(f"video dir not found: {video_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "configs" / "off").mkdir(parents=True, exist_ok=True)
    (out_dir / "configs" / "on").mkdir(parents=True, exist_ok=True)

    default_hoop = tuple(int(x) for x in args.hoop.split(",")) if args.hoop else load_default_hoop(sample_config)
    ball_model = assign_ball_model(sample_config)
    hoop_model = find_hoop_model(sample_config) if not args.no_auto_hoop else None
    print(f"default hoop= {default_hoop}")
    print(f"ball model  = {ball_model or '(none!) on 模式将退化为纯 MOG2'}")
    print(f"hoop model  = {hoop_model or '(none) 使用默认/--hoop 统一框'}")

    tol = max(0.05, args.tolerance)
    truth_files = sorted(truth_dir.glob("*.truth.json"))
    if args.video:
        truth_files = [p for p in truth_files if args.video in p.name]
    if not truth_files:
        raise SystemExit("no truth files")

    rows = []
    agg = {"off": {"tp": 0, "fp": 0, "fn": 0}, "on": {"tp": 0, "fp": 0, "fn": 0}}
    for tf in truth_files:
        stem = tf.name[: -len(".truth.json")]
        video_path = video_dir / f"{stem}.mp4"
        if not video_path.is_file():
            # 兼容 .MOV
            alt = video_dir / f"{stem}.MOV"
            if alt.is_file():
                video_path = alt
            else:
                print(f"!! video not found for {stem}, skip")
                continue

        data = json.loads(tf.read_text(encoding="utf-8"))
        gt_times = sorted(float(e["time_sec"]) for e in data.get("events", []) if float(e["time_sec"]) >= 0)

        # 按视频自动标定篮框（一次），后续 off/on 共用，保证对比公平。
        hoop = default_hoop
        if hoop_model is not None:
            detected, err = detect_hoop_for_video(
                args.python, args.detect_goals, video_path, hoop_model,
                out_dir / "hoop_probe" / stem,
            )
            if detected is not None:
                hoop = detected
                print(f"   hoop[{stem}] = {hoop} (auto)")
            else:
                print(f"   hoop[{stem}] auto failed ({err.strip()[:120]}), use {default_hoop}")

        row = {"video": stem, "gt_count": len(gt_times), "hoop": list(hoop), "off": None, "on": None}
        for mode, enabled in (("off", False), ("on", True)):
            cfg = make_config(hoop, enabled, ball_model)
            cfg_path = out_dir / "configs" / mode / f"{stem}.json"
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

            out_json = out_dir / "detect" / stem / mode / "out.json"
            out_json.parent.mkdir(parents=True, exist_ok=True)
            debug_root = out_dir / "debug" / stem / mode
            rc, so, se = run_detect(args.python, args.detect_goals, video_path, cfg_path, out_json, debug_root)
            if rc != 0:
                print(f"!! {stem} [{mode}] detect failed rc={rc}; stderr tail:")
                print(se.strip()[-1200:])
                continue

            det_times = load_events(out_json)
            tp, fn, fp, matches = match(gt_times, det_times, tol)
            p, r, f1 = prf(tp, fn, fp)
            mean_dev = float(sum(abs(g - d) for g, d in matches if d is not None)) / max(1, tp) if tp else 0.0
            row[mode] = {
                "path": str(out_json),
                "det_count": len(det_times),
                "TP": tp, "FP": fp, "FN": fn,
                "P": p, "R": r, "F1": f1,
                "mean_dev_sec": round(mean_dev, 3),
                "det_timestamps": [round(t, 3) for t in det_times],
                "matches": [[round(g, 3), None if d is None else round(d, 3)] for g, d in matches],
            }
        rows.append(row)

        # 打印单条
        cells = []
        for mode in ("off", "on"):
            d = row[mode]
            if d is None:
                cells.append(f"{'-':>7}{'-':>4}{'-':>4}{'-':>4}{'-':>8}{'-':>8}{'-':>7}")
            else:
                agg[mode]["tp"] += d["TP"]; agg[mode]["fp"] += d["FP"]; agg[mode]["fn"] += d["FN"]
                cells.append(f"{d['det_count']:>7}{d['TP']:>4}{d['FP']:>4}{d['FN']:>4}"
                             f"{fmt_pct(d['P']):>8}{fmt_pct(d['R']):>8}{fmt_pct(d['F1']):>7}")
        print(f"{row['video']:<36}{row['gt_count']:>4} | {cells[0]} | {cells[1]}")

    # ---- 汇总表 ----
    hdr = (f"{'video':<36}{'GT':>4} |"
           f"{'off_det':>7}{'TP':>4}{'FP':>4}{'FN':>4}{'P':>8}{'R':>8}{'F1':>7} |"
           f"{'on_det':>7}{'TP':>4}{'FP':>4}{'FN':>4}{'P':>8}{'R':>8}{'F1':>7}")
    print("\n===== 汇总 =====")
    print("=" * len(hdr))
    print(hdr)
    print("=" * len(hdr))
    for r in rows:
        cells = []
        for mode in ("off", "on"):
            d = r[mode]
            if d is None:
                cells.append(f"{'-':>7}{'-':>4}{'-':>4}{'-':>4}{'-':>8}{'-':>8}{'-':>7}")
            else:
                cells.append(f"{d['det_count']:>7}{d['TP']:>4}{d['FP']:>4}{d['FN']:>4}"
                             f"{fmt_pct(d['P']):>8}{fmt_pct(d['R']):>8}{fmt_pct(d['F1']):>7}")
        print(f"{r['video']:<36}{r['gt_count']:>4} | {cells[0]} | {cells[1]}")
    print("-" * len(hdr))
    agg_cells = []
    for mode in ("off", "on"):
        tp, fp, fn = agg[mode]["tp"], agg[mode]["fp"], agg[mode]["fn"]
        p, r, f1 = prf(tp, fn, fp)
        agg_cells.append(f"{tp+fp:>7}{tp:>4}{fp:>4}{fn:>4}{fmt_pct(p):>8}{fmt_pct(r):>8}{fmt_pct(f1):>7}")
    total_gt = sum(r["gt_count"] for r in rows)
    print(f"{'ALL':<36}{total_gt:>4} | {agg_cells[0]} | {agg_cells[1]}")
    print("=" * len(hdr))

    summary_path = out_dir / "event_comparison.json"
    payload = {
        "tolerance_sec": tol,
        "hoop": list(hoop),
        "ball_model": ball_model,
        "rows": rows,
        "summary": {
            "off": _agg(agg["off"]), "on": _agg(agg["on"]),
        },
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ndetailed json -> {summary_path}")


def _agg(a):
    p, r, f1 = prf(a["tp"], a["fn"], a["fp"])
    return {"det_count": a["tp"] + a["fp"], "TP": a["tp"], "FP": a["fp"], "FN": a["fn"],
            "P": round(p, 3), "R": round(r, 3), "F1": round(f1, 3)}


if __name__ == "__main__":
    main()