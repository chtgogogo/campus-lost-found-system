"""用户表与信誉流水账（§2.1 / §2.9）。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

utcnow = lambda: datetime.now(timezone.utc)


class User(Base):
    """用户表。"""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    student_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    real_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0 普通 / 1 管理员
    credit_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0 正常 / 1 封禁
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("idx_user_role", "role"),
        Index("idx_user_status", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} student_no={self.student_no!r}>"


class TrustScoreLog(Base):
    """信誉流水账（§2.9）。"""

    __tablename__ = "trust_score_log"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    ref_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("idx_trust_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TrustScoreLog id={self.id} user_id={self.user_id} delta={self.delta}>"
