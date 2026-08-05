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
# 用例 A：flow-v2 收紧验证
# 同类 + 同图，但无任何外观/颜色/特征/地点信息，时间相近。
# flow-v2：photo=15 + cat=20 + text=25(失物空词集→中性0.5) + time=5 + location=5 = 70 < 80
#     → is_suspected=False。
# 对照：v4 下此类「同图 + 同类 + 时间近」会被封顶到 80（疑似），flow-v2 因把 50 分
#      预留给 text 主维度而明显收紧到 70，证明算法升级有效。
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
    assert s == 70.0, f"flow-v2 同类同图无属性应得 70，实际 {s}"
    assert MatchService.is_suspected(s) is False, "收紧后应 < 80 阈值，不判疑似"
    # 维度明细也应反映：仅 photo/category/text(中性)/time/location 五维贡献，appearance/feature 为 0
    detail = MatchService().score_detail(lost, found)
    assert detail["photo"] == 15.0
    assert detail["category"] == 20.0
    assert detail["appearance"] == 0.0
    assert detail["feature"] == 0.0
    assert detail["time"] == 5.0
    assert detail["location"] == 5.0
    assert detail["is_other"] is False


def test_case_a_v8_below_v4_ceiling():
    """独立断言：flow-v2 下「同图+同类+无其余属性」的得分 < v4 封顶值 80。

    即便无法在本环境重跑 v4 公式，本断言以 v4 封顶 80 为对照上限，
    证明 flow-v2 把该类目得分从 v4 的疑似区（80）压到了非疑似区（70）。
    """
    lost = _item(image_hash=_SAME_HASH, category_name="钥匙", lost_time=_ANCHOR)
    found = _item(image_hash=_SAME_HASH, category_name="钥匙", found_time=_ANCHOR)
    s = MatchService().score(lost, found)
    assert s == 70.0
    assert s < 80.0, "flow-v2 收紧：该情形得分应低于 v4 封顶的 80"


# ---------------------------------------------------------------------------
# 用例 B：颜色软化验证
# 同类、材质/形状相同，但颜色不同（黑 vs 银）。
# flow-v2：颜色冲突仅使 text 词集「颜色词」不命中，材质/形状仍参与（不整条置零）。
#   lost_tokens={黑色,皮革,圆形}(3) ∩ found_tokens={银色,皮革,圆形}(3) = {皮革,圆形}(2)
#   → text_match_rate = 2/3 → text=33.33
#   → score = 20 + 50·(2/3) + 5 + 5 = 63.33 ≠ 0
# 同色（黑 vs 黑）text 满命中 → text=50 → score=80。
# 故：异色得分(63.33) < 同色得分(80)，且两者均 > 0（软化，非整条置零）。
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
    assert score_diff == pytest.approx(63.33, abs=1e-6), f"应为 63.33，实际 {score_diff}"

    # 3) 同色对照：黑 vs 黑 → 外观满命中 → 得分更高
    lost_same, found_same = _build_color_case("黑色", "黑色")
    app_same = MatchService.appearance_factor(lost_same, found_same)
    score_same = MatchService().score(lost_same, found_same)
    assert app_same == 1.0, f"同色外观因子应满 1.0，实际 {app_same}"
    assert score_same == 80.0, f"同色得分应 80，实际 {score_same}"
    # 异色得分 < 同色得分（颜色冲突仅降低、不消除文字/外观维度贡献）
    assert score_diff < score_same, (
        f"异色得分({score_diff})应 < 同色得分({score_same})"
    )


# ---------------------------------------------------------------------------
# 用例 C：「其他」类纯标签匹配
# 两侧均为 category_name=="其他"，共享 tags/appearance/features/location，photo 缺失。
# 失物侧并集 = tags ∪ appearance分词 ∪ features分词 ∪ location分词（全部共享）
#   → tag_match_rate = 1.0
#   → score = 20·photo(0) + 80·1.0 = 80 ≥ 80 → is_suspected=True。
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
    # photo 缺失 → 照片维度贡献应为 0
    detail = MatchService().score_detail(lost, found)
    assert detail["photo"] == 0.0, "photo 缺失时照片维度应为 0"
    assert detail["is_other"] is True, "应走「其他」类特殊路径"

    # 标签命中率应为 1.0（四字段全共享）
    tmc = MatchService.tag_match_rate(lost, found)
    assert tmc == 1.0, f"tag_match_rate 应 1.0，实际 {tmc}"

    s = MatchService().score(lost, found)
    assert s == 80.0, f"「其他」类纯标签全中应得 80，实际 {s}"
    assert s >= 80.0, "应达到疑似阈值"
    assert MatchService.is_suspected(s) is True, "应判为疑似匹配"
