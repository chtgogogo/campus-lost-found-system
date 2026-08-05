"""v5 独立 QA 边界用例（严过关 / software-qa-engineer）。

不依赖工程师自测，独立重建场景，证明六个硬闸门行为确实成立而非侥幸：

1. 跨用户隔离：A 的会话不出现在 B 的列表（不串号）。
2. success 对无 match_id 的纯 found_id 会话仅软删，且不影响无关 MatchRecord。
3. giveup 后失物 LostItem.status=0 且能在重新发布同品类拾物时再次命中候选（重入池真生效）。
4. 软删后同 pairwise 新建会话产生新会话，旧软删会话不"复活"。
5. 未读粗粒度：最后消息来自对方 → unread=True；来自自己 → unread=False（双方视角）。
"""
from __future__ import annotations

from conftest import API, PNG, auth_header, register_and_login


def _publish_lost(client, token, category_name, title="我的失物", description="丢失物品"):
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": title,
            "description": description,
            "category_name": category_name,
            "appearance": "黑色",  # v8：共享外观属性，使同品类对达到阈值（原 v4 仅靠类目+图即可）
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
            "appearance": "黑色",  # v8：共享外观属性，使同品类对达到阈值
            "contact_allowed": contact_allowed,
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def _publish_pair(client, tag, category="书包"):
    """返回 (token_a, token_b, lost_id, found_id, match_id)，match 来自反向自动匹配。"""
    token_a, _, _, _, _ = register_and_login(client, f"{tag}_a")
    token_b, _, _, _, _ = register_and_login(client, f"{tag}_b")
    lost_id = _publish_lost(client, token_a, category, f"{category}丢失", f"丢失一个{category}")
    found_id = _publish_found(client, token_b, category, f"捡到一个{category}", contact_allowed="1")
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_a))
    matches = r.json()["data"]
    match_id = matches[0]["id"] if matches else None
    return token_a, token_b, lost_id, found_id, match_id


# ---------------- 1. 跨用户隔离（不串号） ----------------
def test_v5_qa_cross_user_session_isolation(client):
    # 会话1：A(失主) ↔ B(拾得者)，联系 B 的拾物
    t_a, _, _, _, _ = register_and_login(client, "iso_a")
    t_b, _, _, _, _ = register_and_login(client, "iso_b")
    found_b = _publish_found(client, t_b, "钥匙", "捡到钥匙", contact_allowed="1")
    r = client.post(f"{API}/im/sessions", headers=auth_header(t_a), json={"found_id": found_b})
    assert r.status_code == 200, r.text
    sid_ab = r.json()["data"]["id"]

    # 会话2：C(失主) ↔ D(拾得者)，联系 D 的拾物
    t_c, _, _, _, _ = register_and_login(client, "iso_c")
    t_d, _, _, _, _ = register_and_login(client, "iso_d")
    found_d = _publish_found(client, t_d, "雨伞", "捡到雨伞", contact_allowed="1")
    r = client.post(f"{API}/im/sessions", headers=auth_header(t_c), json={"found_id": found_d})
    assert r.status_code == 200, r.text
    sid_cd = r.json()["data"]["id"]

    # A 的列表只含会话1，不含会话2
    r = client.get(f"{API}/im/sessions", headers=auth_header(t_a))
    ids_a = [s["id"] for s in r.json()["data"]]
    assert sid_ab in ids_a
    assert sid_cd not in ids_a

    # C 的列表只含会话2，不含会话1
    r = client.get(f"{API}/im/sessions", headers=auth_header(t_c))
    ids_c = [s["id"] for s in r.json()["data"]]
    assert sid_cd in ids_c
    assert sid_ab not in ids_c


# ---------------- 2. success 无 match 仅软删，且不动无关 MatchRecord ----------------
def test_v5_qa_success_no_match_leaves_other_match_untouched(client):
    # 一个真实匹配（A ↔ B）
    t_a, t_b, lost_id, found_id, match_id = _publish_pair(client, "snm")
    assert match_id is not None

    # A 另外联系 C 的拾物，建立纯 found_id 会话（无 match）
    t_c, _, _, _, _ = register_and_login(client, "snm_c")
    found_c = _publish_found(client, t_c, "水杯", "捡到水杯", contact_allowed="1")
    r = client.post(f"{API}/im/sessions", headers=auth_header(t_a), json={"found_id": found_c})
    assert r.status_code == 200, r.text
    sid_found_only = r.json()["data"]["id"]

    # 对该纯 found_id 会话做"招领成功"
    r = client.post(f"{API}/im/sessions/{sid_found_only}/success", headers=auth_header(t_a))
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == 1
    assert body["match_archived"] is False  # 无 match → 不归档

    # 断言无关匹配 m 完全未被触动
    matches = client.get(f"{API}/matches", headers=auth_header(t_a)).json()["data"]["items"]
    m = next((x for x in matches if x["id"] == match_id), None)
    assert m is not None, "无关匹配应仍在"
    assert m["status"] != 2, "招领成功不应误归档无关匹配"
    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(t_a)).json()["data"]
    assert lost["status"] != 3, "招领成功不应误置无关失物为已解决"


# ---------------- 3. giveup 后失物重入池真生效（重新发布命中新候选） ----------------
def test_v5_qa_giveup_reenters_pool_real(client):
    t_a, t_b, lost_id, found_id, match_id = _publish_pair(client, "re")
    assert match_id is not None

    # giveup 前：失物处于匹配中（status != 0），匹配待领（status 0）
    lost_before = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(t_a)).json()["data"]
    assert lost_before["status"] != 0

    # 失主放弃
    r = client.post(f"{API}/matches/{match_id}/giveup", headers=auth_header(t_a))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 5

    # giveup 后：失物重入待匹配池（status=0）
    lost_after = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(t_a)).json()["data"]
    assert lost_after["status"] == 0

    # 重新发布同品类拾物 → 该失物再次成为候选（真重入，而非仅字段变化）
    new_found_id = _publish_found(client, t_b, "书包", "又捡到一个书包", contact_allowed="1")
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(t_a))
    new_matches = r.json()["data"]
    hit = next((m for m in new_matches if m["found_id"] == new_found_id), None)
    assert hit is not None, "重入池后应能再次命中新拾物候选"
    assert hit["id"] != match_id, "应产生新的匹配候选，而非复用已放弃的旧匹配"


# ---------------- 4. 软删后同 pairwise 新建会话：新会话 + 旧不复活 ----------------
def test_v5_qa_soft_delete_then_new_session_same_pair(client):
    t_a, _, _, _, _ = register_and_login(client, "sds_a")
    t_f, _, _, _, _ = register_and_login(client, "sds_f")
    found_id = _publish_found(client, t_f, "眼镜", "捡到眼镜", contact_allowed="1")

    # 第一次建会话
    r = client.post(f"{API}/im/sessions", headers=auth_header(t_a), json={"found_id": found_id})
    assert r.status_code == 200, r.text
    sid_old = r.json()["data"]["id"]

    # 软删
    r = client.delete(f"{API}/im/sessions/{sid_old}", headers=auth_header(t_a))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 1

    # 同 pairwise 再次建会话 → 应新建（复用逻辑只认 status=0）
    r = client.post(f"{API}/im/sessions", headers=auth_header(t_a), json={"found_id": found_id})
    assert r.status_code == 200, r.text
    sid_new = r.json()["data"]["id"]
    assert sid_new != sid_old, "应产生新会话而非复用已软删会话"

    # 列表：含新会话，旧软删会话不出现
    r = client.get(f"{API}/im/sessions", headers=auth_header(t_a))
    ids = [s["id"] for s in r.json()["data"]]
    assert sid_new in ids
    assert sid_old not in ids


# ---------------- 5. 未读粗粒度：双方视角，取决于最后一条消息发送者 ----------------
def test_v5_qa_unread_coarse_grained_both_sides(client):
    t_a, _, _, _, a_id = register_and_login(client, "ur_a")
    t_b, _, _, _, b_id = register_and_login(client, "ur_b")
    found_id = _publish_found(client, t_b, "充电宝", "捡到充电宝", contact_allowed="1")

    r = client.post(f"{API}/im/sessions", headers=auth_header(t_a), json={"found_id": found_id})
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]

    # A（失主）先发消息
    r = client.post(
        f"{API}/im/sessions/{sid}/messages",
        headers=auth_header(t_a),
        json={"content": "在吗"},
    )
    assert r.status_code == 200, r.text

    r_a = client.get(f"{API}/im/sessions", headers=auth_header(t_a)).json()["data"]
    item_a = next(s for s in r_a if s["id"] == sid)
    assert item_a["unread"] is False, "自己发的最后一条消息 → 自己视角 unread=False"

    r_b = client.get(f"{API}/im/sessions", headers=auth_header(t_b)).json()["data"]
    item_b = next(s for s in r_b if s["id"] == sid)
    assert item_b["unread"] is True, "对方发的最后一条消息 → 自己视角 unread=True"

    # B（拾得者）回复
    r = client.post(
        f"{API}/im/sessions/{sid}/messages",
        headers=auth_header(t_b),
        json={"content": "在的"},
    )
    assert r.status_code == 200, r.text

    r_a2 = client.get(f"{API}/im/sessions", headers=auth_header(t_a)).json()["data"]
    item_a2 = next(s for s in r_a2 if s["id"] == sid)
    assert item_a2["unread"] is True, "对方回复后 → 失主视角 unread=True"

    r_b2 = client.get(f"{API}/im/sessions", headers=auth_header(t_b)).json()["data"]
    item_b2 = next(s for s in r_b2 if s["id"] == sid)
    assert item_b2["unread"] is False, "自己回复的最后一条消息 → 拾得者视角 unread=False"


# ---------------- 6. 异常路径：不存在的资源 → 404，不应 500 ----------------
def test_v5_qa_error_paths_not_found(client):
    t_a, _, _, _, _ = register_and_login(client, "ep_a")

    # 不存在的会话：软删 / 招领成功 都应 404
    r = client.delete(f"{API}/im/sessions/999999", headers=auth_header(t_a))
    assert r.status_code == 404, r.text
    r = client.post(f"{API}/im/sessions/999999/success", headers=auth_header(t_a))
    assert r.status_code == 404, r.text

    # 不存在的匹配：giveup 应 404
    r = client.post(f"{API}/matches/999999/giveup", headers=auth_header(t_a))
    assert r.status_code == 404, r.text


# ---------------- 7. 终态 COMPLETED(2) 放弃 → 409（补 REJECTED(3) 之外的另一终态） ----------------
def test_v5_qa_giveup_completed_terminal_rejected(client):
    t_a, t_b, lost_id, found_id, match_id = _publish_pair(client, "gt2")
    assert match_id is not None

    # 招领成功归档 → match 置 COMPLETED(2)
    r = client.post(f"{API}/im/sessions", headers=auth_header(t_a), json={"match_id": match_id})
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]
    r = client.post(f"{API}/im/sessions/{sid}/success", headers=auth_header(t_a))
    assert r.status_code == 200, r.text

    # 终态 COMPLETED 放弃 → 409
    r = client.post(f"{API}/matches/{match_id}/giveup", headers=auth_header(t_a))
    assert r.status_code == 409, r.text
    # 失物不应被误重置
    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(t_a)).json()["data"]
    assert lost["status"] != 0, "终态放弃应被拒绝，失物不应重入池"
