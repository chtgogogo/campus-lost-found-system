"""QA 独立回归：flow-v2 匹配算法增量落地的边缘用例（严过关 / Edward 独立补充）。

设计原则（与工程师自测解耦，独立视角）：
- 纯函数式：直接用 ``types.SimpleNamespace`` 构造失物/拾物对象，复用 ``MatchService``
  的纯函数打分，不依赖任何模型 / 权重 / DB。
- 仅覆盖 flow-v2 五维公式的「收紧」与「颜色软化」与「其他类纯标签」三处关键变更。

flow-v2 普通类五维公式（合计 100，阈值 80）：
    score = 15·photo + 20·category + 50·text + 10·location + 5·time
「其他」类（任一侧 category_name == "其他"）：
    score = 20·photo + 80·tag_match_rate（tag_match_rate 与 text_match_rate 同口径）
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from app.services.match_service import MatchService


# ---- 构造器（与 test_match.py 同口径，独立副本避免耦合） ----
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


# 同一张"图片"的感知哈希（相同即 photo_sim = 1.0；纯函数，不加载模型）。
_SAME_HASH = "abcdef0123456789"
# 时间相近锚点（同刻 → 时间衰减因子 = 1.0 → time 维度满分 5）。
_ANCHOR = datetime(2026, 7, 16, 10, 0, 0)


# ---------------------------------------------------------------------------
# 用例 A：收紧验证（v10 评分 v2 重标定，测试意图不变）
# 同类 + 同图，但无任何外观/颜色/特征/地点信息，时间相近。
# v10 v2：raw = photo_category 20 + time 10 = 30；失主只提供了「类目 + 时间」
#   → W_provided = 20 + 10 = 30 < MATCH_NORM_MIN_WEIGHT(50) → k = 100/50 = 2.0
#   → total = 30 × 2.0 = 60 < 80 → is_suspected=False。
# 对照：v4 下此类「同图 + 同类 + 时间近」会被封顶到 80（疑似）；v2 因把 70 分
#      预留给「量词/颜色/状态/地点/关键词」而收紧到 60，证明算法升级有效。
# 注：v2 下 `photo` 键 = `photo_category`，`category` 键恒 0（R2 §7.1 旧键映射）。
# ---------------------------------------------------------------------------
def test_case_a_v8_tightened_no_attributes():
    lost = _item(
        image_hash=_SAME_HASH,
        category_name="钥匙",
        lost_time=_ANCHOR,
    )
    found = _item(
        image_hash=_SAME_HASH,
        category_name="钥匙",
        found_time=_ANCHOR,
    )
    s = MatchService().score(lost, found)
    assert s == pytest.approx(60.0, abs=0.01), f"v2 同类同图无属性应得 60，实际 {s}"
    assert MatchService.is_suspected(s) is False, "收紧后应 < 80 阈值，不判疑似"
    # 维度明细：v2 下仅 photo_category 与 time 有贡献，文字七维全 0，appearance/feature 恒 0
    detail = MatchService().score_detail(lost, found)
    assert detail["photo"] == 20.0, "photo = photo_category（同类目 20）"
    assert detail["category"] == 0.0, "category 为 deprecated 占位，恒 0"
    assert detail["appearance"] == 0.0
    assert detail["feature"] == 0.0
    assert detail["time"] == 10.0, "同刻 → 时间维度满分 10"
    assert detail["location"] == 0.0, "location = place，双方均无地点信息"
    assert detail["is_other"] is False
    # 归一化口径：失主只填了「类目 + 时间」→ W=30 被 MATCH_NORM_MIN_WEIGHT 兜到 50
    assert detail["raw_total"] == pytest.approx(30.0, abs=0.01)
    assert detail["norm_factor"] == pytest.approx(2.0, abs=0.01)
    assert detail["provided_dims"] == ["photo_category", "time"]


def test_case_a_v8_below_v4_ceiling():
    """独立断言：v2 下「同图+同类+无其余属性」的得分 < v4 封顶值 80。

    即便无法在本环境重跑 v4 公式，本断言以 v4 封顶 80 为对照上限，
    证明评分 v2 把该类目得分从 v4 的疑似区（80）压到了非疑似区（60）。
    """
    lost = _item(image_hash=_SAME_HASH, category_name="钥匙", lost_time=_ANCHOR)
    found = _item(image_hash=_SAME_HASH, category_name="钥匙", found_time=_ANCHOR)
    s = MatchService().score(lost, found)
    assert s == pytest.approx(60.0, abs=0.01)
    assert s < 80.0, "v2 收紧：该情形得分应低于 v4 封顶的 80"


# ---------------------------------------------------------------------------
# 用例 B：颜色软化验证（v10 评分 v2 重标定，测试意图不变）
# 同类、材质/形状相同，但颜色不同（黑 vs 银）。
# v2：颜色冲突只把 color 维度打到 0（并记 color_conflict 信号），
#     材质/形状仍以 keyword 维度计入（不整条置零）。
#   异色 raw = photo_category 20 + color 0 + keyword 10 + time 10 = 40
#   同色 raw = photo_category 20 + color 20 + keyword 10 + time 10 = 60
#   两侧 W_provided 相同（20+20+10+10=60）→ k = 100/60 = 1.6667
#   → 异色 total = 66.67，同色 total = 100.0
# 故：异色得分(66.67) < 同色得分(100.0)，且两者均 > 0（软化，非整条置零）。
# ---------------------------------------------------------------------------
def _build_color_case(lost_color: str, found_color: str) -> tuple:
    lost = _item(
        category_name="钥匙",
        tags=[lost_color],
        appearance="皮革,圆形",
        lost_time=_ANCHOR,
    )
    found = _item(
        category_name="钥匙",
        tags=[found_color],
        appearance="皮革,圆形",
        found_time=_ANCHOR,
    )
    return lost, found


def test_case_b_color_softened_material_still_counts():
    # 异色：黑 vs 银
    lost_diff, found_diff = _build_color_case("黑色", "银色")
    app_diff = MatchService.appearance_factor(lost_diff, found_diff)
    score_diff = MatchService().score(lost_diff, found_diff)

    # 1) 外观维度因材质/形状重叠而 > 0（颜色冲突仅软化颜色属性，不归零整条）
    assert app_diff > 0.0, f"颜色软化后外观因子应 > 0，实际 {app_diff}"
    assert app_diff == pytest.approx(2 / 3, abs=1e-6), f"应为 2/3，实际 {app_diff}"
    # 2) 整体得分不为 0
    assert score_diff > 0.0, f"软化后整条不应为 0，实际 {score_diff}"
    assert score_diff == pytest.approx(66.67, abs=0.01), f"应为 66.67，实际 {score_diff}"
    # 软化口径：color 归零但 keyword（材质/形状）仍在，且记 color_conflict 信号
    detail_diff = MatchService().score_detail(lost_diff, found_diff)
    assert detail_diff["color"] == 0.0, "颜色冲突 → color 维度归零"
    assert detail_diff["keyword"] == 10.0, "材质/形状仍以 keyword 维度计入（软化非置零）"
    assert "color_conflict" in detail_diff["signals"]

    # 3) 同色对照：黑 vs 黑 → 外观满命中 → 得分更高
    lost_same, found_same = _build_color_case("黑色", "黑色")
    app_same = MatchService.appearance_factor(lost_same, found_same)
    score_same = MatchService().score(lost_same, found_same)
    assert app_same == 1.0, f"同色外观因子应满 1.0，实际 {app_same}"
    assert score_same == pytest.approx(100.0, abs=0.01), f"同色得分应 100，实际 {score_same}"
    # 异色得分 < 同色得分（颜色冲突仅降低、不消除文字/外观维度贡献）
    assert score_diff < score_same, (
        f"异色得分({score_diff})应 < 同色得分({score_same})"
    )


# ---------------------------------------------------------------------------
# 用例 C：「其他」类纯标签匹配（v10 评分 v2 重标定，测试意图不变）
# 两侧均为 category_name=="其他"，共享 tags/appearance/features/location，photo 缺失。
# v2 取消了「20·photo + 80·tag」特殊路径（R2 Q7）：双方均为「其他」时类目无判别力
#   → photo_category 取中性 10（而非 0），其余走统一七维公式。
#   raw = photo_category 10 + color 20 + place 15 + keyword 10 + time 10 = 65
#   W_provided = 20 + 20 + 15 + 10 + 10 = 75 → k = 100/75 = 1.3333
#   → total = 65 × 1.3333 = 86.67 ≥ 80 → is_suspected=True。
# tag_match_rate 作为旧键仍回传 1.0（不再参与总分计算，仅供展示）。
# ---------------------------------------------------------------------------
def test_case_c_other_class_pure_tag_reaches_threshold():
    lost = _item(
        category_name="其他",
        tags=["雨伞", "黑色"],
        appearance="金属",
        features="品牌A",
        location="图书馆三楼",
        lost_time=_ANCHOR,
    )
    found = _item(
        category_name="其他",
        tags=["雨伞", "黑色"],
        appearance="金属",
        features="品牌A",
        location="图书馆三楼",
        found_time=_ANCHOR,
    )
    # v2（Q7）：双方均为「其他」→ 类目无判别力 → photo_category 取中性 10
    detail = MatchService().score_detail(lost, found)
    assert detail["photo"] == 10.0, "双方均为「其他」时 photo_category 取中性 10"
    assert detail["is_other"] is True, "is_other 旧键仍标记「其他」类"

    # 标签命中率应为 1.0（四字段全共享）——旧键保留，但不再参与总分
    tmc = MatchService.tag_match_rate(lost, found)
    assert tmc == 1.0, f"tag_match_rate 应 1.0，实际 {tmc}"

    s = MatchService().score(lost, found)
    assert s == pytest.approx(86.67, abs=0.01), f"「其他」类纯标签全中应得 86.67，实际 {s}"
    assert s >= 80.0, "应达到疑似阈值"
    assert MatchService.is_suspected(s) is True, "应判为疑似匹配"
