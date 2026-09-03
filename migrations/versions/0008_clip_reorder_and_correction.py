"""CLIP 两阶段精排 + 数据飞轮：match_record 加 clip_sim 列；新增 correction_sample 表。

变更内容（2026-08-27，用户拍板「核心升级」组合）：
- match_record 新增列 clip_sim（Float，NULL=未精排/CLIP 不可用）——精排不改总分，
  仅作列表「同分打破平局」的次排序键；新增索引 idx_match_clip。
- 新增表 correction_sample（用户纠错样本：视觉预标 vs 用户最终分类，攒数据供微调/修映射）。

幂等：全部基于 inspector 判断列/表/索引存在，重复执行安全。
测试库由 conftest drop_all/create_all 重建，无需迁移。

依赖：0007_dual_handover_code
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0008_clip_reorder_and_correction"
down_revision = "0007_dual_handover_code"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_index(inspector, table: str, index_name: str) -> bool:
    return index_name in {i["name"] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1) match_record.clip_sim
    if not _has_column(inspector, "match_record", "clip_sim"):
        with op.batch_alter_table("match_record") as b:
            b.add_column(sa.Column("clip_sim", sa.Float(), nullable=True))
    if not _has_index(inspector, "match_record", "idx_match_clip"):
        op.create_index("idx_match_clip", "match_record", ["clip_sim"])

    # 2) correction_sample 表
    if not _has_table(inspector, "correction_sample"):
        op.create_table(
            "correction_sample",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("item_type", sa.String(10), nullable=False),
            sa.Column("item_id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=True),
            sa.Column("vision_label", sa.String(64), nullable=True),
            sa.Column("final_category_name", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_table(inspector, "correction_sample"):
        op.drop_table("correction_sample")
    if _has_index(inspector, "match_record", "idx_match_clip"):
        op.drop_index("idx_match_clip", table_name="match_record")
    if _has_column(inspector, "match_record", "clip_sim"):
        with op.batch_alter_table("match_record") as b:
            b.drop_column("clip_sim")
