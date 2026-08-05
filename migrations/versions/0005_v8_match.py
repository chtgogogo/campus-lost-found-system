"""v8 增量迁移：外观/特征/地点三列。

- lost_item / found_item 增加 appearance(VARCHAR 255) / features(VARCHAR 255) / location(VARCHAR 128)，可空，无回填（默认 NULL）。
- 存量数据兼容：三列允许 NULL，匹配时按"缺失降级"处理（不报错、不计分）。
- 「其他」类种子已在 `app/core/seed.py` 中存在（name="其他", yolo_class_id=None），无需在本迁移写入。
- 通过 batch_alter_table(render_as_batch=True) 对 SQLite 安全加列。
- 幂等：基于 inspector 检查列是否已存在。
- 必须提供 downgrade（移除三列）。

依赖：0004_v7_incremental
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0005_v8_match"
down_revision = "0004_v7_incremental"
branch_labels = None
depends_on = None


def _exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


NEW_COLUMNS: dict[str, sa.Column] = {
    "appearance": sa.Column("appearance", sa.String(255), nullable=True),
    "features": sa.Column("features", sa.String(255), nullable=True),
    "location": sa.Column("location", sa.String(128), nullable=True),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table in ("lost_item", "found_item"):
        with op.batch_alter_table(table) as b:
            for col_name, col in NEW_COLUMNS.items():
                if not _exists(inspector, table, col_name):
                    b.add_column(col)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table in ("lost_item", "found_item"):
        with op.batch_alter_table(table) as b:
            for col_name in reversed(list(NEW_COLUMNS.keys())):
                if _exists(inspector, table, col_name):
                    b.drop_column(col_name)
