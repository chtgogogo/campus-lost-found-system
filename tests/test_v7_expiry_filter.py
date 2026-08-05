"""v7 过期 / 失效过滤测试。

- 用户侧：``expires_at <= now`` 或 ``deleted_at`` 非空的物品在列表 / 我的发布中隐藏
- 管理侧：``GET /admin/matches`` 仅返回 ``expires_at + 270天 > now``（1 年留存窗）的匹配
- 完成重置：self-complete 后双方 ``expires_at`` 顺延 ~90 天
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from conftest import API, PNG, auth_header, register_and_login  # noqa: E402

from app.models.item import FoundItem, LostItem  # noqa: E402
from app.models.user import User  # noqa: E402


def _promote_to_admin(client, db):
    token, _, _, _, user_id = register_and_login(client, "adm_exp")
    u = db.get(User, user_id)
    u.role = 1
    db.commit()
    return token


def _publish_lost(client, token, title="失物", desc="丢失", with_image=True):
    files = {"images": ("l.png", PNG, "image/png")} if with_image else {}
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={"title": title, "description": desc, "category_name": "书包", "appearance": "黑色", "lost_time": "2026-07-16T10:00:00"},
        files=files,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def _publish_found(client, token, category="水杯", desc="捡到", appearance=None):
    data = {"keep_status": "0", "category_name": category, "description": desc, "contact_allowed": "1"}
    if appearance is not None:
        data["appearance"] = appearance
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data=data,
        files={"images": ("f.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def _utcnow() -> datetime:
    return datetime.utcnow()


def test_user_side_expired_item_hidden(client, db):
    token, _, _, _, _ = register_and_login(client, "ex1")
    lid = _publish_lost(client, token)
    li = db.get(LostItem, lid)
    li.expires_at = _utcnow() - timedelta(days=1)
    db.commit()
    r = client.get(f"{API}/lost-items?page_size=100", headers=auth_header(token))
    assert lid not in [it["id"] for it in r.json()["data"]["items"]]


def test_user_side_deleted_item_hidden(client, db):
    token, _, _, _, _ = register_and_login(client, "ex2")
    lid = _publish_lost(client, token)
    li = db.get(LostItem, lid)
    li.deleted_at = _utcnow()
    db.commit()
    r = client.get(f"{API}/lost-items?page_size=100", headers=auth_header(token))
    assert lid not in [it["id"] for it in r.json()["data"]["items"]]


def test_user_side_valid_item_visible(client, db):
    token, _, _, _, _ = register_and_login(client, "ex3")
    lid = _publish_lost(client, token)
    r = client.get(f"{API}/lost-items?page_size=100", headers=auth_header(token))
    assert lid in [it["id"] for it in r.json()["data"]["items"]]


def test_admin_side_retention_window(client, db):
    """管理后台仅返回处于 1 年留存窗（expires_at > now-270d）的匹配。"""
    admin = _promote_to_admin(client, db)
    token_a, _, _, _, _ = register_and_login(client, "ex4a")
    token_b, _, _, _, _ = register_and_login(client, "ex4b")
    lid = _publish_lost(client, token_a)
    fid = _publish_found(client, token_b, category="书包", appearance="黑色")  # 同目类 + 共享外观触发自动匹配

    r = client.get(f"{API}/lost-items/{lid}/matches", headers=auth_header(token_a))
    matches = r.json()["data"]
    assert matches, "应自动生成匹配"
    mid = matches[0]["id"]

    # 双方 expires_at 设为 1 年前（超出留存窗）→ 管理列表应隐藏
    lost = db.get(LostItem, lid)
    found = db.get(FoundItem, matches[0]["found_id"])
    old = _utcnow() - timedelta(days=400)
    lost.expires_at = old
    found.expires_at = old
    db.commit()

    r = client.get(f"{API}/admin/matches?page_size=100", headers=auth_header(admin))
    assert r.status_code == 200, r.text
    assert mid not in [it["id"] for it in r.json()["data"]["items"]]

    # 改回未过期 → 可见
    lost.expires_at = _utcnow() + timedelta(days=30)
    found.expires_at = _utcnow() + timedelta(days=30)
    db.commit()
    r2 = client.get(f"{API}/admin/matches?page_size=100", headers=auth_header(admin))
    assert mid in [it["id"] for it in r2.json()["data"]["items"]]


def test_completion_resets_expires_at(client, db):
    """self-complete 完成后，双方 expires_at 顺延 ~90 天（先置过期，验证被重置）。"""
    token_a, _, _, _, _ = register_and_login(client, "ex5a")
    token_b, _, _, _, _ = register_and_login(client, "ex5b")
    # 失物走纯文字（不附图）：测试环境视觉桩对所有图片一律识别为「钥匙」，
    # 失物附图会与拾物（附图同样含「钥匙」）共享名词 tag，在新 top10 含低分行为下
    # 自动生成低分候选 → manual 会被 409 拒绝，无法创建 status=4 供 self-complete。
    lid = _publish_lost(client, token_a, with_image=False)
    fid = _publish_found(client, token_b, category="水杯")  # 不同目类，避免自动匹配冲突

    # 先置过期，验证完成重置
    lost = db.get(LostItem, lid)
    lost.expires_at = _utcnow() - timedelta(days=10)
    db.commit()

    rm = client.post(f"{API}/matches/manual", headers=auth_header(token_a), json={"lost_id": lid, "found_id": fid})
    assert rm.status_code == 200, rm.text
    manual_id = rm.json()["data"]["id"]

    rc = client.post(f"{API}/matches/{manual_id}/self-complete", headers=auth_header(token_a), json={})
    assert rc.status_code == 200, rc.text
    assert rc.json()["data"]["status"] == 2

    db.expire_all()
    lost_after = db.get(LostItem, lid)
    found_after = db.get(FoundItem, fid)
    assert lost_after.expires_at is not None and lost_after.expires_at > _utcnow(), "失物 expires_at 应被重置到未来"
    assert found_after.expires_at is not None and found_after.expires_at > _utcnow(), "拾物 expires_at 应被重置到未来"

    from app.models.match import MatchRecord

    m = db.get(MatchRecord, manual_id)
    assert m.completed_at is not None, "完成匹配应写 completed_at"
