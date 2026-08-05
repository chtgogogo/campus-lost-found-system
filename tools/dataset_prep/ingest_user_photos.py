#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""ingest_user_photos.py — 真实照片数据接入脚手架（方案 C）。

把用户下载的真实校园失物照片「丢进文件夹就能并入训练集」，支持三种模式：

## 用户怎么组织照片
把照片按类别放进子目录，目录名可用「中文」或「12 类英文名」（脚本都认）：

    dataset/user_rare/
    ├── 书包/            ← 中文目录名也支持
    │   ├── schoolbag_1.jpg
    │   └── schoolbag_2.jpg
    ├── 水杯/
    ├── 雨伞/
    ├── 钥匙/
    └── 笔记本电脑/

可用类目（12 类，与 data.yaml 一致）：
    手机(0) 钱包(1) 钥匙(2) 书包(3) 行李箱(4) 笔记本电脑(5)
    校园卡(6) 眼镜(7) 笔记本(8,纸质) 雨伞(9) 水杯(10) 其他(11)

## 三种并入模式（--mode 切换）
- ``folder``（推荐，真实照片零手动标注）：直接按「文件夹名=类目」生成标签，
  不需要任何模型推理，也不用手动画框。每张照片写一个整图框（物品即主体），
  并按 --val-ratio 自动切一部分进验证集（用于真实域评测）。
  注意：整图框训练出来的是「这是什么物品」而非「精确位置」，对本系统
  （用户上传失物照，物品通常是画面主体）完全够用；后续可用迭代标注收紧框。
- ``auto``：用当前 ``models/weights/best.pt`` 推理，高置信同类才自动写框并入，
  其余移到 needs_review。⚠️ 当前 best.pt 在真实域很弱，真实照片大多会被判低置信
  → 基本都进待标注，**真实照片不建议用此模式**。
- ``stage``：仅搬运照片到训练集图片目录，并把原图复制到 needs_review 待手标。

## 用法
    # 真实照片零标注并入（推荐）：文件夹=类目，自动切 20% 验证集
    python tools/dataset_prep/ingest_user_photos.py --mode folder

    # 先预览会并入哪些（不真正写文件）
    python tools/dataset_prep/ingest_user_photos.py --mode folder --dry-run

    # 调验证集比例 / 框大小
    python tools/dataset_prep/ingest_user_photos.py --mode folder --val-ratio 0.2 --box full

提示：脚本假定工作目录为项目根目录（含 ``dataset/`` 与 ``models/``）。
类目名→id 映射从 data.yaml 读取，中文别名仅作便捷映射，最终仍落到 data.yaml 的类。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil

import yaml

# 推理相关惰性导入（仅在 auto 模式真正需要时导入 ultralytics / torch）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ----------------------------- 路径默认 -----------------------------
DEFAULT_DATA = os.path.join(PROJECT_ROOT, "dataset", "final", "data.yaml")
DEFAULT_WEIGHTS = os.path.join(PROJECT_ROOT, "models", "weights", "best.pt")
DEFAULT_SRC = os.path.join(PROJECT_ROOT, "dataset", "user_rare")
DEFAULT_DST_IMAGES = os.path.join(PROJECT_ROOT, "dataset", "final", "images", "train")
DEFAULT_DST_LABELS = os.path.join(PROJECT_ROOT, "dataset", "final", "labels", "train")
DEFAULT_DST_IMAGES_VAL = os.path.join(PROJECT_ROOT, "dataset", "final", "images", "val")
DEFAULT_DST_LABELS_VAL = os.path.join(PROJECT_ROOT, "dataset", "final", "labels", "val")
DEFAULT_REVIEW = os.path.join(PROJECT_ROOT, "dataset", "user_rare", "needs_review")


# 中文文件夹名 → data.yaml 的英文名（便捷映射，最终落到 data.yaml 的类）
CN_ALIASES = {
    "手机": "phone",
    "钱包": "wallet",
    "钥匙": "keys",
    "钥匙串": "keys",
    "书包": "backpack",
    "背包": "backpack",
    "行李箱": "suitcase",
    "笔记本电脑": "laptop",
    "电脑": "laptop",
    "校园卡": "campus_card",
    "学生证": "campus_card",
    "卡类": "campus_card",  # 各类卡（校园卡/银行卡等）
    "眼镜": "glasses",
    "笔记本": "notebook",  # 纸质笔记本；若指笔记本电脑请用「笔记本电脑」目录
    "书本": "notebook",    # 书本/课本，归入纸质笔记本类
    "雨伞": "umbrella",
    "伞": "umbrella",
    "水杯": "bottle",
    "杯子": "bottle",
    "水壶": "bottle",
    "其他": "other",
    "其它": "other",
}


def _load_name_to_id(data_yaml: str) -> dict[str, int]:
    """从 data.yaml 读取 names 列表，返回 {英文名: id} 映射。"""
    if not os.path.exists(data_yaml):
        raise FileNotFoundError("找不到 data.yaml: %s" % data_yaml)
    with open(data_yaml, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    names = cfg.get("names", [])
    if not isinstance(names, list) or not names:
        raise ValueError("data.yaml 中 names 为空或格式不正确。")
    return {str(name): idx for idx, name in enumerate(names)}


def _resolve_class_id(folder_name: str, name_to_id: dict[str, int]) -> int | None:
    """把文件夹名解析成类 id：先试英文名，再试中文别名映射。"""
    if folder_name in name_to_id:
        return name_to_id[folder_name]
    en = CN_ALIASES.get(folder_name)
    if en is not None and en in name_to_id:
        return name_to_id[en]
    return None


def _iter_class_images(src: str, name_to_id: dict[str, int]) -> list[tuple[str, str, int]]:
    """遍历 src 下各分类子目录，返回 [(图片绝对路径, 原始类名, 类id)]。

    文件夹名支持中文（经 CN_ALIASES）或英文（data.yaml）。未知类目录打印
    警告并跳过，不递归更深层级。
    """
    items: list[tuple[str, str, int]] = []
    if not os.path.isdir(src):
        return items
    for raw_name in sorted(os.listdir(src)):
        if raw_name.startswith("."):
            continue  # 跳过隐藏目录（如 .workbuddy）
        class_dir = os.path.join(src, raw_name)
        if not os.path.isdir(class_dir):
            continue
        cid = _resolve_class_id(raw_name, name_to_id)
        if cid is None:
            print("[warn] 忽略未知类目录（不在 data.yaml/中文别名中）: %s" % class_dir)
            continue
        for fn in sorted(os.listdir(class_dir)):
            if fn.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                items.append((os.path.join(class_dir, fn), raw_name, cid))
    return items


def _xyxy_to_yolo(box_xyxy: list[float], img_w: int, img_h: int) -> str:
    """把 xyxy 像素坐标转换为 YOLO 归一化 xywh 文本行。"""
    x1, y1, x2, y2 = box_xyxy
    cx = (x1 + x2) / 2.0 / max(img_w, 1)
    cy = (y1 + y2) / 2.0 / max(img_h, 1)
    w = (x2 - x1) / max(img_w, 1)
    h = (y2 - y1) / max(img_h, 1)
    return "%g %g %g %g" % (cx, cy, w, h)  # 4 个归一化坐标；类 id 由调用方用 "%d %s" 拼接


def _is_val(filename: str, val_ratio: float) -> bool:
    """用文件名哈希确定性地决定该图是否进验证集（可复现）。"""
    h = int(hashlib.md5(filename.encode("utf-8")).hexdigest(), 16)
    return (h % 100) < int(round(val_ratio * 100))


def _box_line(box: str) -> str:
    """返回整图框的 4 个归一化坐标（不含类 id）。"""
    if box == "center":
        return "0.5 0.5 0.85 0.85"
    # 默认 full：物品基本占满画面
    return "0.5 0.5 0.98 0.98"


def _mode_folder(
    images: list[tuple[str, str, int]],
    dst_images: str,
    dst_labels: str,
    dst_images_val: str,
    dst_labels_val: str,
    val_ratio: float,
    box: str,
    dry_run: bool,
) -> tuple[int, int]:
    """folder 模式：按文件夹名=类目生成标签，零手动标注。

    Returns:
        (并入训练集数, 并入验证集数)
    """
    if not dry_run:
        os.makedirs(dst_images, exist_ok=True)
        os.makedirs(dst_labels, exist_ok=True)
        os.makedirs(dst_images_val, exist_ok=True)
        os.makedirs(dst_labels_val, exist_ok=True)

    box_coords = _box_line(box)
    per_class: dict[int, dict[str, int]] = {}
    n_train = n_val = 0
    for path, raw_name, cid in images:
        stem = os.path.splitext(os.path.basename(path))[0]
        is_val = _is_val(os.path.basename(path), val_ratio)
        target_img = dst_images_val if is_val else dst_images
        target_lbl = dst_labels_val if is_val else dst_labels
        if not dry_run:
            with open(os.path.join(target_lbl, "%s.txt" % stem), "w", encoding="utf-8") as f:
                f.write("%d %s\n" % (cid, box_coords))
            shutil.copy2(path, os.path.join(target_img, os.path.basename(path)))
        per_class.setdefault(cid, {"train": 0, "val": 0})
        if is_val:
            per_class[cid]["val"] += 1
            n_val += 1
        else:
            per_class[cid]["train"] += 1
            n_train += 1

    if per_class:
        print("\n[汇总] 各类目并入数量（train / val）：")
        for cid in sorted(per_class):
            c = per_class[cid]
            print("  类 %d : train=%d  val=%d" % (cid, c["train"], c["val"]))
    return n_train, n_val


def _mode_auto(
    images: list[tuple[str, str, int]],
    weights: str,
    dst_images: str,
    dst_labels: str,
    review_dir: str,
    threshold: float,
    device: str,
) -> tuple[int, int]:
    """auto 模式：高置信同类自动写标签并入训练集，其余移到 needs_review。

    Returns:
        (自动并入数, 待人工标注数)
    """
    from PIL import Image
    from ultralytics import YOLO

    if not os.path.exists(weights):
        raise FileNotFoundError("auto 模式需要权重文件: %s（请先训练或确认路径）" % weights)

    model = YOLO(weights)
    os.makedirs(dst_images, exist_ok=True)
    os.makedirs(dst_labels, exist_ok=True)
    os.makedirs(review_dir, exist_ok=True)

    merged = 0
    review = 0
    for path, class_name, cid in images:
        try:
            img = Image.open(path).convert("RGB")
        except Exception as exc:
            print("[warn] 无法读取图片，移到待标注: %s (%s)" % (path, exc))
            _move_to_review(path, class_name, review_dir)
            review += 1
            continue

        results = model.predict(img, conf=threshold, device=device, verbose=False)
        best_box = None
        best_conf = 0.0
        best_cls = -1
        for r in results:
            if r.boxes is None or len(r.boxes) == 0:
                continue
            for i in range(len(r.boxes)):
                conf = float(r.boxes.conf[i].cpu())
                cls = int(r.boxes.cls[i].cpu())
                if conf > best_conf:
                    best_conf = conf
                    best_cls = cls
                    best_box = r.boxes.xyxy[i].cpu().tolist()

        if best_box is not None and best_cls == cid and best_conf >= threshold:
            # 同类 + 高置信 → 自动写标签并入训练集
            stem = os.path.splitext(os.path.basename(path))[0]
            line = _xyxy_to_yolo(best_box, img.width, img.height)
            with open(os.path.join(dst_labels, "%s.txt" % stem), "w", encoding="utf-8") as f:
                f.write("%d %s\n" % (cid, line))
            shutil.copy2(path, os.path.join(dst_images, os.path.basename(path)))
            merged += 1
        else:
            # 低置信或检测到异类 → 待人工标注
            _move_to_review(path, class_name, review_dir)
            review += 1

    return merged, review


def _mode_stage(
    images: list[tuple[str, str, int]],
    dst_images: str,
    review_dir: str,
) -> int:
    """stage 模式：仅搬运照片到训练集，并把原图复制到 needs_review 待手标。

    Returns:
        搬入训练集的照片数。
    """
    os.makedirs(dst_images, exist_ok=True)
    os.makedirs(review_dir, exist_ok=True)
    count = 0
    for path, _class_name, _cid in images:
        shutil.copy2(path, os.path.join(dst_images, os.path.basename(path)))
        shutil.copy2(path, os.path.join(review_dir, os.path.basename(path)))
        count += 1
    return count


def _move_to_review(path: str, class_name: str, review_dir: str) -> None:
    """把一张待标注图片移动到 needs_review/<class_name>/ 下（保持分类目录结构）。"""
    dest_dir = os.path.join(review_dir, class_name)
    os.makedirs(dest_dir, exist_ok=True)
    shutil.move(path, os.path.join(dest_dir, os.path.basename(path)))


def _print_labelimg_guide(review_dir: str, dst_labels: str) -> None:
    """打印 labelImg 手标指引。"""
    print("\n========== 人工标注指引（labelImg）==========")
    print("1) 安装并打开 labelImg：pip install labelImg && labelImg")
    print("2) 打开目录（Open Dir）：%s" % review_dir)
    print("3) 修改保存目录（Change Save Dir）：%s" % dst_labels)
    print("4) 在弹出的标签列表中加载 data.yaml 的 12 类名（或手动输入类名）。")
    print("5) 对每张图框出目标并选对应类别，Ctrl+S 保存 .txt。")
    print("6) 标注完成后即可用 train_vision.py 重新训练（ruby 自动并入 train 集）。")
    print("=============================================\n")


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="ingest_user_photos.py",
        description="真实照片接入脚手架：folder 零标注并入 / auto 模型自动打标 / stage 搬运待手标。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--mode",
        choices=["folder", "auto", "stage"],
        default="folder",
        help="并入方式：folder=按文件夹名零标注并入(推荐)；auto=模型高置信自动打标；stage=仅搬运+人工标注。",
    )
    ap.add_argument("--data", default=DEFAULT_DATA, help="data.yaml 路径（读取类名→id 映射）。")
    ap.add_argument("--weights", default=DEFAULT_WEIGHTS, help="auto 模式使用的推理权重（best.pt）。")
    ap.add_argument("--src", default=DEFAULT_SRC, help="用户照片根目录（含 <类名>/ 子目录，支持中文）。")
    ap.add_argument("--dst-images", default=DEFAULT_DST_IMAGES, help="并入的训练图片目录。")
    ap.add_argument("--dst-labels", default=DEFAULT_DST_LABELS, help="并入的训练标签目录。")
    ap.add_argument("--dst-images-val", default=DEFAULT_DST_IMAGES_VAL, help="并入的验证图片目录（真实域评测用）。")
    ap.add_argument("--dst-labels-val", default=DEFAULT_DST_LABELS_VAL, help="并入的验证标签目录。")
    ap.add_argument("--review", default=DEFAULT_REVIEW, help="待人工标注图片目录。")
    ap.add_argument("--threshold", type=float, default=0.5, help="auto 模式自动打标的置信度阈值。")
    ap.add_argument("--val-ratio", type=float, default=0.2, help="folder 模式切多少比例进验证集（真实域评测）。")
    ap.add_argument("--box", choices=["full", "center"], default="full",
                    help="folder 模式的框：full=整图框(0.98)；center=居中 0.85 框。")
    ap.add_argument("--device", default="0", help="auto 模式推理设备（'0' 或 'cpu'）。")
    ap.add_argument("--dry-run", action="store_true", help="只打印会并入的内容，不真正写文件。")
    return ap.parse_args()


def main() -> None:
    """数据接入主流程。"""
    args = _parse_args()

    name_to_id = _load_name_to_id(args.data)
    images = _iter_class_images(args.src, name_to_id)
    if not images:
        print("[info] 未在 %s 下找到任何 <类名>/<图片>。请按 docstring 组织照片后再运行。" % args.src)
        print("[info] 可用英文名：%s" % ", ".join(name_to_id.keys()))
        print("[info] 也可用中文名：%s" % ", ".join(CN_ALIASES.keys()))
        return

    print("[info] 发现 %d 张待处理照片，涉及类：%s" % (
        len(images),
        ", ".join(sorted({c for _, c, _ in images})),
    ))

    if args.mode == "folder":
        n_train, n_val = _mode_folder(
            images, args.dst_images, args.dst_labels,
            args.dst_images_val, args.dst_labels_val,
            args.val_ratio, args.box, args.dry_run,
        )
        tag = "（dry-run，未写文件）" if args.dry_run else ""
        print("[done] folder 模式完成%s：并入训练集 %d 张，验证集 %d 张。" % (tag, n_train, n_val))
        if not args.dry_run:
            print("[info] 训练/验证图片已并入 dataset/final/images/{train,val}，标签在 labels/{train,val}。")
            print("[info] 原图保留在 %s，可安全重复运行。" % args.src)
    elif args.mode == "auto":
        merged, review = _mode_auto(
            images, args.weights, args.dst_images, args.dst_labels,
            args.review, args.threshold, args.device,
        )
        print("[done] auto 模式完成：自动并入 %d 张，待人工标注 %d 张。" % (merged, review))
        if review > 0:
            print("[info] 待标注图片已移到：%s" % args.review)
            _print_labelimg_guide(args.review, args.dst_labels)
    else:  # stage
        count = _mode_stage(images, args.dst_images, args.review)
        print("[done] stage 模式完成：已搬运 %d 张照片到训练集图片目录。" % count)
        print("[info] 待标注原图已复制到：%s" % args.review)
        _print_labelimg_guide(args.review, args.dst_labels)


if __name__ == "__main__":
    main()
