"""v20③ 定时维护 worker（此前全项目零定时任务，清理全靠管理员手动）。

每天一次，做三件事（详见 CHANGELOG v20③）：
1. 激活既有死代码 ``purge_expired_im``——过期 IM 会话/消息物理删除（审计日志保留）；
2. 识别任务表瘦身——终态（完成/失败）且 ``finished_at`` 超过保留期的 RecognitionTask 删除；
3. 孤儿图片回收——uploads 里不被任何物品引用、且最后修改超过宽限期的文件，
   移入 ``uploads_trash/<日期>/``（可人工恢复，不直接删，防误杀）。

明确不做：audit_log 不在定时清理范围——审计是取证链，只随管理员手动
CleanupService 流程处置；运维可另用 scripts/backup.py 定期备份后自行归档。

实现与 recognition_worker 同模式（常驻 daemon 线程 + stop event），
零新增第三方依赖；测试套件经 conftest 的 MAINTENANCE_ENABLED=false 关闭。
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.item import FoundItem, LostItem
from app.models.recognition import RecognitionTask
from app.schemas.common import RecognitionStatus
from app.services.im_service import purge_expired_im

logger = logging.getLogger("maintenance")

_thread: threading.Thread | None = None
_stop = threading.Event()

# 终态集合：完成(2) / 失败(3)
_TERMINAL_STATUSES = (int(RecognitionStatus.DONE), int(RecognitionStatus.FAILED))


def _utcnow_naive() -> datetime:
    """朴素 UTC（与库内时间列口径一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _referenced_filenames(db: Session) -> set[str]:
    """当前全部物品（含软删，保守起见）引用的图片文件名集合。"""
    names: set[str] = set()
    for row in db.query(LostItem.images).all():
        for u in row[0] or []:
            names.add(str(u).rsplit("/", 1)[-1])
    for row in db.query(FoundItem.images).all():
        for u in row[0] or []:
            names.add(str(u).rsplit("/", 1)[-1])
    return names


def collect_orphan_uploads(db: Session, upload_dir: Path | None = None,
                           now: datetime | None = None) -> list[Path]:
    """返回可回收的孤儿文件列表（只算账不动手，便于测试与 dry-run）。"""
    up = Path(upload_dir or settings.UPLOAD_DIR)
    if not up.is_dir():
        return []
    referenced = _referenced_filenames(db)
    cutoff = (now or _utcnow_naive()) - timedelta(days=settings.ORPHAN_FILE_GRACE_DAYS)
    orphans: list[Path] = []
    for p in sorted(up.iterdir()):
        if not p.is_file():
            continue
        if p.name in referenced:
            continue
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).replace(tzinfo=None)
        if mtime >= cutoff:  # 宽限期内的新文件不碰（可能是刚上传、事务未落库）
            continue
        orphans.append(p)
    return orphans


def run_maintenance(db: Session, now: datetime | None = None) -> dict:
    """执行一轮维护，返回计数摘要（幂等，可安全重复调用）。"""
    now = now or _utcnow_naive()
    result: dict = {"purged_im_sessions": 0, "deleted_recognition_tasks": 0,
                    "trashed_orphan_files": 0, "now": now.isoformat()}

    # 1) 过期 IM 会话（既有函数，此前零调用）
    result["purged_im_sessions"] = purge_expired_im(db, now=now)
    db.commit()

    # 2) 终态识别任务瘦身
    cutoff = now - timedelta(days=settings.RECOGNITION_TASK_RETENTION_DAYS)
    del_res = db.execute(
        delete(RecognitionTask).where(
            RecognitionTask.status.in_(_TERMINAL_STATUSES),
            RecognitionTask.finished_at.isnot(None),
            RecognitionTask.finished_at < cutoff,
        )
    )
    result["deleted_recognition_tasks"] = del_res.rowcount or 0
    db.commit()

    # 3) 孤儿图片移入回收目录（可恢复）
    trash_root = Path(settings.UPLOAD_DIR).parent / "uploads_trash" / now.strftime("%Y%m%d")
    for p in collect_orphan_uploads(db, now=now):
        trash_root.mkdir(parents=True, exist_ok=True)
        target = trash_root / p.name
        if target.exists():
            continue  # 同名已回收（uuid 文件名下几乎不可能），跳过防覆盖
        shutil.move(str(p), str(target))
        result["trashed_orphan_files"] += 1

    if any(result[k] for k in ("purged_im_sessions", "deleted_recognition_tasks", "trashed_orphan_files")):
        logger.info("[maintenance] im=%d tasks=%d orphans=%d",
                    result["purged_im_sessions"], result["deleted_recognition_tasks"],
                    result["trashed_orphan_files"])
    return result


def start(initial_delay_s: float = 120.0) -> None:
    """应用启动入口：延迟首跑（避开启动高峰），此后每 MAINTENANCE_INTERVAL_HOURS 一轮。"""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    interval_s = max(1, settings.MAINTENANCE_INTERVAL_HOURS) * 3600

    def _loop() -> None:
        if _stop.wait(initial_delay_s):
            return
        while True:
            try:
                with SessionLocal() as db:
                    run_maintenance(db)
            except Exception:  # noqa: BLE001 维护线程不因单轮失败退出
                logger.exception("[maintenance] 本轮维护异常，下轮重试")
            if _stop.wait(interval_s):
                return

    _thread = threading.Thread(target=_loop, name="maintenance-worker", daemon=True)
    _thread.start()
    logger.info("[maintenance] 已启动（首跑延迟 %.0fs，间隔 %dh）", initial_delay_s,
                settings.MAINTENANCE_INTERVAL_HOURS)


def stop() -> None:
    """应用关闭入口：置停机位（daemon 线程随进程退出）。"""
    _stop.set()
