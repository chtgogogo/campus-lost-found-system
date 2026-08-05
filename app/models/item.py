"""失物 / 拾物表（§2.3 / §2.4）。

v3 增量变更（增量设计 v3）：
- 删除 `lost_location` / `found_location`（地点语义并入 `description`，见迁移 0002）。
- 新增 `tags`（JSON 数组，发布时由 TaggingService 写入）与 `image_hash`（16-hex 感知哈希，发布时由 PerceptualHash 计算）。
- 保留 `contact_allowed`（拾物，D 需求「联系对方」唯一门控）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

utcnow = lambda: datetime.now(timezone.utc)


class LostItem(Base):
    """失物信息表。"""

    __tablename__ = "lost_item"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    publisher_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("category.id", ondelete="RESTRICT"),
        nullable=True,
    )
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # v3 新增：结构化标签（视觉 label + 颜色词 + 地点词，保序去重）
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # v3 新增：首图感知哈希（16-hex），用于照片相似度匹配；缺失为 NULL
    image_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # v8 新增：外观描述（材质/形状/颜色自由文本，逗号分隔），用于外观维度匹配
    appearance: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # v8 新增：特征描述（品牌/数量/特殊标记自由文本，逗号分隔），用于特征维度匹配
    features: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # v8 新增：地点描述（自由文本），用于地点维度模糊匹配
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lost_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # R3：非必填（迁移 0006 改可空）
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0 待匹配/1 匹配中/2 待认领/3 已解决
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    # v7 新增：失效时间（有效期 = 发布时间 + 90 天）。模型级默认即 utcnow()+90d。
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=lambda: utcnow() + timedelta(days=90)
    )
    # v7 新增：软删时间（用户侧删除置此字段，物理删除因 RESTRICT 外键被禁止）。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_lost_cat_status", "category_id", "status"),
        Index("idx_lost_expires", "expires_at"),
        Index("idx_lost_deleted", "deleted_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LostItem id={self.id} title={self.title!r} status={self.status}>"


class FoundItem(Base):
    """拾物信息表。"""

    __tablename__ = "found_item"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    finder_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("category.id", ondelete="RESTRICT"),
        nullable=True,
    )
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    images: Mapped[list] = mapped_column(JSON, nullable=False)
    # v3 新增：结构化标签（视觉 label + 颜色词 + 地点词，保序去重）
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # v3 新增：首图感知哈希（16-hex），用于照片相似度匹配；缺失为 NULL
    image_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # v8 新增：外观描述（材质/形状/颜色自由文本，逗号分隔），用于外观维度匹配
    appearance: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # v8 新增：特征描述（品牌/数量/特殊标记自由文本，逗号分隔），用于特征维度匹配
    features: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # v8 新增：地点描述（自由文本），用于地点维度模糊匹配
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    found_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    keep_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 暂为保管 / 1 未保管
    contact_allowed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0 待认领 / 1 已解决
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    # v7 新增：失效时间（有效期 = 发布时间 + 90 天）。模型级默认即 utcnow()+90d。
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=lambda: utcnow() + timedelta(days=90)
    )
    # v7 新增：软删时间（用户侧删除置此字段，物理删除因 RESTRICT 外键被禁止）。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_found_cat_status", "category_id", "status"),
        Index("idx_found_expires", "expires_at"),
        Index("idx_found_deleted", "deleted_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FoundItem id={self.id} status={self.status}>"
