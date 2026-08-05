"""属性抽取（三重融合匹配用，无 LLM）。

用 jieba 中文分词 + 子串兜底，从自由描述文本抽取结构化属性：
``category`` / ``color`` / ``pattern`` / ``contents`` / ``size``。
``to_tags()`` 按前缀约定转成标签，汇入现有 ``TaggingService`` 的标签体系
（``app/services/tagging_service.py``），由 ``MatchService`` 现有打分引擎自然完成
"文本重合度"融合——无需新打分函数、无需大模型。

标签前缀约定：图案=``图案:`` / 内含=``内含:`` / 尺寸=``尺寸:`` ；名词与颜色无前缀。
降级铁律：``extract`` 永不抛异常，缺失返回空字段。
"""
from __future__ import annotations

import re

try:
    import jieba

    jieba.setLogLevel(20)  # 静默
    _JIEBA_OK = True
except Exception:  # pragma: no cover
    _JIEBA_OK = False


# 图案（pattern）归一化
PATTERN_NORM: dict[str, str] = {
    "凯蒂猫": "凯蒂猫",
    "hellokitty": "凯蒂猫",
    "hello kitty": "凯蒂猫",
    "kitty": "凯蒂猫",
    "卡通": "卡通",
    "条纹": "条纹",
    "格子": "格子",
    "纯色": "纯色",
    "花纹": "花纹",
    "星星": "星星",
    "爱心": "爱心",
    "小熊": "小熊",
    "米奇": "米奇",
}
# 内含物（contents）归一化
CONTENTS_NORM: dict[str, str] = {
    "银行卡": "银行卡",
    "储蓄卡": "银行卡",
    "信用卡": "银行卡",
    "卡": "银行卡",
    "身份证": "身份证",
    "学生证": "学生证",
    "校园卡": "校园卡",
    "饭卡": "校园卡",
    "钥匙": "钥匙",
    "现金": "现金",
    "零钱": "现金",
    "耳机": "耳机",
    "数据线": "数据线",
    "充电宝": "充电宝",
    "笔记本": "笔记本",
    "书": "书",
    "课本": "课本",
}
# 尺寸（size）归一化
SIZE_NORM: dict[str, str] = {
    "小巧": "小",
    "巴掌大": "小",
    "迷你": "小",
    "很小": "小",
    "娇小": "小",
    "小": "小",
    "大": "大",
    "巨大": "大",
    "超大": "大",
    "挺大": "大",
}
# 颜色归一化（映射到 tagging_service.COLOR_WORDS 既有词，避免 color_conflict 误判）
COLOR_NORM: dict[str, str] = {
    "粉": "粉色",
    "粉红": "粉色",
    "浅粉": "粉色",
    "玫红": "红色",
    "藏青": "深蓝",
    "天蓝": "浅蓝",
}
# 类目口语别名（与 tagging ITEM_NOUN_WORDS 互补；仅补常见别名）
CATEGORY_NORM: dict[str, str] = {
    "皮夹": "钱包",
    "钱夹": "钱包",
    "钥匙串": "钥匙",
    "雨伞": "雨伞",
}


class AttributeExtractor:
    """从描述文本抽取结构化属性（纯函数式，无状态）。"""

    @staticmethod
    def _tokens(text: str) -> list[str]:
        if not text:
            return []
        if _JIEBA_OK:
            try:
                return [t for t in jieba.cut(text) if t.strip()]
            except Exception:  # pragma: no cover
                pass
        # 兜底：按标点/空白切分
        return [p for p in re.split(r"[\s,，。；;、]+", text) if p]

    @classmethod
    def extract(cls, description: str | None) -> dict:
        """抽取属性 dict。

        Returns:
            ``{"category", "color", "pattern":list, "contents":list, "size"}``，
            未识别字段为 ``None`` / 空 list；任何异常降级为全空，绝不阻断发布。
        """
        try:
            raw = (description or "").lower()
            if not raw:
                return {
                    "category": None,
                    "color": None,
                    "pattern": [],
                    "contents": [],
                    "size": None,
                }
            tokens = cls._tokens(raw)

            def _hit(norm_map: dict[str, str], token_only_singlechar: bool = False) -> set[str]:
                out: set[str] = set()
                for k, v in norm_map.items():
                    if len(k) == 1 and token_only_singlechar:
                        # 单字 key（仅尺寸用）只按 token 精确匹配，避免 "大" 误命中 "巴掌大"
                        if k in tokens:
                            out.add(v)
                    else:
                        # 多字 key / 非尺寸单字 key：子串匹配（覆盖 "hellokitty图案"、"粉色的" 含 "粉"）
                        if k in raw:
                            out.add(v)
                # token 匹配（分词后，覆盖 "巴掌大" 作为独立 token）
                for t in tokens:
                    t2 = t.strip().lower()
                    if t2 in norm_map:
                        out.add(norm_map[t2])
                return out

            pattern = sorted(_hit(PATTERN_NORM))
            contents = sorted(_hit(CONTENTS_NORM))
            # 尺寸：单字 key 仅 token 精确匹配；小优先于大（"巴掌大"语义为小却含"大"字）
            _sz = _hit(SIZE_NORM, token_only_singlechar=True)
            size = "小" if "小" in _sz else ("大" if "大" in _sz else None)
            color = sorted(_hit(COLOR_NORM))[0] if _hit(COLOR_NORM) else None
            category = sorted(_hit(CATEGORY_NORM))[0] if _hit(CATEGORY_NORM) else None

            return {
                "category": category,
                "color": color,
                "pattern": pattern,
                "contents": contents,
                "size": size,
            }
        except Exception:  # 降级铁律
            return {
                "category": None,
                "color": None,
                "pattern": [],
                "contents": [],
                "size": None,
            }

    @staticmethod
    def to_tags(attr: dict) -> list[str]:
        """把属性 dict 转成带前缀的标签列表（保序去重）。"""
        tags: list[str] = []
        seen: set[str] = set()

        def _add(t: str) -> None:
            if t and t not in seen:
                seen.add(t)
                tags.append(t)

        if attr.get("category"):
            _add(attr["category"])
        if attr.get("color"):
            _add(attr["color"])
        for p in attr.get("pattern") or []:
            _add(f"图案:{p}")
        for c in attr.get("contents") or []:
            _add(f"内含:{c}")
        if attr.get("size"):
            _add(f"尺寸:{attr['size']}")
        return tags
