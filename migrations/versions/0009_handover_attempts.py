"""交接码防穷举：handover_code 新增 attempts 列（卡#4 安检 L1-9）。

变更内容（2026-09-23）：
- handover_code 新增列 attempts（Integer，NOT NULL，默认 0）——交接码比对失败次数。
- 服务层（handover_service.verify）在错码时 +1，达 5 次将该行 status 置 2（EXPIRED，
  复用现有状态，不新增枚举值）锁定；重新 generate 产生新 seq 行（attempts 归零）天然解锁。
- 不触碰双码模型与 generate 逻辑。

幂等：基于 inspector 判断列存在，重复执行安全。
测试库由 conftest drop_all/create_all 重建，无需迁移。

依赖：0008_clip_reorder_and_correction
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0009_handover_attempts"
down_revision = "0008_clip_reorder_and_correction"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_column(inspector, "handover_code", "attempts"):
        with op.batch_alter_table("handover_code") as b:
            # server_default 兜底存量行；SQLite 走 batch 重建，MySQL 走原生 ALTER
            b.add_column(
                sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0"))
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_column(inspector, "handover_code", "attempts"):
        with op.batch_alter_table("handover_code") as b:
            b.drop_column("attempts")
