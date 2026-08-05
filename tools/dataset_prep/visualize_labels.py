#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""诊断用：抽样训练图像并把标签框画上去，肉眼核对框是否罩在正确物体上。

用法：python tools/dataset_prep/visualize_labels.py
输出：项目根 _tmp_vis/*.png（每张图为原图 + 红色标签框）
"""
from __future__ import annotations

import glob
import os
import random

from PIL import Image, ImageDraw

BASE = r"E:\xuexixiangguan\pythonProject\gongcheng\失物招领系统\dataset\final"
OUT = r"E:\xuexixiangguan\pythonProject\gongcheng\失物招领系统\_tmp_vis"
CLASS_NAMES = [
    "phone", "wallet", "keys", "backpack", "suitcase", "laptop",
    "campus_card", "glasses", "notebook", "umbrella", "bottle", "other",
]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    labels = glob.glob(os.path.join(BASE, "labels", "train", "*.txt"))
    random.seed(7)
    random.shuffle(labels)

    # wanted[class_id] = 需要抽几张；覆盖高低 mAP 类，便于对比
    wanted = {0: 2, 8: 2, 10: 2, 1: 2, 7: 2, 3: 1}
    picked: list[str] = []
    for lf in labels:
        if not any(v > 0 for v in wanted.values()):
            break
        lines = [l for l in open(lf, encoding="utf-8", errors="ignore").read().splitlines() if l.strip()]
        cls = set(int(l.split()[0]) for l in lines if len(l.split()) == 5)
        hit = [c for c in cls if wanted.get(c, 0) > 0]
        if hit:
            picked.append(lf)
            for c in hit:
                wanted[c] -= 1

    random.shuffle(picked)
    saved = 0
    for lf in picked:
        stem = os.path.splitext(os.path.basename(lf))[0]
        impath = None
        for ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            p = os.path.join(BASE, "images", "train", stem + ext)
            if os.path.exists(p):
                impath = p
                break
        if not impath:
            continue
        img = Image.open(impath).convert("RGB")
        w, h = img.size
        scale = min(1.0, 800 / max(w, h))
        if scale < 1:
            img = img.resize((int(w * scale), int(h * scale)))
        w, h = img.size
        draw = ImageDraw.Draw(img)
        names = []
        for line in open(lf, encoding="utf-8", errors="ignore"):
            p = line.split()
            if len(p) != 5:
                continue
            ci = int(p[0])
            x, y, bw, bh = map(float, p[1:5])
            x1, y1 = (x - bw / 2) * w, (y - bh / 2) * h
            x2, y2 = (x + bw / 2) * w, (y + bh / 2) * h
            draw.rectangle([x1, y1, x2, y2], outline="red", width=max(2, int(0.006 * w)))
            names.append(CLASS_NAMES[ci] if 0 <= ci < len(CLASS_NAMES) else str(ci))
        tag = "_".join(names[:4])
        img.save(os.path.join(OUT, f"{stem}__{tag}.png"))
        saved += 1
    print(f"saved {saved} images to {OUT}")


if __name__ == "__main__":
    main()
