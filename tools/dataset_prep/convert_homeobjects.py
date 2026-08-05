#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""convert_homeobjects.py — 从 homeobjects-3K 仅抽取 laptop 类到统一 11 类。

数据源：E:/mod/数据集/homeobjects-3K/images/{train,val}/*.jpg
        E:/mod/数据集/homeobjects-3K/labels/{train,val}/*.txt
输出： E:/mod/processed/homeobjects_laptop/images/{train,val}/*.jpg
        E:/mod/processed/homeobjects_laptop/labels/{train,val}/*.txt

说明：
  - homeobjects 原 12 类家居里只保留 laptop（源 index 6 -> 目标 5），
    其余 11 类全部丢弃。
  - 保留原始 train/val 划分（merge_and_split 会再统一分层抽样）。

用法：
    python convert_homeobjects.py              # 全量抽取 laptop
    python convert_homeobjects.py --limit 20   # smoke test：仅前 20 张含 laptop 的图
"""

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import load_label_map, get_target_classes, write_yolo_label

SRC = "E:/mod/数据集/homeobjects-3K"
OUT_ROOT = "E:/mod/processed"


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract laptop class from HomeObjects-3K.")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out-root", default=OUT_ROOT)
    ap.add_argument("--limit", type=int, default=0,
                    help="最多写出多少张（按含 laptop 的图计数，0=全量）")
    ap.add_argument("--splits", nargs="+", default=["train", "val"])
    args = ap.parse_args()

    lm = load_label_map()
    target = get_target_classes(lm)
    index_to_target = lm["sources"]["homeobjects"]["index_to_target"]

    class_counter = {i: 0 for i in range(len(target))}
    written = 0

    for split in args.splits:
        img_src = os.path.join(args.src, "images", split)
        lbl_src = os.path.join(args.src, "labels", split)
        out_img = os.path.join(args.out_root, "homeobjects_laptop", "images", split)
        out_lbl = os.path.join(args.out_root, "homeobjects_laptop", "labels", split)
        os.makedirs(out_img, exist_ok=True)
        os.makedirs(out_lbl, exist_ok=True)

        if not os.path.isdir(lbl_src):
            print(f"[warn] 缺失标签目录 {lbl_src}", file=sys.stderr)
            continue

        label_files = sorted(f for f in os.listdir(lbl_src) if f.endswith(".txt"))
        for fname in label_files:
            if args.limit and written >= args.limit:
                break
            stem, _ = os.path.splitext(fname)
            kept = []
            with open(os.path.join(lbl_src, fname), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    try:
                        cls = int(parts[0])
                        x, y, w, h = map(float, parts[1:5])
                    except (ValueError, IndexError):
                        continue
                    tgt = index_to_target.get(cls)
                    if tgt is None:
                        continue  # 非 laptop 类，丢弃
                    x = min(max(x, 0.0), 1.0)
                    y = min(max(y, 0.0), 1.0)
                    w = min(max(w, 0.0), 1.0)
                    h = min(max(h, 0.0), 1.0)
                    kept.append((int(tgt), round(x, 6), round(y, 6),
                                 round(w, 6), round(h, 6)))
                    class_counter[int(tgt)] += 1

            if not kept:
                continue
            src = os.path.join(img_src, stem + ".jpg")
            if not os.path.exists(src):
                print(f"[warn] 缺失图片 {src}", file=sys.stderr)
                continue
            shutil.copyfile(src, os.path.join(out_img, stem + ".jpg"))
            write_yolo_label(kept, os.path.join(out_lbl, stem + ".txt"))
            written += 1

        if args.limit and written >= args.limit:
            break

    print(f"\n[convert_homeobjects] 共写出 {written} 张 laptop 图。")
    print("[convert_homeobjects] 各目标类标注数量（homeobjects 源）:")
    for i, name in enumerate(target):
        print(f"  {i:2d} {name:12s} {class_counter[i]}")


if __name__ == "__main__":
    main()
