#!/usr/bin/env python3
"""把 Roboflow 导出的 COCO 标注(basketball-coco-player-detection)转成 YOLO 单类 ball。

用法:
  python3 scripts/convert_ball_coco_to_yolo.py \
    --src /tmp/bball_ds/dl/koppolusameer/basketball-coco-player-detection \
    --dst /Users/.../training/ball_detector/datasets/ball_v1

从每类标注中只取 category_id==1 的 ball。YOLO 格式: <cls> <cx> <cy> <w> <h>(归一化 0~1)。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="数据集根目录(含 train/test/valid 子目录与 _annotations.coco.json)")
    ap.add_argument("--dst", required=True, help="YOLO 输出根目录(images/labels 下放 train/valid/test)")
    args = ap.parse_args()

    ball_cat_id = 1  # 该数据集中 BALL 的 category id
    splits = ["train", "valid", "test"]
    kept_total = 0
    for split in splits:
        ann_path = os.path.join(args.src, split, "_annotations.coco.json")
        img_dir = os.path.join(args.src, split)
        if not os.path.exists(ann_path):
            print(f"skip {split}: no annotations")
            continue
        with open(ann_path, "r", encoding="utf-8") as f:
            coco = json.load(f)

        img_by_id = {im["id"]: im for im in coco["images"]}
        # 只保留 ball 标注
        ball_anns = [a for a in coco["annotations"] if a["category_id"] == ball_cat_id]
        img_with_ball = sorted({img_by_id[a["image_id"]]["file_name"] for a in ball_anns})
        print(f"{split}: coco_imgs={len(coco['images'])} ball_anns={len(ball_anns)} imgs_with_ball={len(img_with_ball)}")

        out_img = os.path.join(args.dst, "images", split)
        out_lbl = os.path.join(args.dst, "labels", split)
        os.makedirs(out_img, exist_ok=True)
        os.makedirs(out_lbl, exist_ok=True)

        # 每张含球图的标注 -> YOLO txt
        per_img: dict[str, list] = {}
        for a in ball_anns:
            fn = img_by_id[a["image_id"]]["file_name"]
            W = img_by_id[a["image_id"]]["width"]
            H = img_by_id[a["image_id"]]["height"]
            x, y, w, h = a["bbox"]
            cx = (x + w / 2.0) / W
            cy = (y + h / 2.0) / H
            bw = w / W
            bh = h / H
            cx = min(1.0, max(0.0, cx))
            cy = min(1.0, max(0.0, cy))
            bw = min(1.0, max(0.0, bw))
            bh = min(1.0, max(0.0, bh))
            per_img.setdefault(fn, []).append((cx, cy, bw, bh))

        for fn, boxes in per_img.items():
            lbl_name = os.path.splitext(fn)[0] + ".txt"
            with open(os.path.join(out_lbl, lbl_name), "w", encoding="utf-8") as f:
                for cx, cy, bw, bh in boxes:
                    f.write(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
            src_img = os.path.join(img_dir, fn)
            if os.path.exists(src_img):
                shutil.copy2(src_img, os.path.join(out_img, fn))
            else:
                print(f"  WARN missing image: {fn}")

        kept_total += len(per_img)

    print(f"\n完成:已保留 {kept_total} 张含球图片并转 YOLO 标注 -> {args.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
