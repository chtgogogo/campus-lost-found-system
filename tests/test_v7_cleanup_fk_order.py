"""v7 周期清理依赖序测试。

- 超 1 年（双方 expires_at < now-270d）的匹配按 IMSession→MatchRecord→Item 依赖序物理清理，
  不破坏 RESTRICT FK（物品仍被匹配引用时不会被提前删）。
- 未超期数据不被清理。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from conftest import API, PNG, auth_header, register_and_login  # noqa: E402

from app.models.im import IMMessage, IMSession  # noqa: E402
from app.models.item import FoundItem, LostItem  # noqa: E402
from app.models.match import MatchRecord  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.cleanup import CleanupService  # noqa: E402


def _utcnow() -> datetime:
    return datetime.utcnow()


def _publish_pair(client, ta, tb, lost_title, found_desc):
    # 失物走纯文字（不附图）：测试环境视觉桩对所有图片一律识别为「钥匙」，
    # 失物附图会与拾物（附图同样含「钥匙」）共享名词 tag，在新 top10 含低分行为下
    # 自动生成低分候选 → manual 会被 409 拒绝，无法创建 status=4 供清理流程。
    rl = client.post(
        f"{API}/lost-items",
        headers=auth_header(ta),
        data={"title": lost_title, "description": "desc", "category_name": "书包", "lost_time": "2026-07-16T10:00:00"},
    )
    lid = rl.json()["data"]["item"]["id"]
    rf = client.post(
        f"{API}/found-items",
        headers=auth_header(tb),
        data={"keep_status": "1", "category_name": "水杯", "description": found_desc, "contact_allowed": "1"},
        files={"images": ("f.png", PNG, "image/png")},
    )
    fid = rf.json()["data"]["item"]["id"]
    rm = client.post(f"{API}/matches/manual", headers=auth_header(ta), json={"lost_id": lid, "found_id": fid})
    assert rm.status_code == 200, rm.text
    return lid, fid, rm.json()["data"]["id"]


def test_cleanup_purges_old_match_in_dependency_order(client, db):
    token_a, _, _, _, _ = register_and_login(client, "cl_a")
    token_b, _, _, _, _ = register_and_login(client, "cl_b")
    lid, fid, mid = _publish_pair(client, token_a, token_b, "清理测试失物", "捡到水杯")

    # IM 会话 + 消息
    rs = client.post(f"{API}/im/sessions", headers=auth_header(token_a), json={"match_id": mid})
    assert rs.status_code == 200, rs.text
    sid = rs.json()["data"]["id"]
    client.post(f"{API}/im/sessions/{sid}/messages", headers=auth_header(token_a), json={"content": "清理对话"})

    # 双方 expires_at 设为 1 年前（超出留存窗）→ 应被清理
    lost = db.get(LostItem, lid)
    found = db.get(FoundItem, fid)
    old = _utcnow() - timedelta(days=400)
    lost.expires_at = old
    found.expires_at = old
    db.commit()

    result = CleanupService(db).run_once()
    assert result["purged_matches"] >= 1

    # 依赖序：IMMessage → IMSession → MatchRecord 均被清理
    db.expire_all()
    assert db.get(MatchRecord, mid) is None
    assert db.get(IMSession, sid) is None
    assert db.query(IMMessage).filter(IMMessage.session_id == sid).count() == 0
    # 物品随后被清理（无剩余引用）
    assert db.get(LostItem, lid) is None
    assert db.get(FoundItem, fid) is None


def test_cleanup_keeps_recent_data(client, db):
    token_a, _, _, _, _ = register_and_login(client, "cl2_a")
    token_b, _, _, _, _ = register_and_login(client, "cl2_b")
    lid, fid, mid = _publish_pair(client, token_a, token_b, "近期失物", "近期捡到水杯")

    # 未过期（默认 now+90d）→ 不应被清理
    result = CleanupService(db).run_once()
    assert result["purged_matches"] == 0
    db.expire_all()
    assert db.get(MatchRecord, mid) is not None
    assert db.get(LostItem, lid) is not None
    assert db.get(FoundItem, fid) is not None
