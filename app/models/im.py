"""IM 会话与消息表（§2.7 / §2.8，P1 增量复用）。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

utcnow = lambda: datetime.now(timezone.utc)


class IMSession(Base):
    """IM 会话表。"""

    __tablename__ = "im_session"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    match_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("match_record.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # v4：无 match 的「联系」会话绑定到具体拾物，强溯源 + 发送端二次门控
    found_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("found_item.id", ondelete="RESTRICT"),
        nullable=True,
    )
    lost_user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    finder_user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0 开启 / 1 关闭
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_im_match", "match_id"),
        # 注意：found_id 索引由迁移 0003 显式创建（名为 ix_im_found），
        # 此处保持 idx_im_found 以与 0001 建表一致，避免与 0003 重复建同名列上索引。
        Index("idx_im_found", "found_id"),
        Index("idx_im_lost", "lost_user_id"),
        Index("idx_im_finder", "finder_user_id"),
        Index("idx_im_status", "status"),
        Index("idx_im_expires", "expires_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IMSession id={self.id} match_id={self.match_id}>"


class IMMessage(Base):
    """IM 消息表。"""

    __tablename__ = "im_message"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("im_session.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sender_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sender_role: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 失主 / 1 拾得者
    content_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # 0 文字 / 1 预设模板
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("idx_im_msg_session_sent", "session_id", "sent_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IMMessage id={self.id} session_id={self.session_id}>"
