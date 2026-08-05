#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""extract_metrics.py — 从训练结果提取指标，生成论文 Table 4-x 格式的表格。

读取：
    results.csv           默认 runs/detect/lostfound_v1/results.csv
                          （Ultralytics 训练的聚合指标：mAP@0.5 / mAP@0.5:0.95 / P / R）
    per_class_ap.csv      （可选）同级目录，逐类指标。
                          列：class_index, class_name, ap50, ap50_95, precision, recall
                          若缺失，则逐类 mAP 单元格标记为“仅聚合指标”。

输出：
    <out>/table_4x_metrics.md   论文表格（markdown）
    <out>/table_4x_metrics.csv  同表（csv）

玩偶(doll) 已移除训练类目：识别时低置信归为“其他”类，不进入本表。

生成 per_class_ap.csv 的方法（训练完成后，需要 GPU / 权重）：
    from ultralytics import YOLO
    m = YOLO('runs/detect/lostfound_v1/weights/best.pt')
    r = m.val(split='test')          # 或 split='val'
    # r.box.ap 为逐类 AP@0.5:0.95；r.box.p / r.box.r 为逐类 P/R
    # 自行写盘为 per_class_ap.csv 即可被本脚本读取。

用法：
    python extract_metrics.py
    python extract_metrics.py --results runs/detect/lostfound_v1/results.csv --out .
    python extract_metrics.py --per-class my_per_class_ap.csv
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import load_label_map, get_target_classes


def find_col(header, *candidates):
    """返回第一个包含候选子串的列下标，找不到返回 -1。"""
    for cand in candidates:
        for i, h in enumerate(header):
            if cand in h:
                return i
    return -1


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract metrics into paper Table 4-x.")
    ap.add_argument("--results", default="runs/detect/lostfound_v1/results.csv")
    ap.add_argument("--per-class", default=None,
                    help="逐类指标 csv；缺省尝试与 results 同目录的 per_class_ap.csv")
    ap.add_argument("--out", default=None, help="输出目录；缺省为 results 同级目录")
    args = ap.parse_args()

    if not os.path.exists(args.results):
        raise FileNotFoundError(f"找不到 results.csv: {args.results}")

    lm = load_label_map()
    target = get_target_classes(lm)
    nc = len(target)

    # ---- 聚合指标（取 mAP@0.5 最大的 epoch）----
    best = {"epoch": 0, "mAP50": 0.0, "mAP50-95": 0.0, "precision": 0.0, "recall": 0.0}
    with open(args.results, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        ci_epoch = find_col(header, "epoch")
        ci_p = find_col(header, "precision(B)")
        ci_r = find_col(header, "recall(B)")
        ci_m50 = find_col(header, "mAP50(B)")
        ci_m5095 = find_col(header, "mAP50-95")

        def num(v):
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0

        for row in reader:
            if not row:
                continue
            m50 = num(row[ci_m50]) if ci_m50 >= 0 else 0.0
            if m50 > best["mAP50"]:
                best["mAP50"] = m50
                best["mAP50-95"] = num(row[ci_m5095]) if ci_m5095 >= 0 else 0.0
                best["precision"] = num(row[ci_p]) if ci_p >= 0 else 0.0
                best["recall"] = num(row[ci_r]) if ci_r >= 0 else 0.0
                best["epoch"] = int(num(row[ci_epoch])) if ci_epoch >= 0 else 0

    # ---- 逐类指标（可选）----
    per = {}
    pc_path = args.per_class
    if pc_path is None:
        pc_path = os.path.join(os.path.dirname(os.path.abspath(args.results)),
                               "per_class_ap.csv")
    if os.path.exists(pc_path):
        with open(pc_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                idx = int(row["class_index"])
                per[idx] = {
                    "ap50": float(row["ap50"]),
                    "ap50_95": float(row["ap50_95"]),
                    "precision": float(row["precision"]),
                    "recall": float(row["recall"]),
                }

    # ---- 组装表格 ----
    md = []
    md.append("# 表 4-x  失物招领检测器在测试集上的性能 (Lost-Found Detector, Test Set)")
    md.append("")
    md.append(
        f"**总体指标（best epoch={best['epoch']}）**: "
        f"mAP@0.5 = {best['mAP50']:.3f}, "
        f"mAP@0.5:0.95 = {best['mAP50-95']:.3f}, "
        f"Precision = {best['precision']:.3f}, "
        f"Recall = {best['recall']:.3f}"
    )
    md.append("")
    md.append("| 类别 Class | 索引 idx | mAP@0.5 | mAP@0.5:0.95 | Precision | Recall | 备注 |")
    md.append("|---|---|---|---|---|---|---|")

    csv_rows = [["class", "index", "map50", "map50_95", "precision", "recall", "note"]]
    for i, name in enumerate(target):
        if i in per:
            p = per[i]
            md.append(f"| {name} | {i} | {p['ap50']:.3f} | {p['ap50_95']:.3f} | "
                      f"{p['precision']:.3f} | {p['recall']:.3f} | |")
            csv_rows.append([name, i, f"{p['ap50']:.3f}", f"{p['ap50_95']:.3f}",
                             f"{p['precision']:.3f}", f"{p['recall']:.3f}", ""])
        else:
            md.append(f"| {name} | {i} | — | — | — | — | 仅聚合指标 (逐类未提供) |")
            csv_rows.append([name, i, "", "", "", "", "仅聚合指标 (逐类未提供)"])

    md.append("")
    md_text = "\n".join(md)

    out_dir = args.out or os.path.dirname(os.path.abspath(args.results))
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "table_4x_metrics.md")
    csv_path = os.path.join(out_dir, "table_4x_metrics.csv")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(csv_rows)

    print(md_text)
    print(f"\n[extract_metrics] 写出 {md_path}")
    print(f"[extract_metrics] 写出 {csv_path}")


if __name__ == "__main__":
    main()
