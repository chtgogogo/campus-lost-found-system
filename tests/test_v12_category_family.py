"""v12 增量测试：类目家族匹配 + 状态成色词扩充 + 标签预览接口。

覆盖三块改动（PRD-v12）：
1. `category_service`：家族表 / 歧义桥 / affinity（纯函数单测）；
2. 打分接入：`_score_photo_category` 同家族 15 分档（ItemFeatures 单测）；
   状态词表：九成新 vs 磨损 反义冲突、九成新 vs 八成新 同侧命中；
3. 接口：POST /api/v1/tags-preview 返回与发布一致的抽取标签；
   端到端：失主「银行卡」能召回并匹配拾主「校园卡」（同家族兜底）。
"""
from __future__ import annotations

import os

import pytest

from app.core.config import settings
from app.services.category_service import (
    category_affinity,
    family_of,
    same_family,
)
from app.services.match_service import ItemFeatures, MatchService
from app.services.scoring_refs import (
    PHOTO_CAT_FAMILY,
    PHOTO_CAT_SAME,
    extract_states,
    state_score,
)

from conftest import API, PNG, auth_header, register_and_login


# ---------------- 1. 家族服务纯函数 ----------------
class TestCategoryFamily:
    def test_same_family_pairs(self):
        """同家族典型对：证件 / 数码 / 雨具 / 杯壶。"""
        assert same_family("银行卡", "学生证")
        assert same_family("校园卡", "身份证")
        assert same_family("手机", "充电宝")
        assert same_family("雨伞", "遮阳伞")
        assert same_family("水杯", "保温杯")

    def test_cross_family_is_false(self):
        """不同家族 / 未收录词 / 空值 → False。"""
        assert not same_family("书包", "钱包")          # 形态近但语义远，刻意不共族
        assert not same_family("雨伞", "水杯")
        assert not same_family("吉他", "假牙")           # 未收录自由类目
        assert not same_family("手机", "")
        assert not same_family(None, "手机")

    def test_equal_words_are_not_family(self):
        """相等走精确档，same_family 刻意返回 False（打分端先判相等）。"""
        assert not same_family("手机", "手机")

    def test_ambiguity_bridge(self):
        """歧义桥：笔记本（本子）↔ 笔记本电脑（电脑）按同家族处理。"""
        assert same_family("笔记本", "笔记本电脑")
        # 桥只对登记词对生效，不外溢到同族其他词
        assert not same_family("课本", "电脑")

    def test_family_of_and_affinity(self):
        assert family_of("银行卡") == "证件卡类"
        assert family_of("其他") is None
        assert category_affinity("手机", "手机") == 1.0
        assert category_affinity("银行卡", "学生证") == 0.75
        assert category_affinity("雨伞", "水杯") == 0.0


# ---------------- 2. 打分接入 ----------------
def _feat(name: str, cat_id: int | None = None) -> ItemFeatures:
    return ItemFeatures(
        category_id=cat_id,
        category_name=name,
        qty=set(),
        colors=set(),
        states=set(),
        place={lvl: set() for lvl in ("room", "floor", "building", "campus")},
        keywords=set(),
        residual_text="",
    )


class TestPhotoCategoryFamilyScoring:
    def test_family_gets_15(self):
        """同家族不同词：15 分档（介于精确 20 与子串近似 10 之间）。"""
        score = MatchService._score_photo_category(_feat("银行卡"), _feat("学生证"))
        assert score == PHOTO_CAT_FAMILY == 15.0

    def test_exact_still_20(self):
        assert MatchService._score_photo_category(_feat("雨伞"), _feat("雨伞")) == PHOTO_CAT_SAME

    def test_other_category_neutral_unchanged(self):
        other = settings.OTHER_CATEGORY_NAME
        assert MatchService._score_photo_category(_feat(other), _feat(other)) == 10.0
        # 一方「其他」一方具体类目：不进家族档，维持既有 0 分口径
        assert MatchService._score_photo_category(_feat(other), _feat("手机")) == 0.0


class TestStateLevelsV12:
    def test_wear_conflicts_with_intact(self):
        """完好 vs 磨损：同组反义（完好↔破损侧）→ 0 分 + conflict 信号。"""
        score, conflict = state_score({"完好"}, {"磨损"})
        assert score == 0.0 and conflict

    def test_grade_conflicts_with_old(self):
        """九成新 vs 破旧：v18 档位距离化——差 4 档 → 保底 1.0 分、无冲突信号。

        行为变更声明（v18）：旧口径「新旧组跨侧即 0 分 + state_conflict 一票否决」
        已被档位距离分取代（连续谱：丢时九成新、被捡到时显旧，可能是同一把的合理
        折旧）；真正的硬矛盾由完好↔破损反义对与 NEW/DAMAGED 强冲突继续守护
        （见上方 test_wear_conflicts_with_intact）。
        """
        score, conflict = state_score({"九成新"}, {"破旧"})
        assert score == 1.0 and not conflict

    def test_grade_coexists_with_wear(self):
        """九成新 vs 磨损：跨组不判冲突（八成新本就带磨损，判冲突会误伤）。"""
        score, conflict = state_score({"九成新"}, {"磨损"})
        assert not conflict

    def test_same_grade_hits(self):
        """九成新 vs 八成新：v18 档位距离化——相邻档 0.85，不再同侧满分。

        行为变更声明（v18）：相邻档给 0.85 是有意的量化口径（八成新与九成新主观
        折旧差异常在误差内，但不应与完全同档等权）；同档仍是满分（全新 vs 全新）。
        """
        score, conflict = state_score({"九成新"}, {"八成新"})
        assert score == 8.5 and not conflict

    def test_extract_states_new_words(self):
        """新词可从描述文本抽取（「有划痕」含子串「划痕」）。"""
        states, _ = extract_states("外壳有划痕，八成新", {"八成新", "有划痕", "外壳"})
        assert "划痕" in states
        assert "八成新" in states


# ---------------- 3. 接口与端到端 ----------------
class TestTagsPreviewApi:
    def test_preview_returns_tags(self, client):
        token, *_ = register_and_login(client, "v12p")
        r = client.post(
            f"{API}/tags-preview",
            headers=auth_header(token),
            json={
                "title": "黑色雨伞一把",
                "description": "图书馆三楼丢的，伞面有白色星星图案",
                "category_name": "雨伞",
            },
        )
        assert r.status_code == 200, r.text
        tags = r.json()["data"]["tags"]
        assert "雨伞" in tags
        assert "黑色" in tags
        assert "图书馆" in tags

    def test_preview_requires_auth(self, client):
        r = client.post(f"{API}/tags-preview", json={"description": "x"})
        assert r.status_code == 401


class TestFamilyRecallE2E:
    def test_bank_card_matches_campus_card(self, client):
        """端到端：失主「银行卡」（自定义类目）↔ 拾主「校园卡」（系统类目）。

        v12 前该对既不召回（无共享名词 tag）也不给类目分；v12 后同家族召回 + 15 分档。
        """
        # 审查 P0-CI 修复（2026-09-24）：本用例经发布链路接真实视觉——photo_cat 维度
        # 需 best.pt 检出才能拿「同判」20 分档；权重缺失时（CI/裸仓）该维只能拿
        # 「缺失/其他」10 分档，归一化后 raw 上限 35 < 阈值 78，数学上不可能过。
        # 故权重缺失 → skip（与 test_qa_bestpt_regression 的真实图用例同口径），
        # 本地有权重时照常真跑（防回归价值不变）。
        weight_path = os.path.join(settings.YOLO_MODEL_DIR, settings.YOLO_COCO_MODEL)
        if not os.path.exists(weight_path):
            pytest.skip(f"best.pt 权重缺失，photo_cat 维无法达阈值（非阻塞）: {weight_path}")
        token_a, *_ = register_and_login(client, "fa")
        token_b, *_ = register_and_login(client, "fb")

        r = client.post(
            f"{API}/lost-items",
            headers=auth_header(token_a),
            data={
                "title": "银行卡",
                "description": "在图书馆丢了一张银行卡",
                "category_name": "银行卡",
            },
            files={"images": ("lost.png", PNG, "image/png")},
        )
        assert r.status_code == 200, r.text

        r = client.post(
            f"{API}/found-items",
            headers=auth_header(token_b),
            data={
                "keep_status": "0",
                "category_name": "校园卡",
                "description": "图书馆捡到一张校园卡",
            },
            files={"images": ("found.png", PNG, "image/png")},
        )
        assert r.status_code == 200, r.text
        matches = r.json()["data"]["suspected_matches"]
        assert matches, "同家族类目（银行卡 ↔ 校园卡）应触发反向匹配"
