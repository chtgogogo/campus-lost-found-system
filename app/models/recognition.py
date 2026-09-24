"""异步识别任务表（v17④ 识别链路异步化）。

发布接口不再同步执行 YOLO 推理：落库物品 → 写本表 → 立即返回「识别中」；
由后台单线程 worker（app/services/recognition_worker.py）消费。

幂等设计（file_hash 唯一索引）：
- 视觉识别结果只取决于图片字节，故 file_hash = 首图 SHA-256，**同一张图全库只跑一次推理**；
- 每次发布都会拿到自己的任务行：首发 = 主任务（parent_id 为空、file_hash 落唯一索引）；
  同哈希重复发布 = 子任务（parent_id 指向主任务、file_hash 为 NULL——SQLite/MySQL 唯一索引
  均允许多个 NULL），worker 处理子任务时从主任务复制结果，不再推理；
- CLIP 精排任务（task_type="clip"）同样入本表，取代 FastAPI BackgroundTasks
  （进程重启即丢）——payload 存 match_ids，file_hash 为 NULL。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schemas.common import RecognitionStatus


def utcnow() -> datetime:
    """朴素 UTC 当前时间（与项目其他表口径一致）。"""
    from datetime import timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


class RecognitionTask(Base):
    """异步识别任务（yolo 主/子任务 + clip 精排任务）。"""

    __tablename__ = "recognition_task"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    # 任务类型：yolo（物品识别）/ clip（候选精排）
    task_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=int(RecognitionStatus.PENDING))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ---- 幂等键：主任务存首图 SHA-256（唯一索引）；子任务/clip 任务为 NULL ----
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 子任务引用同哈希主任务：复制结果，不重复推理
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True
    )

    # ---- yolo 任务的归属物品 ----
    item_type: Mapped[str | None] = mapped_column(String(8), nullable=True)   # lost / found
    item_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True
    )

    # ---- clip 任务的参数（JSON：{"match_ids": [...]}） ----
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 主任务的推理结果缓存（子任务复制用） ----
    result_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("uq_recognition_file_hash", "file_hash", unique=True),
        Index("idx_recognition_status", "status"),
        Index("idx_recognition_item", "item_type", "item_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RecognitionTask id={self.id} type={self.task_type} status={self.status} "
            f"parent={self.parent_id} retry={self.retry_count}>"
        )
