"""v17④ 识别链路异步化：新增 recognition_task 表 + lost/found_item 补 recognize_status 列。

变更内容（2026-09-25）：
- 新表 recognition_task：异步识别任务（yolo 主/子任务 + clip 精排任务），
  file_hash 唯一索引做幂等键（同一张图全库只跑一次推理），子任务以 parent_id 引用主任务复制结果。
- lost_item / found_item 新增 recognize_status（SmallInteger，NOT NULL，默认 2=DONE）：
  存量行历史上识别在发布内同步完成，默认 DONE 避免老数据显示「识别中」；列表/卡片零额外查询可展示。

幂等：基于 inspector 判断表/列存在，重复执行安全。
测试库由 conftest drop_all/create_all 重建，无需迁移。

依赖：0009_handover_attempts
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0010_recognition_task"
down_revision = "0009_handover_attempts"
branch_labels = None
depends_on = None


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "recognition_task"):
        op.create_table(
            "recognition_task",
            # 主键：MySQL BigInteger 自增 / SQLite Integer（与项目其他表同款 with_variant 口径）
            sa.Column(
                "id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                primary_key=True,
                autoincrement=True,
            ),
            sa.Column("task_type", sa.String(16), nullable=False),
            sa.Column("status", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("file_hash", sa.String(64), nullable=True),
            sa.Column(
                "parent_id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                nullable=True,
            ),
            sa.Column("item_type", sa.String(8), nullable=True),
            sa.Column(
                "item_id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                nullable=True,
            ),
            sa.Column("payload", sa.Text(), nullable=True),
            sa.Column("result_category_id", sa.Integer(), nullable=True),
            sa.Column("result_label", sa.String(100), nullable=True),
            sa.Column("result_confidence", sa.Float(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
        op.create_index("uq_recognition_file_hash", "recognition_task", ["file_hash"], unique=True)
        op.create_index("idx_recognition_status", "recognition_task", ["status"])
        op.create_index("idx_recognition_item", "recognition_task", ["item_type", "item_id"])

    for table in ("lost_item", "found_item"):
        if not _has_column(inspector, table, "recognize_status"):
            with op.batch_alter_table(table) as b:
                # 2=DONE：存量行识别在发布内同步完成，默认 DONE 避免老数据显示「识别中」
                b.add_column(
                    sa.Column(
                        "recognize_status",
                        sa.SmallInteger(),
                        nullable=False,
                        server_default=sa.text("2"),
                    )
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table in ("lost_item", "found_item"):
        if _has_column(inspector, table, "recognize_status"):
            with op.batch_alter_table(table) as b:
                b.drop_column("recognize_status")

    if _has_table(inspector, "recognition_task"):
        op.drop_index("idx_recognition_item", table_name="recognition_task")
        op.drop_index("idx_recognition_status", table_name="recognition_task")
        op.drop_index("uq_recognition_file_hash", table_name="recognition_task")
        op.drop_table("recognition_task")
