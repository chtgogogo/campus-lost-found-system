#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""convert_leftincar.py — 转换 leftincar-data（YOLO 格式，10 类）到统一 11 类。

数据源：E:/mod/数据集/leftincar-data/images/*.bmp  (971 张)
        E:/mod/数据集/leftincar-data/labels/*.txt  (934 个，部分图无标注)
输出： E:/mod/processed/leftincar/images/{train,val}/*.jpg  (bmp->jpg 转码省空间)
        E:/mod/processed/leftincar/labels/{train,val}/*.txt  (class_id 改写)

说明：
  - 仅处理“有标注文件”的图，保证 image/label 成对。
  - 按映射改写 class_id：clothing(6) 丢弃，handbag(9)->3(backpack)。
  - bmp 转 jpg（quality=95）以大幅节省磁盘。
  - 因源只有 train 无 val，按 8:2 可复现随机切分（--seed）。

用法：
    python convert_leftincar.py                # 全量，8:2 切分
    python convert_leftincar.py --limit 20     # smoke test：仅前 20 张（含保留类）
    python convert_leftincar.py --train-ratio 0.8 --seed 42
"""

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image

from common import load_label_map, get_target_classes, write_yolo_label

SRC = "E:/mod/数据集/leftincar-data"
OUT_ROOT = "E:/mod/processed"


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert leftincar-data to unified 12-class YOLO.")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out-root", default=OUT_ROOT)
    ap.add_argument("--limit", type=int, default=0,
                    help="最多处理多少张（按保留类标注计数，0=全量）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--train-ratio", type=float, default=0.8)
    args = ap.parse_args()

    lm = load_label_map()
    target = get_target_classes(lm)
    index_to_target = lm["sources"]["leftincar"]["index_to_target"]

    img_src = os.path.join(args.src, "images")
    lbl_src = os.path.join(args.src, "labels")

    label_files = sorted(f for f in os.listdir(lbl_src) if f.endswith(".txt"))

    pairs = []  # (src_bmp, stem, kept_lines)
    class_counter = {i: 0 for i in range(len(target))}
    written = 0

    for fname in label_files:
        if args.limit and written >= args.limit:
            break
        stem, _ = os.path.splitext(fname)
        bmp = os.path.join(img_src, stem + ".bmp")
        if not os.path.exists(bmp):
            print(f"[warn] 标注 {fname} 缺少对应图片", file=sys.stderr)
            continue

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
                    continue  # clothing 等丢弃类
                # 防御性归一化
                x = min(max(x, 0.0), 1.0)
                y = min(max(y, 0.0), 1.0)
                w = min(max(w, 0.0), 1.0)
                h = min(max(h, 0.0), 1.0)
                kept.append((int(tgt), round(x, 6), round(y, 6),
                             round(w, 6), round(h, 6)))
                class_counter[int(tgt)] += 1

        if not kept:
            continue  # 例如仅含 clothing 的图 -> 变成空标注，跳过
        pairs.append((bmp, stem, kept))
        written += 1

    # 可复现 8:2 切分
    random.seed(args.seed)
    random.shuffle(pairs)
    n = len(pairs)
    n_train = int(round(n * args.train_ratio))
    train_pairs = pairs[:n_train]
    val_pairs = pairs[n_train:]

    for split, sp in (("train", train_pairs), ("val", val_pairs)):
        out_img = os.path.join(args.out_root, "leftincar", "images", split)
        out_lbl = os.path.join(args.out_root, "leftincar", "labels", split)
        os.makedirs(out_img, exist_ok=True)
        os.makedirs(out_lbl, exist_ok=True)
        for bmp, stem, kept in sp:
            dst_jpg = os.path.join(out_img, stem + ".jpg")
            with Image.open(bmp) as im:
                im.convert("RGB").save(dst_jpg, "JPEG", quality=95)
            write_yolo_label(kept, os.path.join(out_lbl, stem + ".txt"))

    print(f"\n[convert_leftincar] 保留 {n} 张图（已丢弃 clothing-only / 无标注图）。")
    print(f"[convert_leftincar] 切分: train={len(train_pairs)} val={len(val_pairs)}")
    print("[convert_leftincar] 各目标类标注数量（leftincar 源）:")
    for i, name in enumerate(target):
        print(f"  {i:2d} {name:12s} {class_counter[i]}")


if __name__ == "__main__":
    main()
