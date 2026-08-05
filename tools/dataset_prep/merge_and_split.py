#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""merge_and_split.py — 合并三源到统一 11 类，并按分层抽样划分 train/val/test。

读取（上游 convert_* 的输出）：
    E:/mod/processed/coco_train|val/{images,labels}
    E:/mod/processed/leftincar/images|labels/{train,val}
    E:/mod/processed/homeobjects_laptop/images|labels/{train,val}

输出：
    E:/mod/processed/final/images/{train,val,test}/*.jpg
    E:/mod/processed/final/labels/{train,val,test}/*.txt
    E:/mod/processed/final/data.yaml   (11 类 names + path + train/val/test)

划分策略：对每个目标类（以“主类”= 图中最小 class_id 归属）独立做 7:2:1
可复现随机切分，保证各类在三个集合中的比例一致（分层抽样）。
多标签图按主类归并，因此每张图只会落在一个集合，避免泄漏。
文件名加源前缀（coco_/leftincar_/home_）防止跨源重名。

用法：
    python merge_and_split.py                 # 合并全量（需先跑完三个 convert）
    python merge_and_split.py --limit 60      # smoke test：仅合并前 60 个样本对
"""

import argparse
import os
import random
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml

from common import load_label_map, get_target_classes


def iter_sources(processed: str) -> list[tuple[str, str, str]]:
    """返回 [(tag, images_dir, labels_dir), ...]，覆盖三源的全部子集。"""
    return [
        ("coco", f"{processed}/coco_train/images", f"{processed}/coco_train/labels"),
        ("coco", f"{processed}/coco_val/images", f"{processed}/coco_val/labels"),
        ("leftincar", f"{processed}/leftincar/images/train", f"{processed}/leftincar/labels/train"),
        ("leftincar", f"{processed}/leftincar/images/val", f"{processed}/leftincar/labels/val"),
        ("home", f"{processed}/homeobjects_laptop/images/train", f"{processed}/homeobjects_laptop/labels/train"),
        ("home", f"{processed}/homeobjects_laptop/images/val", f"{processed}/homeobjects_laptop/labels/val"),
    ]


def collect_pairs(sources: list) -> list[tuple]:
    """收集 (tag, img_path, lbl_path, stem)，要求 image/label 成对。"""
    items = []
    for tag, img_dir, lbl_dir in sources:
        if not os.path.isdir(img_dir):
            print(f"[warn] 缺失源目录 {img_dir}", file=sys.stderr)
            continue
        for fn in sorted(os.listdir(img_dir)):
            if not fn.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                continue
            stem, _ = os.path.splitext(fn)
            lp = os.path.join(lbl_dir, stem + ".txt")
            if not os.path.exists(lp):
                continue
            items.append((tag, os.path.join(img_dir, fn), lp, stem))
    return items


def label_classes(lbl_path: str) -> set:
    cls = set()
    with open(lbl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                cls.add(int(line.split()[0]))
            except (ValueError, IndexError):
                pass
    return cls


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge 3 sources and stratified split.")
    ap.add_argument("--processed", default="E:/mod/processed")
    ap.add_argument("--out", default="E:/mod/processed/final")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ratios", type=float, nargs=3, default=[0.7, 0.2, 0.1],
                    help="train val test 比例，默认 0.7 0.2 0.1")
    ap.add_argument("--limit", type=int, default=0,
                    help="最多合并多少对（0=全量），用于 smoke test")
    args = ap.parse_args()

    sources = iter_sources(args.processed)
    lm = load_label_map()
    target = get_target_classes(lm)
    nc = len(target)

    items = collect_pairs(sources)
    if args.limit:
        items = items[: args.limit]
    print(f"[merge] 共收集 {len(items)} 对（image+label）标注样本。")

    # 按主类（图中最小 class_id）分组，便于分层抽样
    by_class = {i: [] for i in range(nc)}
    for tag, ip, lp, stem in items:
        cls = label_classes(lp)
        if not cls:
            continue
        primary = min(cls)
        by_class[primary].append((tag, ip, lp, stem, cls))

    r_train, r_val, r_test = args.ratios
    random.seed(args.seed)
    splits = {"train": [], "val": [], "test": []}
    for c in range(nc):
        grp = by_class[c]
        random.shuffle(grp)
        n = len(grp)
        nt = int(round(n * r_train))
        nv = int(round(n * r_val))
        splits["train"].extend(grp[:nt])
        splits["val"].extend(grp[nt:nt + nv])
        splits["test"].extend(grp[nt + nv:])

    # 复制文件（加源前缀防重名）
    for split in ("train", "val", "test"):
        od_img = os.path.join(args.out, "images", split)
        od_lbl = os.path.join(args.out, "labels", split)
        os.makedirs(od_img, exist_ok=True)
        os.makedirs(od_lbl, exist_ok=True)
        for tag, ip, lp, stem, cls in splits[split]:
            new_stem = f"{tag}_{stem}"
            shutil.copyfile(ip, os.path.join(od_img, new_stem + os.path.splitext(ip)[1]))
            shutil.copyfile(lp, os.path.join(od_lbl, new_stem + ".txt"))

    # 统计各类在各集合中的图像数（一张图可含多类）
    dist = {s: {i: 0 for i in range(nc)} for s in splits}
    for split in splits:
        for tag, ip, lp, stem, cls in splits[split]:
            for c in cls:
                dist[split][c] += 1

    print("\n[merge] 各类图像数分布（一张图可计入多个类）:")
    print(f"{'class':12s} {'idx':>3s} {'train':>6s} {'val':>6s} {'test':>6s}")
    for i, name in enumerate(target):
        print(f"{name:12s} {i:3d} {dist['train'][i]:6d} {dist['val'][i]:6d} {dist['test'][i]:6d}")

    # 写 data.yaml（list 形式 names，索引即 class_id）
    data = {
        "path": os.path.abspath(args.out),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "nc": nc,
        "names": target,
    }
    yaml_path = os.path.join(args.out, "data.yaml")
    os.makedirs(args.out, exist_ok=True)
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    print(f"\n[merge] 写出 {yaml_path}")
    print(f"[merge] train={len(splits['train'])} val={len(splits['val'])} "
          f"test={len(splits['test'])} 总={len(items)}")


if __name__ == "__main__":
    main()
