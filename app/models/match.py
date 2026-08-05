"""匹配记录与动态交接码表（§2.5 / §2.6）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

utcnow = lambda: datetime.now(timezone.utc)


class MatchRecord(Base):
    """匹配记录表。"""

    __tablename__ = "match_record"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    lost_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("lost_item.id", ondelete="RESTRICT"),
        nullable=False,
    )
    found_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("found_item.id", ondelete="RESTRICT"),
        nullable=False,
    )
    match_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0 待认领/1 认领中/2 已完成/3 已拒绝/4 待自取/5 已放弃/6 已撤回
    # v2 新增：完成方式标记（0=双向交接 keep0 / 1=keep1 单边「申请即完成」）；
    # 作为撤回动作的唯一门控（flow_type==1 && status==2 可撤回）。
    flow_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    claim_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    code_expire: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    # v7 新增：完成时间（完成交接时置此字段，并据以重置关联双方的 expires_at）。
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_match_lost", "lost_id"),
        Index("idx_match_found", "found_id"),
        Index("idx_match_status", "status"),
        Index("idx_match_completed", "completed_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MatchRecord id={self.id} score={self.match_score} status={self.status}>"


class HandoverCode(Base):
    """动态交接码审计镜像表（§2.6，MVP 用 DB 存储 + expire_at 判定替代 Redis）。"""

    __tablename__ = "handover_code"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("match_record.id", ondelete="RESTRICT"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    code: Mapped[str] = mapped_column(String(12), nullable=False)
    qr_token: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0 有效/1 已验证/2 已过期
    verified_by_lost: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by_finder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gps_lost: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gps_finder: Mapped[str | None] = mapped_column(String(50), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expire_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("uq_handover_match_seq", "match_id", "seq", unique=True),
        Index("idx_handover_code", "code"),
        Index("idx_handover_status", "status"),
        Index("idx_handover_expire", "expire_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HandoverCode id={self.id} match_id={self.match_id} code={self.code!r}>"
