"""v7 软删测试：``DELETE /items/{id}`` 置 ``deleted_at``（非物理删、非置 status=RESOLVED）。

- 软删后列表不可见（list_lost / list_found / my_items 均过滤 deleted_at）
- 软删不破坏 FK（被匹配引用的物品软删后，匹配记录仍在）
- 软删保留拒绝进行中匹配逻辑
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from conftest import API, PNG, auth_header, register_and_login  # noqa: E402

from app.models.item import FoundItem, LostItem  # noqa: E402
from app.models.match import MatchRecord  # noqa: E402


def _publish_lost(client, token, title="失物", desc="丢失"):
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={"title": title, "description": desc, "category_name": "书包", "appearance": "黑色", "lost_time": "2026-07-16T10:00:00"},
        files={"images": ("l.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def _publish_found(client, token, desc="捡到"):
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={"keep_status": "0", "category_name": "书包", "description": desc, "appearance": "黑色", "contact_allowed": "1"},
        files={"images": ("f.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def test_soft_delete_sets_deleted_at(client, db):
    token, _, _, _, _ = register_and_login(client, "sd1")
    lid = _publish_lost(client, token)
    r = client.delete(f"{API}/lost-items/{lid}", headers=auth_header(token))
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["deleted_at"] is not None, "软删应置 deleted_at"
    # DB 行仍在（非物理删）
    li = db.get(LostItem, lid)
    assert li is not None
    assert li.deleted_at is not None
    assert li.status != 3, "软删不应置 status=RESOLVED（已解决由完成交接产生）"


def test_soft_deleted_hidden_from_list(client, db):
    token, _, _, _, _ = register_and_login(client, "sd2")
    lid = _publish_lost(client, token)
    client.delete(f"{API}/lost-items/{lid}", headers=auth_header(token))
    r = client.get(f"{API}/lost-items?page_size=100", headers=auth_header(token))
    assert r.status_code == 200
    assert lid not in [it["id"] for it in r.json()["data"]["items"]]


def test_soft_deleted_hidden_from_my_items(client, db):
    token, _, _, _, _ = register_and_login(client, "sd3")
    lid = _publish_lost(client, token)
    client.delete(f"{API}/lost-items/{lid}", headers=auth_header(token))
    r = client.get(f"{API}/users/me/items", headers=auth_header(token))
    assert r.status_code == 200
    lost = r.json()["data"]["lost"]
    assert lid not in [it["id"] for it in lost]


def test_soft_delete_keeps_match_fk(client, db):
    """软删被匹配引用的物品不破坏 FK：匹配记录仍在。"""
    token_a, _, _, _, _ = register_and_login(client, "sd4a")
    token_b, _, _, _, _ = register_and_login(client, "sd4b")
    lid = _publish_lost(client, token_a)
    _publish_found(client, token_b)
    r = client.get(f"{API}/lost-items/{lid}/matches", headers=auth_header(token_a))
    matches = r.json()["data"]
    assert matches, "应自动生成匹配"
    mid = matches[0]["id"]
    # 软删失物（仍被匹配引用）
    client.delete(f"{API}/lost-items/{lid}", headers=auth_header(token_a))
    # 匹配记录仍在（FK 未被破坏，RESTRICT 约束满足）
    m = db.get(MatchRecord, mid)
    assert m is not None
    assert m.lost_id == lid


def test_soft_delete_rejects_pending_match(client, db):
    """软删失物应拒绝其待处理匹配（PENDING_CLAIM/CLAIMING → REJECTED=3）。"""
    token_a, _, _, _, _ = register_and_login(client, "sd5a")
    token_b, _, _, _, _ = register_and_login(client, "sd5b")
    lid = _publish_lost(client, token_a)
    _publish_found(client, token_b)
    r = client.get(f"{API}/lost-items/{lid}/matches", headers=auth_header(token_a))
    mid = r.json()["data"][0]["id"]
    # 认领中（status 0 → 1）
    client.post(f"{API}/matches/{mid}/claim", headers=auth_header(token_a), json={"claim_reason": "是我的"})
    # 软删失物
    client.delete(f"{API}/lost-items/{lid}", headers=auth_header(token_a))
    m = db.get(MatchRecord, mid)
    assert m.status == 3, "软删应拒绝待处理匹配（status=3 REJECTED）"


def test_manual_match_rejects_soft_deleted_found_item(client, db):
    """v7（工程师收尾修复③）：拾物已软删则手动匹配被拒（422），且不生成匹配。"""
    token_a, _, _, _, _ = register_and_login(client, "sd6a")
    token_b, _, _, _, _ = register_and_login(client, "sd6b")
    lid = _publish_lost(client, token_a)
    fid = _publish_found(client, token_b)
    # 拾得者软删拾物
    rdel = client.delete(f"{API}/found-items/{fid}", headers=auth_header(token_b))
    assert rdel.status_code == 200, rdel.text
    rm = client.post(f"{API}/matches/manual", headers=auth_header(token_a), json={"lost_id": lid, "found_id": fid})
    assert rm.status_code == 422, rm.text
    assert rm.json()["code"] == 9001
    # 不应生成手动匹配（status=4）
    matches = db.query(MatchRecord).filter(MatchRecord.lost_id == lid, MatchRecord.found_id == fid).all()
    assert not any(int(m.status) == 4 for m in matches), "软删拾物不应生成手动匹配(status=4)"


def test_manual_match_rejects_soft_deleted_lost_item(client, db):
    """v7（工程师收尾修复③）：失物已软删则手动匹配被拒（422），且不生成匹配。"""
    token_a, _, _, _, _ = register_and_login(client, "sd7a")
    token_b, _, _, _, _ = register_and_login(client, "sd7b")
    lid = _publish_lost(client, token_a)
    fid = _publish_found(client, token_b)
    # 失主软删自己的失物
    rdel = client.delete(f"{API}/lost-items/{lid}", headers=auth_header(token_a))
    assert rdel.status_code == 200, rdel.text
    rm = client.post(f"{API}/matches/manual", headers=auth_header(token_a), json={"lost_id": lid, "found_id": fid})
    assert rm.status_code == 422, rm.text
    assert rm.json()["code"] == 9001
    matches = db.query(MatchRecord).filter(MatchRecord.lost_id == lid, MatchRecord.found_id == fid).all()
    assert not any(int(m.status) == 4 for m in matches), "软删失物不应生成手动匹配(status=4)"
