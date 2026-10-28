#!/usr/bin/env python3
"""对比两种检测模式（纯 MOG2 / YOLO+MOG2）的事件质量。

输入:
    --truth-dir   真值 JSON 目录（scripts/annotate_truth.py 生成）
    --detections  检测结果根目录，结构为:
                   <root>/<video_stem>/<mode>/out.json   （mode 为 off|on）
                   <root>/<video_stem>/<run*.json>       （或按 glob 指定）

说明:
    compare_events.py 不自己跑检测。先手动跑：
        python3 detect_goals.py --video v.mp4 --config cfg_off.json --output .../stem/off/out.json ...
        python3 detect_goals.py --video v.mp4 --config cfg_on.json  --output .../stem/on/out.json ...

    事件匹配规则:
        真值每个进球 timestamp GT；检测事件 D。
        若存在 |D.time_sec - GT| <= tolerance 且未被占用，则算 TP（GT 与 D 都标记）。
        未被匹配的真值 -> FN；未被匹配的检测 -> FP。
        按 GT 顺序贪心匹配（GT 与 D 都按时间排序）。
"""

import argparse
import glob
import json
import re
import sys
from pathlib import Path

DEFAULT_TOLERANCE = 1.0  # 秒


def load_truth(truth_path: Path):
    with open(truth_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    events = [float(e["time_sec"]) for e in data.get("events", []) if float(e["time_sec"]) >= 0]
    return sorted(set(events)), data


def load_detection(json_path: Path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    events = sorted(
        float(e["time_sec"]) for e in data.get("events", []) if float(e["time_sec"]) >= 0
    )
    meta = data.get("meta", {})
    return events, meta


def match(gt_times, det_times, tol):
    """贪心匹配，返回 (tp_count, fn_count, fp_count, matches)。

    matches: 按 GT 顺序的 [(gt, det)] 列表，det 可能为 None(FN)。
    """
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


def discover_detections(det_root: Path, video_stem: str):
    """为单个视频查找两种模式的检测结果。

    规则:
        <root>/<stem>/off/out.json
        <root>/<stem>/on/out.json
        或 <root>/<stem>_off.json / <root>/<stem>_on.json
        或 <root>/<stem>/<mode>_out.json（glob 兜底）
    """
    out = {}
    candidates = {
        "off": [
            det_root / video_stem / "off" / "out.json",
            det_root / f"{video_stem}_off.json",
        ],
        "on": [
            det_root / video_stem / "on" / "out.json",
            det_root / f"{video_stem}_on.json",
        ],
    }
    for mode, paths in candidates.items():
        for p in paths:
            if p.is_file():
                out[mode] = p
                break
    if not out:
        # 兜底 glob：<stem>*out*.json 尝试分类
        hits = sorted(glob.glob(str(det_root / f"{video_stem}*out*.json")))
        for h in hits:
            if "off" in Path(h).stem and "off" not in out:
                out["off"] = Path(h)
            if "on" in Path(h).stem and "on" not in out:
                out["on"] = Path(h)
    return out


def main():
    parser = argparse.ArgumentParser(description="Compare MOG2 vs YOLO+MOG2 event quality")
    parser.add_argument("--truth-dir", required=True, help="truth JSON directory from annotate_truth.py")
    parser.add_argument("--detections", required=True, help="root dir of detection outputs (see docstring)")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="matching tolerance in seconds")
    parser.add_argument("--video", default="", help="restrict to one video stem (optional)")
    args = parser.parse_args()

    truth_dir = Path(args.truth_dir)
    det_root = Path(args.detections)
    if not truth_dir.is_dir():
        raise SystemExit(f"truth dir not found: {truth_dir}")
    if not det_root.is_dir():
        raise SystemExit(f"detections root not found: {det_root}")

    truth_files = sorted(truth_dir.glob("*.truth.json"))
    if args.video:
        truth_files = [p for p in truth_files if args.video in p.stem]

    if not truth_files:
        raise SystemExit("no truth json files found")

    tol = max(0.05, args.tolerance)
    rows = []
    for tp_ in truth_files:
        stem = tp_.name[: -len(".truth.json")]
        gt_times, truth_meta = load_truth(tp_)
        dets = discover_detections(det_root, stem)

        row = {
            "video": stem,
            "gt_count": len(gt_times),
            "off": None,
            "on": None,
        }
        for mode in ("off", "on"):
            jp = dets.get(mode)
            if jp is None:
                continue
            det_times, meta = load_detection(jp)
            tp_n, fn_n, fp_n, matches = match(gt_times, det_times, tol)
            p, r, f1 = prf(tp_n, fn_n, fp_n)
            mean_dev = float(sum(abs(g - d) for g, d in matches if d is not None)) / max(1, tp_n) if tp_n else 0.0
            row[mode] = {
                "path": str(jp),
                "det_count": len(det_times),
                "TP": tp_n, "FP": fp_n, "FN": fn_n,
                "P": p, "R": r, "F1": f1,
                "mean_dev_sec": mean_dev,
                "gf_timestamps": [round(t, 3) for t in gt_times],
                "det_timestamps": [round(t, 3) for t in det_times],
                "matches": [[round(g, 3), None if d is None else round(d, 3)] for g, d in matches],
            }
        rows.append(row)

    # ---- 表格 ----
    hdr = (f"{'video':<36}{'GT':>4} |"
           f"{'off_det':>7}{'TP':>4}{'FP':>4}{'FN':>4}{'P':>8}{'R':>8}{'F1':>7} |"
           f"{'on_det':>7}{'TP':>4}{'FP':>4}{'FN':>4}{'P':>8}{'R':>8}{'F1':>7}")
    print("=" * len(hdr))
    print(hdr)
    print("=" * len(hdr))
    agg = {"off": {"tp": 0, "fp": 0, "fn": 0}, "on": {"tp": 0, "fp": 0, "fn": 0}}
    total_gt = 0
    for r in rows:
        total_gt += r["gt_count"]
        cells = []
        for mode in ("off", "on"):
            d = r[mode]
            if d is None:
                cells.append(f"{'-':>7}{'-':>4}{'-':>4}{'-':>4}{'-':>8}{'-':>8}{'-':>7}")
            else:
                agg[mode]["tp"] += d["TP"]; agg[mode]["fp"] += d["FP"]; agg[mode]["fn"] += d["FN"]
                cells.append(f"{d['det_count']:>7}{d['TP']:>4}{d['FP']:>4}{d['FN']:>4}"
                             f"{fmt_pct(d['P']):>8}{fmt_pct(d['R']):>8}{fmt_pct(d['F1']):>7}")
        print(f"{r['video']:<36}{r['gt_count']:>4} | {cells[0]} | {cells[1]}")
    print("-" * len(hdr))
    agg_row = []
    for mode in ("off", "on"):
        tp_, fp_, fn_ = agg[mode]["tp"], agg[mode]["fp"], agg[mode]["fn"]
        p, r, f1 = prf(tp_, fn_, fp_)
        agg_row.append(f"{tp_+fp_:>7}{tp_:>4}{fp_:>4}{fn_:>4}{fmt_pct(p):>8}{fmt_pct(r):>8}{fmt_pct(f1):>7}")
    print(f"{'ALL':<36}{total_gt:>4} | {agg_row[0]} | {agg_row[1]}")
    print("=" * len(hdr))

    # ---- 明细 dump ----
    out_path = det_root / "event_comparison.json"
    dump = {"tolerance_sec": tol, "rows": rows}
    out_path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ndetailed json -> {out_path}")


if __name__ == "__main__":
    main()