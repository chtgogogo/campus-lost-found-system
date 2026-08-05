"""flow-v3 增量验收测试（设计 `docs/architecture/v9_flow_v3_incremental_design.md` §6 T05）。

**flow-v3 范围**（仅描述相对 flow-v2 的增量，未提及部分一律沿用 flow-v2 口径）：

- 变更 A · keep1 **单向**进入匹配池
  - 正向（失主 → 拾物，`PublishService._recall_lost_candidates`）：**放开**，keep1 拾物
    可作为失主侧候选自动生成（F3-1 / F3-10 / F3-13）。
  - 反向（拾物 → 失物，`PublishService._reverse_match_found`）：**保留早退**，绝不为
    keep1 拾得者生成候选（F3-2，单向性核心）。
- 变更 A' · keep1 单向性守卫（设计 §2.1–§2.3）：候选是"一条记录、两侧可见"，反向排除
  拦不住拾得者侧渲染，故补 `confirm-return` / `reject` 两处 422 守卫（F3-5 / F3-6），
  与既有 `claim` 守卫（F3-7）三者对称；同时**保留**拾得者侧可见性（F3-8，方案 1）。
- 变更 B · 新增 `MATCH_LOW_SCORE=60`，仅驱动**失主侧**低分弱化视觉；`suspected` 阈值仍 80；
  「低分不打扰」整体删除（F3-11 + 前端静态口径守护 F3-15/16/17）。
- 变更 C · 不提供存量回填脚本 —— `refresh-matches` 即自助回填工具（F3-10）。

不在本文件范围（由既有文件覆盖，仅在此登记不回归）：keep0 双向闭环（`test_flow_v2.py` /
`test_handover_audit.py`）、manual 分流（`test_flow_v2.py`）、五维公式（`test_match.py`）。

全程走真实发布/路由链路（FastAPI TestClient + 隔离 SQLite 测试库），复用 conftest。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.item import FoundItem
from app.models.match import HandoverCode, MatchRecord

from conftest import API, PNG, auth_header, register_and_login

# 前端源码根目录（用于变更 B / 单向性的静态口径守护，见 F3-15 ~ F3-17）
WEB_SRC = Path(__file__).resolve().parents[1] / "web" / "src"

# §2.7 R-1 观察用例产出的实际行为记录（不作为失败判定，由 QA 报告引用）
OBSERVATIONS: list[str] = []


# ---------------- helpers ----------------
def _publish_lost(client, token, category_name, title="我的失物", description="丢失物品",
                  lost_time=None, with_image=True):
    data = {"title": title, "description": description, "category_name": category_name}
    if lost_time is not None:
        data["lost_time"] = lost_time
    files = {"images": ("lost.png", PNG, "image/png")} if with_image else {}
    r = client.post(f"{API}/lost-items", headers=auth_header(token), data=data, files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _publish_found(client, token, category_name, description, keep_status="1", contact_allowed="1"):
    """默认 keep_status='1'（留在原地未挪动）—— 本文件主场景即 keep1 单向性。"""
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


def _audit_actions(db, target_id) -> set[str]:
    db.expire_all()
    return {
        row.action
        for row in db.query(AuditLog)
        .filter(AuditLog.target_type == "match", AuditLog.target_id == target_id)
        .all()
    }


def _keep1_auto_candidate(client, tag: str):
    """搭建 flow-v3 主场景：keep1 拾物先发 → 失主发同品类失物 → 正向自动生成候选。

    返回 (token_owner, token_finder, lost_id, found_id, match)。
    """
    token_finder, _, _, _, _ = register_and_login(client, f"{tag}f")
    token_owner, _, _, _, _ = register_and_login(client, f"{tag}o")
    found_id = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")["item"]["id"]
    lost = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")
    lost_id = lost["item"]["id"]
    match = next((m for m in lost["suspected_matches"] if m["found_id"] == found_id), None)
    assert match is not None, f"flow-v3 正向召回应生成 keep1 候选，实际 {lost['suspected_matches']}"
    return token_owner, token_finder, lost_id, found_id, match


def _read_web(rel: str) -> str:
    p = WEB_SRC / rel
    assert p.exists(), f"前端源文件缺失：{p}"
    return p.read_text(encoding="utf-8")


# ==================== 变更 A：keep1 单向性（F3-1 / F3-2） ====================
def test_f3_01_keep1_candidate_auto_generated_forward(client, db):
    """F3-1 正向放开：先发 keep1 拾物 → 再发同品类失物 → 自动生成 keep1 候选。

    断言：`suspected_matches` 含该 found_id；候选 status=0（待认领）；lost.status=MATCHING(1)。
    """
    token_owner, _, lost_id, found_id, match = _keep1_auto_candidate(client, "f301")

    assert match["status"] == 0, f"自动候选应为待认领 status=0，实际 {match['status']}"
    assert match["found_item"]["keep_status"] == 1, "候选对端应为 keep1 拾物"

    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token_owner)).json()["data"]
    assert lost["status"] == 1, f"生成候选后失物应置匹配中(1)，实际 {lost['status']}"

    db.expire_all()
    row = (
        db.query(MatchRecord)
        .filter(MatchRecord.lost_id == lost_id, MatchRecord.found_id == found_id)
        .first()
    )
    assert row is not None and int(row.status) == 0, "库内应存在一条 status=0 的 keep1 候选"


def test_f3_02_keep1_reverse_still_generates_nothing(client, db):
    """F3-2 单向性核心：先发失物 → 再发 keep1 拾物 → 反向仍不生成任何候选。

    断言：`suspected_matches == []` **且**查库确认该 (lost, found) 无 MatchRecord。
    """
    token_owner, _, _, _, _ = register_and_login(client, "f302o")
    token_finder, _, _, _, _ = register_and_login(client, "f302f")
    lost_id = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")["item"]["id"]
    data = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")
    found_id = data["item"]["id"]

    assert data["suspected_matches"] == [], "keep1 拾物发布不得反向生成候选（早退保留）"

    db.expire_all()
    rows = (
        db.query(MatchRecord)
        .filter(MatchRecord.lost_id == lost_id, MatchRecord.found_id == found_id)
        .all()
    )
    assert rows == [], f"库内不应存在该 (lost, found) 的 MatchRecord，实际 {rows}"

    # 拾得者「我的匹配」也应为空（反向未生成 → 无记录可见）
    r = client.get(f"{API}/matches", headers=auth_header(token_finder), params={"page_size": 200})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["total"] == 0, "反向未生成候选时拾得者侧应无任何匹配"


# ==================== 「我要领走」端到端（F3-3 / F3-4） ====================
def test_f3_03_claim_complete_end_to_end_on_auto_candidate(client, db):
    """F3-3 「我要领走」：对自动生成的 keep1 候选直接 claim-complete 一步到位终态。

    断言：status=2 / flow_type=1 / completed_at 非空 / lost=3 / found=1 /
    审计含 keep1_claim_complete / **全程无 HandoverCode 生成**。
    """
    token_owner, token_finder, lost_id, found_id, match = _keep1_auto_candidate(client, "f303")
    match_id = match["id"]

    r = client.post(f"{API}/matches/{match_id}/claim-complete", headers=auth_header(token_owner), json={})
    assert r.status_code == 200, r.text
    m = r.json()["data"]
    assert m["status"] == 2, f"应一步到位终态已完成，实际 {m['status']}"
    assert m["flow_type"] == 1, "keep1 一步完成应标记 flow_type=1"
    assert m["completed_at"] is not None, "completed_at 应有值"

    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token_owner)).json()["data"]
    found = client.get(f"{API}/found-items/{found_id}", headers=auth_header(token_owner)).json()["data"]
    assert lost["status"] == 3, f"失物应置已解决(3)，实际 {lost['status']}"
    assert found["status"] == 1, f"拾物应置已解决(1)，实际 {found['status']}"

    assert "keep1_claim_complete" in _audit_actions(db, match_id), "应写审计 keep1_claim_complete"

    db.expire_all()
    codes = db.query(HandoverCode).filter(HandoverCode.match_id == match_id).count()
    assert codes == 0, f"keep1 一步完成不应生成交接码，实际 {codes} 条"

    # 防御纵深：终态后拾得者再调 confirm-return 仍被 keep1 守卫 422（不因状态变化而放开）
    r = client.post(f"{API}/matches/{match_id}/confirm-return", headers=auth_header(token_finder))
    assert r.status_code == 422, r.text


def test_f3_04_revoke_then_reclaim_on_auto_candidate(client, db):
    """F3-4 撤回后可再申请（自动候选版）：revoke → refresh-matches 重新召回 → 再次一步完成。

    验证 `_exists_match` 排除终态 {2,3,6} 是"撤回后可再申请"的基础（回归点 §9-2）。
    """
    token_owner, _, lost_id, found_id, match = _keep1_auto_candidate(client, "f304")
    match_id = match["id"]

    client.post(f"{API}/matches/{match_id}/claim-complete", headers=auth_header(token_owner), json={})
    r = client.post(f"{API}/matches/{match_id}/revoke", headers=auth_header(token_owner), json={})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 6, "撤回后应进入终态 status=6"
    assert "keep1_claim_revoke" in _audit_actions(db, match_id), "应写审计 keep1_claim_revoke"

    # 刷新候选 → 同 (lost, found) 再次生成 status=0 候选
    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["created"] == 1, f"撤回后刷新应重新召回同一 keep1 拾物，实际 created={data['created']}"
    again = [m for m in data["matches"] if m["found_id"] == found_id and m["status"] == 0]
    assert again, f"应存在新的 status=0 候选，实际 {[(m['found_id'], m['status']) for m in data['matches']]}"

    # 再次「我要领走」成功
    r = client.post(
        f"{API}/matches/{again[0]['id']}/claim-complete", headers=auth_header(token_owner), json={}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 2, "撤回后同对应可再次一步完成"


# ==================== 变更 A'：keep1 单向性守卫（F3-5 / F3-6 / F3-7 / F3-8） ====================
def test_f3_05_finder_confirm_return_on_keep1_rejected_422(client, db):
    """F3-5 守卫：拾得者对 keep1 自动候选调 confirm-return → 422 / code 9001，且 status 未被改。"""
    _, token_finder, _, _, match = _keep1_auto_candidate(client, "f305")
    match_id = match["id"]

    r = client.post(f"{API}/matches/{match_id}/confirm-return", headers=auth_header(token_finder))
    assert r.status_code == 422, r.text
    assert r.json()["code"] == 9001, r.text

    db.expire_all()
    row = db.get(MatchRecord, match_id)
    assert int(row.status) == 0, f"被守卫拦截后 status 应保持 0，实际 {row.status}"
    assert "confirm_return" not in _audit_actions(db, match_id), "被拦截不应写 confirm_return 审计"


def test_f3_06_finder_reject_on_keep1_rejected_422_no_harassment_loop(client, db):
    """F3-6 守卫：拾得者对 keep1 自动候选调 reject → 422，status 未被打成 3（REJECTED）。

    附加验证设计 §2.3 的"骚扰循环"已被根除：status 仍为 0 → `_exists_match` 阻断 →
    失主刷新候选 `created=0`，不会再召回同一对生成新候选供拾得者反复拒绝。
    """
    token_owner, token_finder, lost_id, found_id, match = _keep1_auto_candidate(client, "f306")
    match_id = match["id"]

    r = client.post(f"{API}/matches/{match_id}/reject", headers=auth_header(token_finder), json={"reason": "不是我的"})
    assert r.status_code == 422, r.text
    assert r.json()["code"] == 9001, r.text

    db.expire_all()
    row = db.get(MatchRecord, match_id)
    assert int(row.status) == 0, f"reject 被守卫拦截后 status 不得变为 3，实际 {row.status}"

    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["created"] == 0, "候选未被打成终态 → 刷新不应重复生成（无骚扰循环）"

    # 失主一侧路径未被守卫误伤：仍可正常一步完成
    r = client.post(f"{API}/matches/{match_id}/claim-complete", headers=auth_header(token_owner), json={})
    assert r.status_code == 200 and r.json()["data"]["status"] == 2, r.text


def test_f3_07_owner_claim_on_keep1_rejected_422(client):
    """F3-7 守卫不回归（AC-A6）：失主对 keep1 自动候选走普通 claim 仍 422 / code 9001。"""
    token_owner, _, _, _, match = _keep1_auto_candidate(client, "f307")

    r = client.post(
        f"{API}/matches/{match['id']}/claim",
        headers=auth_header(token_owner),
        json={"claim_reason": "特征吻合"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == 9001, r.text


def test_f3_08_keep1_candidate_visible_to_finder(client):
    """F3-8 可见性守护（设计 §2.2 方案 1）：keep1 候选在拾得者 `GET /matches` 中**仍可见**。

    单向性由「前端只读 + 后端 422 守卫」两层保证，**不由列表层过滤保证**。
    本用例防止后续误在 `list_my_matches` 的 as_found 分支加 keep_status 过滤
    （那会让拾得者连"已完成/已撤回"记录也一起消失，破坏 PRD US-4）。
    """
    token_owner, token_finder, _, found_id, match = _keep1_auto_candidate(client, "f308")
    match_id = match["id"]

    r = client.get(f"{API}/matches", headers=auth_header(token_finder), params={"page_size": 200})
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    mine = [m for m in items if m["id"] == match_id]
    assert mine, f"拾得者侧应能看到 keep1 候选（只读可见），实际 {[m['id'] for m in items]}"
    assert mine[0]["found_item"]["keep_status"] == 1
    assert mine[0]["status"] == 0

    # 完成后（终态）拾得者侧同样保持可见，保证"善意有没有被接住"的语义连续
    client.post(f"{API}/matches/{match_id}/claim-complete", headers=auth_header(token_owner), json={})
    r = client.get(
        f"{API}/matches", headers=auth_header(token_finder), params={"status": 2, "page_size": 200}
    )
    assert r.status_code == 200, r.text
    assert any(m["id"] == match_id for m in r.json()["data"]["items"]), "已完成记录应在拾得者侧保留可见"


# ==================== 上限 / 回填 / 常量 / 明细 / 软删（F3-9 ~ F3-13） ====================
def test_f3_09_top10_cap_not_broken_by_keep1(client):
    """F3-9 top10 不破（回归点 §9-3 / §2.7 R-3）：12 件 keep1 拾物 + 1 件失物 → 恰好 10 条候选。

    keep1 候选只能经失主侧动作创建，天然受 `scored[:MATCH_TOP_N]` 约束；
    再 `refresh-matches` 应幂等返回 created=0。
    """
    token_finder, _, _, _, _ = register_and_login(client, "f309f")
    token_owner, _, _, _, _ = register_and_login(client, "f309o")
    for i in range(12):
        _publish_found(client, token_finder, "书包", f"捡到第{i}个黑色书包", keep_status="1")

    lost = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")
    lost_id = lost["item"]["id"]
    matches = lost["suspected_matches"]
    assert len(matches) == settings.MATCH_TOP_N, f"应严格取前 10 条候选，实际 {len(matches)}"
    found_ids = [m["found_id"] for m in matches]
    assert len(found_ids) == len(set(found_ids)), "候选不得重复"

    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["created"] == 0, f"候选已满时刷新应幂等 created=0，实际 {data['created']}"
    assert len(data["matches"]) == settings.MATCH_TOP_N, "候选总量仍应为 10"


def test_f3_10_legacy_keep1_self_backfill_via_refresh(client):
    """F3-10 存量自助回填（变更 C）：漏网的 keep1 拾物由失主点一次「刷新候选」即可补入。

    构造"存量"场景：失主先发失物（此时无拾物 → 0 候选）→ keep1 拾物后发（反向早退 → 仍 0 候选）
    → 该 (lost, found) 处于"两条自动路径都没覆盖"的状态 → `refresh-matches` 补入。
    这正是设计 §2.5"不写回填脚本 ≠ 老数据失联"的可执行证明。
    """
    token_owner, _, _, _, _ = register_and_login(client, "f310o")
    token_finder, _, _, _, _ = register_and_login(client, "f310f")
    lost = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")
    lost_id = lost["item"]["id"]
    assert lost["suspected_matches"] == [], "无拾物时不应有候选"

    found_id = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")["item"]["id"]

    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["created"] == 1, f"刷新应补入 1 条 keep1 候选，实际 {data['created']}"
    assert any(m["found_id"] == found_id and m["status"] == 0 for m in data["matches"]), (
        f"补入的应为该 keep1 拾物候选，实际 {[(m['found_id'], m['status']) for m in data['matches']]}"
    )

    # 幂等：再刷一次 created=0
    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.json()["data"]["created"] == 0, "重复刷新应幂等"


def test_f3_11_low_score_and_threshold_constants_decoupled():
    """F3-11 常量断言（变更 B）：MATCH_LOW_SCORE=60 新增，MATCH_THRESHOLD=80 未漂移。

    两者语义完全解耦：60 = 失主侧低分**视觉**弱化阈值（仅前端用）；80 = suspected 判定唯一口径。
    """
    assert settings.MATCH_LOW_SCORE == 60.0, f"低分视觉阈值应为 60.0，实际 {settings.MATCH_LOW_SCORE}"
    assert settings.MATCH_THRESHOLD == 80.0, f"suspected 阈值应保持 80.0，实际 {settings.MATCH_THRESHOLD}"
    assert settings.MATCH_LOW_SCORE < settings.MATCH_THRESHOLD, "低分阈值须严格低于疑似阈值"
    assert settings.MATCH_TOP_N == 10, "候选上限不变"


def test_f3_11b_suspected_semantics_not_drifted_by_low_score(client, db):
    """F3-11b 分数区间语义（§4.5 矩阵后端可测部分）：suspected 仍以 80 为界，与 60 无关。

    60–79 区间的候选：`suspected=false` 但仍是**正常候选**（不被弱化为不可操作），
    解释体 threshold 仍回传 80 —— 这是"删除低分不打扰"后拾得者侧仍显示操作按钮的后端依据。
    """
    token_owner, token_finder, _, _, match = _keep1_auto_candidate(client, "f311")
    match_id = match["id"]

    # 直接改分构造 60–79 与 <60 两档，验证 suspected 口径不随 MATCH_LOW_SCORE 漂移
    for score, expect_suspected in ((85.0, True), (70.0, False), (45.0, False)):
        row = db.get(MatchRecord, match_id)
        row.match_score = score
        db.commit()
        r = client.get(f"{API}/matches", headers=auth_header(token_owner), params={"page_size": 200})
        out = next(m for m in r.json()["data"]["items"] if m["id"] == match_id)
        assert out["suspected"] is expect_suspected, (
            f"score={score} 的 suspected 应为 {expect_suspected}，实际 {out['suspected']}"
        )
        # 拾得者侧同样能看到（60-79 / <60 都不被后端过滤，弱化纯前端视觉）
        r_f = client.get(f"{API}/matches", headers=auth_header(token_finder), params={"page_size": 200})
        assert any(m["id"] == match_id for m in r_f.json()["data"]["items"]), (
            f"score={score} 的候选在拾得者侧不应被后端过滤"
        )


def test_f3_12_score_detail_five_dimensions_on_keep1_candidate(client):
    """F3-12 五维明细完整（回归点 §9-10）：keep1 候选与 keep0 候选的明细口径完全一致。

    断言 photo/category/text/location/time 五维均非 None，total 与 match_score 一致，
    且 total ≈ 五维之和（浮点二次舍入误差 < 0.05）。
    """
    token_owner, _, lost_id, found_id, match = _keep1_auto_candidate(client, "f312")

    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    out = next(m for m in r.json()["data"] if m["found_id"] == found_id)

    dims = ("photo", "category", "text", "location", "time")
    for key in dims:
        assert out.get(key) is not None, f"keep1 候选缺少五维明细 {key}：{out}"
    assert out["text_match_rate"] is not None, "应回传文字词覆盖率原始值"
    assert out["total"] is not None
    assert abs(out["total"] - out["match_score"]) < 0.01, (
        f"total 应与 match_score 一致，实际 {out['total']} vs {out['match_score']}"
    )
    assert abs(out["total"] - sum(out[k] for k in dims)) < 0.05, (
        f"total 应等于五维加权之和，实际 total={out['total']} 五维和={sum(out[k] for k in dims)}"
    )
    # [deprecated] 占位维度恒 0，不因 keep1 路径复活
    assert out["appearance"] == 0.0 and out["feature"] == 0.0


def test_f3_13_soft_deleted_keep1_excluded_from_recall(client, db):
    """F3-13 软删不回归（v7 Q8 / 回归点 §9-8）：软删的 keep1 拾物不进候选。

    删除 `keep_status` 过滤时若误删了同处的 `deleted_at.is_(None)`，本用例会立刻变红。
    """
    token_finder, _, _, _, _ = register_and_login(client, "f313f")
    token_owner, _, _, _, _ = register_and_login(client, "f313o")
    alive_id = _publish_found(client, token_finder, "书包", "捡到黑色书包", keep_status="1")["item"]["id"]
    dead_id = _publish_found(client, token_finder, "书包", "又捡到黑色书包", keep_status="1")["item"]["id"]

    dead = db.get(FoundItem, dead_id)
    dead.deleted_at = datetime(2026, 8, 5, 12, 0, 0)
    db.commit()

    lost = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")
    found_ids = {m["found_id"] for m in lost["suspected_matches"]}
    assert alive_id in found_ids, f"未软删的 keep1 拾物应进候选，实际 {found_ids}"
    assert dead_id not in found_ids, f"软删的 keep1 拾物不得进候选，实际 {found_ids}"


# ==================== F3-14：观察用例（设计 §2.7 R-1，不作为失败判定） ====================
def test_f3_14_observe_keep1_completion_over_active_keep0_claim(client, db):
    """F3-14 **观察用例**（§2.7 R-1，本轮不修，仅记录实际行为）。

    场景：同一失物下同时存在「keep0 认领中(status=1)」与「keep1 待认领候选(status=0)」，
    失主对 keep1 候选一步完成 → `complete_keep1_claim` 不校验 lost.status，直接把
    lost 置 RESOLVED(3)，那条 keep0 CLAIMING 记录会被 `_counterpart_hidden` 对双方隐藏，
    成为悬挂记录。该行为是 **flow-v2 既有行为**（manual 路径同样可触发），非 flow-v3 引入，
    但变更 A 使该路径"从边缘变常规"。

    断言范围仅限"keep1 一步完成本身成功"（确定行为）；悬挂记录的表现写入 `OBSERVATIONS`
    供 QA 报告引用，**不作为失败判定**（避免把待立项问题固化成回归红线）。
    """
    token_owner, _, _, _, _ = register_and_login(client, "f314o")
    token_k0, _, _, _, _ = register_and_login(client, "f314a")
    token_k1, _, _, _, _ = register_and_login(client, "f314b")
    keep0_id = _publish_found(client, token_k0, "书包", "捡到黑色书包", keep_status="0")["item"]["id"]
    keep1_id = _publish_found(client, token_k1, "书包", "又捡到黑色书包", keep_status="1")["item"]["id"]
    lost = _publish_lost(client, token_owner, "书包", "黑色书包", "图书馆丢失黑色书包")
    lost_id = lost["item"]["id"]
    by_found = {m["found_id"]: m for m in lost["suspected_matches"]}
    assert keep0_id in by_found and keep1_id in by_found, "前置：两条候选都应生成"

    # keep0 候选进入认领中
    r = client.post(
        f"{API}/matches/{by_found[keep0_id]['id']}/claim",
        headers=auth_header(token_owner),
        json={"claim_reason": "书包内有我的学生证"},
    )
    assert r.status_code == 200 and r.json()["data"]["status"] == 1, r.text

    # 对 keep1 候选一步完成（确定行为：成功）
    r = client.post(
        f"{API}/matches/{by_found[keep1_id]['id']}/claim-complete",
        headers=auth_header(token_owner),
        json={},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 2, "keep1 一步完成本身应成功（服务层不校验 lost.status）"

    # ---- 以下仅记录实际行为，不做失败判定 ----
    db.expire_all()
    k0_row = db.get(MatchRecord, by_found[keep0_id]["id"])
    owner_ids = {
        m["id"]
        for m in client.get(
            f"{API}/matches", headers=auth_header(token_owner), params={"page_size": 200}
        ).json()["data"]["items"]
    }
    finder_ids = {
        m["id"]
        for m in client.get(
            f"{API}/matches", headers=auth_header(token_k0), params={"page_size": 200}
        ).json()["data"]["items"]
    }
    OBSERVATIONS.append(
        "R-1 观察：lost={lost} 下 keep1 一步完成后，keep0 CLAIMING 记录 id={mid} "
        "库内 status={st}；失主侧可见={o}；keep0 拾得者侧可见={f}".format(
            lost=lost_id,
            mid=k0_row.id,
            st=int(k0_row.status),
            o=k0_row.id in owner_ids,
            f=k0_row.id in finder_ids,
        )
    )
    print("[F3-14 OBSERVATION]", OBSERVATIONS[-1])


# ==================== 前端静态口径守护（变更 B / 单向性，F3-15 ~ F3-17） ====================
# 说明：前端无独立单测框架，此处以「源码静态断言」守护 §4.4 文案与 §4.5 行为矩阵的
# 关键口径，成本极低且能在 CI 中拦截口径漂移；真机渲染仍以 `npm run build` + 人工走查为准。
def test_f3_15_frontend_constants_low_score_60_and_threshold_80_kept():
    """F3-15：`constants.ts` 新增 MATCH_LOW_SCORE=60，且 MATCH_THRESHOLD=80 **必须保留导出**。

    MATCH_THRESHOLD 虽已从 MatchesView 移除引用，但 mockAdapter 仍靠它算 suspected，
    删除会直接打断 mock 演示口径（设计 §7-3）。
    """
    src = _read_web("api/constants.ts")
    assert "export const MATCH_LOW_SCORE = 60" in src, "constants.ts 应导出 MATCH_LOW_SCORE = 60"
    assert "export const MATCH_THRESHOLD = 80" in src, "MATCH_THRESHOLD = 80 不得删除（mock 依赖）"
    assert "export const MATCH_TOP_N = 10" in src


def test_f3_16_matches_view_keep1_and_low_score_copy():
    """F3-16：`MatchesView.vue` 的 §4.4 文案与 §4.5 矩阵关键分支齐备。

    覆盖：失主侧「我要领走」按钮文案、拾得者侧 keep1 只读文案、isLowScore 切 60、
    低分文案常量插值（杜绝硬编码 60）、「低分不打扰」分支已删除、`scoreColor` 配色豁免未被误改。
    """
    src = _read_web("views/MatchesView.vue")

    # 失主侧 keep1 按钮文案 + 二次确认标题（§4.4）
    assert "我要领走" in src, "失主侧 keep1 候选按钮文案应为「我要领走」"
    assert "申请匹配" in src, "keep0 候选按钮文案「申请匹配」不得丢失"
    assert "确认领走" in src, "keep1 二次确认标题应为「确认领走」"
    # 拾得者侧 keep1 只读（§2.2 方案 1 的前端一半）
    assert "留在原地·等待失主自取" in src, "拾得者侧 keep1 应渲染只读文案"
    # keep1 派生判定存在
    assert "isKeep1Candidate" in src, "应存在 isKeep1Candidate 派生函数"

    # 低分口径切 60：isLowScore 必须引用常量而非硬编码
    assert "m.match_score < MATCH_LOW_SCORE" in src, "isLowScore 应改用 MATCH_LOW_SCORE"
    assert "MATCH_LOW_SCORE" in src.split("</template>")[-1], "script 段应引用 MATCH_LOW_SCORE"
    assert "${MATCH_LOW_SCORE}" in src, "低分二次确认文案应走常量插值，不得硬编码 60"
    assert "match_score < MATCH_THRESHOLD" not in src, "低分判定不得再引用 MATCH_THRESHOLD(80)"

    # 「低分不打扰」整体删除（Q2 拍板）
    assert "疑似候选（等待失主申请）" not in src, "「低分不打扰」只读分支应已整体删除"

    # §2.6 陷阱2 豁免：scoreColor 的 80/90 是进度环配色，必须原样保留
    assert "function scoreColor" in src, "scoreColor 配色函数不得被误删"
    assert ">= 90" in src and ">= 80" in src, "scoreColor 的 90/80 三档配色阈值属豁免项，不得改动"


def test_f3_17_mock_adapter_keeps_unidirectional_alignment():
    """F3-17：`mockAdapter.ts` 与后端保持**不对称**口径（设计 §7-1）。

    正向 `genCandidatesForLost` 删除 keep_status 过滤；反向 `handleCreateFound` 的
    isKeep1 早退保留；suspected 仍以 MATCH_THRESHOLD 计算；confirm-return / reject
    补 keep1 拦截以对齐后端 T02。
    """
    src = _read_web("api/mockAdapter.ts")
    assert "f.keep_status === 0" not in src, "mock 正向候选池不得再按 keep_status 过滤（变更 A）"
    assert "isKeep1 ? [] : genCandidatesForFound" in src, "mock 反向 keep1 早退必须保留（单向性）"
    assert "score >= MATCH_THRESHOLD" in src, "mock 的 suspected 仍以 80 为界，不随 60 漂移"
    assert src.count("m.found_item?.keep_status === 1") >= 3, (
        "mock 的 claim / confirm-return / reject 三处均应有 keep1 拦截，与后端守卫对齐"
    )
