"""训练数据导出（v17）：把「照片 ↔ 用户填写类别」的配对数据导出成可训练格式。

背景（执行指令外的用户需求，2026-09-25）：系统当前 AI 只识别种子 11 类；每次发布时
照片落盘 uploads/、用户填写的 category_name 存物品表——**配对数据从第一天就在积累**。
本脚本把存量配对一键导出为 YOLOv8 分类训练要求的 ImageFolder 目录结构，
攒够数据后即可训练识别更多种类::

    # 导出（默认输出 training_dataset/，数据库取 DATABASE_URL 或 .env）
    .venv/Scripts/python.exe scripts/export_training_data.py
    # 指定输出目录 + 把「其他」类也导出（默认跳过——它是降级筐，不是真类目）
    .venv/Scripts/python.exe scripts/export_training_data.py --out training_dataset_2 --include-other

产出：
    training_dataset/
    ├── dataset/<类名>/<lost|found>_<物品id>_<序号>.<ext>   # ImageFolder：每类一个文件夹
    └── corrections.csv                                     # 数据飞轮：AI 预标 vs 用户最终分类（高价值纠错对）
    控制台打印每类样本数统计（含缺失文件/跳过计数）。

后续训练路径（YOLOv8 分类，权重与数据就绪后）::
    yolo classify train data=training_dataset/dataset model=yolov8n-cls.pt epochs=100

纪律：本脚本**只读数据库与上传目录、只写输出目录**，绝不触碰 dev.db 内容本身。
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.correction import CorrectionSample  # noqa: E402
from app.models.item import FoundItem, LostItem  # noqa: E402

OTHER_CATEGORY = "其他"
_SAFE_NAME_RE = re.compile(r"[\\/:*?\"<>|\s]+")


def _safe_class_dir(name: str) -> str:
    """类目名 → 目录名：空白与文件系统非法字符替换为下划线。"""
    cleaned = _SAFE_NAME_RE.sub("_", (name or "").strip())
    return cleaned or "_unnamed"


def _first_image_file(images: list | None) -> Path | None:
    """取物品首图在本地的路径（/uploads/xxx 相对 URL → UPLOAD_DIR/xxx）。"""
    if not images:
        return None
    name = str(images[0]).rsplit("/", 1)[-1]
    if not name:
        return None
    path = Path(settings.UPLOAD_DIR) / name
    return path if path.is_file() else None


def export_training_data(db, out_dir: Path, include_other: bool = False) -> dict:
    """导出「照片↔类别」配对 → ImageFolder + 纠错样本 CSV。返回统计 dict。

    Args:
        db: SQLAlchemy Session（调用方负责创建/关闭）。
        out_dir: 输出根目录（自动创建 dataset/ 与 corrections.csv）。
        include_other: 是否导出「其他」类（默认 False：降级筐对训练无意义）。
    """
    dataset_dir = out_dir / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    stats: dict = {
        "total": 0,
        "exported": 0,
        "skipped_missing_file": 0,
        "skipped_other": 0,
        "skipped_no_category": 0,
        "classes": {},
        "corrections": 0,
    }

    items: list[tuple[str, int, str, list | None]] = []
    for it in db.query(LostItem).all():
        items.append(("lost", it.id, it.category_name or "", it.images))
    for it in db.query(FoundItem).all():
        items.append(("found", it.id, it.category_name or "", it.images))
    stats["total"] = len(items)

    for item_type, item_id, category_name, images in items:
        if not category_name.strip():
            stats["skipped_no_category"] += 1
            continue
        if category_name.strip() == OTHER_CATEGORY and not include_other:
            stats["skipped_other"] += 1
            continue
        src = _first_image_file(images)
        if src is None:
            stats["skipped_missing_file"] += 1
            continue
        class_dir = dataset_dir / _safe_class_dir(category_name)
        class_dir.mkdir(parents=True, exist_ok=True)
        # 文件名带来源（item_type + item_id）：训练样本可追溯回具体发布记录
        dest = class_dir / f"{item_type}_{item_id}{src.suffix.lower() or '.png'}"
        shutil.copy2(src, dest)
        stats["exported"] += 1
        label = category_name.strip()
        stats["classes"][label] = stats["classes"].get(label, 0) + 1

    # 数据飞轮纠错样本：AI 预标 ≠ 用户最终分类（v11 CorrectionSample）
    corrections_path = out_dir / "corrections.csv"
    with open(corrections_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item_type", "item_id", "user_id", "vision_label", "final_category_name"])
        for s in db.query(CorrectionSample).all():
            writer.writerow([s.item_type, s.item_id, s.user_id, s.vision_label, s.final_category_name])
            stats["corrections"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="导出「照片↔用户类别」训练数据（ImageFolder + 纠错 CSV）")
    parser.add_argument("--out", type=str, default="training_dataset", help="输出目录（默认 ./training_dataset）")
    parser.add_argument("--include-other", action="store_true", help="把「其他」类也导出（默认跳过）")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    db = SessionLocal()
    try:
        stats = export_training_data(db, out_dir, include_other=args.include_other)
    finally:
        db.close()

    print(f"[导出完成] {out_dir}")
    print(f"  物品总数={stats['total']}  导出={stats['exported']}  "
          f"缺首图跳过={stats['skipped_missing_file']}  其他类跳过={stats['skipped_other']}  "
          f"无类别跳过={stats['skipped_no_category']}")
    print(f"  纠错样本(AI预标≠用户最终)={stats['corrections']} → corrections.csv")
    if stats["classes"]:
        print("  每类样本数（升序——先给样本少的类补数据）：")
        for name, count in sorted(stats["classes"].items(), key=lambda x: x[1]):
            print(f"    {name}: {count}")
    print(
        "\n后续训练（YOLOv8 分类）：\n"
        "  yolo classify train data=" + str(out_dir / "dataset").replace("\\", "/")
        + " model=yolov8n-cls.pt epochs=100 imgsz=224"
    )
    print("建议：每类 ≥100 张再开始训练；少于 30 张的类先补采集，否则容易过拟合。")


if __name__ == "__main__":
    main()
