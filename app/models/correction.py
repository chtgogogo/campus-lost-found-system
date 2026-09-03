"""用户纠错样本（数据飞轮，2026-08-27 新增）。

发布时若用户**最终分类** ≠ 视觉预标 label（用户改掉了系统预填），记录该「纠正样本」。
攒够数据后可：① 微调 YOLO 分类器；② 统计高频误分类修正映射。

设计铁律：只加存储、不加任何推理逻辑；写入失败不影响发布（同事务内 try/except 吞掉）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

utcnow = lambda: datetime.now(timezone.utc)


class CorrectionSample(Base):
    """视觉预标 → 用户最终分类的纠错样本。"""

    __tablename__ = "correction_sample"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    item_type: Mapped[str] = mapped_column(String(10), nullable=False)  # lost / found
    item_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True
    )
    vision_label: Mapped[str | None] = mapped_column(String(64), nullable=True)  # YOLO 预标
    final_category_name: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 用户最终分类
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CorrectionSample id={self.id} {self.vision_label}→{self.final_category_name}>"
