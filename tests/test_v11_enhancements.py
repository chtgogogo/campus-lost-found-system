"""v11 增强（2026-08-27）测试：品牌/型号识别、地点归一化、CLIP 两阶段精排、数据飞轮。

覆盖用户拍板的「核心升级」组合（⑤⑥③④），不含已否决的照片取色①/置信度阈值②：
1. 品牌词典：extract_brand / normalize_token / normalize_tokens（纯函数）。
2. 品牌归一化参与打分：feature_factor 让「苹果手机」vs「iPhone」互相命中。
3. 地点归一化：三教→教学楼、3楼→三楼，extract_place 四级抽取改善。
4. CLIP 精排：reorder_match_ids 写 clip_sim；CLIP 不可用静默保持 NULL（降级零风险）。
5. MatchOut.clip_sim 透传。
6. 数据飞轮：发布时用户分类 ≠ 视觉预标 → correction_sample 落库。
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import brand_dict
from app.services import scoring_refs
from app.services.match_service import MatchService


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


# ---------------- 1. 品牌词典（纯函数） ----------------
def test_extract_brand_chinese_and_english():
    assert brand_dict.extract_brand("丢了一部iPhone 14 Pro") == {"苹果"}
    assert brand_dict.extract_brand("华为Mate 60 Pro") == {"华为"}
    assert brand_dict.extract_brand("红米Note 12手机") == {"小米"}
    assert brand_dict.extract_brand("一个普通水杯") == set()
    assert brand_dict.extract_brand(None) == set()


def test_normalize_token_brand_alias():
    assert brand_dict.normalize_token("iphone") == "苹果"
    assert brand_dict.normalize_token("Apple") == "苹果"
    assert brand_dict.normalize_token("红米") == "小米"
    assert brand_dict.normalize_token("苹果手机") == "苹果"
    # 非品牌原样返回（不得误归）
    assert brand_dict.normalize_token("红色") == "红色"
    assert brand_dict.normalize_token("书包") == "书包"


def test_normalize_tokens_batch():
    out = brand_dict.normalize_tokens({"iphone", "Apple", "红色", "书包"})
    assert out == {"苹果", "红色", "书包"}


# ---------------- 1.5 品牌→产品展开（2026-08-28 增强） ----------------
def test_expand_brand_tokens():
    """「苹果15」/「iPhone」→ 品牌+产品双词；「手机」原样。"""
    assert brand_dict.expand_brand_tokens({"苹果15"}) == {"苹果", "手机"}
    assert brand_dict.expand_brand_tokens({"iphone"}) == {"苹果", "手机"}
    assert brand_dict.expand_brand_tokens({"手机"}) == {"手机"}
    assert brand_dict.expand_brand_tokens({"MacBook"}) == {"苹果", "笔记本"}
    assert brand_dict.expand_brand_tokens(None) == set()


def test_brand_product_scoring_order():
    """失主「苹果15」：拾1「手机」应匹配上（>0）；拾2「iPhone」应**显著更高**。

    语义：品牌型号能关联到物品通名（苹果15→手机），且同品牌+同产品双命中分更高。
    """
    from datetime import datetime, timezone

    T = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
    lost = _item(category_name="手机", title="丢了一个苹果15", description="丢了一个苹果15", lost_time=T)
    f_generic = _item(category_name="手机", description="捡到一部手机", found_time=T)
    f_brand = _item(category_name="手机", description="捡到一部iPhone", found_time=T)

    s_generic = MatchService().score(lost, f_generic)
    s_brand = MatchService().score(lost, f_brand)
    assert s_generic > 0, "品牌型号应能匹配上物品通名（苹果15 ↔ 手机）"
    assert s_brand > s_generic, f"iPhone 候选应高于手机候选：{s_brand} vs {s_generic}"
    # iPhone 双命中（苹果+手机）应达疑似线
    assert s_brand >= 80, f"iPhone 候选应疑似（≥80），实际 {s_brand}"


def test_tagging_injects_brand_product():
    """发布标签：『丢了一个苹果15』→ tags 含 苹果（品牌）+ 手机（产品推断）。"""
    from app.services.tagging_service import TaggingService

    tags = TaggingService.extract(title="丢了一个苹果15", description="丢了一个苹果15")
    assert "苹果" in tags, f"应注入品牌词，实际 {tags}"
    assert "手机" in tags, f"应注入产品词（苹果15→手机），实际 {tags}"


# ---------------- 2. 品牌归一化参与打分 ----------------
def test_feature_factor_brand_normalized():
    """features 侧「苹果手机」vs「iPhone」→ 归一为同一品牌词 → 满命中。"""
    lost = _item(category_name="手机", features="苹果手机")
    found = _item(category_name="手机", features="iPhone")
    assert MatchService.feature_factor(lost, found) == 1.0


# ---------------- 3. 地点归一化 ----------------
def test_normalize_location_text():
    assert scoring_refs.normalize_location_text("在三教3楼捡到") == "在第三教学楼三楼捡到"
    assert scoring_refs.normalize_location_text("图书馆3楼") == "图书馆三楼"
    assert scoring_refs.normalize_location_text(None) == ""


def test_extract_place_alias_normalized():
    place, rest = scoring_refs.extract_place("在三教3楼丢的")
    assert place["building"] == {"教学楼"}, f"三教应归一为教学楼，实际 {place['building']}"
    assert place["floor"] == {"三楼"}, f"3楼应归一为三楼，实际 {place['floor']}"


def test_place_score_benefits_from_normalization():
    """失主写「三教」，拾主写「教学楼」→ 归一后 building 层级命中（而非 0）。"""
    lost_place, _ = scoring_refs.extract_place("在三教丢的")
    found_place, _ = scoring_refs.extract_place("在教学楼捡到")
    assert scoring_refs.place_score(lost_place, found_place) == scoring_refs.PLACE_SCORE_ALL_HIT


# ---------------- 4. CLIP 两阶段精排 ----------------
def test_clip_reorder_writes_clip_sim(client, db, monkeypatch):
    import app.services.clip_reorder as cr
    from app.models.item import FoundItem, LostItem
    from app.models.match import MatchRecord
    from app.models.user import User

    ua = User(phone="13800000001", password_hash="x", student_no="clip_a")
    ub = User(phone="13800000002", password_hash="x", student_no="clip_b")
    db.add_all([ua, ub])
    db.flush()
    lost = LostItem(publisher_id=ua.id, category_id=1, category_name="手机", title="iPhone",
                    description="", tags=["手机"], images=["/uploads/a.png"], status=0)
    found = FoundItem(finder_id=ub.id, category_id=1, category_name="手机", description="",
                      tags=["手机"], images=["/uploads/b.png"], status=0,
                      keep_status=0, contact_allowed=1)
    db.add_all([lost, found])
    db.flush()
    m = MatchRecord(lost_id=lost.id, found_id=found.id, match_score=80.0, status=0)
    db.add(m)
    db.commit()
    db.refresh(m)

    monkeypatch.setattr(cr, "_read_first_image_bytes", lambda urls: b"fake-bytes")
    monkeypatch.setattr(cr, "clip_image_similarity", lambda a, b: 0.9123)
    cr.reorder_match_ids([m.id])

    db.refresh(m)
    assert m.clip_sim == pytest.approx(0.9123)


def test_clip_reorder_silent_when_unavailable(client, db, monkeypatch):
    """CLIP 不可用/图片缺失 → clip_sim 保持 NULL，静默降级（激活前行为）。"""
    import app.services.clip_reorder as cr
    from app.models.item import FoundItem, LostItem
    from app.models.match import MatchRecord
    from app.models.user import User

    ua = User(phone="13800000003", password_hash="x", student_no="clip_c")
    ub = User(phone="13800000004", password_hash="x", student_no="clip_d")
    db.add_all([ua, ub])
    db.flush()
    lost = LostItem(publisher_id=ua.id, category_id=1, category_name="手机", title="x",
                    description="", tags=["手机"], images=["/uploads/c.png"], status=0)
    found = FoundItem(finder_id=ub.id, category_id=1, category_name="手机", description="",
                      tags=["手机"], images=["/uploads/d.png"], status=0,
                      keep_status=0, contact_allowed=1)
    db.add_all([lost, found])
    db.flush()
    m = MatchRecord(lost_id=lost.id, found_id=found.id, match_score=80.0, status=0)
    db.add(m)
    db.commit()
    db.refresh(m)

    monkeypatch.setattr(cr, "_read_first_image_bytes", lambda urls: None)
    cr.reorder_match_ids([m.id])
    db.refresh(m)
    assert m.clip_sim is None

    # 再测：读图成功但 CLIP 不可用（返回 None）→ 同样保持 NULL
    monkeypatch.setattr(cr, "_read_first_image_bytes", lambda urls: b"x")
    monkeypatch.setattr(cr, "clip_image_similarity", lambda a, b: None)
    cr.reorder_match_ids([m.id])
    db.refresh(m)
    assert m.clip_sim is None


# ---------------- 5. MatchOut.clip_sim 透传 ----------------
def test_match_out_clip_sim_passthrough():
    from app.schemas.match import MatchOut

    m = SimpleNamespace(
        id=1, lost_id=1, found_id=1, match_score=90.0, status=0,
        claim_reason=None, completed_at=None, flow_type=0,
        created_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        clip_sim=0.87,
    )
    out = MatchOut.from_model(m)
    assert out.clip_sim == 0.87
    m2 = SimpleNamespace(
        id=2, lost_id=1, found_id=1, match_score=90.0, status=0,
        claim_reason=None, completed_at=None, flow_type=0,
        created_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        clip_sim=None,
    )
    out2 = MatchOut.from_model(m2)
    assert out2.clip_sim is None


# ---------------- 6. 数据飞轮（用户纠错样本） ----------------
def test_correction_sample_recorded_on_publish(client, db, monkeypatch):
    """用户分类「雨伞」≠ 视觉预标「书包」→ correction_sample 落库。"""
    from conftest import API, auth_header, register_and_login  # noqa: E402

    from app.models.correction import CorrectionSample
    from app.services.vision_service import get_vision_service

    token, _, _, _, _ = register_and_login(client, "cs")
    vision = get_vision_service()
    monkeypatch.setattr(
        vision, "predict",
        lambda b: {"category_id": 5, "label": "书包", "confidence": 0.8},
    )
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={"title": "丢了一把伞", "description": "红色雨伞", "category_name": "雨伞"},
    )
    assert r.status_code == 200, r.text

    rows = db.query(CorrectionSample).all()
    assert len(rows) == 1, f"应记录 1 条纠错样本，实际 {len(rows)}"
    assert rows[0].vision_label == "书包"
    assert rows[0].final_category_name == "雨伞"
    assert rows[0].item_type == "lost"
    assert rows[0].item_id is not None


def test_no_correction_sample_when_vision_absent(client, db, monkeypatch):
    """视觉不可用（confidence=0 占位）→ 不记录样本（避免脏数据）。"""
    from conftest import API, auth_header, register_and_login  # noqa: E402

    from app.models.correction import CorrectionSample
    from app.services.vision_service import get_vision_service

    token, _, _, _, _ = register_and_login(client, "cs2")
    vision = get_vision_service()
    monkeypatch.setattr(
        vision, "predict",
        lambda b: {"category_id": 5, "label": "书包", "confidence": 0.0},
    )
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={"title": "丢了一把伞", "description": "红色雨伞", "category_name": "雨伞"},
    )
    assert r.status_code == 200, r.text
    assert db.query(CorrectionSample).count() == 0
