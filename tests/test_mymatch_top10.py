"""mymatch-top10 增量行为回归测试（PRD 2026-08-05 §7 验收标准 1-6 + 新接口）。

覆盖：
- 验收1 发布即见（含低分）：score<80 候选落库、suspected=false、「我的匹配」进行中可见。
- 验收2 排序与上限：按 match_score 降序；单件失物候选 ≤ MATCH_TOP_N(10)。
- 验收3 申请匹配闭环：低分候选 status=0 → claim(理由) → status=1 → 确认归还 → 交接码 → 完成。
  + 非失主 claim 403；空理由 400；不存在匹配 404。
- 验收4 幂等去重：同一 (lost_id, found_id) 不重复生成（重复刷新 created=0）。
- 验收5 高分不回归：score≥80 候选（suspected=true）认领/确认归还/交接码/完成流程不回归。
- 验收6 拾物发布对称生成候选（Q5）：拾得者「我的匹配」也可见低分候选。
- P2-1 refresh-matches：增量补新拾物、去重、≤10；非失主 403；已解决/软删/不存在 4xx。
- P1-2 对端已解决/软删隐藏；P1-4 page_size=200；/lost-items/{id}/matches 放开阈值。
- 对称路径单件失物候选 ≤10 上限（Q5 对称不应突破 P0-1/P0-2 上限）。
- 拾物已解决/软删不可申请（manual 409/422）。

说明：本文件不改 app/、web/ 实现；分数口径沿用 flow-v2 五维公式（同图+同类+同色文字全中=95，
异色仅丢文字维度 → 70 <80）。helper `_publish_found` 默认 keep_status="0"（暂为保管）。

⚠️ flow-v3 修订批注（口径已变，本文件断言未受影响）：
flow-v2 R2-a 原为「keep_status=1 拾物退出自动**双向**匹配池」，flow-v3 已修订为
**单向进池**——keep1 拾物可作为**失主侧**候选被正向召回（`_recall_lost_candidates` 放开
keep_status 过滤），但**永不**为拾得者反向生成候选（`_reverse_match_found` 保留 keep1 早退）。
本文件全部用例走 keep0（暂为保管）的「自动候选/认领闭环」语义，keep0 路径两版行为一致，
故无需改动断言；keep1 单向性专项覆盖见 `tests/test_flow_v3.py`。
"""
from __future__ import annotations

from datetime import datetime

from app.models import FoundItem
from conftest import API, PNG, auth_header, register_and_login

MATCH_TOP_N = 10
THRESHOLD = 80.0


# ---------------- helpers ----------------
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


def _publish_lost(client, token, title, category_name, with_image=True):
    files = {"images": ("lost.png", PNG, "image/png")} if with_image else {}
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": title,
            "description": title,
            "category_name": category_name,
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files=files,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _desc_sorted(matches) -> bool:
    return all(
        float(matches[i]["match_score"]) >= float(matches[i + 1]["match_score"])
        for i in range(len(matches) - 1)
    )


def _claim_handover_close(client, token_owner, token_finder, match_id):
    """完整闭环：认领 → 确认归还 → 双码生成 → 交叉验证 → 完成。返回最终 MatchOut。"""
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=auth_header(token_owner),
        json={"claim_reason": "钥匙齿纹一致，可凭钥匙扣辨认"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 1, "claim 后应进入认领中"

    r = client.post(
        f"{API}/matches/{match_id}/confirm-return",
        headers=auth_header(token_finder),
    )
    assert r.status_code == 200, r.text

    # 失主生成 lost_code
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate",
        headers=auth_header(token_owner),
    )
    assert r.status_code == 200, r.text
    lost_code = r.json()["data"]["code"]
    assert len(lost_code) == 4

    # 拾得者生成 finder_code
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate",
        headers=auth_header(token_finder),
    )
    assert r.status_code == 200, r.text
    finder_code = r.json()["data"]["code"]
    assert len(finder_code) == 4

    # 失主验证拾得者的码
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=auth_header(token_owner),
        json={"code": finder_code, "role": "lost", "gps": "30.1,104.1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["both_verified"] is False

    # 拾得者验证失主的码
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=auth_header(token_finder),
        json={"code": lost_code, "role": "finder", "gps": "30.2,104.2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["both_verified"] is True

    r = client.get(
        f"{API}/matches",
        headers=auth_header(token_owner),
        params={"status": 2, "page_size": 200},
    )
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    completed = next((m for m in items if m["id"] == match_id), None)
    assert completed is not None, "闭环完成后应出现在「已完成」tab"
    assert completed["status"] == 2
    return completed


# ---------------- 验收1：发布即见（含低分） ----------------
def test_ac1_publish_lost_low_score_candidate_visible(client):
    """发布失物 → 含低分候选（score<80, suspected=false）；「我的匹配」进行中 tab 可见。"""
    token_owner, _, _, _, _ = register_and_login(client, "mtop1o")
    token_finder, _, _, _, _ = register_and_login(client, "mtop1f")

    found_black_id = _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙")
    found_silver_id = _publish_found(client, token_finder, "钥匙", "捡到一把银色钥匙")

    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    matches = lost["suspected_matches"]
    lost_id = lost["item"]["id"]
    assert len(matches) <= MATCH_TOP_N, f"候选应 ≤10: {len(matches)}"
    assert _desc_sorted(matches), "候选应按分数降序"

    by_found = {m["found_id"]: m for m in matches}
    assert found_silver_id in by_found and found_black_id in by_found, f"候选集合: {list(by_found)}"
    silver = by_found[found_silver_id]
    black = by_found[found_black_id]
    assert silver["match_score"] >= THRESHOLD and silver["suspected"] is True
    assert black["match_score"] < THRESHOLD and black["suspected"] is False
    assert silver["match_score"] > black["match_score"]

    # 「我的匹配」进行中 tab（status=0）应能看到低分候选
    r = client.get(
        f"{API}/matches",
        headers=auth_header(token_owner),
        params={"status": 0, "page_size": 200},
    )
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    low = [m for m in items if m["lost_id"] == lost_id and m["found_id"] == found_black_id]
    assert low, f"低分候选应在进行中 tab 可见: {items}"
    assert low[0]["match_score"] < THRESHOLD and low[0]["suspected"] is False


# ---------------- 验收2：排序与上限 ----------------
def test_ac2_cap_10_and_desc_order(client):
    """单件失物候选 ≤10；按分数降序；(lost_id, found_id) 不重复。"""
    token_owner, _, _, _, _ = register_and_login(client, "mtop2o")
    token_finder, _, _, _, _ = register_and_login(client, "mtop2f")

    for _ in range(12):
        _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙")

    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    matches = lost["suspected_matches"]
    assert len(matches) == MATCH_TOP_N, f"应严格取前 10 条候选，实际 {len(matches)}"
    assert _desc_sorted(matches)
    found_ids = [m["found_id"] for m in matches]
    assert len(found_ids) == len(set(found_ids)), "候选不得重复"


# ---------------- 验收3：申请匹配闭环（低分） ----------------
def test_ac3_low_score_claim_closed_loop(client):
    """低分候选「申请匹配」= claim → 认领中 → 确认归还 → 交接码 → 完成。"""
    token_owner, _, _, _, _ = register_and_login(client, "mtop3o")
    token_finder, _, _, _, _ = register_and_login(client, "mtop3f")

    found_black_id = _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙")
    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    black = next(m for m in lost["suspected_matches"] if m["found_id"] == found_black_id)
    assert black["match_score"] < THRESHOLD

    completed = _claim_handover_close(client, token_owner, token_finder, black["id"])
    assert completed["match_score"] < THRESHOLD, "低分候选同样应走通闭环"


def test_ac3_claim_guards(client):
    """验收3守卫：空理由 400；非失主（拾得者/第三方）claim 403；不存在匹配 404。"""
    token_owner, _, _, _, _ = register_and_login(client, "mtop3go")
    token_finder, _, _, _, _ = register_and_login(client, "mtop3gf")
    token_third, _, _, _, _ = register_and_login(client, "mtop3gt")

    _publish_found(client, token_finder, "钥匙", "捡到一把银色钥匙")
    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    match_id = lost["suspected_matches"][0]["id"]

    # 空理由 → 400 code 3002
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=auth_header(token_owner),
        json={"claim_reason": ""},
    )
    assert r.status_code == 400 and r.json()["code"] == 3002, r.text

    # 非失主（拾得者 / 第三方）→ 403
    for tok in (token_finder, token_third):
        r = client.post(
            f"{API}/matches/{match_id}/claim",
            headers=auth_header(tok),
            json={"claim_reason": "我是失主"},
        )
        assert r.status_code == 403, r.text

    # 不存在的匹配 → 404
    r = client.post(
        f"{API}/matches/999999/claim",
        headers=auth_header(token_owner),
        json={"claim_reason": "x"},
    )
    assert r.status_code == 404, r.text


# ---------------- 验收4：幂等去重（refresh） ----------------
def test_ac4_idempotent_refresh(client):
    """同一 (lost_id, found_id) 不重复生成：无新拾物刷新 created=0；增量补新、再刷新幂等。"""
    token_owner, _, _, _, _ = register_and_login(client, "mtop4o")
    token_finder, _, _, _, _ = register_and_login(client, "mtop4f")

    _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙")
    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    lost_id = lost["item"]["id"]
    before = len(lost["suspected_matches"])

    # 先认领一条 → lost.status=2，后续对称匹配不再补该失物（隔离「对称」与「刷新」两个来源）
    claimable = next(m for m in lost["suspected_matches"] if m["status"] == 0)
    r = client.post(
        f"{API}/matches/{claimable['id']}/claim",
        headers=auth_header(token_owner),
        json={"claim_reason": "钥匙齿纹一致"},
    )
    assert r.status_code == 200, r.text

    # 无新拾物 → 刷新 created=0
    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["created"] == 0, r.text

    # 新拾物发布（对称不补该失物）→ 刷新增量补 created=1、去重
    _publish_found(client, token_finder, "钥匙", "捡到一把铜色钥匙")
    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["created"] == 1, f"应增量补 1 条: {data}"
    assert len(data["matches"]) == before + 1, f"候选总量应为 before+1: {len(data['matches'])}"
    assert len(data["matches"]) <= MATCH_TOP_N

    # 再刷新 → created=0（幂等，不重复生成）
    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["created"] == 0, r.text

    # 全量候选无重复 (lost_id, found_id)
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_owner))
    items = r.json()["data"]
    pairs = [(m["lost_id"], m["found_id"]) for m in items]
    assert len(pairs) == len(set(pairs)), "不得出现重复 (lost_id, found_id)"


# ---------------- 验收5：高分不回归 ----------------
def test_ac5_high_score_flow_no_regression(client):
    """score≥80 候选（suspected=true）认领/确认归还/交接码/完成流程不回归。"""
    token_owner, _, _, _, _ = register_and_login(client, "mtop5o")
    token_finder, _, _, _, _ = register_and_login(client, "mtop5f")

    found_silver_id = _publish_found(client, token_finder, "钥匙", "捡到一把银色钥匙")
    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    silver = next(m for m in lost["suspected_matches"] if m["found_id"] == found_silver_id)
    assert silver["match_score"] >= THRESHOLD and silver["suspected"] is True

    completed = _claim_handover_close(client, token_owner, token_finder, silver["id"])
    assert completed["match_score"] >= THRESHOLD
    assert completed["suspected"] is True, "高分候选 suspected=true 展示不回归"


# ---------------- 验收6：拾物发布对称生成候选（Q5） ----------------
def test_ac6_finder_side_symmetric_low_score_candidate(client):
    """拾物发布对称生成候选；拾得者「我的匹配」也能看到低分候选（suspected=false）。"""
    token_owner, _, _, _, _ = register_and_login(client, "mtop6o")
    token_finder, _, _, _, _ = register_and_login(client, "mtop6f")

    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    lost_id = lost["item"]["id"]
    assert lost["suspected_matches"] == [], "无拾物时不应有候选"

    found_id = _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙")

    r = client.get(
        f"{API}/matches",
        headers=auth_header(token_finder),
        params={"status": 0, "page_size": 200},
    )
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    mine = [m for m in items if m["lost_id"] == lost_id and m["found_id"] == found_id]
    assert mine, f"拾得者侧应可见对称候选: {items}"
    assert mine[0]["match_score"] < THRESHOLD, "对称候选应为低分（黑 vs 银）"
    assert mine[0]["suspected"] is False


# ---------------- P2-1 refresh-matches 守卫 ----------------
def test_refresh_matches_guards(client, db):
    """refresh-matches 守卫：非失主 403；不存在 404；软删/已解决失物 422。"""
    token_owner, _, _, _, _ = register_and_login(client, "mrefo")
    token_finder, _, _, _, _ = register_and_login(client, "mreff")

    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    lost_id = lost["item"]["id"]

    # 非失主 → 403
    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_finder))
    assert r.status_code == 403, r.text

    # 不存在 → 404
    r = client.post(f"{API}/lost-items/999999/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 404, r.text

    # 软删失物 → 422（ParamError）
    from app.models.item import LostItem as _LostItem

    lost_row = db.get(_LostItem, lost_id)
    lost_row.deleted_at = datetime(2026, 8, 5, 12, 0, 0)
    db.commit()
    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 422, r.text

    # 已解决失物 → 422：先走完整闭环到 lost.status=RESOLVED
    token_owner2, _, _, _, _ = register_and_login(client, "mref2o")
    token_finder2, _, _, _, _ = register_and_login(client, "mref2f")
    found_silver_id = _publish_found(client, token_finder2, "钥匙", "捡到一把银色钥匙")
    lost2 = _publish_lost(client, token_owner2, "银色钥匙", "银色钥匙", with_image=True)
    lost2_id = lost2["item"]["id"]
    silver = next(m for m in lost2["suspected_matches"] if m["found_id"] == found_silver_id)
    _claim_handover_close(client, token_owner2, token_finder2, silver["id"])
    r = client.post(f"{API}/lost-items/{lost2_id}/refresh-matches", headers=auth_header(token_owner2))
    assert r.status_code == 422, r.text


# ---------------- P1-4 / T02：/matches 分页 + 对端过滤 ----------------
def test_matches_page_size_200_no_truncation(client):
    """page_size=200 生效；多件失物×10 候选（>100 条）仍可完整返回。"""
    token_owner, _, _, _, _ = register_and_login(client, "mpg200o")
    token_finder, _, _, _, _ = register_and_login(client, "mpg200f")

    for _ in range(10):
        _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙")
    lost_ids = []
    for i in range(11):
        lost = _publish_lost(client, token_owner, f"银色钥匙{i}", "银色钥匙", with_image=True)
        lost_ids.append(lost["item"]["id"])

    r = client.get(
        f"{API}/matches",
        headers=auth_header(token_owner),
        params={"page_size": 200},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["page_size"] == 200
    assert data["total"] == 110, f"应 110 条候选（11×10），实际 {data['total']}"
    assert len(data["items"]) == 110

    # 超过 le=200 → 422
    r = client.get(
        f"{API}/matches",
        headers=auth_header(token_owner),
        params={"page_size": 201},
    )
    assert r.status_code == 422, r.text


def test_counterpart_hidden_resolved_and_soft_deleted(client, db):
    """P1-2：进行中候选的对端已解决/软删 → 从 /matches 与 /lost-items/{id}/matches 隐藏。"""
    from app.models.item import LostItem

    token_owner, _, _, _, _ = register_and_login(client, "mhido")
    token_finder, _, _, _, _ = register_and_login(client, "mhidf")

    found_id = _publish_found(client, token_finder, "钥匙", "捡到一把银色钥匙")
    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    lost_id = lost["item"]["id"]
    match_id = lost["suspected_matches"][0]["id"]

    # 对端拾物置已解决（RESOLVED=1）
    found = db.get(FoundItem, found_id)
    found.status = 1
    db.commit()

    r = client.get(
        f"{API}/matches",
        headers=auth_header(token_owner),
        params={"status": 0, "page_size": 200},
    )
    assert r.status_code == 200, r.text
    assert all(m["id"] != match_id for m in r.json()["data"]["items"]), "对端已解决的候选应隐藏"

    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    assert all(m["id"] != match_id for m in r.json()["data"]), "lost 匹配列表也应隐藏"

    # 重置待认领后软删对端拾物 → 同样隐藏
    found.status = 0
    found.deleted_at = datetime(2026, 8, 5, 12, 0, 0)
    db.commit()
    r = client.get(
        f"{API}/matches",
        headers=auth_header(token_owner),
        params={"status": 0, "page_size": 200},
    )
    assert r.status_code == 200, r.text
    assert all(m["id"] != match_id for m in r.json()["data"]["items"]), "对端软删的候选应隐藏"


# ---------------- T02：/lost-items/{id}/matches 放开阈值 ----------------
def test_lost_items_matches_contains_low_score(client):
    """GET /lost-items/{id}/matches：含低分、≤10、降序；非失主 403。"""
    token_owner, _, _, _, _ = register_and_login(client, "mlosto")
    token_finder, _, _, _, _ = register_and_login(client, "mlostf")

    found_black_id = _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙")
    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    lost_id = lost["item"]["id"]

    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    items = r.json()["data"]
    assert len(items) <= MATCH_TOP_N
    assert _desc_sorted(items)
    assert any(m["found_id"] == found_black_id and m["match_score"] < THRESHOLD for m in items), (
        "lost 匹配列表应含低分候选"
    )

    # 非失主 → 403
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_finder))
    assert r.status_code == 403, r.text


# ---------------- 对称路径单件失物候选 ≤10 上限（Q5） ----------------
def test_symmetric_found_publish_respects_per_lost_cap(client):
    """Q5 对称：新拾物发布不应让单件失物候选数超过 MATCH_TOP_N(10)（P0-1/P0-2 上限）。"""
    token_owner, _, _, _, _ = register_and_login(client, "mcapo")
    token_finder, _, _, _, _ = register_and_login(client, "mcapf")

    for _ in range(10):
        _publish_found(client, token_finder, "钥匙", "捡到一把黑色钥匙")
    lost = _publish_lost(client, token_owner, "银色钥匙", "银色钥匙", with_image=True)
    lost_id = lost["item"]["id"]
    assert len(lost["suspected_matches"]) == MATCH_TOP_N

    # 第 11 条拾物发布：对称路径会尝试为该失物（仍 MATCHING）补候选
    _publish_found(client, token_finder, "钥匙", "捡到一把铜色钥匙")

    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    items = r.json()["data"]
    assert len(items) <= MATCH_TOP_N, f"对称补候选突破单件失物 10 条上限: {len(items)} 条"


# ---------------- 拾物已解决/软删不可申请（manual） ----------------
def test_manual_match_rejected_when_found_resolved_or_soft_deleted(client, db):
    """「申请匹配」（manual）对已解决/软删拾物拒绝：409 / 422。"""
    token_owner, _, _, _, _ = register_and_login(client, "mmano")
    token_finder, _, _, _, _ = register_and_login(client, "mmanf")

    lost_id = _publish_lost(client, token_owner, "我的手机", "手机", with_image=True)["item"]["id"]
    found_id = _publish_found(client, token_finder, "水杯", "捡到一只水杯")

    # 对端拾物已解决 → 409（MatchProcessedError）
    found = db.get(FoundItem, found_id)
    found.status = 1
    db.commit()
    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_owner),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r.status_code == 409, r.text

    # 对端拾物软删 → 422（ParamError）
    found.status = 0
    found.deleted_at = datetime(2026, 8, 5, 12, 0, 0)
    db.commit()
    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_owner),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r.status_code == 422, r.text
