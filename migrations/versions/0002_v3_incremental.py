"""v3 增量迁移：地点列并入描述 + 新增 tags / image_hash 列。

- 先将存量 `lost_location` / `found_location` 文本并入 `description`（标记 `[地点]`），
  保留地点线索（F1 / Q1）。
- 通过 `batch_alter_table`（render_as_batch=True）对 SQLite 安全加列 / 删列。
- 幂等：基于 inspector 检查列是否存在，重复执行 `upgrade head` 安全。

依赖：0001_initial
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "0002_v3_incremental"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    lost_cols = {c["name"] for c in inspector.get_columns("lost_item")}
    found_cols = {c["name"] for c in inspector.get_columns("found_item")}

    # 1) 存量地点并入 description（仅当原地点列仍存在）
    if _column_exists(inspector, "lost_item", "lost_location"):
        bind.execute(
            text(
                "UPDATE lost_item SET description = "
                "COALESCE(description, '') || ' [地点] ' || lost_location "
                "WHERE lost_location IS NOT NULL AND lost_location <> ''"
            )
        )
    if _column_exists(inspector, "found_item", "found_location"):
        bind.execute(
            text(
                "UPDATE found_item SET description = "
                "COALESCE(description, '') || ' [地点] ' || found_location "
                "WHERE found_location IS NOT NULL AND found_location <> ''"
            )
        )

    # 2) lost_item：加 tags / image_hash，删 lost_location
    with op.batch_alter_table("lost_item") as batch_op:
        if not _column_exists(inspector, "lost_item", "tags"):
            batch_op.add_column(sa.Column("tags", sa.JSON(), nullable=True))
        if not _column_exists(inspector, "lost_item", "image_hash"):
            batch_op.add_column(sa.Column("image_hash", sa.String(16), nullable=True))
        if _column_exists(inspector, "lost_item", "lost_location"):
            batch_op.drop_column("lost_location")

    # 3) found_item：加 tags / image_hash，删 found_location
    with op.batch_alter_table("found_item") as batch_op:
        if not _column_exists(inspector, "found_item", "tags"):
            batch_op.add_column(sa.Column("tags", sa.JSON(), nullable=True))
        if not _column_exists(inspector, "found_item", "image_hash"):
            batch_op.add_column(sa.Column("image_hash", sa.String(16), nullable=True))
        if _column_exists(inspector, "found_item", "found_location"):
            batch_op.drop_column("found_location")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    with op.batch_alter_table("lost_item") as batch_op:
        if not _column_exists(inspector, "lost_item", "lost_location"):
            batch_op.add_column(sa.Column("lost_location", sa.String(200), nullable=False, server_default=""))
        if _column_exists(inspector, "lost_item", "image_hash"):
            batch_op.drop_column("image_hash")
        if _column_exists(inspector, "lost_item", "tags"):
            batch_op.drop_column("tags")

    with op.batch_alter_table("found_item") as batch_op:
        if not _column_exists(inspector, "found_item", "found_location"):
            batch_op.add_column(sa.Column("found_location", sa.String(200), nullable=True))
        if _column_exists(inspector, "found_item", "image_hash"):
            batch_op.drop_column("image_hash")
        if _column_exists(inspector, "found_item", "tags"):
            batch_op.drop_column("tags")
