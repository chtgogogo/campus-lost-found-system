"""v17 训练数据导出脚本单测：ImageFolder 结构 / 跳过规则 / 纠错 CSV / 统计口径。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from app.models.correction import CorrectionSample
from app.models.item import FoundItem, LostItem
from scripts.export_training_data import _safe_class_dir, export_training_data


def _mk_png(dir: Path, name: str) -> Path:
    """往临时上传目录写一张真 PNG（导出脚本按 URL 从该目录读文件）。"""
    buf_path = dir / name
    Image.new("RGB", (8, 8), (200, 10, 10)).save(buf_path, "PNG")
    return buf_path


def _seed(db, upload_dir: Path):
    """播种：书包×2（有图）、雨伞×1（有图，AI预标≠用户最终）、其他×1（有图）、无图×1、无类别×1。"""
    from app.schemas.common import FoundItemStatus, LostItemStatus

    now = datetime.utcnow() + timedelta(days=90)

    def mk_lost(category, images):
        it = LostItem(
            publisher_id=1, category_name=category, title="t", description="d",
            category_id=None, status=int(LostItemStatus.PENDING_MATCH), images=images,
        )
        it.expires_at = now
        db.add(it)
        return it

    def mk_found(category, images):
        it = FoundItem(
            finder_id=1, category_name=category, description="d", images=images,
            keep_status=0, status=int(FoundItemStatus.PENDING),
        )
        it.expires_at = now
        db.add(it)
        return it

    b1 = _mk_png(upload_dir, "b1.png")
    b2 = _mk_png(upload_dir, "b2.png")
    y1 = _mk_png(upload_dir, "y1.png")
    o1 = _mk_png(upload_dir, "o1.png")

    # images 列为 URL 列表（JSON 列），首图文件需真实存在于 UPLOAD_DIR
    mk_lost("书包", [f"/uploads/{b1.name}"])
    mk_found("书包", [f"/uploads/{b2.name}"])
    lost_y = mk_lost("雨伞", [f"/uploads/{y1.name}"])
    mk_lost("其他", [f"/uploads/{o1.name}"])
    mk_lost("水杯", ["/uploads/missing.png"])  # 文件缺失
    mk_lost("", [f"/uploads/{b1.name}"])       # 无类别
    db.flush()

    db.add(
        CorrectionSample(
            item_type="lost", item_id=lost_y.id, user_id=1,
            vision_label="书包", final_category_name="雨伞",
        )
    )
    db.commit()


def test_safe_class_dir_strips_illegal_chars():
    assert _safe_class_dir("手机") == "手机"
    assert _safe_class_dir("a/b\\c:d") == "a_b_c_d"
    assert _safe_class_dir("  ") == "_unnamed"


def test_export_training_data_full_flow(db, tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    out_dir = tmp_path / "out"
    _seed(db, upload_dir)

    # 上传目录 monkeypatch 到临时目录（脚本读 settings.UPLOAD_DIR）
    from app.core.config import settings

    original = settings.UPLOAD_DIR
    settings.UPLOAD_DIR = str(upload_dir)
    try:
        stats = export_training_data(db, out_dir, include_other=False)
    finally:
        settings.UPLOAD_DIR = original

    # ---- 统计口径 ----
    assert stats["total"] == 6
    assert stats["exported"] == 3, "书包×2 + 雨伞×1 导出（其他/缺图/无类别跳过）"
    assert stats["skipped_other"] == 1
    assert stats["skipped_missing_file"] == 1
    assert stats["skipped_no_category"] == 1
    assert stats["classes"] == {"书包": 2, "雨伞": 1}
    assert stats["corrections"] == 1

    # ---- ImageFolder 结构：每类一个文件夹，文件名带来源可追溯 ----
    ds = out_dir / "dataset"
    assert sorted(p.name for p in ds.iterdir()) == ["书包", "雨伞"]
    bag_files = sorted(p.name for p in (ds / "书包").iterdir())
    assert len(bag_files) == 2
    # 文件名格式 <item_type>_<item_id>.<ext>：失物/拾物来源各一（id 自增不可硬编码）
    assert any(f.startswith("lost_") for f in bag_files), bag_files
    assert any(f.startswith("found_") for f in bag_files), bag_files
    umbrella_files = list((ds / "雨伞").iterdir())
    assert len(umbrella_files) == 1 and umbrella_files[0].name.startswith("lost_")
    # 拷贝的是真 PNG（非空）
    assert all(p.stat().st_size > 0 for p in (ds / "书包").iterdir())

    # ---- 纠错样本 CSV ----
    import csv

    with open(out_dir / "corrections.csv", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["item_type", "item_id", "user_id", "vision_label", "final_category_name"]
    assert rows[1][0] == "lost" and rows[1][2] == "1"
    assert rows[1][3] == "书包" and rows[1][4] == "雨伞"


def test_export_include_other(db, tmp_path):
    upload_dir = tmp_path / "uploads2"
    upload_dir.mkdir()
    out_dir = tmp_path / "out2"
    _seed(db, upload_dir)

    from app.core.config import settings

    original = settings.UPLOAD_DIR
    settings.UPLOAD_DIR = str(upload_dir)
    try:
        stats = export_training_data(db, out_dir, include_other=True)
    finally:
        settings.UPLOAD_DIR = original

    assert stats["exported"] == 4, "include_other 时其他类也导出"
    assert stats["classes"]["其他"] == 1
    assert (out_dir / "dataset" / "其他").is_dir()
