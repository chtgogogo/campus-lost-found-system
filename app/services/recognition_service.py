"""异步识别任务入队服务（v17④）。

发布路径只调用 ``enqueue_yolo`` / ``enqueue_clip`` 两个函数；消费在
``app/services/recognition_worker.py``（单线程 worker）。

幂等语义（执行指令④验收项「同哈希重复提交只识别一次」）：
- 首图 SHA-256 相同 → 全库只有一条**主任务**（file_hash 落唯一索引）会真正执行 YOLO 推理；
- 同哈希的后续发布各拿一条**子任务**（parent_id 指向主任务，file_hash=NULL，
  唯一索引允许多 NULL），worker 处理子任务时从主任务**复制结果**（无推理）：
  - 主任务已完成 → 子任务入队即完成（结果同步复制，发布响应立即可用）；
  - 主任务进行中 → 子任务置 pending，等 worker 轮到时复制。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.recognition import RecognitionTask
from app.schemas.common import RecognitionStatus


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue_yolo(db: Session, item_type: str, item_id: int, file_hash: str | None) -> RecognitionTask:
    """为发布物品入队 YOLO 识别任务（同事务调用方 commit）。

    Args:
        item_type: "lost" / "found"。
        file_hash: 首图 SHA-256；无图时为 None（仍入队，worker 直接以降级结果收尾——
            与视觉服务「无权重降级」同口径）。

    Returns:
        本物品自己的任务行（主任务或子任务，publish 响应据此展示「识别中」）。
    """
    primary: RecognitionTask | None = None
    if file_hash:
        primary = (
            db.query(RecognitionTask)
            .filter(
                RecognitionTask.task_type == "yolo",
                RecognitionTask.file_hash == file_hash,
                RecognitionTask.parent_id.is_(None),
            )
            .one_or_none()
        )

    if primary is not None and primary.status == int(RecognitionStatus.DONE):
        # 同图已识别过：子任务入队即完成，物品立即获得识别结果（零推理）
        task = RecognitionTask(
            task_type="yolo",
            status=int(RecognitionStatus.DONE),
            parent_id=primary.id,
            item_type=item_type,
            item_id=item_id,
            result_category_id=primary.result_category_id,
            result_label=primary.result_label,
            result_confidence=primary.result_confidence,
            finished_at=_now(),
        )
    elif primary is not None:
        # 同图识别中：挂子任务排队，worker 在主任务完成后复制结果
        task = RecognitionTask(
            task_type="yolo",
            status=int(RecognitionStatus.PENDING),
            parent_id=primary.id,
            item_type=item_type,
            item_id=item_id,
        )
    else:
        task = RecognitionTask(
            task_type="yolo",
            status=int(RecognitionStatus.PENDING),
            file_hash=file_hash,
            item_type=item_type,
            item_id=item_id,
        )
    db.add(task)
    db.flush()
    return task


def enqueue_clip(db: Session, match_ids: list[int]) -> RecognitionTask:
    """CLIP 精排入队（v17④：取代 FastAPI BackgroundTasks——进程重启不再丢任务）。"""
    task = RecognitionTask(
        task_type="clip",
        status=int(RecognitionStatus.PENDING),
        payload=json.dumps({"match_ids": [int(m) for m in match_ids]}),
    )
    db.add(task)
    db.commit()
    return task
