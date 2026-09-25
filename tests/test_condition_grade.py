"""v18 成色/新旧优化测试：档位梯距离分 + 录入档位词抽取 + 缺陷正交共存。"""
from __future__ import annotations

from app.services.scoring_refs import (
    STATE_SCORE_FULL,
    condition_distance_score,
    condition_grade,
    extract_states,
    new_vs_damaged_conflict,
    state_score,
)


# ---------------- 档位提取 ----------------

def test_condition_grade_extraction():
    assert condition_grade({"全新"}) == 0
    assert condition_grade({"95新"}) == 2
    assert condition_grade({"九成新"}) == 3
    assert condition_grade({"五成新"}) == 7
    assert condition_grade({"破旧"}) == 7
    assert condition_grade({"划痕"}) is None, "缺陷词不是档位词"
    assert condition_grade(set()) is None


def test_condition_distance_score_matrix():
    full = {"全新"}
    assert condition_distance_score(full, {"全新"}) == 1.0, "同档满分"
    assert condition_distance_score(full, {"95新"}) == 0.6, "差两档 → 0.6"
    assert condition_distance_score(full, {"九成新"}) == 0.35, "差三档 → 0.35"
    assert condition_distance_score(full, slightly := {"八成新"}) == 0.1, "差四档 → 保底 0.1（改前同侧满分，不合理）"
    assert condition_distance_score({"九成新"}, slightly) == 0.85, "相邻档 0.85"
    assert condition_distance_score({"全新"}, {"破旧"}) == 0.1, "全新 vs 破旧 保底 0.1"
    # 单侧无档位 → None（回退原逻辑中性分，不惩罚未填）
    assert condition_distance_score({"全新"}, {"划痕"}) is None
    assert condition_distance_score(set(), {"全新"}) is None


# ---------------- state_score 集成 ----------------

def test_state_score_uses_condition_distance():
    # 两侧都有档位 → 距离分（全新 vs 八成新差四档：10 × 0.1 = 1）
    score, conflict = state_score({"全新"}, {"八成新"})
    assert score == 1.0 and conflict is False
    # 同档满分
    score, _ = state_score({"全新"}, {"全新"})
    assert score == STATE_SCORE_FULL
    # 一侧无档位（只有缺陷词）→ 走原逻辑（失主有档位词命中不了缺陷 → 零命中 0 分）
    score, conflict = state_score({"全新"}, {"划痕"})
    assert score == 0.0 and conflict is False


def test_mixed_words_fall_back_to_ratio():
    """混合场景（档位词+其它状态词）回落原比例逻辑，其它状态词不被短路吞掉。

    - {"全新","脏"} vs {"全新"}：若按纯距离会满分 10（"脏"被无视）；回落比例逻辑
      → 全新 命中（1/2）→ 5 分，"脏"未对上照常扣。
    - {"新","干净"} vs {"崭新"}：新 命中 崭新 → 5 分（v10 原断言恢复）。
    """
    score, conflict = state_score({"全新", "脏"}, {"全新"})
    assert score == 5.0 and conflict is False
    score, conflict = state_score({"新", "干净"}, {"崭新"})
    assert score == 5.0 and conflict is False


def test_state_score_legacy_pairs_unchanged():
    """非档位反义组（完好↔破损）行为不变：冲突 0 分 + 信号。"""
    score, conflict = state_score({"完好"}, {"破损"})
    assert score == 0.0 and conflict is True
    # 中性分：失主没写状态词
    score, conflict = state_score(set(), {"完好"})
    assert score == 3.0 and conflict is False


def test_new_vs_damaged_conflict_still_works():
    """NEW/DAMAGED 跨组强冲突保留：全新 vs 破损 仍触发（与档位距离正交）。"""
    assert new_vs_damaged_conflict({"全新"}, {"破损"}) is True
    # 中低档位（五成新）不算"新侧"——五成新+破损 合理共存，不触发强冲突
    assert new_vs_damaged_conflict({"五成新"}, {"破损"}) is False


# ---------------- 抽取：新档位词可从自然语言抽出 ----------------

def test_extract_states_recognizes_new_grades():
    from app.services.match_service import MatchService

    toks = MatchService._split_attrs("键盘99新，只有轻微使用痕迹")
    states, _ = extract_states(toks, "键盘99新，只有轻微使用痕迹")
    assert "99新" in states
    toks2 = MatchService._split_attrs("水杯七成新，杯盖有划痕")
    states2, _ = extract_states(toks2, "水杯七成新，杯盖有划痕")
    assert "七成新" in states2 and "划痕" in states2
