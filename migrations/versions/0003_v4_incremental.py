"""v4 增量迁移：im_session 新增 found_id 列（无 match 联系溯源）。

- 仅对 `im_session` 增加可空 `found_id`（BigInteger，FK→found_item.id，索引），
  用于「未匹配即联系」场景将会话强绑定到具体拾物（v4 主理人拍板：强溯源 + 发送端二次门控）。
- 通过 `batch_alter_table`（render_as_batch=True）对 SQLite 安全加列。
- 幂等：基于 inspector 检查列是否存在，重复执行 `upgrade head` 安全。
- 配套 ORM 模型见 `app/models/im.py`（IMSession.found_id）。

依赖：0002_v3_incremental
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_v4_incremental"
down_revision = "0002_v3_incremental"
branch_labels = None
depends_on = None


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    with op.batch_alter_table("im_session") as batch_op:
        if not _column_exists(inspector, "im_session", "found_id"):
            batch_op.add_column(
                sa.Column(
                    "found_id",
                    sa.BigInteger().with_variant(sa.Integer, "sqlite"),
                    # SQLite batch 模式重建表会重新挂外键，必须显式命名约束
                    sa.ForeignKey(
                        "found_item.id",
                        ondelete="RESTRICT",
                        name="fk_im_session_found_id",
                    ),
                    nullable=True,
                )
            )
        if not _column_exists(inspector, "im_session", "ix_im_found"):
            batch_op.create_index("ix_im_found", ["found_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    with op.batch_alter_table("im_session") as batch_op:
        if _column_exists(inspector, "im_session", "ix_im_found"):
            batch_op.drop_index("ix_im_found")
        if _column_exists(inspector, "im_session", "found_id"):
            batch_op.drop_column("found_id")
