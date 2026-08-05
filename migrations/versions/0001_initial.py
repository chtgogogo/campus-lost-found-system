"""首版迁移：建表 + 索引（audit_log 按月分区仅 MySQL，SQLite 用普通表）。

MVP 开发期可直接用 `Base.metadata.create_all`；此迁移用于 MySQL 生产环境
（通过 Alembic 执行）。审计分区由 deploy/mysql/init.sql 显式定义。
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

from app.core.database import Base
from app import models  # noqa: F401  确保全部模型注册

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())
    # 仅创建尚未存在的表（幂等）
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            table.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=bind, checkfirst=True)
