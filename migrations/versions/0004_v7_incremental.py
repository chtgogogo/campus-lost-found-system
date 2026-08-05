"""v7 增量迁移：失效 / 软删 / 完成时间字段。

- lost_item / found_item 增加 expires_at(可空) + deleted_at(可空) + 索引
- match_record 增加 completed_at(可空) + 索引
- 存量回填：expires_at = created_at + 90天；已完成匹配 completed_at = created_at
- 通过 batch_alter_table(render_as_batch=True) 对 SQLite 安全加列
- 幂等：基于 inspector 检查列/索引是否存在
- 所有索引显式命名，规避 v4 name 坑

依赖：0003_v4_incremental
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "0004_v7_incremental"
down_revision = "0003_v4_incremental"
branch_labels = None
depends_on = None

EXPIRE_DAYS = 90
ADMIN_RETENTION_DAYS = 270


def _exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def _index_exists(inspector, table: str, index: str) -> bool:
    return index in {i["name"] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name  # 'sqlite' / 'mysql'

    with op.batch_alter_table("lost_item") as b:
        if not _exists(inspector, "lost_item", "expires_at"):
            b.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        if not _exists(inspector, "lost_item", "deleted_at"):
            b.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        if not _index_exists(inspector, "lost_item", "idx_lost_expires"):
            b.create_index("idx_lost_expires", ["expires_at"])
        if not _index_exists(inspector, "lost_item", "idx_lost_deleted"):
            b.create_index("idx_lost_deleted", ["deleted_at"])

    with op.batch_alter_table("found_item") as b:
        if not _exists(inspector, "found_item", "expires_at"):
            b.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        if not _exists(inspector, "found_item", "deleted_at"):
            b.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        if not _index_exists(inspector, "found_item", "idx_found_expires"):
            b.create_index("idx_found_expires", ["expires_at"])
        if not _index_exists(inspector, "found_item", "idx_found_deleted"):
            b.create_index("idx_found_deleted", ["deleted_at"])

    with op.batch_alter_table("match_record") as b:
        if not _exists(inspector, "match_record", "completed_at"):
            b.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        if not _index_exists(inspector, "match_record", "idx_match_completed"):
            b.create_index("idx_match_completed", ["completed_at"])

    # ---- 存量回填（按方言分支，保证 SQLite/MySQL 均可执行） ----
    if dialect == "sqlite":
        op.execute(text("UPDATE lost_item SET expires_at = datetime(created_at, '+90 days') WHERE expires_at IS NULL"))
        op.execute(text("UPDATE found_item SET expires_at = datetime(created_at, '+90 days') WHERE expires_at IS NULL"))
    else:  # mysql / 其他
        op.execute(text("UPDATE lost_item SET expires_at = created_at + INTERVAL 90 DAY WHERE expires_at IS NULL"))
        op.execute(text("UPDATE found_item SET expires_at = created_at + INTERVAL 90 DAY WHERE expires_at IS NULL"))
    # 已完成匹配（status=2）best-effort 回填 completed_at = created_at
    op.execute(text("UPDATE match_record SET completed_at = created_at WHERE completed_at IS NULL AND status = 2"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    with op.batch_alter_table("match_record") as b:
        if _index_exists(inspector, "match_record", "idx_match_completed"):
            b.drop_index("idx_match_completed")
        if _exists(inspector, "match_record", "completed_at"):
            b.drop_column("completed_at")

    with op.batch_alter_table("found_item") as b:
        if _index_exists(inspector, "found_item", "idx_found_deleted"):
            b.drop_index("idx_found_deleted")
        if _index_exists(inspector, "found_item", "idx_found_expires"):
            b.drop_index("idx_found_expires")
        if _exists(inspector, "found_item", "deleted_at"):
            b.drop_column("deleted_at")
        if _exists(inspector, "found_item", "expires_at"):
            b.drop_column("expires_at")

    with op.batch_alter_table("lost_item") as b:
        if _index_exists(inspector, "lost_item", "idx_lost_deleted"):
            b.drop_index("idx_lost_deleted")
        if _index_exists(inspector, "lost_item", "idx_lost_expires"):
            b.drop_index("idx_lost_expires")
        if _exists(inspector, "lost_item", "deleted_at"):
            b.drop_column("deleted_at")
        if _exists(inspector, "lost_item", "expires_at"):
            b.drop_column("expires_at")
