"""属性抽取单元测试（三重融合匹配）。

覆盖用户真实描述例子 + 边界（空串/无匹配/英文混排）。
"""
from app.core.attribute_extractor import AttributeExtractor


def test_user_example_full():
    # 用户原例：拾者描述
    text = "捡到一个钱包，上面有hellokitty图案，粉色的，里面有几张银行卡，比较小巧，巴掌大"
    attr = AttributeExtractor.extract(text)
    assert attr["category"] in (None, "钱包")  # 钱包由 tagging 名词补，这里不强制
    assert attr["color"] == "粉色"
    assert "凯蒂猫" in attr["pattern"]
    assert "银行卡" in attr["contents"]
    assert attr["size"] == "小"

    tags = AttributeExtractor.to_tags(attr)
    assert "粉色" in tags
    assert "图案:凯蒂猫" in tags
    assert "内含:银行卡" in tags
    assert "尺寸:小" in tags


def test_loser2_example():
    # 失者2：粉色钱包 + 银行卡 + 凯蒂猫
    text = "我的一个粉色钱包丢了，里面放着我的银行卡，上面印着一个凯蒂猫图案"
    attr = AttributeExtractor.extract(text)
    assert attr["color"] == "粉色"
    assert "凯蒂猫" in attr["pattern"]
    assert "银行卡" in attr["contents"]
    tags = AttributeExtractor.to_tags(attr)
    assert "图案:凯蒂猫" in tags
    assert "内含:银行卡" in tags


def test_loser1_example():
    # 失者1：钱包 + 蓝色 + 很小
    # 注：标准色"蓝色"由 tagging_service.COLOR_WORDS 负责，AttributeExtractor 仅补口语变体
    text = "我丢了个钱包，蓝色的，很小"
    attr = AttributeExtractor.extract(text)
    assert attr["color"] is None  # 蓝色由 tagging 的 COLOR_WORDS 补足
    assert attr["size"] == "小"
    tags = AttributeExtractor.to_tags(attr)
    assert "尺寸:小" in tags


def test_english_mixed_hello_kitty():
    attr = AttributeExtractor.extract("一个 hello kitty 图案的粉色包")
    assert "凯蒂猫" in attr["pattern"]
    assert attr["color"] == "粉色"


def test_empty_and_none():
    assert AttributeExtractor.extract("") == {
        "category": None,
        "color": None,
        "pattern": [],
        "contents": [],
        "size": None,
    }
    assert AttributeExtractor.extract(None)["pattern"] == []


def test_no_match_returns_empty():
    attr = AttributeExtractor.extract("今天天气真好，食堂的饭很好吃")
    assert attr["pattern"] == []
    assert attr["contents"] == []
    assert attr["size"] is None
    assert attr["color"] is None


def test_to_tags_dedup_and_order():
    attr = {
        "category": "钱包",
        "color": "粉色",
        "pattern": ["凯蒂猫"],
        "contents": ["银行卡"],
        "size": "小",
    }
    tags = AttributeExtractor.to_tags(attr)
    assert tags == ["钱包", "粉色", "图案:凯蒂猫", "内含:银行卡", "尺寸:小"]
    # 重复调用不引入重复
    assert AttributeExtractor.to_tags(attr) == tags
