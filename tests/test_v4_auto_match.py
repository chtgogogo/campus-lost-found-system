"""v8 自动匹配回归测试（颜色软化验收）。

v8 关键变更：删除「颜色冲突整条置零」硬门控。颜色仅作为外观维度的一个属性，
冲突时该属性计 0，材质/形状仍参与；不同色物品不再被硬排除，而是按其它维度自然计分。

本文件覆盖：
- 同色（银色）钥匙在「有图 + 类目命中 + 时间近」下应达到疑似阈值（80）。
- 不同色（黑色）钥匙因外观颜色冲突仅丢失外观维度分数，总分降至 60（低于阈值）；
  mymatch-top10 增量后低分候选仍会入库展示（score<80, suspected=false），
  且明显低于同色钥匙（颜色软化：仅降外观维度，不归零整条）。

全程走真实发布链路（打标 → 类目解析 → 名词召回 → 六维打分 → 阈值判定），
不绕过服务层，确保端到端正确性。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from conftest import API, PNG, auth_header, register_and_login


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


def _publish_lost(client, token, title, category_name, with_image: bool = False):
    """发布失物；with_image=True 时附带图片（v8 需照片/属性佐证才能达阈值）。"""
    files = {"images": ("lost.png", PNG, "image/png")} if with_image else {}
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": title,
            "description": title,  # 必填项，纯文字场景下与标题一致
            "category_name": category_name,
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files=files,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_v8_ac1_same_color_key_suspected(client):
    """v8：有图 + 同色（银色）钥匙应达到疑似阈值（≥80）。"""
    token_owner, _, _, _, _ = register_and_login(client, "ac1o")
    token_finder, _, _, _, _ = register_and_login(client, "ac1f")

    found_a_id = _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙", keep_status="0", contact_allowed="1")
    found_b_id = _publish_found(client, token_finder, "钥匙", "捡到一把银色钥匙", keep_status="0", contact_allowed="1")

    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    matches = lost["suspected_matches"]
    found_ids = {m["found_id"] for m in matches}

    # 同色（银色）钥匙应被匹配并达阈值
    assert found_b_id in found_ids, f"银色钥匙应被匹配，实际匹配: {found_ids}"
    for m in matches:
        if m["found_id"] == found_b_id:
            assert m["match_score"] >= 80.0, f"同色匹配分应达阈值: {m}"


def test_v8_ac2_diff_color_demoted_not_suspected(client):
    """v8：不同色（黑色）钥匙因颜色冲突仅丢失外观维度分数，低于阈值（颜色软化）。

    mymatch-top10 增量后，低分候选不再被硬过滤：黑色钥匙会以低分候选出现在
    `suspected_matches` 中（score<80 且 suspected=false），且明显低于同色钥匙
    （颜色软化：仅降外观维度，不整条归零）——测试意图不变（低分不触发高分行为）。
    """
    token_owner, _, _, _, _ = register_and_login(client, "ac2o")
    token_finder, _, _, _, _ = register_and_login(client, "ac2f")

    found_a_id = _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙", keep_status="0", contact_allowed="1")
    found_b_id = _publish_found(client, token_finder, "钥匙", "捡到一把银色钥匙", keep_status="0", contact_allowed="1")

    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    matches = lost["suspected_matches"]
    by_found = {m["found_id"]: m for m in matches}

    # 同色（银）钥匙应达阈值并保持 suspected=true
    assert found_b_id in by_found, f"银色钥匙应被匹配，实际: {list(by_found)}"
    silver = by_found[found_b_id]
    assert silver["match_score"] >= 80.0, f"同色匹配分应达阈值: {silver}"
    assert silver["suspected"] is True, f"高分候选 suspected 应保持 true: {silver}"

    # 不同色（黑）钥匙仍会作为低分候选出现，但 score<80 且 suspected=false（top10 含低分）
    assert found_a_id in by_found, f"黑色钥匙应作为低分候选出现，实际: {list(by_found)}"
    black = by_found[found_a_id]
    assert black["match_score"] < 80.0, f"黑色钥匙应低于阈值: {black}"
    assert black["suspected"] is False, f"低分候选不应标记疑似: {black}"

    # 颜色软化：同色 > 异色（仅降外观维度，不整条归零）
    assert silver["match_score"] > black["match_score"], (
        f"同色应高于异色: silver={silver['match_score']}, black={black['match_score']}"
    )
