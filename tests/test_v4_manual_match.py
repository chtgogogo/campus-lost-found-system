"""v4 手动匹配 / 自取 / 无 match 联系 回归测试。

覆盖：
- `POST /matches/manual`：失主对「待认领」拾物发起待自取匹配（status=4）；权限/状态/去重校验。
- `POST /matches/{id}/self-complete`：失主单边归档（不调 handover）；双端置已解决。
- `POST /found-items`：keep_status=0 且 contact_allowed=0 → 拒绝（v4 强制联系）。
- `POST /im/sessions`：found_id 无 match 建会话（match_id=null, found_id 绑定）；
  contact_allowed==0 → 403（强溯源 + 门控）；
  卡#5 串线修复：第二联系者得独立会话、双方互不可见、A 旧会话复用回归。
"""
from __future__ import annotations

from datetime import datetime

from conftest import API, PNG, auth_header, register_and_login


def _publish_lost(client, token, category_name, title="我的失物", description="丢失物品", with_image=True):
    files = {"images": ("lost.png", PNG, "image/png")} if with_image else {}
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": title,
            "description": description,
            "category_name": category_name,
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files=files,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def _publish_found(client, token, category_name, description, keep_status="0", contact_allowed="1"):
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={
            "keep_status": keep_status,
            "category_name": category_name,
            "description": description,
            "contact_allowed": contact_allowed,
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def test_v4_manual_match_and_self_complete(client):
    """手动申请匹配 → 待自取(status=4) → 自取完成(status=2, 双端已解决)。"""
    token_owner, _, _, _, _ = register_and_login(client, "mo")
    token_finder, _, _, _, _ = register_and_login(client, "mf")

    # 失主手机 + 拾者水杯：类目/名词均不相交，发布链路不会产生自动匹配。
    # 失物走纯文字（不附图）：测试环境视觉桩对所有图片一律识别为「钥匙」，
    # 若附图会把「钥匙」注入失物 tags，与拾物（附图同样含「钥匙」）共享名词 tag，
    # 在新 top10 含低分行为下会自动生成低分候选 → manual 会被 409 拒绝。
    lost_id = _publish_lost(client, token_owner, "手机", "我的手机", with_image=False)
    found_id = _publish_found(client, token_finder, "水杯", "捡到水杯", keep_status="0", contact_allowed="1")

    # 手动申请匹配
    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_owner),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r.status_code == 200, r.text
    m = r.json()["data"]
    assert m["status"] == 4
    assert m["lost_id"] == lost_id and m["found_id"] == found_id
    match_id = m["id"]

    # 我的匹配（status=4）可见
    r2 = client.get(f"{API}/matches?status=4", headers=auth_header(token_owner))
    assert r2.status_code == 200
    ids = [x["id"] for x in r2.json()["data"]["items"]]
    assert match_id in ids

    # 失主自取完成（不调 handover）
    r3 = client.post(
        f"{API}/matches/{match_id}/self-complete",
        headers=auth_header(token_owner),
        json={},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["data"]["status"] == 2

    # 双端已解决
    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token_owner)).json()["data"]
    found = client.get(f"{API}/found-items/{found_id}", headers=auth_header(token_owner)).json()["data"]
    assert lost["status"] == 3  # 失物已解决
    assert found["status"] == 1  # 拾物已解决


def test_v4_manual_match_requires_owner(client):
    """非失主不可发起手动匹配。"""
    token_owner, _, _, _, _ = register_and_login(client, "mo2")
    token_finder, _, _, _, _ = register_and_login(client, "mf2")
    token_other, _, _, _, _ = register_and_login(client, "mo3")

    lost_id = _publish_lost(client, token_owner, "手机", "我的手机")
    found_id = _publish_found(client, token_finder, "水杯", "捡到水杯")

    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_other),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r.status_code == 403


def test_v4_manual_match_rejects_duplicate(client):
    """同一 (lost, found) 已存在进行中匹配时拒绝重复。"""
    token_owner, _, _, _, _ = register_and_login(client, "mo4")
    token_finder, _, _, _, _ = register_and_login(client, "mf4")

    lost_id = _publish_lost(client, token_owner, "手机", "我的手机", with_image=False)
    found_id = _publish_found(client, token_finder, "水杯", "捡到水杯")

    body = {"lost_id": lost_id, "found_id": found_id}
    r1 = client.post(f"{API}/matches/manual", headers=auth_header(token_owner), json=body)
    assert r1.status_code == 200
    r2 = client.post(f"{API}/matches/manual", headers=auth_header(token_owner), json=body)
    assert r2.status_code == 409


def test_v4_keep_status_zero_requires_contact(client):
    """keep_status=0 且 contact_allowed=0 → 拒绝发布（v4 强制联系）。"""
    token, _, _, _, _ = register_and_login(client, "kg")
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={
            "keep_status": "0",
            "category_name": "钥匙",
            "description": "代为保管钥匙",
            "contact_allowed": "0",
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code in (400, 422), r.text


def test_v4_keep_status_zero_with_contact_ok(client):
    """keep_status=0 且 contact_allowed=1 → 发布成功，contact_allowed 强制为 1。"""
    token, _, _, _, _ = register_and_login(client, "kf")
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={
            "keep_status": "0",
            "category_name": "钥匙",
            "description": "代为保管钥匙",
            "contact_allowed": "1",
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["item"]["contact_allowed"] == 1


def test_v4_no_match_contact_found_id(client):
    """无 match 联系：found_id 建会话（match_id=null, found_id 绑定）。"""
    token_owner, _, _, _, owner_id = register_and_login(client, "no")
    token_finder, _, _, _, finder_id = register_and_login(client, "nf")

    found_id = _publish_found(client, token_finder, "钥匙", "捡到钥匙", keep_status="1", contact_allowed="1")

    r = client.post(f"{API}/im/sessions", headers=auth_header(token_owner), json={"found_id": found_id})
    assert r.status_code == 200, r.text
    s = r.json()["data"]
    assert s["match_id"] is None
    assert s["found_id"] == found_id
    assert s["lost_user_id"] == owner_id
    assert s["finder_user_id"] == finder_id


def test_v4_no_match_contact_found_id_gated(client):
    """无 match 联系：contact_allowed==0 的拾物 → 403。"""
    token_owner, _, _, _, _ = register_and_login(client, "no2")
    token_finder, _, _, _, _ = register_and_login(client, "nf2")

    # keep_status=1 才允许 contact_allowed=0（keep_status=0 强制 1）
    found_id = _publish_found(client, token_finder, "钥匙", "捡到钥匙", keep_status="1", contact_allowed="0")

    r = client.post(f"{API}/im/sessions", headers=auth_header(token_owner), json={"found_id": found_id})
    assert r.status_code == 403, r.text


def test_v4_contact_second_user_gets_independent_session(client):
    """卡#5 串线修复：第二个联系者不再拿到他人的活跃会话。

    用户 A、B 先后联系同一件拾物 → 各自获得独立会话（同一拾物允许多条一对一
    私聊线）；双方各自发消息 200；B 不可读 A 的会话（403）；A 旧会话复用回归
    （A 再次发起仍返回自己的原会话）。
    """
    token_a, _, _, _, user_a = register_and_login(client, "ca")
    token_b, _, _, _, user_b = register_and_login(client, "cb")
    token_finder, _, _, _, finder_id = register_and_login(client, "cf")

    found_id = _publish_found(client, token_finder, "钥匙", "捡到钥匙", keep_status="1", contact_allowed="1")

    # A 先联系 → 会话 S1（A 为失主侧）
    r = client.post(f"{API}/im/sessions", headers=auth_header(token_a), json={"found_id": found_id})
    assert r.status_code == 200, r.text
    s1 = r.json()["data"]
    assert s1["lost_user_id"] == user_a and s1["finder_user_id"] == finder_id

    # B 后联系 → 必须得到自己的新会话（修复前：复用 A 的 S1 → B 后续 403 死会话）
    r = client.post(f"{API}/im/sessions", headers=auth_header(token_b), json={"found_id": found_id})
    assert r.status_code == 200, r.text
    s2 = r.json()["data"]
    assert s2["id"] != s1["id"], "B 不应复用 A 的会话"
    assert s2["found_id"] == found_id
    assert s2["lost_user_id"] == user_b and s2["finder_user_id"] == finder_id

    # 双方各自在自己的会话里发消息，均 200
    r = client.post(f"{API}/im/sessions/{s1['id']}/messages", headers=auth_header(token_a), json={"content": "同学你好，那是我丢的钥匙"})
    assert r.status_code == 200, r.text
    r = client.post(f"{API}/im/sessions/{s2['id']}/messages", headers=auth_header(token_b), json={"content": "拾物者您好，我也想认领"})
    assert r.status_code == 200, r.text

    # 互不可见：B 读 A 的会话 → 403；A 读 B 的会话 → 403
    r = client.get(f"{API}/im/sessions/{s1['id']}/messages", headers=auth_header(token_b))
    assert r.status_code == 403, r.text
    r = client.get(f"{API}/im/sessions/{s2['id']}/messages", headers=auth_header(token_a))
    assert r.status_code == 403, r.text

    # A 旧会话复用回归：A 再次发起 → 仍返回自己的原会话 S1
    r = client.post(f"{API}/im/sessions", headers=auth_header(token_a), json={"found_id": found_id})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["id"] == s1["id"]
