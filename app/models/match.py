"""匹配记录与动态交接码表（§2.5 / §2.6）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    DateTime,
    Float,
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
    # 2026-08-27（CLIP 两阶段精排）：图片相似度（0-1），NULL=未精排/CLIP 不可用。
    # 精排不改变 match_score（总分语义与阈值不变），仅作为列表**同分打破平局**的次排序键。
    clip_sim: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("idx_match_lost", "lost_id"),
        Index("idx_match_found", "found_id"),
        Index("idx_match_status", "status"),
        Index("idx_match_completed", "completed_at"),
        Index("idx_match_clip", "clip_sim"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MatchRecord id={self.id} score={self.match_score} status={self.status}>"


class HandoverCode(Base):
    """动态交接码审计镜像表（双码交叉验证模型，§2.6）。

    失主生成 lost_code（4位数字，10s 过期）；拾得者生成 finder_code（4位数字，10s 过期）。
    拾得者输入失主的码 → lost_code_verified=True（证明是授权领取人）；
    失主输入拾得者的码 → finder_code_verified=True（确认物品已收到）。
    双方交叉验证通过 → 交接完成。
    """

    __tablename__ = "handover_code"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("match_record.id", ondelete="RESTRICT"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    # ---- 双码（各自4位数字，独立生成、独立10s过期） ----
    lost_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    finder_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    lost_code_expire: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finder_code_expire: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ---- 交叉验证标记 ----
    # lost_code_verified = 拾得者已正确输入失主的码（证明自己是授权领取人）
    lost_code_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # finder_code_verified = 失主已正确输入拾得者的码（确认物品已交到自己手中）
    finder_code_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ---- 行级状态 ----
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0 有效/1 已验证/2 已过期

    # ---- GPS（验证时记录） ----
    gps_lost: Mapped[str | None] = mapped_column(String(50), nullable=True)   # 失主验证时（输入拾得者码）的GPS
    gps_finder: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 拾得者验证时（输入失主码）的GPS

    # ---- 审计时间 ----
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("uq_handover_match_seq", "match_id", "seq", unique=True),
        Index("idx_handover_lost_code", "lost_code"),
        Index("idx_handover_finder_code", "finder_code"),
        Index("idx_handover_status", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HandoverCode id={self.id} match_id={self.match_id} seq={self.seq}>"
