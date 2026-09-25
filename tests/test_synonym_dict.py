"""v18 校园同义词词典测试：等价组 / 俚语探测 / 打分端到端（雨伞形态案例）。

案例来自用户真实诉求：失主写「像枪一样的短收缩伞」，拾主写「折叠伞，弯钩柄」——
改前系统认不出（token 必须一字不差），改后经俚语探测 + 等价组互相命中。
"""
from __future__ import annotations

from types import SimpleNamespace

import app.services.match_service as ms
from app.services.match_service import MatchService, _token_hit
from app.services.synonym_dict import SLANG_TO_STANDARD, expand_slang, synonym_lookup


# ---------------- 词典层 ----------------

def test_synonym_groups_bidirectional():
    """等价组两两互等：新组与迁移的存量组都要双向可查。"""
    assert "折叠伞" in synonym_lookup("坨坨伞")
    assert "坨坨伞" in synonym_lookup("折叠伞")
    assert "校园卡" in synonym_lookup("饭卡")
    assert "饭卡" in synonym_lookup("校园卡")
    assert "钥匙扣" in synonym_lookup("钥匙")  # 存量组不回归
    assert synonym_lookup("不存在的词") == set()


def test_expand_slang_substring_and_exact():
    """俚语探测：整块长 token 内含俚语子串 → 标准词注入；俚语独立成 token 同样触发。"""
    expanded = expand_slang({"像枪一样的短收缩伞"})
    assert "枪型" in expanded, "长 token 含「像枪」→ 注入枪型"
    assert "折叠伞" in expanded, "长 token 含「收缩伞」→ 注入折叠伞"
    assert "像枪一样的短收缩伞" in expanded, "原 token 保留（只增不改）"
    assert expand_slang({"像枪"}) == {"像枪", "枪型"}, "俚语独立成 token 也触发"
    assert expand_slang({"手机壳"}) == {"手机壳"}, "通用词不得误触发（手机不在俚语层）"
    assert expand_slang(set()) == set()


def test_slang_targets_exist_in_groups():
    """俚语标准词必须是某等价组成员（保证标准词自身也有同义展开，防笔误悬空）。"""
    from app.services.synonym_dict import _PAIRS

    all_words = set(_PAIRS.keys())
    for standard in SLANG_TO_STANDARD.values():
        assert standard in all_words, f"俚语标准词 {standard} 不在任何等价组中"


# ---------------- 命中层 ----------------

def test_token_hit_zh_synonyms_unconditional(monkeypatch):
    """中文同义命中不再依赖 USE_WORDNET（离线/未装 nltk 也能命中）。"""
    monkeypatch.setattr(ms, "USE_WORDNET", False)
    assert _token_hit("坨坨伞", {"折叠伞"}) is True
    assert _token_hit("饭卡", {"校园卡"}) is True
    assert _token_hit("充电砖", {"移动电源"}) is True
    assert _token_hit("完全无关", {"折叠伞"}) is False


# ---------------- 打分端到端（用户雨伞案例） ----------------

def _umbrella(features: str):
    return SimpleNamespace(
        title=None if "捡" in features else "雨伞",
        description="",
        category_name="雨伞",
        category_id=10,
        tags=["雨伞"],
        appearance=None,
        features=features,
        location="图书馆",
        lost_time=None,
        found_time=None,
    )


def test_umbrella_shape_features_score_together():
    """失主「像枪一样的短收缩伞」vs 拾主「折叠伞，弯钩柄」：特征维度必须 > 0。"""
    lost = SimpleNamespace(
        title="雨伞", description="像枪一样的短收缩伞，上面有白色图案",
        category_name="雨伞", category_id=10, tags=["雨伞"], appearance=None,
        features="枪型伞柄", location="二教", lost_time=None, found_time=None,
    )
    found = SimpleNamespace(
        title=None, description="捡到一把折叠伞，弯钩柄的",
        category_name="雨伞", category_id=10, tags=["雨伞"], appearance=None,
        features="折叠伞, 弯钩柄", location="二教", lost_time=None, found_time=None,
    )
    detail = MatchService().score_detail(lost, found)
    # 特征词实际进入 keyword 维度（v10：旧 feature 键恒 0，特征 token 走文字流水线）：
    # 失主「枪型伞柄」经俚语/等价展开后应被拾主「折叠伞/弯钩柄」词集部分命中
    assert detail["keyword"] > 0, f"关键词维度应得分，实际 {detail}"


def test_umbrella_slang_description_hits_text():
    """失主把形态写进描述（非特征栏）时，文字维度同样受益于俚语探测。"""
    lost = SimpleNamespace(
        title="雨伞", description="一把坨坨伞",
        category_name="雨伞", category_id=10, tags=["雨伞"], appearance=None,
        features=None, location="操场", lost_time=None, found_time=None,
    )
    found = SimpleNamespace(
        title=None, description="捡到折叠伞一把，已放失物处",
        category_name="雨伞", category_id=10, tags=["雨伞"], appearance=None,
        features=None, location="操场", lost_time=None, found_time=None,
    )
    matcher = MatchService()
    lost_tokens = matcher._text_token_set(lost, is_lost=True)
    found_tokens = matcher._text_token_set(found, is_lost=False)
    # 同义命中发生在打分阶段（_token_hit 查等价组），token 集合本身无需出现标准词
    assert _token_hit("坨坨伞", found_tokens) is True, "「坨坨伞」应经等价组命中「折叠伞」"
    hit = sum(1 for t in lost_tokens if _token_hit(t, found_tokens))
    assert hit >= 1, "失主词集应有至少一个 token（坨坨伞）命中拾主词集"
