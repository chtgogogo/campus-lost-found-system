"""v5 增量回归测试（软删会话 / 招领成功归档 / 未能找回重入池 / 零迁移）。

覆盖：
- ``GET /im/sessions``：仅列 status=0 且参与者含当前用户的会话，富化标题/对方/未读。
- ``DELETE /im/sessions/{id}``：软删 status=1，从列表消失；非参与者 403。
- ``POST /im/sessions/{id}/success``：软删 + 关联未完成 match 归档（双端已解决）；无 match 仅软删。
- ``POST /matches/{id}/giveup``：仅失主；非终态双写 status=5 + lost=0；非失主 403；终态 409；幂等。
- 重入池验证：giveup 后失物 status=0，可被自动（新拾物发布）与手动（同拾物）再次匹配命中。
- 零迁移：不新增 0004 迁移文件。
"""
from __future__ import annotations

import os

from conftest import API, PNG, auth_header, register_and_login


def _publish_lost(client, token, category_name, title="我的失物", description="丢失物品"):
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": title,
            "description": description,
            "category_name": category_name,
            "lost_time": "2026-07-16T10:00:00",
        },
        files={"images": ("lost.png", PNG, "image/png")},
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


def _publish_pair_bag(client, tag):
    """发布同品类失主/拾得者，触发自动匹配，返回 (token_a, token_b, lost_id, found_id, match_id)。"""
    token_a, _, _, _, _ = register_and_login(client, f"{tag}_a")
    token_b, _, _, _, _ = register_and_login(client, f"{tag}_b")
    lost_id = _publish_lost(client, token_a, "书包", "黑色书包", "图书馆丢失黑色书包")
    found_id = _publish_found(client, token_b, "书包", "捡到黑色书包", keep_status="0", contact_allowed="1")
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_a))
    matches = r.json()["data"]
    match_id = matches[0]["id"] if matches else None
    return token_a, token_b, lost_id, found_id, match_id


# ---------------- IM 会话列表 + 软删 ----------------
def test_v5_im_sessions_list_and_soft_delete(client):
    token_owner, _, _, _, owner_id = register_and_login(client, "so")
    token_finder, _, _, _, finder_id = register_and_login(client, "sf")
    found_id = _publish_found(client, token_finder, "钥匙", "捡到钥匙", contact_allowed="1")

    # 创建会话（owner 联系 finder 的拾物）
    r = client.post(f"{API}/im/sessions", headers=auth_header(token_owner), json={"found_id": found_id})
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]

    # 列表（owner 视角）：仅 status=0 参与者
    r = client.get(f"{API}/im/sessions", headers=auth_header(token_owner))
    assert r.status_code == 200
    items = r.json()["data"]
    assert any(s["id"] == sid for s in items)
    item = next(s for s in items if s["id"] == sid)
    assert item["title"] == "联系对方 · 钥匙"
    assert item["peer_user"]["id"] == finder_id
    assert item["unread"] is False  # 无消息

    # finder 视角亦可见（参与者）
    r = client.get(f"{API}/im/sessions", headers=auth_header(token_finder))
    assert r.status_code == 200
    assert any(s["id"] == sid for s in r.json()["data"])

    # 非参与者不可见
    token_other, _, _, _, _ = register_and_login(client, "so2")
    r = client.get(f"{API}/im/sessions", headers=auth_header(token_other))
    assert r.status_code == 200
    assert not any(s["id"] == sid for s in r.json()["data"])

    # 软删
    r = client.delete(f"{API}/im/sessions/{sid}", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 1
    r = client.get(f"{API}/im/sessions", headers=auth_header(token_owner))
    assert not any(s["id"] == sid for s in r.json()["data"])

    # 非参与者删除 → 403
    r = client.delete(f"{API}/im/sessions/{sid}", headers=auth_header(token_other))
    assert r.status_code == 403


# ---------------- 招领成功归档（带 match） ----------------
def test_v5_im_success_archives_match(client):
    token_a, _, lost_id, found_id, match_id = _publish_pair_bag(client, "sa")
    assert match_id is not None

    r = client.post(f"{API}/im/sessions", headers=auth_header(token_a), json={"match_id": match_id})
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]

    r = client.post(f"{API}/im/sessions/{sid}/success", headers=auth_header(token_a))
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == 1
    assert body["match_archived"] is True

    # match 归档为已完成(2)
    items = client.get(f"{API}/matches?status=2", headers=auth_header(token_a)).json()["data"]["items"]
    assert any(x["id"] == match_id for x in items)
    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token_a)).json()["data"]
    found = client.get(f"{API}/found-items/{found_id}", headers=auth_header(token_a)).json()["data"]
    assert lost["status"] == 3
    assert found["status"] == 1

    # 会话从列表消失
    r = client.get(f"{API}/im/sessions", headers=auth_header(token_a))
    assert not any(s["id"] == sid for s in r.json()["data"])


# ---------------- 招领成功（无 match）仅软删 ----------------
def test_v5_im_success_no_match_soft_delete_only(client):
    token_owner, _, _, _, _ = register_and_login(client, "no_m")
    token_finder, _, _, _, _ = register_and_login(client, "nf_m")
    found_id = _publish_found(client, token_finder, "钥匙", "捡到钥匙", contact_allowed="1")
    r = client.post(f"{API}/im/sessions", headers=auth_header(token_owner), json={"found_id": found_id})
    sid = r.json()["data"]["id"]
    r = client.post(f"{API}/im/sessions/{sid}/success", headers=auth_header(token_owner))
    assert r.status_code == 200
    assert r.json()["data"]["match_archived"] is False
    assert r.json()["data"]["status"] == 1


# ---------------- 未能找回：双写 + 重入池 + 权限 ----------------
def test_v5_giveup_and_reenter_pool(client):
    token_a, token_b, lost_id, found_id, match_id = _publish_pair_bag(client, "g")
    assert match_id is not None

    # 失主放弃
    r = client.post(f"{API}/matches/{match_id}/giveup", headers=auth_header(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 5
    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token_a)).json()["data"]
    assert lost["status"] == 0  # 重入待匹配池

    # 幂等：再次放弃仍成功（保持 5 / lost=0）
    r = client.post(f"{API}/matches/{match_id}/giveup", headers=auth_header(token_a))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == 5

    # 非失主 → 403
    r = client.post(f"{API}/matches/{match_id}/giveup", headers=auth_header(token_b))
    assert r.status_code == 403

    # 自动重入：发布同品类新拾物触发新匹配
    new_found_id = _publish_found(client, token_b, "书包", "又捡到黑色书包", contact_allowed="1")
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_a))
    new_matches = r.json()["data"]
    assert any(m["found_id"] == new_found_id for m in new_matches)

    # 手动重入：对同一拾物（原 found_id）再次手动匹配（原 match status=5 不阻拦）
    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_a),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 4


# ---------------- 未能找回：终态拒绝 ----------------
def test_v5_giveup_terminal_rejected(client):
    token_a, token_b, _, _, match_id = _publish_pair_bag(client, "gt")
    assert match_id is not None
    # 拾得者拒绝 → status 3（终态）
    r = client.post(f"{API}/matches/{match_id}/reject", headers=auth_header(token_b), json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == 3
    # 终态放弃 → 409
    r = client.post(f"{API}/matches/{match_id}/giveup", headers=auth_header(token_a))
    assert r.status_code == 409, r.text


# ---------------- 零迁移 ----------------
def test_v5_no_new_migration():
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    f = os.path.join(base, "migrations", "versions", "0004_v5_incremental.py")
    assert not os.path.exists(f), "v5 应零迁移，不应新增 0004 迁移文件"
