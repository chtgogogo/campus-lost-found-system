"""v10 变更 A：评分引擎 v2 + Q10 归一化（AC-A1~A11）。

纯单元测试，不起 HTTP、不落库 —— 打分是纯函数，用轻量伪物品对象直接驱动
``MatchService``，避免被发布链路的类目解析/视觉降级干扰。

覆盖：
- 黄金用例 A/B/C 的逐维分值、``raw_total``、归一化后 ``total``、``norm_factor``、``signals``；
- 归一化边界（护栏 / 七维全填 k=1 / kill switch / W_provided=0）；
- 颜色合类（同系 / 邻接 / 通配 / 跨系冲突 / 单侧缺失）；
- 量词五档、状态冲突与单字误命中、地点四级、时间衰减；
- ``score_detail`` 的新键与旧键映射（R2 §7.1）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.config import settings
from app.services import color_family, scoring_refs
from app.services.match_service import MatchService, dim_max_scores

# 固定基准时刻，避免测试随真实时间漂移
DAY = datetime(2026, 8, 6, 10, 0, 0)


class FakeItem:
    """轻量伪物品：只携带打分链路读取的字段，全部有默认值（模拟"用户没填"）。"""

    def __init__(self, **kw):
        self.title = None
        self.description = None
        self.tags = []
        self.appearance = None
        self.features = None
        self.location = None
        self.category_id = None
        self.category_name = None
        self.lost_time = None
        self.found_time = None
        self.image_hash = None
        self.image_bytes = None
        for k, v in kw.items():
            setattr(self, k, v)


def _lost(**kw) -> FakeItem:
    """构造失主侧伪物品（默认给类目与 lost_time，贴近真实必填项）。"""
    kw.setdefault("category_id", 1)
    kw.setdefault("category_name", "钥匙")
    kw.setdefault("lost_time", DAY)
    return FakeItem(**kw)


def _found(**kw) -> FakeItem:
    """构造候选侧伪物品（默认同类目、同日拾得）。"""
    kw.setdefault("category_id", 1)
    kw.setdefault("category_name", "钥匙")
    kw.setdefault("found_time", DAY)
    return FakeItem(**kw)


# ---------------------------------------------------------------------------
# 黄金用例（R2 §2.4，QA 直接照抄）
# ---------------------------------------------------------------------------
GOLDEN_LOST = dict(
    title="一串黑色钥匙",
    description="教学楼四楼402掉落",
    tags=["钥匙", "黑色", "教学楼", "四楼"],
)

GOLDEN_CASES = [
    # (名称, 候选描述, 候选 tags, 期望 raw_total, 期望 total, 期望 signals)
    ("A", "一把银色钥匙，教学楼", ["钥匙", "银色", "教学楼"], 45.0, 56.25, ["color_conflict"]),
    ("B", "一把黑色钥匙，402", ["钥匙", "黑色"], 69.0, 86.25, []),
    ("C", "一串钥匙，四楼，黑", ["钥匙", "四楼"], 78.0, 97.5, []),
]


@pytest.fixture
def matcher() -> MatchService:
    """每个用例一个全新 MatchService（隔离实例级 _feature_cache）。"""
    return MatchService()


def test_a1_golden_lost_feature_extraction(matcher):
    """AC-A1：黄金用例失主侧抽取结果必须与 R2 §2.4 完全一致。

    `keywords` 必须为空 —— 「钥匙」∈NOUN_SET、「掉落」∈STOPWORDS_V2；
    若这里非空，W_provided 会从 80 变 90，A/B/C 三条断言会全部失配。
    """
    f = matcher.extract_features(_lost(**GOLDEN_LOST), is_lost=True)
    assert f.qty == {(1, "串")}
    assert f.colors == {"黑色"}
    assert f.states == set()
    assert f.place["room"] == {"402"}
    assert f.place["floor"] == {"四楼"}
    assert f.place["building"] == {"教学楼"}
    assert f.keywords == set(), "残余关键词必须为空，否则归一化分母错"


def test_a2_golden_provided_dims_and_norm_factor(matcher):
    """AC-A2：W_provided=80（20+15+20+15+10）→ k=1.25，且 provided 只由失主侧决定。"""
    detail = matcher.score_detail(_lost(**GOLDEN_LOST), _found(description="一把黑色钥匙，402"))
    assert detail["provided_dims"] == ["photo_category", "qty", "color", "place", "time"]
    assert detail["norm_factor"] == 1.25


@pytest.mark.parametrize("name,desc,tags,raw,total,signals", GOLDEN_CASES)
def test_a3_golden_cases_raw_and_normalized(matcher, name, desc, tags, raw, total, signals):
    """AC-A3：黄金用例 A/B/C 的 raw_total = 45/69/78、total = 56.25/86.25/97.5。"""
    detail = matcher.score_detail(_lost(**GOLDEN_LOST), _found(description=desc, tags=tags))
    assert detail["raw_total"] == pytest.approx(raw), f"候选 {name} raw_total 失配"
    assert detail["total"] == pytest.approx(total), f"候选 {name} total 失配"
    assert detail["norm_factor"] == 1.25
    assert detail["signals"] == signals, f"候选 {name} signals 失配"


def test_a4_golden_per_dimension_breakdown(matcher):
    """AC-A4：黄金用例逐维分值（R2 §2.4 表格）逐格核对。"""
    expected = {
        "一把银色钥匙，教学楼": dict(photo_category=20, qty=5, color=0, state=0, place=10, keyword=0, time=10),
        "一把黑色钥匙，402": dict(photo_category=20, qty=5, color=20, state=0, place=14, keyword=0, time=10),
        "一串钥匙，四楼，黑": dict(photo_category=20, qty=15, color=20, state=0, place=13, keyword=0, time=10),
    }
    lost = _lost(**GOLDEN_LOST)
    for desc, dims in expected.items():
        detail = MatchService().score_detail(lost, _found(description=desc))
        for key, val in dims.items():
            assert detail[key] == pytest.approx(val), f"{desc} 的 {key} 维应为 {val}，实际 {detail[key]}"


def test_a5_golden_ordering_and_suspect_line(matcher):
    """AC-A5：排序 C > B > A；B/C 越过疑似线 80，A 落入 flow-v3 低分弱化区（<60）。"""
    lost = _lost(**GOLDEN_LOST)
    scores = {
        name: MatchService().score(lost, _found(description=desc, tags=tags))
        for name, desc, tags, _, _, _ in GOLDEN_CASES
    }
    assert scores["C"] > scores["B"] > scores["A"]
    assert MatchService.is_suspected(scores["B"]) and MatchService.is_suspected(scores["C"])
    assert not MatchService.is_suspected(scores["A"])
    assert scores["A"] < settings.MATCH_LOW_SCORE, "A 应落入 flow-v3 低分弱化区"


# ---------------------------------------------------------------------------
# 归一化边界（R2 §2.2.4 / §2.2.5）
# ---------------------------------------------------------------------------
def test_a6_norm_min_weight_guard_blocks_pure_photo_false_positive(matcher):
    """AC-A6：只填类目的纯图失物 W_provided=20，护栏把分母抬到 50 → 满分候选仅 40，不误报。"""
    lost = FakeItem(category_id=1, category_name="钥匙")   # 无 lost_time、无任何文字
    detail = matcher.score_detail(lost, _found(description="一串黑色钥匙，教学楼四楼402"))
    assert detail["provided_dims"] == ["photo_category"]
    assert detail["norm_factor"] == pytest.approx(100.0 / settings.MATCH_NORM_MIN_WEIGHT)
    assert detail["total"] == pytest.approx(40.0)
    assert not MatchService.is_suspected(detail["total"]), "纯图失物不得因归一化被误判疑似"


def test_a7_full_seven_dims_gives_k_equals_one(matcher):
    """AC-A7：七维全填 → W_provided=100 → k=1.0（用户明确要求的边界）。"""
    lost = _lost(
        title="一串全新的黑色钥匙",
        description="教学楼四楼402掉落，挂着蜡笔小新挂坠",
        tags=["钥匙"],
    )
    detail = matcher.score_detail(lost, _found(description="一串全新黑色钥匙，教学楼四楼402，蜡笔小新挂坠"))
    assert set(detail["provided_dims"]) == set(dim_max_scores().keys())
    assert detail["norm_factor"] == 1.0
    assert detail["total"] == pytest.approx(detail["raw_total"])


def test_a8_normalize_kill_switch(matcher, monkeypatch):
    """AC-A8：MATCH_NORMALIZE=False → k≡1.0，退回纯 raw 分（AB / 回滚开关）。"""
    monkeypatch.setattr(settings, "MATCH_NORMALIZE", False)
    detail = MatchService().score_detail(_lost(**GOLDEN_LOST), _found(description="一串钥匙，四楼，黑"))
    assert detail["norm_factor"] == 1.0
    assert detail["total"] == pytest.approx(detail["raw_total"]) == pytest.approx(78.0)


def test_a9_zero_provided_weight_degrades_to_one(matcher):
    """边界：W_provided=0（理论不出现）→ k=1.0，不抛异常。"""
    assert matcher._normalize_factor(0.0) == 1.0
    empty = FakeItem()
    detail = matcher.score_detail(empty, FakeItem())
    assert detail["provided_dims"] == []
    assert detail["norm_factor"] == 1.0
    assert 0.0 <= detail["total"] <= 100.0


def test_a10_total_is_clamped_to_100(matcher):
    """边界：raw_total × k > 100 时必须夹到 100。"""
    lost = _lost(title="一串黑色钥匙", description="教学楼四楼402", tags=["钥匙"])
    detail = matcher.score_detail(lost, _found(description="一串黑色钥匙，教学楼四楼402"))
    assert detail["total"] <= 100.0
    assert detail["total"] == pytest.approx(100.0), "完美候选在归一化后应恢复满分上限"


def test_a11_k_depends_only_on_lost_side(matcher):
    """⚠️ 铁律（R2 §2.2.3）：同一件失物的所有候选必须共享同一个 k。"""
    lost = _lost(**GOLDEN_LOST)
    ks = {
        MatchService().score_detail(lost, _found(description=desc, tags=tags))["norm_factor"]
        for _, desc, tags, _, _, _ in GOLDEN_CASES
    }
    # 再加一个「候选什么都没写」的极端情形
    ks.add(MatchService().score_detail(lost, _found())["norm_factor"])
    assert ks == {1.25}, "候选侧信息不得影响归一化系数"


# ---------------------------------------------------------------------------
# 颜色合类（PRD §A.3.4 / color_family.py）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "lost_words,found_words,expected,conflict",
    [
        ({"黑"}, {"黑色"}, color_family.COLOR_SCORE_SAME, False),          # 裸字 vs 带色字
        ({"青"}, {"蓝色"}, color_family.COLOR_SCORE_SAME, False),          # PRD：青归蓝系
        ({"银灰"}, {"灰色"}, color_family.COLOR_SCORE_SAME, False),        # 灰银已合并同系
        ({"灰色"}, {"白色"}, color_family.COLOR_SCORE_ADJACENT, False),    # 邻接：灰银↔白
        ({"紫色"}, {"蓝色"}, color_family.COLOR_SCORE_ADJACENT, False),    # 邻接：紫↔蓝
        ({"彩色"}, {"黑色"}, color_family.COLOR_SCORE_WILDCARD, False),    # 通配词永不冲突
        ({"黑白"}, {"白色"}, color_family.COLOR_SCORE_SAME, False),        # 多归属词任一命中
        ({"黑色"}, {"粉色"}, color_family.COLOR_SCORE_CONFLICT, True),     # 跨系冲突
        (set(), {"黑色"}, color_family.COLOR_SCORE_MISSING, False),        # 失主没填 → 0 不冲突
        ({"黑色"}, set(), color_family.COLOR_SCORE_MISSING, False),        # 候选没填 → 0 不冲突
    ],
)
def test_color_family_scoring(lost_words, found_words, expected, conflict):
    """颜色合类打分与冲突判定（含裸色字 / 通配 / 多归属 / 邻接 / 单侧缺失）。"""
    score, has_conflict = color_family.color_score(lost_words, found_words)
    assert score == expected
    assert has_conflict is conflict


def test_color_longest_word_first():
    """⚠️ 长词优先铁律：`黑白` 不得被切成 `黑`，`银灰色` 不得被切成 `灰色`+`银`。"""
    words, rest = color_family.extract_color_words("黑白条纹的银灰色行李箱")
    assert "黑白" in words and "黑" not in words and "白" not in words
    assert "银灰色" in words and "银" not in words and "灰色" not in words
    assert "银" not in rest and "灰" not in rest, "命中片段必须被消费，不得残留进 keyword"
    # 「+色」变体统一派生，避免逐词枚举漏项
    for w in ("深蓝色", "军绿色", "玫红色", "卡其色"):
        fams, _wild = color_family.color_families_of({w})
        assert fams, f"{w} 应可归类"


def test_color_family_single_source_of_truth():
    """架构约定：13 个色系全部定义在 color_family.py，且邻接表对称。"""
    assert len(color_family.COLOR_FAMILY) == 13
    for fam, neighbours in color_family.ADJACENT_FAMILIES.items():
        for other in neighbours:
            assert fam in color_family.ADJACENT_FAMILIES[other], f"{fam}↔{other} 邻接不对称"


# ---------------------------------------------------------------------------
# 量词 / 状态 / 地点 / 时间
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "lost_pairs,found_pairs,expected",
    [
        ({(1, "串")}, {(1, "串")}, scoring_refs.QTY_SCORE_SAME_CLS_SAME_NUM),   # 15
        ({(1, "把")}, {(2, "把")}, scoring_refs.QTY_SCORE_SAME_CLS_DIFF_NUM),   # 8
        ({(1, "串")}, {(1, "把")}, scoring_refs.QTY_SCORE_DIFF_CLS_SAME_NUM),   # 5
        ({(1, "串")}, {(2, "把")}, scoring_refs.QTY_SCORE_DIFF_CLS_DIFF_NUM),   # 2
        ({(1, "串")}, set(), scoring_refs.QTY_SCORE_FOUND_MISSING),             # 3
        (set(), {(1, "串")}, scoring_refs.QTY_SCORE_LOST_MISSING),              # 0
    ],
)
def test_qty_five_tiers(lost_pairs, found_pairs, expected):
    """量词五档 + 双侧缺失规则（PRD §A.3.3）。"""
    assert scoring_refs.qty_score(lost_pairs, found_pairs) == expected


def test_qty_best_pair_across_multiple():
    """多组量词取最佳配对（与颜色同口径）。"""
    assert scoring_refs.qty_score({(1, "串"), (2, "个")}, {(3, "本"), (1, "串")}) == 15.0


def test_qty_chinese_number_parsing():
    """中文数字解析：一/两/十/十二/二十三 + 阿拉伯数字。"""
    assert scoring_refs.parse_cn_number("一") == 1
    assert scoring_refs.parse_cn_number("两") == 2
    assert scoring_refs.parse_cn_number("十") == 10
    assert scoring_refs.parse_cn_number("十二") == 12
    assert scoring_refs.parse_cn_number("二十三") == 23
    assert scoring_refs.parse_cn_number("3") == 3


def test_state_conflict_and_partial_hit():
    """状态：反义冲突优先置 0 并给信号；同侧近义算命中；部分命中按比例。"""
    assert scoring_refs.state_score({"新"}, {"旧"}) == (scoring_refs.STATE_SCORE_CONFLICT, True)
    assert scoring_refs.state_score({"新"}, {"全新"}) == (scoring_refs.STATE_SCORE_FULL, False)
    score, conflict = scoring_refs.state_score({"新", "干净"}, {"崭新"})
    assert conflict is False
    assert score == pytest.approx(scoring_refs.STATE_SCORE_FULL / 2)
    assert scoring_refs.state_score(set(), {"新"}) == (scoring_refs.STATE_SCORE_MISSING, False)


def test_state_single_char_requires_whole_token():
    """单字状态词必须整 token 命中：`新生`/`空调`/`大门` 不得误判为 新/空/大。"""
    hits, _ = scoring_refs.extract_states("新生 空调 大门", {"新生", "空调", "大门"})
    assert hits == set()
    hits2, _ = scoring_refs.extract_states("很新的 空", {"很新的", "空"})
    assert hits2 == {"新", "空"}


@pytest.mark.parametrize(
    "found_place,expected",
    [
        ({"room": {"402"}, "floor": {"四楼"}, "building": {"教学楼"}, "campus": set()},
         scoring_refs.PLACE_SCORE_ALL_HIT),                 # 全命中 15
        ({"room": {"402"}, "floor": set(), "building": set(), "campus": set()},
         scoring_refs.PLACE_SCORE_ROOM),                    # 最深=房间 14
        ({"room": set(), "floor": {"四楼"}, "building": set(), "campus": set()},
         scoring_refs.PLACE_SCORE_FLOOR),                   # 最深=楼层 13
        ({"room": set(), "floor": set(), "building": {"教学楼"}, "campus": set()},
         scoring_refs.PLACE_SCORE_BUILDING),                # 最深=楼/场所 10
        ({"room": set(), "floor": set(), "building": set(), "campus": set()},
         scoring_refs.PLACE_SCORE_NONE),                    # 无命中 0
    ],
)
def test_place_four_levels(found_place, expected):
    """地点四级：全命中 15，否则按最深命中层级给基础分（PRD §A.3.6）。"""
    lost_place = {"room": {"402"}, "floor": {"四楼"}, "building": {"教学楼"}, "campus": set()}
    assert scoring_refs.place_score(lost_place, found_place) == expected


def test_place_room_regex_does_not_match_phone_number():
    """ROOM_RE 边界：不得从手机号 / 长数字串里截出假房间号。"""
    place, _ = scoring_refs.extract_place("联系13800138000")
    assert place["room"] == set()
    place2, _ = scoring_refs.extract_place("A402 教室")
    assert place2["room"] == {"A402"}


def test_place_campus_level():
    """校区级由 CAMPUS_RE 通用模式抽取（不枚举各校校区名）。"""
    place, _ = scoring_refs.extract_place("东校区图书馆")
    assert place["campus"] == {"东校区"}
    assert place["building"] == {"图书馆"}


def test_time_decay_and_neutral(matcher):
    """时间：同日 10；Δ=τ 时衰减到 10/e；候选无时间 → 中性 5 且仍进分母。"""
    lost = _lost(**GOLDEN_LOST)
    same_day = matcher.score_detail(lost, _found(description="一串黑色钥匙"))
    assert same_day["time"] == pytest.approx(10.0)

    tau = settings.MATCH_TIME_TAU_DAYS
    far = MatchService().score_detail(
        lost, _found(description="一串黑色钥匙", found_time=DAY + timedelta(days=tau))
    )
    # score_detail 对各维度保留两位小数，故容差取 0.01
    assert far["time"] == pytest.approx(10.0 * 0.36787944, abs=0.01)

    no_time = MatchService().score_detail(
        lost, _found(description="一串黑色钥匙", found_time=None)
    )
    assert no_time["time"] == pytest.approx(scoring_refs.TIME_SCORE_NEUTRAL)
    assert "time" in no_time["provided_dims"], "候选没填时间不得改变失主的标尺"


def test_time_not_provided_when_lost_time_missing(matcher):
    """失主无 lost_time → time 维度 provided=False，不进分母。"""
    lost = _lost(lost_time=None, title="一串黑色钥匙", description="教学楼四楼402掉落")
    detail = matcher.score_detail(lost, _found(description="一串黑色钥匙"))
    assert "time" not in detail["provided_dims"]
    assert detail["time"] == 0.0


# ---------------------------------------------------------------------------
# 照片 / 系统分类（PRD §A.3.2，Q7）
# ---------------------------------------------------------------------------
def test_photo_category_tiers(matcher):
    """分类：同类目 20；近似 10；不同 0；缺失 10；双方均「其他」10（Q7 取消特殊路径）。"""
    lost = _lost(description="黑色钥匙")
    assert matcher.score_detail(lost, _found(description="黑色钥匙"))["photo_category"] == 20.0

    diff = MatchService().score_detail(
        lost, _found(category_id=2, category_name="钱包", description="黑色钱包")
    )
    assert diff["photo_category"] == 0.0

    missing = MatchService().score_detail(
        lost, _found(category_id=None, category_name=None, description="黑色钥匙")
    )
    assert missing["photo_category"] == scoring_refs.PHOTO_CAT_NEUTRAL

    other_name = settings.OTHER_CATEGORY_NAME
    both_other = MatchService().score_detail(
        _lost(category_id=99, category_name=other_name, description="黑色物件"),
        _found(category_id=99, category_name=other_name, description="黑色物件"),
    )
    assert both_other["photo_category"] == scoring_refs.PHOTO_CAT_NEUTRAL
    assert both_other["is_other"] is True


def test_photo_category_exact_false_demotes_to_approx(matcher):
    """`exact_category=False` 沿用 flow-v2 `category_hit(exact=False)` 口径 → 降为近似档。"""
    lost = _lost(description="黑色钥匙")
    detail = matcher.score_detail(lost, _found(description="黑色钥匙"), exact_category=False)
    assert detail["photo_category"] == scoring_refs.PHOTO_CAT_APPROX


# ---------------------------------------------------------------------------
# score_detail 契约（R2 §7.1）
# ---------------------------------------------------------------------------
def test_score_detail_new_keys_present(matcher):
    """AC-A9：score_detail 必须输出全部 10 个新键。"""
    detail = matcher.score_detail(_lost(**GOLDEN_LOST), _found(description="一把黑色钥匙，402"))
    for key in (
        "photo_category", "qty", "color", "state", "place", "keyword",
        "signals", "raw_total", "norm_factor", "provided_dims",
    ):
        assert key in detail, f"缺少新键 {key}"


def test_score_detail_legacy_key_mapping(matcher):
    """AC-A10：旧键按 R2 §7.1 映射，老 JSON 消费者不断裂。"""
    detail = matcher.score_detail(_lost(**GOLDEN_LOST), _found(description="一把黑色钥匙，402"))
    assert detail["photo"] == detail["photo_category"]
    assert detail["category"] == 0.0
    text = detail["qty"] + detail["color"] + detail["state"] + detail["place"] + detail["keyword"]
    assert detail["text"] == pytest.approx(text)
    assert detail["text_match_rate"] == pytest.approx(text / 70, abs=1e-4)
    assert detail["location"] == detail["place"]
    assert detail["appearance"] == 0.0 and detail["feature"] == 0.0
    assert detail["total"] == MatchService().score(_lost(**GOLDEN_LOST), _found(description="一把黑色钥匙，402"))


def test_a11_no_magic_numbers_weights_from_config():
    """AC-A11：七维满分全部取自 config.MATCH_W2_*，与档位常量保持一致。"""
    maxima = dim_max_scores()
    assert maxima == {
        "photo_category": 20.0, "qty": 15.0, "color": 20.0,
        "state": 10.0, "place": 15.0, "keyword": 10.0, "time": 10.0,
    }
    assert sum(maxima.values()) == 100.0
    # 档位常量必须与 config 满分一致，否则「满分候选」归一化后拿不到 100
    assert color_family.COLOR_SCORE_SAME == maxima["color"]
    assert scoring_refs.QTY_SCORE_SAME_CLS_SAME_NUM == maxima["qty"]
    assert scoring_refs.STATE_SCORE_FULL == maxima["state"]
    assert scoring_refs.PLACE_SCORE_ALL_HIT == maxima["place"]
    assert scoring_refs.PHOTO_CAT_SAME == maxima["photo_category"]


def test_feature_cache_is_instance_level():
    """`_feature_cache` 必须挂在实例上：两个 MatchService 不共享，避免跨请求泄漏。"""
    a, b = MatchService(), MatchService()
    item = _lost(**GOLDEN_LOST)
    a.extract_features(item, is_lost=True)
    assert a._feature_cache and not b._feature_cache
    # 同实例同对象 → 命中缓存返回同一个 ItemFeatures
    assert a.extract_features(item, is_lost=True) is a.extract_features(item, is_lost=True)


def test_keyword_dimension_hit_rate(matcher):
    """关键词：`10 × 命中数 / 失主残余 token 数`，物品名词与类目名已被排除。

    残余分词为**确定性标点/空白切分**（刻意不用 jieba，见 `_residual_tokens`），
    因此用例文本以标点分隔品牌/图案词。
    """
    lost = _lost(title="黑色钥匙", description="蜡笔小新挂坠，施华洛世奇水钻")
    f = matcher.extract_features(lost, is_lost=True)
    assert f.keywords == {"蜡笔小新挂坠", "施华洛世奇水钻"}
    assert "钥匙" not in f.keywords, "物品名词必须排除"

    full = MatchService().score_detail(lost, _found(description="蜡笔小新挂坠，施华洛世奇水钻"))
    assert full["keyword"] == pytest.approx(settings.MATCH_W2_KEYWORD)

    half = MatchService().score_detail(lost, _found(description="施华洛世奇水钻"))
    assert half["keyword"] == pytest.approx(settings.MATCH_W2_KEYWORD / 2)

    none = MatchService().score_detail(lost, _found(description="没有任何附加特征"))
    assert none["keyword"] == 0.0
