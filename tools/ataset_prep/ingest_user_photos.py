# -*- coding: utf-8 -*-
"""稀有类真实照片接入脚手架（C 方案）。

你把下载的真实失物照片按类放到 dataset/user_rare/<类名>/ 下，本脚本把它们并入训练集。

约定：
  dataset/user_rare/campus_card/*.jpg   # 校园卡照片
  dataset/user_rare/wallet/*.jpg        # 钱包照片
  dataset/user_rare/keys/*.jpg          # 钥匙照片
  dataset/user_rare/glasses/*.jpg       # 眼镜照片
  （其他要补的类，用 12 类英文名建文件夹即可）

两种并入方式：
  auto  ：用当前 models/weights/best.pt 自动标注。置信度 >= --conf 且类别与文件夹一致 -> 直接并入
          train；否则移到 dataset/user_rare/needs_review/<类>/ 待你用 labelImg 手标。
  stage ：仅把照片复制到 dataset/final/images/train，并列出到 needs_review 待人工标注（不自动写标签）。

用法：
  python tools/dataset_prep/ingest_user_photos.py --mode auto --conf 0.5
  python tools/dataset_prep/ingest_user_photos.py --mode stage
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA = PROJECT_ROOT / "dataset" / "final" / "data.yaml"
USER_RARE = PROJECT_ROOT / "dataset" / "user_rare"
FINAL_IMG = PROJECT_ROOT / "dataset" / "final" / "images" / "train"
FINAL_LBL = PROJECT_ROOT / "dataset" / "final" / "labels" / "train"
NEEDS_REVIEW = PROJECT_ROOT / "dataset" / "user_rare" / "needs_review"


def load_names(data_arg: str) -> list[str]:
    p = Path(data_arg)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve() if not p.exists() else p.resolve()
    with open(p, "r", encoding="utf-8") as f:
        d = yaml.safe_load(f)
    return d["names"]


def _copy_to_train(img: Path, class_id: int, xywhn) -> None:
    FINAL_IMG.mkdir(parents=True, exist_ok=True)
    FINAL_LBL.mkdir(parents=True, exist_ok=True)
    dst_img = FINAL_IMG / f"{img.stem}__u{img.suffix}"
    # 避免重名覆盖
    i = 1
    while dst_img.exists():
        dst_img = FINAL_IMG / f"{img.stem}__u_{i}{img.suffix}"
        i += 1
    shutil.copy(img, dst_img)
    dst_lbl = FINAL_LBL / (dst_img.stem + ".txt")
    with open(dst_lbl, "w", encoding="utf-8") as f:
        cx, cy, w, h = xywhn
        f.write(f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")


def _to_review(img: Path, class_name: str) -> None:
    dst = NEEDS_REVIEW / class_name
    dst.mkdir(parents=True, exist_ok=True)
    shutil.move(str(img), str(dst / img.name))


def auto_mode(names: list[str], conf: float) -> None:
    from ultralytics import YOLO

    model = YOLO(str(PROJECT_ROOT / "models" / "weights" / "best.pt"))
    stats = {"ingested": 0, "review": 0}
    for class_dir in sorted(p for p in USER_RARE.iterdir() if p.is_dir() and p.name in names):
        cid = names.index(class_dir.name)
        for img in sorted(class_dir.glob("*.[jpJP][pnPN][gG]")) + sorted(class_dir.glob("*.png")):
            res = model.predict(str(img), conf=0.01, verbose=False)[0]
            boxes = res.boxes
            chosen = None
            if boxes is not None and len(boxes):
                # 选与文件夹类一致、且最高置信度的框
                for b in boxes:
                    if int(b.cls[0]) == cid and float(b.conf[0]) >= conf:
                        if chosen is None or float(b.conf[0]) > chosen[1]:
                            chosen = (b, float(b.conf[0]))
            if chosen is not None:
                b = chosen[0]
                xyxy = b.xyxyn[0].tolist()  # 归一化 xyxy
                x1, y1, x2, y2 = xyxy
                cx, cy, w, h = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1
                _copy_to_train(img, cid, (cx, cy, w, h))
                stats["ingested"] += 1
                print(f"  [并入] {class_dir.name}/{img.name} conf={chosen[1]:.2f}")
            else:
                _to_review(img, class_dir.name)
                stats["review"] += 1
                print(f"  [待手标] {class_dir.name}/{img.name}（无合格检测，移入 needs_review）")
    print(f"\nauto 完成：自动并入 {stats['ingested']} 张，待手标 {stats['review']} 张")


def stage_mode(names: list[str]) -> None:
    FINAL_IMG.mkdir(parents=True, exist_ok=True)
    count = 0
    for class_dir in sorted(p for p in USER_RARE.iterdir() if p.is_dir() and p.name in names):
        for img in sorted(class_dir.glob("*.[jpJP][pnPN][gG]")) + sorted(class_dir.glob("*.png")):
            dst = FINAL_IMG / f"{img.stem}__u{img.suffix}"
            i = 1
            while dst.exists():
                dst = FINAL_IMG / f"{img.stem}__u_{i}{img.suffix}"
                i += 1
            shutil.copy(img, dst)
            _to_review(img, class_dir.name)  # 原图移入 needs_review 待标注
            count += 1
            print(f"  [staged] {class_dir.name}/{img.name} -> images/train（请手标后放 labels/train）")
    print(f"\nstage 完成：{count} 张已复制到训练图目录，原图移入 needs_review 待 labelImg 标注")


def main():
    ap = argparse.ArgumentParser(description="稀有类真实照片接入训练集（C）")
    ap.add_argument("--mode", choices=["auto", "stage"], default="auto")
    ap.add_argument("--conf", type=float, default=0.5, help="auto 模式置信度阈值")
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    args = ap.parse_args()

    if not USER_RARE.exists():
        sys.exit(f"[提示] 没找到 {USER_RARE}，请先按 dataset/user_rare/<类名>/ 放照片")

    names = load_names(args.data)
    print(f"[ingest] 类别数={len(names)}，模式={args.mode}")
    if args.mode == "auto":
        auto_mode(names, args.conf)
    else:
        stage_mode(names)
    print("[ingest] 完成后，再次运行 train_vision.py 重训即可把新数据纳入。")


if __name__ == "__main__":
    main()
