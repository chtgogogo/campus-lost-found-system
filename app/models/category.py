"""物品分类表（§2.2）。"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Index, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Category(Base):
    """物品分类（含识别模式 / YOLO 提示词）。"""

    __tablename__ = "category"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    yolo_class_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recognition_mode: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0=COCO / 1=YOLO-World
    yolo_prompt: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True
    )
    is_active: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    __table_args__ = (
        Index("idx_category_name", "name"),
        Index("idx_category_parent", "parent_id"),
        Index("idx_category_active", "is_active"),
        Index("idx_category_mode", "recognition_mode"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Category id={self.id} name={self.name!r}>"
