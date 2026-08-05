#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""convert_coco.py — 将 COCO 2017 instances JSON 转换为统一 11 类 YOLO 格式。

数据源：E:/mod/数据集/{train,val}2017/{train,val}2017/  (图片，注意可能嵌套一层)
        E:/mod/数据集/annotations_trainval2017/annotations/instances_{split}2017.json
输出： E:/mod/processed/coco_{train,val}/{images,labels}/

用法：
    python convert_coco.py                 # 处理全量 train + val
    python convert_coco.py --limit 20      # smoke test：仅写出前 20 张（含目标类标注的）图片
    python convert_coco.py --splits train  # 只处理 train

映射规则来自 label_map.yaml（coco.name_to_target），仅保留 8 个目标类，
其余 72 个 COCO 类全部丢弃。
"""

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import load_label_map, get_target_classes, write_yolo_label

# 默认路径（全部位于 E 盘）
DATASET_ROOT = "E:/mod/数据集"
ANNOT_ROOT = "E:/mod/数据集/annotations_trainval2017/annotations"
OUT_ROOT = "E:/mod/processed"


def coco_image_dir(dataset_root: str, split: str) -> str:
    """定位 COCO 图片目录，兼容平铺与嵌套一层 train2017/ 两种情况。"""
    base = os.path.join(dataset_root, f"{split}2017")
    nested = os.path.join(base, f"{split}2017")
    return nested if os.path.isdir(nested) else base


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert COCO 2017 to unified 12-class YOLO.")
    ap.add_argument("--dataset-root", default=DATASET_ROOT)
    ap.add_argument("--annot-root", default=ANNOT_ROOT)
    ap.add_argument("--out-root", default=OUT_ROOT)
    ap.add_argument("--limit", type=int, default=0,
                    help="最多写出多少张图（按含目标类标注的图计数，0=全量）")
    ap.add_argument("--splits", nargs="+", default=["train", "val"])
    args = ap.parse_args()

    lm = load_label_map()
    target = get_target_classes(lm)
    name_to_target = lm["sources"]["coco"]["name_to_target"]

    written = 0
    class_counter = {i: 0 for i in range(len(target))}

    for split in args.splits:
        json_path = os.path.join(args.annot_root, f"instances_{split}2017.json")
        if not os.path.exists(json_path):
            print(f"[warn] 缺失标注文件 {json_path}", file=sys.stderr)
            continue

        img_dir = coco_image_dir(args.dataset_root, split)
        out_img_dir = os.path.join(args.out_root, f"coco_{split}", "images")
        out_lbl_dir = os.path.join(args.out_root, f"coco_{split}", "labels")
        os.makedirs(out_img_dir, exist_ok=True)
        os.makedirs(out_lbl_dir, exist_ok=True)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cat_name = {c["id"]: c["name"] for c in data["categories"]}
        anns_by_img: dict[int, list] = {}
        for a in data["annotations"]:
            anns_by_img.setdefault(a["image_id"], []).append(a)

        print(f"[convert_coco] {split}: {len(data['images'])} 张图, "
              f"标注文件 {os.path.basename(json_path)}")

        for im in data["images"]:
            if args.limit and written >= args.limit:
                break

            iid = im["id"]
            fname = im["file_name"]
            stem, _ = os.path.splitext(fname)
            iw, ih = im["width"], im["height"]
            if not iw or not ih:
                continue

            kept = []
            for a in anns_by_img.get(iid, []):
                nm = cat_name.get(a["category_id"])
                tgt = name_to_target.get(nm)
                if tgt is None:
                    continue  # 非目标类，丢弃
                x, y, w, h = a["bbox"]
                if w <= 0 or h <= 0:
                    continue
                cx = min(max((x + w / 2.0) / iw, 0.0), 1.0)
                cy = min(max((y + h / 2.0) / ih, 0.0), 1.0)
                nw = min(max(w / iw, 0.0), 1.0)
                nh = min(max(h / ih, 0.0), 1.0)
                kept.append((int(tgt), round(cx, 6), round(cy, 6),
                             round(nw, 6), round(nh, 6)))
                class_counter[int(tgt)] += 1

            if not kept:
                continue  # 该图不含任何目标类，跳过（不复制）

            src = os.path.join(img_dir, fname)
            dst = os.path.join(out_img_dir, stem + ".jpg")
            if not os.path.exists(src):
                print(f"[warn] 缺失图片 {src}", file=sys.stderr)
                continue
            shutil.copyfile(src, dst)
            write_yolo_label(kept, os.path.join(out_lbl_dir, stem + ".txt"))
            written += 1

        if args.limit and written >= args.limit:
            break

    print(f"\n[convert_coco] 共写出 {written} 张图。")
    print("[convert_coco] 各目标类标注数量（COCO 源）:")
    for i, name in enumerate(target):
        print(f"  {i:2d} {name:12s} {class_counter[i]}")


if __name__ == "__main__":
    main()
