"""三重融合匹配集成测试。

验证：拾者描述 F 与失者描述 L2（高度重合）的匹配分 > 与 L1（部分重合）的匹配分；
且 MatchOut.shared_attributes 正确反映失物/拾物标签交集（可解释性）。
"""
from datetime import datetime
from types import SimpleNamespace

from app.services.match_service import MatchService
from app.services.tagging_service import TaggingService
from app.schemas.match import MatchOut

_DEFAULT_DT = datetime(2026, 1, 1, 0, 0, 0)


# 用户原例
F_DESC = "捡到一个钱包，上面有hellokitty图案，粉色的，里面有几张银行卡，比较小巧，巴掌大"
L1_DESC = "我丢了个钱包，蓝色的，很小"
L2_DESC = "我的一个粉色钱包丢了，里面放着我的银行卡，上面印着一个凯蒂猫图案"


def _tags(desc: str) -> list[str]:
    return TaggingService.extract(
        title="丢的钱包", description=desc, vision_label=None, category_name="钱包"
    )


def _item(tags: list[str], description: str = ""):
    """Mock 失物/拾物 ORM 对象，覆盖 LostItemOut/FoundItemOut.from_model 所需全部字段。"""
    return SimpleNamespace(
        id=1,
        publisher_id=1,
        finder_id=1,
        category_id=None,
        category_name="钱包",
        title="钱包",
        description=description,
        images=[],
        color=None,
        tags=tags or [],
        image_hash=None,
        lost_time=_DEFAULT_DT,
        found_time=_DEFAULT_DT,
        created_at=_DEFAULT_DT,
        expires_at=None,
        deleted_at=None,
        status=0,
        keep_status=0,
        contact_allowed=1,
    )


def test_tagging_enriches_description_with_dimensions():
    f_tags = _tags(F_DESC)
    assert "钱包" in f_tags
    assert "粉色" in f_tags
    assert "图案:凯蒂猫" in f_tags
    assert "内含:银行卡" in f_tags
    assert "尺寸:小" in f_tags


def test_l2_scores_higher_than_l1():
    f = _item(_tags(F_DESC))
    l1 = _item(_tags(L1_DESC))
    l2 = _item(_tags(L2_DESC))

    s1 = MatchService().score(l1, f)
    s2 = MatchService().score(l2, f)
    # L2 与 F 高度重合（钱包/粉色/凯蒂猫/银行卡）应显著高于 L1（颜色冲突：蓝 vs 粉）
    assert s2 > s1
    assert s2 > 0


def test_shared_attributes_explainable():
    f = _item(_tags(F_DESC))
    l1 = _item(_tags(L1_DESC))
    l2 = _item(_tags(L2_DESC))

    m1 = SimpleNamespace(id=1, lost_id=1, found_id=1, match_score=0.0, status=0,
                         claim_reason=None, created_at=_DEFAULT_DT, completed_at=None)
    m2 = SimpleNamespace(id=2, lost_id=2, found_id=1, match_score=0.0, status=0,
                         claim_reason=None, created_at=_DEFAULT_DT, completed_at=None)

    out1 = MatchOut.from_model(m1, lost_item=l1, found_item=f)
    out2 = MatchOut.from_model(m2, lost_item=l2, found_item=f)

    # L2 与 F 共享 4 个维度
    assert "钱包" in out2.shared_attributes
    assert "粉色" in out2.shared_attributes
    assert "图案:凯蒂猫" in out2.shared_attributes
    assert "内含:银行卡" in out2.shared_attributes
    # L1 与 F 仅共享 钱包 + 尺寸:小（颜色蓝 vs 粉冲突）
    assert "钱包" in out1.shared_attributes
    assert "尺寸:小" in out1.shared_attributes
    assert "粉色" not in out1.shared_attributes
