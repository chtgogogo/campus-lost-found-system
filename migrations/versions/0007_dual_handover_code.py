"""双码交叉验证模型重构：handover_code 表字段增删 + 索引调整。

变更内容：
- 新增列：lost_code / finder_code / lost_code_expire / finder_code_expire /
          lost_code_verified / finder_code_verified
- 删除列：code / qr_token / verified_by_lost / verified_by_finder / expire_at
- 删除索引：idx_handover_code / idx_handover_expire
- 新增索引：idx_handover_lost_code / idx_handover_finder_code
- 保留索引：uq_handover_match_seq / idx_handover_status
- 清空存量数据（无生产价值）

幂等：全部基于 inspector 判断列/索引存在，重复执行安全。
测试库由 conftest drop_all/create_all 重建，无需迁移。

依赖：0006_flow_v2
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0007_dual_handover_code"
down_revision = "0006_flow_v2"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_index(inspector, table: str, index_name: str) -> bool:
    return index_name in {i["name"] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 0) 清空存量数据（旧格式数据无生产价值）
    op.execute("DELETE FROM handover_code")

    # 1) 先删除引用旧列的索引（避免 batch 重建表时引用已删除列报错）
    for idx_name in ("idx_handover_code", "idx_handover_expire"):
        if _has_index(inspector, "handover_code", idx_name):
            op.drop_index(idx_name, table_name="handover_code")

    # 2) 列增删（batch_alter_table 自动处理 SQLite 表重建）
    with op.batch_alter_table("handover_code") as b:
        # 新增列
        if not _has_column(inspector, "handover_code", "lost_code"):
            b.add_column(sa.Column("lost_code", sa.String(4), nullable=True))
        if not _has_column(inspector, "handover_code", "finder_code"):
            b.add_column(sa.Column("finder_code", sa.String(4), nullable=True))
        if not _has_column(inspector, "handover_code", "lost_code_expire"):
            b.add_column(sa.Column("lost_code_expire", sa.DateTime(), nullable=True))
        if not _has_column(inspector, "handover_code", "finder_code_expire"):
            b.add_column(sa.Column("finder_code_expire", sa.DateTime(), nullable=True))
        if not _has_column(inspector, "handover_code", "lost_code_verified"):
            b.add_column(
                sa.Column("lost_code_verified", sa.Boolean(), nullable=False, server_default="0")
            )
        if not _has_column(inspector, "handover_code", "finder_code_verified"):
            b.add_column(
                sa.Column("finder_code_verified", sa.Boolean(), nullable=False, server_default="0")
            )
        # 删除旧列
        if _has_column(inspector, "handover_code", "code"):
            b.drop_column("code")
        if _has_column(inspector, "handover_code", "qr_token"):
            b.drop_column("qr_token")
        if _has_column(inspector, "handover_code", "verified_by_lost"):
            b.drop_column("verified_by_lost")
        if _has_column(inspector, "handover_code", "verified_by_finder"):
            b.drop_column("verified_by_finder")
        if _has_column(inspector, "handover_code", "expire_at"):
            b.drop_column("expire_at")

    # 3) 创建新索引
    inspector = inspect(bind)
    if not _has_index(inspector, "handover_code", "idx_handover_lost_code"):
        op.create_index("idx_handover_lost_code", "handover_code", ["lost_code"])
    if not _has_index(inspector, "handover_code", "idx_handover_finder_code"):
        op.create_index("idx_handover_finder_code", "handover_code", ["finder_code"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1) 删除新索引
    for idx_name in ("idx_handover_lost_code", "idx_handover_finder_code"):
        if _has_index(inspector, "handover_code", idx_name):
            op.drop_index(idx_name, table_name="handover_code")

    # 2) 恢复旧列 + 删除新列
    with op.batch_alter_table("handover_code") as b:
        if not _has_column(inspector, "handover_code", "code"):
            b.add_column(sa.Column("code", sa.String(12), nullable=True))
        if not _has_column(inspector, "handover_code", "qr_token"):
            b.add_column(sa.Column("qr_token", sa.String(64), nullable=True))
        if not _has_column(inspector, "handover_code", "verified_by_lost"):
            b.add_column(
                sa.Column("verified_by_lost", sa.Boolean(), nullable=False, server_default="0")
            )
        if not _has_column(inspector, "handover_code", "verified_by_finder"):
            b.add_column(
                sa.Column("verified_by_finder", sa.Boolean(), nullable=False, server_default="0")
            )
        if not _has_column(inspector, "handover_code", "expire_at"):
            b.add_column(sa.Column("expire_at", sa.DateTime(), nullable=True))
        if _has_column(inspector, "handover_code", "lost_code"):
            b.drop_column("lost_code")
        if _has_column(inspector, "handover_code", "finder_code"):
            b.drop_column("finder_code")
        if _has_column(inspector, "handover_code", "lost_code_expire"):
            b.drop_column("lost_code_expire")
        if _has_column(inspector, "handover_code", "finder_code_expire"):
            b.drop_column("finder_code_expire")
        if _has_column(inspector, "handover_code", "lost_code_verified"):
            b.drop_column("lost_code_verified")
        if _has_column(inspector, "handover_code", "finder_code_verified"):
            b.drop_column("finder_code_verified")

    # 3) 恢复旧索引
    inspector = inspect(bind)
    if not _has_index(inspector, "handover_code", "idx_handover_code"):
        op.create_index("idx_handover_code", "handover_code", ["code"])
    if not _has_index(inspector, "handover_code", "idx_handover_expire"):
        op.create_index("idx_handover_expire", "handover_code", ["expire_at"])
