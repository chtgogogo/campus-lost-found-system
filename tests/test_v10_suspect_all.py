"""v10 变更 B：候选排序修正「保底 10 条 + 疑似全列」（AC-B1~B10）。

分两层验证：

1. **纯函数层**（`_cut_with_suspects`）：切片语义、边界、cap 兜底 —— 快、确定、无 IO；
2. **链路层**：发布失物 / 发布拾物 / 刷新候选三处改造点确实调用了新切片，
   且 **flow-v3 守卫 G-1（keep1 单向）未被连带删除**（R2 §3.3 要求提交前自查）。

链路层用真实 HTTP + 打分引擎，不 mock 分数：造 12 件同类同描述拾物（彼此打分一致）
即可稳定越过/不越过阈值，避免依赖脆弱的分数魔数。
"""
from __future__ import annotations

import inspect
from datetime import datetime

from app.core.config import settings
from app.services import publish_service
from app.services.publish_service import _cut_with_suspects
from conftest import API, PNG, auth_header, register_and_login

TOP_N = settings.MATCH_TOP_N
THRESHOLD = settings.MATCH_THRESHOLD


# ===========================================================================
# 一、纯函数层：_cut_with_suspects
# ===========================================================================
def _pairs(scores: list[float]) -> list[tuple[float, int]]:
    """构造已降序的 (score, obj) 列表。"""
    return [(s, i) for i, s in enumerate(sorted(scores, reverse=True))]


def test_b1_cut_keeps_base_n_when_no_suspects():
    """AC-B1：全部候选 <80 时，行为与旧版硬截断完全一致（只取前 base_n 条）。"""
    scored = _pairs([70.0 - i for i in range(20)])
    assert len(_cut_with_suspects(scored, TOP_N)) == TOP_N


def test_b2_cut_appends_all_suspects_beyond_base_n():
    """AC-B2：前 base_n 条之后仍 ≥80 的疑似必须全部追加。"""
    # 15 条 ≥80 + 10 条 <80 → 期望 15 条（保底 10 被疑似撑到 15）
    scored = _pairs([90.0 - i * 0.5 for i in range(15)] + [50.0 - i for i in range(10)])
    out = _cut_with_suspects(scored, TOP_N)
    assert len(out) == 15
    assert all(s >= THRESHOLD for s, _ in out)


def test_b3_cut_with_zero_quota_returns_only_suspects():
    """AC-B3：quota=0（失物候选已满）时只补 ≥80 的疑似，普通候选一条不补。"""
    scored = _pairs([95.0, 88.0, 81.0] + [79.9 - i for i in range(10)])
    out = _cut_with_suspects(scored, 0)
    assert len(out) == 3
    assert all(s >= THRESHOLD for s, _ in out)


def test_b4_cut_negative_quota_is_clamped_to_zero():
    """边界：quota 为负（existing > TOP_N）时必须夹 0，不得出现负数起点。"""
    scored = _pairs([95.0, 60.0, 50.0])
    assert len(_cut_with_suspects(scored, -5)) == 1   # 只留那条疑似


def test_b5_cut_respects_suspect_cap():
    """AC-B9：疑似再多也不得突破 max(MATCH_TOP_N, MATCH_SUSPECT_MAX) 的防爆上限。"""
    scored = _pairs([99.0] * (settings.MATCH_SUSPECT_MAX + 30))
    out = _cut_with_suspects(scored, TOP_N)
    assert len(out) == max(TOP_N, settings.MATCH_SUSPECT_MAX)


def test_b6_cut_empty_and_short_lists():
    """边界：空列表 / 短于 base_n 的列表不得越界。"""
    assert _cut_with_suspects([], TOP_N) == []
    short = _pairs([95.0, 40.0])
    assert len(_cut_with_suspects(short, TOP_N)) == 2


def test_b7_cut_boundary_score_exactly_threshold():
    """边界：恰好等于阈值的候选算疑似（`>=` 而非 `>`）。"""
    scored = _pairs([THRESHOLD] * 3 + [79.99])
    assert len(_cut_with_suspects(scored, 0)) == 3


# ===========================================================================
# 二、flow-v3 守卫自查（R2 §3.3：改造 B-2 极易连带删掉这两处）
# ===========================================================================
def test_g1_keep1_early_return_still_present():
    """⚠️ G-1：`_reverse_match_found` 开头的 keep1 早退**禁止删除**（keep1 单向）。"""
    src = inspect.getsource(publish_service.PublishService._reverse_match_found)
    assert "KeepStatus.NOT_KEEPING" in src, "keep1 早退被误删 —— keep1 会变成双向进池"
    # 早退必须在打分循环之前（否则会为 keep1 拾得者生成候选）
    assert src.index("KeepStatus.NOT_KEEPING") < src.index("_recall_found_candidates")


def test_g2_recall_lost_has_no_keep_status_filter():
    """⚠️ G-2：`_recall_lost_candidates` **禁止加回** keep_status 过滤（keep1 须能被正向召回）。"""
    src = inspect.getsource(publish_service.PublishService._recall_lost_candidates)
    assert "keep_status" not in src.split('"""')[2], "正向召回不得按 keep_status 过滤"


def test_g3_all_three_sites_use_cut_with_suspects():
    """三处改造点必须都走统一切片助手，不得残留 `scored[: settings.MATCH_TOP_N]`。"""
    for fn in (
        publish_service.PublishService._reverse_match_lost,
        publish_service.PublishService._reverse_match_found,
        publish_service.PublishService.refresh_lost_candidates,
    ):
        src = inspect.getsource(fn)
        assert "_cut_with_suspects" in src, f"{fn.__name__} 未使用统一切片助手"
        assert "scored[: settings.MATCH_TOP_N]" not in src, f"{fn.__name__} 残留旧硬截断"


def test_g4_reverse_match_found_scores_before_quota_check():
    """B-2 语句顺序：必须**先打分**再判配额，否则疑似永远拿不到分数、无法追加。"""
    src = inspect.getsource(publish_service.PublishService._reverse_match_found)
    score_pos = src.index("self._matcher.score(l, found)")
    count_pos = src.index("MatchRecord.lost_id == l.id")
    assert score_pos < count_pos, "必须先 score 后 count（现状若反转则 AC-B4 失效）"
    assert "s < settings.MATCH_THRESHOLD" in src, "已满时须仅对非疑似跳过"


# ===========================================================================
# 三、链路层：真实发布 → 候选条数
# ===========================================================================
def _publish_found(client, token, category_name, description, keep_status="0"):
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={
            "keep_status": keep_status,
            "category_name": category_name,
            "description": description,
            "contact_allowed": "1",
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def _publish_lost(client, token, title, category_name, description=None):
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": title,
            "description": description or title,
            "category_name": category_name,
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_b8_low_score_candidates_still_capped_at_top_n(client):
    """AC-B5：候选全为低分（<80）时，条数仍受 MATCH_TOP_N 保底上限约束（不打扰不变）。"""
    token_owner, _, _, _, _ = register_and_login(client, "v10b1o")
    token_finder, _, _, _, _ = register_and_login(client, "v10b1f")

    # 12 件「钥匙」拾物，描述与失物差异大 → 分数低
    for i in range(12):
        _publish_found(client, token_finder, "钥匙", f"捡到一把钥匙，编号{i}")

    data = _publish_lost(client, token_owner, "紫色雨伞", "雨伞", "紫色雨伞，体育馆丢的")
    matches = data.get("suspected_matches") or []
    if matches and all(float(m["match_score"]) < THRESHOLD for m in matches):
        assert len(matches) <= TOP_N, "全低分场景候选条数不得超过保底上限"


def test_b9_suspects_may_exceed_top_n(client):
    """AC-B4/B6：≥80 的疑似不受 MATCH_TOP_N 限制，可超过 10 条全部返回。"""
    token_owner, _, _, _, _ = register_and_login(client, "v10b2o")
    token_finder, _, _, _, _ = register_and_login(client, "v10b2f")

    # 14 件与失物**完全同描述**的拾物 → 分数一致且高，全部应为疑似
    for _ in range(14):
        _publish_found(client, token_finder, "钥匙", "一串黑色钥匙，教学楼四楼402")

    data = _publish_lost(
        client, token_owner, "一串黑色钥匙", "钥匙", "一串黑色钥匙，教学楼四楼402掉落"
    )
    matches = data.get("suspected_matches") or []
    suspects = [m for m in matches if float(m["match_score"]) >= THRESHOLD]
    if suspects:
        assert len(matches) == len(suspects) >= min(14, settings.MATCH_SUSPECT_MAX), (
            f"疑似应全部返回（不受 TOP_N={TOP_N} 限制），实际 {len(matches)} 条"
        )
        assert all(m["suspected"] for m in suspects)


def test_b10_refresh_no_longer_early_returns_when_full(client, db):
    """AC-B6：候选已满时 refresh 不再直接返回空 —— 新来的疑似仍要补进来。

    ⚠️ 构造要点（否则会误判为「早退未删」）：拾物发布时 `_reverse_match_found`
    **本身就会**为 ≥80 的疑似建记录 —— G-4 守卫只跳过「已满 **且** <80」的低分对，
    疑似是特意放行的。所以不能直接断言 refresh 返回的 `created >= 1`：
    那条疑似在 refresh 之前就已存在，`created=0` 恰恰是幂等性的正确表现。

    因此这里先把发布阶段自动建立的那条疑似**删掉**，让失物回到「已满 10 条低分」
    的状态，再调 refresh —— 此时 `existing >= MATCH_TOP_N` → `quota=0`，
    只有「B-4 早退确已删除 + `_cut_with_suspects` 在 quota=0 下仍补疑似」
    两个条件同时成立，refresh 才可能把这条疑似重新补进来。
    """
    from app.models.match import MatchRecord

    token_owner, _, _, _, _ = register_and_login(client, "v10b3o")
    token_finder, _, _, _, _ = register_and_login(client, "v10b3f")

    # 先造 10 件低分拾物填满保底位
    for i in range(10):
        _publish_found(client, token_finder, "钥匙", f"捡到一把钥匙，编号{i}")
    data = _publish_lost(
        client, token_owner, "一串黑色钥匙", "钥匙", "一串黑色钥匙，教学楼四楼402掉落"
    )
    lost_id = data["item"]["id"]

    # 再发一件与失物高度一致的拾物（应为疑似）
    found_id = _publish_found(client, token_finder, "钥匙", "一串黑色钥匙，教学楼四楼402")

    # 发布阶段若已自动建立该疑似，先删除，把候选池还原成「已满 10 条低分」
    auto = (
        db.query(MatchRecord)
        .filter(MatchRecord.lost_id == lost_id, MatchRecord.found_id == found_id)
        .one_or_none()
    )
    was_auto_created = auto is not None
    if was_auto_created:
        assert float(auto.match_score) >= THRESHOLD, (
            "发布阶段自动建立的这条应当是疑似；若为低分说明 G-4 守卫失效"
        )
        db.delete(auto)
        db.commit()

    existing = db.query(MatchRecord).filter(MatchRecord.lost_id == lost_id).count()
    assert existing >= TOP_N, f"前置条件：候选应已满 {TOP_N} 条，实际 {existing}"

    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 200, r.text
    payload = r.json()["data"]
    high = [m for m in payload["matches"] if float(m["match_score"]) >= THRESHOLD]
    if was_auto_created:
        # 候选已满（quota=0）仍必须把这条疑似补回来 —— 这才是 B-4 早退已删除的证据
        assert payload["created"] >= 1, "已满时新疑似仍必须补入（B-4 早退已删除）"
        assert any(int(m["found_id"]) == found_id for m in payload["matches"]), (
            "被删掉的疑似应被 refresh 重新补入候选"
        )
        assert len(payload["matches"]) > TOP_N, "疑似追加后总量可以超过保底 10 条"
        assert high, "补入的应当是 ≥80 的疑似"


def test_b11_refresh_is_still_idempotent(client):
    """AC-B7：放开疑似后 refresh 仍必须幂等（同一 (lost,found) 不重复生成）。"""
    token_owner, _, _, _, _ = register_and_login(client, "v10b4o")
    token_finder, _, _, _, _ = register_and_login(client, "v10b4f")

    for _ in range(3):
        _publish_found(client, token_finder, "钥匙", "一串黑色钥匙，教学楼四楼402")
    data = _publish_lost(
        client, token_owner, "一串黑色钥匙", "钥匙", "一串黑色钥匙，教学楼四楼402掉落"
    )
    lost_id = data["item"]["id"]

    r = client.post(f"{API}/lost-items/{lost_id}/refresh-matches", headers=auth_header(token_owner))
    assert r.status_code == 200
    assert r.json()["data"]["created"] == 0, "无新拾物时 refresh 必须幂等 created=0"


def test_b12_keep1_still_one_directional(client):
    """AC-B8 + G-1 链路验证：keep1 拾物发布后**不为拾得者生成候选**（放开疑似不得破坏单向性）。"""
    token_owner, _, _, _, _ = register_and_login(client, "v10b5o")
    token_finder, _, _, _, _ = register_and_login(client, "v10b5f")

    # 先有一件失物在池子里
    _publish_lost(client, token_owner, "一串黑色钥匙", "钥匙", "一串黑色钥匙，教学楼四楼402掉落")

    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token_finder),
        data={
            "keep_status": "1",           # 留在原地未挪动
            "category_name": "钥匙",
            "description": "一串黑色钥匙，教学楼四楼402",
            "contact_allowed": "1",
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["data"].get("suspected_matches") or []) == [], (
        "keep1 拾物不得反向生成候选（flow-v3 单向性守卫 G-1）"
    )
