"""v20③ 定时维护 worker 测试（2026-09-28）。

覆盖：过期 IM 会话+消息清理（既有 purge_expired_im 死代码激活）、
终态识别任务瘦身（旧的删 / 新的留 / pending 永不删）、
孤儿图片移回收目录（被引用不动 / 宽限期内不动）、幂等性。
线程循环本身不起（conftest 已 MAINTENANCE_ENABLED=false，单测直调 run_maintenance）。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import register_and_login

from app.models.im import IMMessage, IMSession
from app.models.item import LostItem
from app.models.recognition import RecognitionTask
from app.services.maintenance_worker import run_maintenance


def _naive_utc(days: float) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch):
    from app.core.config import settings

    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(d))
    return d


def _mk_im_session(db, lost_uid, finder_uid, expires_at) -> int:
    s = IMSession(lost_user_id=lost_uid, finder_user_id=finder_uid,
                  status=0, expires_at=expires_at, created_at=_naive_utc(40))
    db.add(s)
    db.flush()
    db.add(IMMessage(session_id=s.id, sender_id=lost_uid, sender_role=0, content="你好"))
    db.commit()
    return s.id


def test_purge_expired_im_sessions(client, db, upload_dir):
    token_a, _, _, _, uid_a = register_and_login(client, "mta")
    _, _, _, _, uid_b = register_and_login(client, "mtb")
    expired_id = _mk_im_session(db, uid_a, uid_b, expires_at=_naive_utc(1))
    alive_id = _mk_im_session(db, uid_a, uid_b, expires_at=_naive_utc(-30))  # 未来 30 天过期

    result = run_maintenance(db)

    assert result["purged_im_sessions"] == 1
    assert db.query(IMSession).filter(IMSession.id == expired_id).count() == 0
    assert db.query(IMMessage).filter(IMMessage.session_id == expired_id).count() == 0
    assert db.query(IMSession).filter(IMSession.id == alive_id).count() == 1


def _mk_task(db, status: int, finished_days_ago: float | None) -> int:
    t = RecognitionTask(task_type="vision", status=status,
                        created_at=_naive_utc(60), updated_at=_naive_utc(1),
                        finished_at=_naive_utc(finished_days_ago) if finished_days_ago is not None else None)
    db.add(t)
    db.commit()
    return t.id


def test_recognition_task_pruning(client, db, upload_dir):
    old_done = _mk_task(db, 2, 40)      # 终态 + 超 30 天 → 删
    new_done = _mk_task(db, 2, 1)       # 终态 + 1 天前 → 留
    old_pending = _mk_task(db, 0, None) # pending 永不删（防丢任务）

    result = run_maintenance(db)

    assert result["deleted_recognition_tasks"] == 1
    assert db.query(RecognitionTask).filter(RecognitionTask.id == old_done).count() == 0
    assert db.query(RecognitionTask).filter(RecognitionTask.id.in_([new_done, old_pending])).count() == 2


def test_orphan_files_moved_to_trash(client, db, upload_dir):
    token, _, _, _, uid = register_and_login(client, "mto")
    db.add(LostItem(publisher_id=uid, category_id=1, category_name="手机", title="x",
                    description="", tags=["手机"], images=["/uploads/referenced.png"], status=0))
    db.commit()

    referenced = upload_dir / "referenced.png"
    referenced.write_bytes(b"keep")
    fresh_orphan = upload_dir / "fresh.png"
    fresh_orphan.write_bytes(b"too new")
    old_orphan = upload_dir / "old.png"
    old_orphan.write_bytes(b"orphan")
    week_ago = datetime.now().timestamp() - 8 * 86400
    os.utime(old_orphan, (week_ago, week_ago))  # mtime 拨回 8 天前（超 7 天宽限）

    result = run_maintenance(db)

    assert result["trashed_orphan_files"] == 1
    assert referenced.exists() and fresh_orphan.exists()
    assert not old_orphan.exists()
    trash = Path(upload_dir).parent / "uploads_trash"
    assert (trash / old_orphan.name).exists() or any(trash.rglob(old_orphan.name))


def test_run_maintenance_idempotent(client, db, upload_dir):
    token, _, _, _, uid = register_and_login(client, "mti")
    orphan = upload_dir / "gone.png"
    orphan.write_bytes(b"x")
    week_ago = datetime.now().timestamp() - 8 * 86400
    os.utime(orphan, (week_ago, week_ago))

    first = run_maintenance(db)
    second = run_maintenance(db)

    assert first["trashed_orphan_files"] == 1
    assert second["trashed_orphan_files"] == 0
    assert second["purged_im_sessions"] == 0
    assert second["deleted_recognition_tasks"] == 0
