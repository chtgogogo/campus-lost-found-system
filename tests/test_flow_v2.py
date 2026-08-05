"""flow-v2 增量验收测试（PRD 2026-08-05 §8 验收标准 2/3/4/6/7/8 + 设计 §2.4.1）。

⚠️ flow-v3 修订批注（见 `docs/architecture/v9_flow_v3_incremental_design.md`）：
R2-a 原「keep1 退出自动**双向**匹配」口径已被 flow-v3 修订为「keep1 **单向**进入匹配池」——
正向（失主 → 拾物，`_recall_lost_candidates`）**参与召回**；反向（拾物 → 失物，
`_reverse_match_found`）**仍不生成候选**。本文件对应两条用例的断言已按新口径调整
（`test_keep1_found_publish_still_has_no_candidates` 保持不变、
`test_lost_publish_includes_keep1_candidates` 断言反转），其余章节口径不变。

覆盖（对照增量 PRD 与架构设计）：
- R2-a（flow-v3 修订）keep1 **单向**进匹配池：发布 keep1 拾物仍无候选（反向不放开）；
  **失物发布召回包含 keep1**（正向放开，flow-v3 修订）；keep0 不回归。
- R2-b（P0-3）申请即完成：legacy keep1 候选 claim-complete 一步到位终态（status=2 + flow_type=1 +
  completed_at + lost/found 已解决 + 审计）；claim 对 keep1 被 422 拦截；manual 对 keep1 分流一步完成。
- R2-c（P0-4/P1-2）撤回与恢复可申请：revoke → status=6 + lost 回退 0 + found 回退 0 + 审计；撤回后
  同 (lost, found) 可再次 manual；keep0 完成记录 revoke 409；非失主 claim-complete/revoke 403。
- R3（P0-5）：不传 lost_time 发布失物 200 且 null；传值正常。
- R4（P0-6/P0-7）：行李箱可测断言（text 40 > 20，总分 67.5 > 52.5）；location/time 空值中性 0.5；
  text 失物空词集 0.5；「其他」无词 → 40；score_detail 五维键 + appearance/feature 恒 0。
- R1（P0-1）：后端 resolved 接口对已解决失物/拾物仍正确返回（BoardView 只展示拾物为前端行为，
  由 `npm run build` + 人工可测清单验证，见 T05 交付说明）。

全程走真实发布/路由链路（FastAPI TestClient + 隔离 SQLite 测试库），复用 conftest。
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.models.audit import AuditLog
from app.models.match import MatchRecord
from app.models.item import FoundItem, LostItem
from app.services.match_service import MatchService

from conftest import API, PNG, auth_header, register_and_login


# ---------------- helpers ----------------
def _publish_lost(client, token, category_name, title="我的失物", description="丢失物品", lost_time=None, with_image=True):
    data = {
        "title": title,
        "description": description,
        "category_name": category_name,
    }
    if lost_time is not None:
        data["lost_time"] = lost_time
    files = {"images": ("lost.png", PNG, "image/png")} if with_image else {}
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data=data,
        files=files,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


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
    return r.json()["data"]


def _insert_legacy_candidate(db, lost_id, found_id, score=85.0) -> int:
    """直接落一条 status=0 候选，返回 match_id。

    flow-v3 起该候选亦可由**正向召回自动生成**（失主发布失物 / 刷新候选），
    本 helper 保留的唯一目的是**精确控制分数**与隔离召回链路，不再代表"存量数据专属路径"。
    自动候选版的等价用例见 `tests/test_flow_v3.py`（F3-3 / F3-4）。
    """
    m = MatchRecord(lost_id=lost_id, found_id=found_id, match_score=score, status=0)
    db.add(m)
    db.commit()
    return m.id


def _audit_actions(db, target_id) -> set[str]:
    db.expire_all()
    return {
        row.action
        for row in db.query(AuditLog)
        .filter(AuditLog.target_type == "match", AuditLog.target_id == target_id)
        .all()
    }


# ---------------- R2-a（flow-v3 修订）：keep1 单向进匹配池 ----------------
def test_keep1_found_publish_still_has_no_candidates(client):
    """发布 keep_status=1 拾物 → suspected_matches == []（反向仍不匹配失物）。

    ⚠️ flow-v3 **有意保留**该断言（`_reverse_match_found` 的 keep1 早退不删）：
    keep1 拾得者只负责"看见 → 拍照 → 发出来帮忙"，物品不在他手上，不应收到任何
    需要他处理的候选。本用例若变红 = 反向早退被误删 = 单向性被破坏，属**严重回归**。
    """
    token_finder, _, _, _, _ = register_and_login(client, "v2k1f")
    token_owner, _, _, _, _ = register_and_login(client, "v2k1o")
    _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")
    data = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")
    assert data["suspected_matches"] == [], "keep1 拾物发布不应生成任何候选（反向早退保留）"


def test_lost_publish_includes_keep1_candidates(client):
    """失物发布召回**包含** keep1 拾物：同品类 keep0 与 keep1 均进候选。

    flow-v3 变更 A（断言相对 flow-v2 已反转）：`_recall_lost_candidates` 删除
    keep_status 过滤，失主需要被系统告知"原地就有一件很像的东西"。
    单向性由反向侧（见上一条用例）保证，不由正向过滤保证。
    """
    token_owner, _, _, _, _ = register_and_login(client, "v2k2o")
    token_finder, _, _, _, _ = register_and_login(client, "v2k2f")
    keep0_id = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="0")["item"]["id"]
    keep1_id = _publish_found(client, token_finder, "书包", "又捡到黑色书包", keep_status="1")["item"]["id"]
    data = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")
    found_ids = {m["found_id"] for m in data["suspected_matches"]}
    assert keep0_id in found_ids, f"keep0 拾物应进候选，实际 {found_ids}"
    assert keep1_id in found_ids, f"flow-v3：keep1 拾物应进候选（正向放开），实际 {found_ids}"


def test_keep0_found_publish_reverse_matches_lost(client):
    """keep0 拾物发布仍反向匹配存量失物（keep0 行为不回归）。"""
    token_owner, _, _, _, _ = register_and_login(client, "v2k3o")
    token_finder, _, _, _, _ = register_and_login(client, "v2k3f")
    _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")
    data = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="0")
    assert data["suspected_matches"], "keep0 拾物发布应触发反向匹配"


# ---------------- R2-b：申请即完成（P0-3 / P1-1） ----------------
def test_keep1_candidate_claim_rejected_422(client, db):
    """存量 keep1 候选走普通 claim 被 422 拦截（应使用「申请即完成」）。"""
    token_owner, _, _, _, _ = register_and_login(client, "v2c1o")
    token_finder, _, _, _, _ = register_and_login(client, "v2c1f")
    lost_id = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")["item"]["id"]
    found_id = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")["item"]["id"]
    match_id = _insert_legacy_candidate(db, lost_id, found_id)
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=auth_header(token_owner),
        json={"claim_reason": "特征吻合"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == 9001


def test_claim_complete_one_step_keeps_terminal_and_audit(client, db):
    """claim-complete 一步到位：status=2 + flow_type=1 + completed_at + 双端已解决 + 审计。"""
    token_owner, _, _, _, _ = register_and_login(client, "v2cc1o")
    token_finder, _, _, _, _ = register_and_login(client, "v2cc1f")
    lost_id = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")["item"]["id"]
    found_id = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")["item"]["id"]
    match_id = _insert_legacy_candidate(db, lost_id, found_id)

    r = client.post(f"{API}/matches/{match_id}/claim-complete", headers=auth_header(token_owner), json={})
    assert r.status_code == 200, r.text
    m = r.json()["data"]
    assert m["status"] == 2, f"应一步到位终态已完成，实际 {m['status']}"
    assert m["flow_type"] == 1, "keep1 申请即完成应标记 flow_type=1"
    assert m["completed_at"] is not None, "completed_at 应有值"

    # 双端已解决
    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token_owner)).json()["data"]
    found = client.get(f"{API}/found-items/{found_id}", headers=auth_header(token_owner)).json()["data"]
    assert lost["status"] == 3, "失物应置已解决(3)"
    assert found["status"] == 1, "拾物应置已解决(1)"

    # 审计留档
    assert "keep1_claim_complete" in _audit_actions(db, match_id), "应写审计 keep1_claim_complete"


def test_manual_keep1_branch_one_step_complete(client):
    """manual 对 keep1 拾物分流：直接一步完成 status=2（不生成 status=4 待自取）。"""
    token_owner, _, _, _, _ = register_and_login(client, "v2m1o")
    token_finder, _, _, _, _ = register_and_login(client, "v2m1f")
    lost_id = _publish_lost(client, token_owner, "手机", "我的手机", "丢失手机", lost_time="2026-07-16T10:00:00")["item"]["id"]
    found_id = _publish_found(client, token_finder, "水杯", "捡到水杯", keep_status="1")["item"]["id"]
    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_owner),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r.status_code == 200, r.text
    m = r.json()["data"]
    assert m["status"] == 2, f"keep1 manual 应一步完成 status=2，实际 {m['status']}"
    assert m["flow_type"] == 1


def test_manual_keep0_still_status4(client):
    """manual 对 keep0 拾物保持现状：status=4 待自取（不回归）。"""
    token_owner, _, _, _, _ = register_and_login(client, "v2m2o")
    token_finder, _, _, _, _ = register_and_login(client, "v2m2f")
    # 失物走纯文字：避免与拾物（附图，测试环境视觉桩统一识别为「钥匙」）共享名词 tag 自动生成候选
    lost_id = _publish_lost(client, token_owner, "手机", "我的手机", "丢失手机", lost_time="2026-07-16T10:00:00", with_image=False)["item"]["id"]
    found_id = _publish_found(client, token_finder, "水杯", "捡到水杯", keep_status="0")["item"]["id"]
    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_owner),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 4, "keep0 manual 应保持 status=4"


# ---------------- R2-c：撤回与恢复可申请（P0-4 / P1-2） ----------------
def test_revoke_restores_claimable_and_status6_visible(client, db):
    """撤回：status→6、lost 回退 PENDING_MATCH(0)、found 回退 PENDING(0)、审计；status=6 在 /matches 可见。"""
    token_owner, _, _, _, _ = register_and_login(client, "v2r1o")
    token_finder, _, _, _, _ = register_and_login(client, "v2r1f")
    lost_id = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")["item"]["id"]
    found_id = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")["item"]["id"]
    match_id = _insert_legacy_candidate(db, lost_id, found_id)
    client.post(f"{API}/matches/{match_id}/claim-complete", headers=auth_header(token_owner), json={})
    completed_at = client.get(f"{API}/matches", headers=auth_header(token_owner), params={"status": 2, "page_size": 200}).json()["data"]["items"][0]["completed_at"]

    r = client.post(f"{API}/matches/{match_id}/revoke", headers=auth_header(token_owner), json={})
    assert r.status_code == 200, r.text
    m = r.json()["data"]
    assert m["status"] == 6, f"撤回后应进入终态 status=6，实际 {m['status']}"
    assert m["flow_type"] == 1

    # 双端状态回退
    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token_owner)).json()["data"]
    found = client.get(f"{API}/found-items/{found_id}", headers=auth_header(token_owner)).json()["data"]
    assert lost["status"] == 0, f"失物应回退待匹配(0)，实际 {lost['status']}"
    assert found["status"] == 0, f"拾物应回退待认领(0)，实际 {found['status']}"

    # 撤回记录在已完成侧灰显（status=6 可见，_counterpart_hidden 不拦截终态）
    items = client.get(f"{API}/matches", headers=auth_header(token_owner), params={"status": 6, "page_size": 200}).json()["data"]["items"]
    assert any(x["id"] == match_id for x in items), "status=6 撤回记录应在 /matches 可见"

    # completed_at 保留原值 + 审计
    assert m["completed_at"] == completed_at, "撤回应保留原 completed_at"
    assert "keep1_claim_revoke" in _audit_actions(db, match_id), "应写审计 keep1_claim_revoke"

    # 撤回后同 (lost, found) 可再次申请即完成（_exists_match/manual 去重排除 6）
    r2 = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_owner),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == 2, "撤回后同对应可再次申请即完成"


def test_keep0_completed_cannot_revoke(client, db):
    """keep0（双向交接）完成记录不可撤回 → 409。"""
    token_owner, _, _, _, _ = register_and_login(client, "v2r2o")
    token_finder, _, _, _, _ = register_and_login(client, "v2r2f")
    # 失物走纯文字：避免自动候选（同上）
    lost_id = _publish_lost(client, token_owner, "手机", "我的手机", "丢失手机", lost_time="2026-07-16T10:00:00", with_image=False)["item"]["id"]
    found_id = _publish_found(client, token_finder, "水杯", "捡到水杯", keep_status="0")["item"]["id"]
    r = client.post(
        f"{API}/matches/manual",
        headers=auth_header(token_owner),
        json={"lost_id": lost_id, "found_id": found_id},
    )
    assert r.status_code == 200, r.text
    mid = r.json()["data"]["id"]
    r = client.post(f"{API}/matches/{mid}/self-complete", headers=auth_header(token_owner), json={})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 2
    # keep0 完成记录 flow_type=0 → 撤回被 409 拒绝
    r = client.post(f"{API}/matches/{mid}/revoke", headers=auth_header(token_owner), json={})
    assert r.status_code == 409, r.text


def test_non_owner_claim_complete_and_revoke_forbidden(client, db):
    """非失主 claim-complete / revoke → 403。"""
    token_owner, _, _, _, _ = register_and_login(client, "v2p1o")
    token_finder, _, _, _, _ = register_and_login(client, "v2p1f")
    token_other, _, _, _, _ = register_and_login(client, "v2p1t")
    lost_id = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")["item"]["id"]
    found_id = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")["item"]["id"]
    match_id = _insert_legacy_candidate(db, lost_id, found_id)

    r = client.post(f"{API}/matches/{match_id}/claim-complete", headers=auth_header(token_other), json={})
    assert r.status_code == 403, r.text

    # 失主完成后再由第三方撤回 → 403
    client.post(f"{API}/matches/{match_id}/claim-complete", headers=auth_header(token_owner), json={})
    r = client.post(f"{API}/matches/{match_id}/revoke", headers=auth_header(token_other), json={})
    assert r.status_code == 403, r.text


# ---------------- R3：lost_time 非必填 ----------------
def test_publish_lost_without_lost_time_null(client):
    """不传 lost_time 发布失物 → 200 且 lost_time==null。"""
    token, _, _, _, _ = register_and_login(client, "v3n1")
    data = _publish_lost(client, token, "书包", "黑色书包", "图书馆丢失黑色书包")
    assert data["item"]["lost_time"] is None, "未传 lost_time 应落库 null"


def test_publish_lost_with_lost_time_value(client):
    """传 lost_time 发布失物 → 200 且值正常。"""
    token, _, _, _, _ = register_and_login(client, "v3n2")
    lost_time = "2026-07-16T10:00:00"
    data = _publish_lost(client, token, "书包", "黑色书包", "图书馆丢失黑色书包", lost_time=lost_time)
    assert data["item"]["lost_time"] is not None, "传 lost_time 应正常存储"


# ---------------- R4：新公式（纯函数级断言） ----------------
def _item(**kw):
    defaults = dict(
        lost_time=None,
        found_time=None,
        image_hash=None,
        tags=None,
        appearance=None,
        features=None,
        location=None,
        category_name=None,
        title="",
        description="",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_luggage_text_40_over_20_and_total_67_5_over_52_5():
    """PRD §5.2 可测断言：失物词集 5 词；拾物2 text=40 > 拾物1 text=20；总分 67.5 > 52.5。"""
    lost = _item(
        category_name="行李箱",
        title="两个行李箱",
        description="黄色和粉色，在教学楼看见",
        tags=["黄色", "粉色", "教学楼"],
        location="教学楼",
    )
    # 拾物1：命中 行李箱/教学楼 = 2/5 → text 20；地点同（教学楼）→ location 10 → 总分 52.5
    f1 = _item(
        category_name="行李箱",
        description="行李箱和教学楼",
        tags=["行李箱", "教学楼"],
        location="教学楼",
    )
    # 拾物2：命中 行李箱/两个/黄色/粉色 = 4/5 → text 40；地点空 → 0.5 → 总分 67.5
    f2 = _item(
        category_name="行李箱",
        description="行李箱两个，黄色的和粉色",
        tags=["行李箱", "黄色", "粉色"],
    )

    svc = MatchService()
    assert svc.text_match_rate(lost, f1) == 0.4
    assert svc.text_match_rate(lost, f2) == 0.8
    d1 = svc.score_detail(lost, f1)
    d2 = svc.score_detail(lost, f2)
    # v10 评分 v2：text 变成 qty+color+state+place+keyword 的兼容视图。
    # f1：qty=3(拾物未给数量) + place=15(同为教学楼) → text=18；
    # f2：qty=15(两个 vs 两个) + color=20(黄/粉全中) → text=35。
    # 两侧 k 相同（k 只由失主侧决定：W=photo_category+qty+color+place=70 → k=100/70≈1.4286），
    # 因此本用例真正要守护的「f2 明显优于 f1」仍然成立。
    assert d1["text"] == pytest.approx(18.0, abs=0.01), f"实际 {d1['text']}"
    assert d2["text"] == pytest.approx(35.0, abs=0.01), f"实际 {d2['text']}"
    assert d1["total"] == pytest.approx(54.29, abs=0.01), f"实际 {d1['total']}"
    assert d2["total"] == pytest.approx(78.57, abs=0.01), f"实际 {d2['total']}"
    assert d2["total"] > d1["total"], "数量+颜色全中的候选必须排在只命中地点的候选之前"
    # 可解释：shared_text 含命中词
    assert sorted(svc.shared_text_tokens(lost, f2)) == ["两个", "粉色", "行李箱", "黄色"]
    assert sorted(svc.shared_text_tokens(lost, f1)) == ["教学楼", "行李箱"]


def test_empty_location_time_neutral_half():
    """Q6 空值规则：location / time 任一侧缺失 → 中性 0.5（不惩罚）。"""
    lost = _item(tags=["钥匙"], lost_time=None, location=None)
    found = _item(tags=["钥匙"], found_time=None, location=None)
    svc = MatchService()
    assert svc.location_factor(lost, found) == 0.5
    assert svc.time_decay_factor(lost.lost_time, found.found_time) == 0.5
    # v10：空值不再折算「中性半分」，而是该维度**不计分也不计入 W_provided**
    # （既不惩罚也不虚增；惩罚与否交由归一化分母体现）。
    # 两侧地点/时间全空 → place=0、time=0，且 W_provided=0 → k 降级 1.0。
    detail = svc.score_detail(lost, found)
    assert detail["location"] == 0.0
    assert detail["time"] == 0.0
    assert detail["provided_dims"] == []
    assert detail["norm_factor"] == 1.0, "W_provided<=0 时归一化降级为 1.0，不放大空信息"


def test_text_empty_lost_tokens_neutral_and_other_no_words():
    """失主侧空词集：旧比率函数仍返回中性 0.5，但 v10 计分不再据此虚增分数。

    v10 语义变更：失主没给任何描述 → 各文本子维度都「未提供」，
    既不得分也不进 W_provided，避免「什么都没写反而拿中性分」。
    """
    svc = MatchService()
    lost = _item(tags=None, description="", title="")
    found = _item(tags=["钥匙"])
    # [deprecated] 旧比率函数行为保持不变（仍被前端/存量代码引用）
    assert svc.text_match_rate(lost, found) == 0.5, "失物侧空词集应中性 0.5"
    # v10：空词集 → 五个文本子维度全部未提供 → text 兼容视图为 0
    detail = svc.score_detail(lost, found)
    assert detail["text"] == 0.0
    assert detail["provided_dims"] == []
    assert detail["norm_factor"] == 1.0

    lost_other = _item(category_name="其他")
    found_other = _item(category_name="其他", tags=["雨伞"])
    assert svc.tag_match_rate(lost_other, found_other) == 0.5, "「其他」失物空词集应中性 0.5"
    # v10：「其他」类无词 → 仅 photo_category=10；W=10 → k=100/max(10,50)=2.0 → 20
    assert svc.score(lost_other, found_other) == pytest.approx(20.0, abs=0.01)


def test_score_detail_five_dimensions_and_deprecated_zeros():
    """score_detail 返回五维键 + text_match_rate + shared_text；appearance/feature 恒 0。"""
    lost = _item(
        image_hash="abcdef0123456789",
        category_name="钥匙",
        tags=["黑色", "钥匙"],
        location="图书馆",
        lost_time=datetime(2026, 7, 16, 10, 0, 0),
    )
    found = _item(
        image_hash="abcdef0123456789",
        category_name="钥匙",
        tags=["黑色", "钥匙"],
        location="图书馆",
        found_time=datetime(2026, 7, 16, 10, 0, 0),
    )
    detail = MatchService().score_detail(lost, found)
    for key in ("photo", "category", "text", "text_match_rate", "location", "time", "total"):
        assert key in detail, f"score_detail 缺少键 {key}"
    assert detail["appearance"] == 0.0 and detail["feature"] == 0.0, "appearance/feature 应恒为 0 占位"
    assert detail["is_other"] is False
    assert detail["total"] == 100.0, "全维度命中应满分 100"


# ---------------- R1：已完成交接只展示拾物（后端 resolved 接口契约） ----------------
def test_resolved_endpoints_contain_resolved_found_and_lost(client, db):
    """R1 数据契约：keep1 完成后 found.status=1 / lost.status=3，resolved_only 接口分别正确返回。
    （BoardView「已完成交接只展示拾物」为前端收敛行为，见 build 验证 + 人工可测清单。）"""
    token_owner, _, _, _, _ = register_and_login(client, "v1o")
    token_finder, _, _, _, _ = register_and_login(client, "v1f")
    lost_id = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")["item"]["id"]
    found_id = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")["item"]["id"]
    match_id = _insert_legacy_candidate(db, lost_id, found_id)
    client.post(f"{API}/matches/{match_id}/claim-complete", headers=auth_header(token_owner), json={})

    r_found = client.get(f"{API}/found-items?resolved_only=true&page_size=100", headers=auth_header(token_finder))
    assert r_found.status_code == 200, r_found.text
    found_ids = [it["id"] for it in r_found.json()["data"]["items"]]
    assert found_id in found_ids, "已解决拾物应出现在 resolved_only 拾物列表"

    r_lost = client.get(f"{API}/lost-items?resolved_only=true&page_size=100", headers=auth_header(token_owner))
    assert r_lost.status_code == 200, r_lost.text
    lost_ids = [it["id"] for it in r_lost.json()["data"]["items"]]
    assert lost_id in lost_ids, "已解决失物应出现在 resolved_only 失物列表"
