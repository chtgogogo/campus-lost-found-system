"""v4 独立边界用例（QA 补充，证明 AC 非侥幸 + 门控闭环）。

独立于工程师既有 test_v4_*.py，全部走真实发布/路由链路：
- 纯文字失物无名词 → 不误匹配任何有名词候选（防误报）。
- 双方都指定颜色且相同 → 应匹配（颜色一致不冲突）。
- 颜色冲突且无私物名词共享 → 不应匹配。
- 无进行中失物时 POST /matches/manual → 400 拒绝。
- 非失主（含拾得者/第三方）调 POST /matches/{id}/self-complete → 403。
"""
from __future__ import annotations

from datetime import datetime

from conftest import API, PNG, auth_header, register_and_login


def _publish_found(client, token, category_name, description, keep_status="1", contact_allowed="1"):
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


def _publish_lost_pure_text(client, token, title, category_name):
    """发布纯文字失物（无图，模拟无视觉类目场景）。"""
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": title,
            "description": title,
            "category_name": category_name,
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _publish_lost_with_image(client, token, category_name, title="我的失物", description="丢失物品"):
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": title,
            "description": description,
            "category_name": category_name,
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def test_qa_edge_pure_text_no_noun_no_false_match(client):
    """纯文字失物无物品名词（"在图书馆捡到一个东西"）→ 不应误匹配有名词候选（防误报）。"""
    token_owner, _, _, _, _ = register_and_login(client, "eqo1")
    token_finder, _, _, _, _ = register_and_login(client, "eqf1")

    found_key_id = _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙", keep_status="1", contact_allowed="1")

    lost = _publish_lost_pure_text(client, token_owner, "在图书馆捡到一个东西", "其他")
    matches = lost["suspected_matches"]
    found_ids = {m["found_id"] for m in matches}

    assert found_ids == set(), f"无名词失物不应匹配任何候选，实际: {found_ids}"
    assert found_key_id not in found_ids


def test_qa_edge_same_color_both_specified_should_match(client):
    """双方都指定颜色且相同（C=黑色钥匙 vs A=黑色钥匙）→ 应匹配（颜色一致不冲突）。

    v8：同色 + 有图（photo=20）+ 类目命中(30) + 外观颜色命中(20) + 时间近(10) = 80，达阈值。
    """
    token_owner, _, _, _, _ = register_and_login(client, "eqo2")
    token_finder, _, _, _, _ = register_and_login(client, "eqf2")

    found_a_id = _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙", keep_status="0", contact_allowed="1")

    # v8：失物需附图（或外观/特征佐证）才能凑满权重达到阈值。
    # 直接读取发布响应中的 suspected_matches（反向主动匹配结果），无需再 GET 物品详情。
    r_lost = client.post(
        f"{API}/lost-items",
        headers=auth_header(token_owner),
        data={
            "title": "黑色钥匙",
            "description": "黑色钥匙",
            "category_name": "钥匙",
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r_lost.status_code == 200, r_lost.text
    lost = r_lost.json()["data"]
    matches = lost["suspected_matches"]
    found_ids = {m["found_id"] for m in matches}

    assert found_a_id in found_ids, f"同色(黑)应匹配，实际: {found_ids}"
    for m in matches:
        if m["found_id"] == found_a_id:
            assert m["match_score"] >= 80.0, f"同色匹配分应达阈值: {m}"


def test_qa_edge_color_conflict_no_noun_share_no_match(client):
    """颜色冲突且无私物名词共享（C=银色水杯 vs A=黑色钥匙）→ 不应匹配。"""
    token_owner, _, _, _, _ = register_and_login(client, "eqo3")
    token_finder, _, _, _, _ = register_and_login(client, "eqf3")

    found_a_id = _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙", keep_status="1", contact_allowed="1")

    lost = _publish_lost_pure_text(client, token_owner, "银色水杯", "水杯")
    matches = lost["suspected_matches"]
    found_ids = {m["found_id"] for m in matches}

    assert found_a_id not in found_ids, f"无名词共享+颜色冲突不应匹配黑钥匙，实际: {found_ids}"


def test_qa_edge_manual_match_rejected_without_in_progress_lost(client):
    """无进行中失物（失物已解决 status=3）时 POST /matches/manual → 400 拒绝。"""
    token_owner, _, _, _, _ = register_and_login(client, "eqo4")
    token_finder, _, _, _, _ = register_and_login(client, "eqf4")

    found_id = _publish_found(client, token_finder, "水杯", "捡到水杯", keep_status="1", contact_allowed="1")
    lost_id = _publish_lost_with_image(client, token_owner, "手机", "我的手机")

    # 撤销失物 → status=3（不再进行中）
    r = client.delete(f"{API}/lost-items/{lost_id}", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text

    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_owner),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    # 业务参数校验（ParamError）→ 本代码库约定返回 422，与既有 keep_status 测试一致
    assert r.status_code in (400, 422), r.text


def test_qa_edge_self_complete_non_owner_forbidden(client):
    """非失主（拾得者、第三方）调 POST /matches/{id}/self-complete → 403。"""
    token_owner, _, _, _, _ = register_and_login(client, "eqo5")
    token_finder, _, _, _, _ = register_and_login(client, "eqf5")
    token_third, _, _, _, _ = register_and_login(client, "eqt5")

    # 失物走纯文字：测试环境视觉桩对所有图片一律识别为「钥匙」，失物附图会与拾物
    # （附图同样含「钥匙」）共享名词 tag，在新 top10 含低分行为下自动生成低分候选
    # → manual 会被 409 拒绝，无法到达 self-complete 权限校验点。
    lost_id = _publish_lost_pure_text(client, token_owner, "我的手机", "手机")["item"]["id"]
    found_id = _publish_found(client, token_finder, "水杯", "捡到水杯", keep_status="1", contact_allowed="1")

    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_owner),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r.status_code == 200, r.text
    match_id = r.json()["data"]["id"]

    # 拾得者（参与者但非失主）调用 → 403
    r_finder = client.post(
        f"{API}/matches/{match_id}/self-complete",
        headers=auth_header(token_finder),
        json={},
    )
    assert r_finder.status_code == 403, r_finder.text

    # 完全无关第三方调用 → 403
    r_third = client.post(
        f"{API}/matches/{match_id}/self-complete",
        headers=auth_header(token_third),
        json={},
    )
    assert r_third.status_code == 403, r_third.text
