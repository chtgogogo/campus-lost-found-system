"""v2 flow 增量迁移：lost_item.lost_time 可空 + match_record.flow_type 列。

R3（时间非必填）：
- lost_item.lost_time：nullable=False → nullable=True（SQLite 走 batch 重建表，MySQL 直接改列约束）。

R2（keep1 完成方式标记）：
- match_record.flow_type：新增列（SmallInteger, nullable=False, server_default="0"；
  0=双向交接 / 1=keep1 单边「申请即完成」，作为撤回动作唯一门控）。

- status=6（REVOKED）是 SmallInteger 值域扩展，无需改表。
- 幂等：全部基于 inspector 判断列存在 / 当前 nullable，重复执行安全。
- 测试库由 conftest drop_all/create_all 重建，无需迁移。

依赖：0005_v8_match
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0006_flow_v2"
down_revision = "0005_v8_match"
branch_labels = None
depends_on = None


def _exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1) lost_item.lost_time → nullable（幂等：当前已 nullable 则跳过）
    lost_cols = {c["name"]: c for c in inspector.get_columns("lost_item")}
    if "lost_time" in lost_cols:
        cur_nullable = bool(lost_cols["lost_time"].get("nullable", False))
        if not cur_nullable:
            with op.batch_alter_table("lost_item") as b:
                b.alter_column("lost_time", existing_type=sa.DateTime(), nullable=True)

    # 2) match_record.flow_type 加列（幂等：已存在则跳过）
    with op.batch_alter_table("match_record") as b:
        if not _exists(inspector, "match_record", "flow_type"):
            b.add_column(
                sa.Column("flow_type", sa.SmallInteger(), nullable=False, server_default="0")
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1) match_record.flow_type 删除
    with op.batch_alter_table("match_record") as b:
        if _exists(inspector, "match_record", "flow_type"):
            b.drop_column("flow_type")

    # 2) lost_item.lost_time 恢复 nullable=False
    lost_cols = {c["name"]: c for c in inspector.get_columns("lost_item")}
    if "lost_time" in lost_cols:
        cur_nullable = bool(lost_cols["lost_time"].get("nullable", False))
        if cur_nullable:
            with op.batch_alter_table("lost_item") as b:
                b.alter_column("lost_time", existing_type=sa.DateTime(), nullable=False)
