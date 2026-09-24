"""异步识别 worker（v17④）：单线程消费 recognition_task。

设计口径（诚实规模）：
- **单线程**是有意选择：SQLite 单写者，校园单机部署不装多 worker/分布式；
  并发安全由「条件 UPDATE 原子领取」保证——即使未来起多进程，同一条任务也只会被
  领取一次（执行指令④验收项「并发消费不重复执行」的机制基础）。
- 重试：异常 → retry_count+1 重新排队；达 ``settings.RECOGNITION_MAX_RETRIES`` →
  failed 死信（error 可查，物品 recognize_status 同步置 FAILED）。
- 崩溃恢复：进程重启时把遗留的 running 任务重置为 pending（``recover_stale_running``），
  单线程模型下「启动时还在 running」必然是上次崩溃的残留。
- 子任务（同哈希重复发布）：等主任务完成后复制结果，不重复推理；主任务还没跑完时
  本轮跳过（``_RetryLater``，不消耗重试次数）。
- CLIP 精排任务与 YOLO 同队列串行：torch 模型加载从此只发生在这一个线程，
  消除主线程 YOLO × 后台线程 CLIP 并发 load 的 Windows 段错误竞态（v17② 实录）。
"""
from __future__ import annotations

import json
import logging
import os
import threading

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.item import FoundItem, LostItem
from app.models.recognition import RecognitionTask, utcnow
from app.schemas.common import RecognitionStatus
from app.services.clip_reorder import reorder_match_ids
from app.services.publish_service import PublishService
from app.services.vision_service import get_vision_service

logger = logging.getLogger("recognition_worker")

_stop = threading.Event()
_thread: threading.Thread | None = None


class _RetryLater(Exception):
    """内部信号：本轮跳过（如子任务等主任务），不消耗重试次数、不算失败。"""


# ---------------- 领取 / 恢复 ----------------

def claim_next(db: Session) -> RecognitionTask | None:
    """原子领取下一条 pending 任务（FIFO）。

    先 SELECT 再**带状态条件的 UPDATE**：并发 claim 时只有一个调用方能让
    ``claimed`` 行数非 0，其余拿到 None —— 任务不会被执行两次。
    """
    task = (
        db.query(RecognitionTask)
        .filter(RecognitionTask.status == int(RecognitionStatus.PENDING))
        .order_by(RecognitionTask.id)
        .first()
    )
    if task is None:
        return None
    claimed = (
        db.query(RecognitionTask)
        .filter(
            RecognitionTask.id == task.id,
            RecognitionTask.status == int(RecognitionStatus.PENDING),
        )
        .update({"status": int(RecognitionStatus.RUNNING), "started_at": utcnow()})
    )
    db.commit()
    return task if claimed else None


def recover_stale_running(db: Session) -> int:
    """把遗留的 running 任务重置为 pending（进程崩溃恢复）。返回重置条数。"""
    n = (
        db.query(RecognitionTask)
        .filter(RecognitionTask.status == int(RecognitionStatus.RUNNING))
        .update({"status": int(RecognitionStatus.PENDING), "started_at": None})
    )
    db.commit()
    return n


# ---------------- 执行 ----------------

def _load_item(db: Session, task: RecognitionTask):
    if task.item_type == "lost":
        return db.get(LostItem, task.item_id)
    return db.get(FoundItem, task.item_id)


def _read_first_image_bytes(image_urls) -> bytes | None:
    """按 /uploads/xxx 相对 URL 读首图字节（与 clip_reorder 同款实现口径）。"""
    if not image_urls:
        return None
    name = str(image_urls[0]).rsplit("/", 1)[-1]
    if not name:
        return None
    path = os.path.join(settings.UPLOAD_DIR, name)
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def _apply_to_item(db: Session, task: RecognitionTask, vision_result: dict) -> None:
    """把视觉结果回填到任务归属的物品（类目/标签/纠错样本/补匹配）并置 DONE。"""
    item = _load_item(db, task)
    if item is None:
        return  # 物品已被删除：任务照常完成，无处回填
    PublishService(db).apply_vision_result(task.item_type, item, vision_result)
    item.recognize_status = int(RecognitionStatus.DONE)


def _run_yolo(db: Session, task: RecognitionTask) -> None:
    if task.parent_id is not None:
        # 子任务：从主任务复制结果，绝不重复推理（幂等验收项）
        parent = db.get(RecognitionTask, task.parent_id)
        if parent is None:
            raise RuntimeError(f"主任务 {task.parent_id} 不存在")
        if parent.status == int(RecognitionStatus.DONE):
            vision_result = {
                "category_id": parent.result_category_id,
                "label": parent.result_label,
                "confidence": parent.result_confidence or 0.0,
            }
            task.result_category_id = parent.result_category_id
            task.result_label = parent.result_label
            task.result_confidence = parent.result_confidence
            _apply_to_item(db, task, vision_result)
            return
        if parent.status == int(RecognitionStatus.FAILED):
            # 主任务死信 → 子任务同样走重试/死信（不悄悄吞掉）
            raise RuntimeError(f"主任务 {parent.id} 失败: {(parent.error or '')[:200]}")
        raise _RetryLater()  # 主任务尚未完成：下轮再复制
    # 主任务：真实推理
    item = _load_item(db, task)
    if item is None:
        return  # 物品已被删除（如清理服务/用户撤销）：无事可做，任务按完成收尾，不进死信
    img = _read_first_image_bytes(item.images)
    vision_result = get_vision_service().predict(img or b"")
    task.result_category_id = vision_result.get("category_id")
    task.result_label = vision_result.get("label")
    task.result_confidence = float(vision_result.get("confidence") or 0.0)
    _apply_to_item(db, task, vision_result)


def _run_clip(db: Session, task: RecognitionTask) -> None:
    payload = json.loads(task.payload or "{}")
    reorder_match_ids(payload.get("match_ids") or [])


def process_task(db: Session, task_id: int) -> None:
    """执行单个任务；异常按重试上限走死信。``_RetryLater`` 静默回到队列。"""
    task = db.get(RecognitionTask, task_id)
    if task is None or task.status != int(RecognitionStatus.RUNNING):
        return
    try:
        if task.task_type == "clip":
            _run_clip(db, task)
        else:
            _run_yolo(db, task)
        task.status = int(RecognitionStatus.DONE)
        task.finished_at = utcnow()
        task.error = None
        db.commit()
    except _RetryLater:
        db.rollback()
    except Exception as exc:
        db.rollback()
        task = db.get(RecognitionTask, task_id)
        task.retry_count = int(task.retry_count or 0) + 1
        if task.retry_count >= settings.RECOGNITION_MAX_RETRIES:
            task.status = int(RecognitionStatus.FAILED)
            task.error = f"{type(exc).__name__}: {exc}"[:2000]
            task.finished_at = utcnow()
            item = _load_item(db, task)
            if item is not None:
                item.recognize_status = int(RecognitionStatus.FAILED)
            logger.error("任务 %s 重试耗尽进入死信: %s", task_id, task.error)
        else:
            task.status = int(RecognitionStatus.PENDING)  # 重新排队（单 worker FIFO，立即重试）
        db.commit()


# ---------------- 测试助手 / 后台线程 ----------------

def drain_all() -> int:
    """同步清空全部 pending 任务（单测直接驱动 worker，不经后台线程）。返回处理条数。"""
    processed = 0
    while True:
        with SessionLocal() as db:
            task = claim_next(db)
            if task is None:
                return processed
            process_task(db, task.id)
            processed += 1


def start(poll_interval: float = 1.0) -> None:
    """应用启动入口：先恢复遗留 running 任务，再起常驻单线程。"""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    with SessionLocal() as db:
        recovered = recover_stale_running(db)
    if recovered:
        logger.warning("[recognition-worker] 恢复 %d 个中断任务（上次进程退出遗留 running）", recovered)

    def _loop() -> None:
        while not _stop.is_set():
            try:
                with SessionLocal() as db:
                    task = claim_next(db)
                    if task is None:
                        _stop.wait(poll_interval)
                        continue
                    process_task(db, task.id)
            except Exception:  # pragma: no cover - 循环保活兜底
                logger.exception("[recognition-worker] 循环异常（继续运行）")
                _stop.wait(poll_interval)

    _thread = threading.Thread(target=_loop, name="recognition-worker", daemon=True)
    _thread.start()
    logger.info("[recognition-worker] 已启动（单线程，poll=%.1fs）", poll_interval)


def stop() -> None:
    """应用关闭入口：置停机位（daemon 线程随进程退出）。"""
    _stop.set()
