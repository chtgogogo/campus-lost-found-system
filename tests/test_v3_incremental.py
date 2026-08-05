"""v3 增量回归测试（需求 A–E）。

覆盖：
- 需求 D（联系对方 / IM）：门控（对端 contact_allowed==0 → 403）、禁链接（→ 422）、
  每条消息镜像 audit_log（action="im_message"）、轮询增量、参与者鉴权、门控双保险。
- 需求 E（我的发布）：GET /users/me/items 返回当前用户本人失物/拾物，且携带 v3 标签。
- 需求 B（自动标签）：发布时抽取结构化标签（颜色词 / 地点词）并随输出透传。

约定：复用 conftest 的 `client` / `db` fixtures 与 `register_and_login` / `PNG` helpers。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.models import AuditLog, FoundItem, MatchRecord

from conftest import API, PNG, auth_header, register_and_login


# ---------------- 本地 helper ----------------
def _publish_match(client, contact_allowed: int = 1):
    """发布失主 A 与拾得者 B 的同类目记录，B 的 contact_allowed 可控。

    flow-v3（修订 flow-v2 R2-a）：keep_status=1 拾物**单向**进池——可被失主侧正向召回，
    但永不为拾得者**反向**生成候选。本 helper 依赖反向自动匹配，故必须走 keep_status=0
    （暂为保管，强制 contact_allowed=1）以触发自动反向匹配；「关闭联系」门控场景
    由测试在 DB 中把 found.contact_allowed 置 0 复现（与 test_im_gate_double_check 同款手法）。

    返回 (token_a, token_b, match_id)。
    """
    token_a, _, _, _, _ = register_and_login(client, "va")
    token_b, _, _, _, _ = register_and_login(client, "vb")
    lost_time = datetime(2026, 7, 16, 10, 0, 0).isoformat()
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token_a),
        data={
            "title": "黑色书包",
            "description": "图书馆丢失黑色书包",
            "category_name": "书包",
            "lost_time": lost_time,
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token_b),
        data={
            "keep_status": "0",
            "description": "捡到黑色书包看起来像图书馆丢的",
            "category_name": "书包",
            "contact_allowed": "1",
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    matches = r.json()["data"]["suspected_matches"]
    assert matches, "拾物发布应触发反向匹配"
    match_id = matches[0]["id"]
    return token_a, token_b, match_id


# ================= 需求 D：IM 联系对方 =================
def test_im_session_allowed_when_contact_enabled(client):
    """对端开启联系（contact_allowed=1）时可直接建会话（200）。"""
    token_a, _, match_id = _publish_match(client, contact_allowed=1)
    r = client.post(
        f"{API}/im/sessions",
        headers=auth_header(token_a),
        json={"match_id": match_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0
    assert "id" in body["data"]
    assert body["data"]["match_id"] == match_id


def test_im_session_blocked_when_contact_disabled(client, db):
    """对端关闭联系（contact_allowed=0）时建会话返回 403（Q5 单一门控）。"""
    token_a, _, match_id = _publish_match(client, contact_allowed=1)
    # keep_status=0 强制 contact_allowed=1，故关闭联系场景在 DB 中置 0 复现（门控唯一来源 found.contact_allowed）
    match = db.get(MatchRecord, match_id)
    found = db.get(FoundItem, match.found_id)
    found.contact_allowed = 0
    db.commit()
    r = client.post(
        f"{API}/im/sessions",
        headers=auth_header(token_a),
        json={"match_id": match_id},
    )
    assert r.status_code == 403, r.text
    assert "未开启联系" in r.json()["message"]


def test_im_send_message_success_and_audit_mirror(client, db):
    """发送消息成功（200），且每条消息镜像至 audit_log（im_message）。"""
    token_a, _, match_id = _publish_match(client, contact_allowed=1)
    s = client.post(
        f"{API}/im/sessions",
        headers=auth_header(token_a),
        json={"match_id": match_id},
    )
    session_id = s.json()["data"]["id"]

    r = client.post(
        f"{API}/im/sessions/{session_id}/messages",
        headers=auth_header(token_a),
        json={"content": "您好，请问是您丢的书包吗？"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["content"] == "您好，请问是您丢的书包吗？"

    # 镜像审计（冒领溯源）
    mirror = (
        db.query(AuditLog)
        .filter(AuditLog.action == "im_message", AuditLog.target_type == "im_session")
        .all()
    )
    assert len(mirror) >= 1
    assert mirror[0].target_id == session_id


def test_im_send_message_rejects_link(client):
    """消息含外部链接被拦截（422，防导流 / 防骚扰）。"""
    token_a, _, match_id = _publish_match(client, contact_allowed=1)
    s = client.post(
        f"{API}/im/sessions",
        headers=auth_header(token_a),
        json={"match_id": match_id},
    )
    session_id = s.json()["data"]["id"]

    r = client.post(
        f"{API}/im/sessions/{session_id}/messages",
        headers=auth_header(token_a),
        json={"content": "加我微信 https://evil.example.com"},
    )
    assert r.status_code == 422, r.text
    assert "链接" in r.json()["message"]


def test_im_polling_returns_messages_incrementally(client):
    """轮询历史：since_id 增量仅返回新消息（前端 ~4s 轮询机制）。"""
    token_a, _, match_id = _publish_match(client, contact_allowed=1)
    s = client.post(
        f"{API}/im/sessions",
        headers=auth_header(token_a),
        json={"match_id": match_id},
    )
    session_id = s.json()["data"]["id"]

    m1 = client.post(
        f"{API}/im/sessions/{session_id}/messages",
        headers=auth_header(token_a),
        json={"content": "第一条"},
    ).json()["data"]
    m2 = client.post(
        f"{API}/im/sessions/{session_id}/messages",
        headers=auth_header(token_a),
        json={"content": "第二条"},
    ).json()["data"]

    # 全量
    all_msgs = client.get(
        f"{API}/im/sessions/{session_id}/messages",
        headers=auth_header(token_a),
        params={"since_id": 0},
    )
    assert all_msgs.status_code == 200, all_msgs.text
    assert len(all_msgs.json()["data"]) == 2

    # 增量（仅第二条）
    since = client.get(
        f"{API}/im/sessions/{session_id}/messages",
        headers=auth_header(token_a),
        params={"since_id": m1["id"]},
    )
    inc = since.json()["data"]
    assert len(inc) == 1
    assert inc[0]["id"] == m2["id"]


def test_im_non_participant_forbidden(client):
    """非会话双方成员访问会话返回 403。"""
    token_a, _, match_id = _publish_match(client, contact_allowed=1)
    s = client.post(
        f"{API}/im/sessions",
        headers=auth_header(token_a),
        json={"match_id": match_id},
    )
    session_id = s.json()["data"]["id"]

    token_c, _, _, _, _ = register_and_login(client, "vc")
    r = client.get(
        f"{API}/im/sessions/{session_id}/messages",
        headers=auth_header(token_c),
    )
    assert r.status_code == 403, r.text


def test_im_gate_double_check_after_contact_disabled(client, db):
    """门控双保险：会话建立后对端关闭联系，再发消息仍被拒（403）。"""
    token_a, _, match_id = _publish_match(client, contact_allowed=1)
    s = client.post(
        f"{API}/im/sessions",
        headers=auth_header(token_a),
        json={"match_id": match_id},
    )
    session_id = s.json()["data"]["id"]

    # 对端关闭联系
    match = db.get(MatchRecord, match_id)
    found = db.get(FoundItem, match.found_id)
    found.contact_allowed = 0
    db.commit()

    r = client.post(
        f"{API}/im/sessions/{session_id}/messages",
        headers=auth_header(token_a),
        json={"content": "还能联系吗"},
    )
    assert r.status_code == 403, r.text


# ================= 需求 E：我的发布 =================
def test_mypublish_returns_own_items_with_tags(client):
    """GET /users/me/items 仅返回当前用户本人发布的物品并携带标签。"""
    token_a, _, _, _, _ = register_and_login(client, "ve")
    lost_time = datetime(2026, 7, 16, 10, 0, 0).isoformat()
    lost_resp = client.post(
        f"{API}/lost-items",
        headers=auth_header(token_a),
        data={
            "title": "黑色书包",
            "description": "图书馆丢失黑色书包",
            "category_name": "书包",
            "lost_time": lost_time,
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert lost_resp.status_code == 200, lost_resp.text
    lost_id = lost_resp.json()["data"]["item"]["id"]

    r = client.get(f"{API}/users/me/items", headers=auth_header(token_a))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "lost" in data and "found" in data
    # 仅 A 发布过失物，未发布拾物
    assert data["found"] == []
    assert any(it["id"] == lost_id for it in data["lost"])
    mine = next(it for it in data["lost"] if it["id"] == lost_id)
    assert "黑色" in mine["tags"]
    assert "图书馆" in mine["tags"]


# ================= 需求 B：自动标签 =================
def test_published_item_has_structured_tags(client):
    """发布时抽取结构化标签：颜色词「黑色」与地点词「图书馆」应入 tags。"""
    token_a, _, _, _, _ = register_and_login(client, "vb_tag")
    lost_time = datetime(2026, 7, 16, 10, 0, 0).isoformat()
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token_a),
        data={
            "title": "黑色书包",
            "description": "图书馆丢失黑色书包",
            "category_name": "书包",
            "lost_time": lost_time,
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    item = r.json()["data"]["item"]
    assert isinstance(item["tags"], list)
    assert "黑色" in item["tags"]
    assert "图书馆" in item["tags"]


def test_found_item_contact_allowed_default_enabled(client):
    """拾物未显式传 contact_allowed 时默认开启（=1）。"""
    token_b, _, _, _, _ = register_and_login(client, "vb_ca")
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token_b),
        data={
            "keep_status": "0",
            "description": "捡到一把黑色雨伞",
            "category_name": "雨伞",
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["item"]["contact_allowed"] == 1
