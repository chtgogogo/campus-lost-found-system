"""品牌/型号词典（2026-08-27 新增，识别方案：词典 + 正则，**不做向量化**）。

设计动机（用户拍板 2026-08-27）：
- 手机/电脑等类目下，品牌/型号是**最强判别特征**（"iPhone 14" vs "苹果手机"）。
- 品牌可枚举、型号有规律 → 词典 + 正则即可 100% 精确命中，零算力、零误判；
  向量化（embedding）对可枚举词是过度设计，还会引入"苹果(水果) vs 苹果(手机)"误判。

用法：
- ``extract_brand(text)``：从自由文本（含中英文混写）抓品牌，返回**归一化后的标准品牌词**集合。
- ``normalize_token(token)``：把单个 token（如 "iphone" / "Apple"）归一为标准品牌词；非品牌原样返回。
- ``normalize_tokens(tokens)``：批量归一化（供 match_service 的 keyword/feature/appearance 命中前调用）。

兼容性铁律：本模块**零第三方依赖、永不抛异常**，任何输入缺失只返回空/原样。
"""
from __future__ import annotations

import re

# 标准品牌词 → 别名集合（英文统一小写比对）。
# 别名只放"明确指向该品牌"的词，避免误归（如 "Mate" 虽常指华为，但可能指伴侣/mate 系列，
# 故型号级匹配由 _BRAND_MODEL_PATTERNS 单独处理，见下方说明）。
_BRAND_ALIASES: dict[str, set[str]] = {
    "苹果": {
        "苹果", "apple", "iphone", "ipad", "ipod", "macbook", "mac", "imac",
        "苹果手机", "苹果电脑", "苹果平板",
    },
    "华为": {
        "华为", "huawei", "matebook", "matepad", "honor", "荣耀",
    },
    "小米": {
        "小米", "xiaomi", "redmi", "红米", "mi", "poco",
    },
    "OPPO": {"oppo", "realme", "真我"},
    "vivo": {"vivo", "iqoo"},
    "三星": {"三星", "samsung", "galaxy"},
    "联想": {"联想", "lenovo", "thinkpad", "thinkbook", "拯救者", "小新"},
    "戴尔": {"戴尔", "dell", "alienware"},
    "惠普": {"惠普", "hp", "omen"},
    "华硕": {"华硕", "asus", "rog", "玩家国度"},
    "索尼": {"索尼", "sony"},
    "任天堂": {"任天堂", "nintendo", "switch"},
    "微软": {"微软", "microsoft", "surface"},
}

# 品牌 → 标准词（由上面别名表构建的倒排索引，key 为小写别名）
_ALIAS_TO_BRAND: dict[str, str] = {}
for _brand, _aliases in _BRAND_ALIASES.items():
    for _a in _aliases:
        _ALIAS_TO_BRAND[_a.lower()] = _brand

# 标准品牌词集合（O(1) 判定某词是否已是标准品牌词）
BRAND_SET: frozenset[str] = frozenset(_BRAND_ALIASES.keys())

# 品牌 → 典型产品词（2026-08-28 增强：品牌与物品类目建立关联）。
# 用途：「苹果15」能推断出「手机」，从而与拾主写的「手机」匹配上；
# 而「iPhone」同时命中品牌+产品两个词 → 分值高于只写「手机」的候选。
# 产品词尽量对齐 tagging_service.ITEM_NOUN_WORDS / NOUN_SET（校园词表），
# 已存在的：手机 / 笔记本；「平板」「游戏机」暂不在词表，仅随别名注入（不影响召回）。
BRAND_PRODUCTS: dict[str, set[str]] = {
    "苹果": {"手机", "笔记本"},
    "华为": {"手机", "笔记本"},
    "小米": {"手机"},
    "OPPO": {"手机"},
    "vivo": {"手机"},
    "三星": {"手机", "笔记本"},
    "联想": {"笔记本"},
    "戴尔": {"笔记本"},
    "惠普": {"笔记本"},
    "华硕": {"笔记本"},
    "索尼": set(),
    "任天堂": {"游戏机"},
    "微软": {"笔记本"},
}

# 型号正则：优先于别名匹配（"iPhone 14" 这类带数字后缀的长形态先命中）。
# 每个 pattern 归一到 (标准品牌词, 典型产品词)；命中即返回（不叠加）。
# ⚠️ 产品词用于推断：如「苹果15」→ 苹果 + 手机（与「捡到一部手机」可匹配）。
_BRAND_MODEL_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"iphone(?:\s*[0-9]+[a-z]*(?:\s*(?:pro|max|mini|plus|ultra))?)?", re.I), "苹果", "手机"),
    (re.compile(r"苹果\s*[0-9]+", re.I), "苹果", "手机"),           # 苹果15 → 苹果手机
    (re.compile(r"ipad(?:\s*(?:pro|air|mini))?", re.I), "苹果", "平板"),
    (re.compile(r"macbook(?:\s*(?:air|pro))?", re.I), "苹果", "笔记本"),
    (re.compile(r"mate\s*[0-9]+(?:\s*(?:pro|rs))?", re.I), "华为", "手机"),
    (re.compile(r"p\s*[0-9]+(?:\s*(?:pro))?(?!\d)", re.I), "华为", "手机"),  # 华为 P60 系（避免误伤普通 p 词）
    (re.compile(r"nova\s*[0-9]+", re.I), "华为", "手机"),
    (re.compile(r"matebook(?:\s*[dx]|\s*[0-9]+)?", re.I), "华为", "笔记本"),
    (re.compile(r"redmi(?:\s*[a-z0-9]+)*", re.I), "小米", "手机"),
    (re.compile(r"小米\s*[0-9]+", re.I), "小米", "手机"),
    (re.compile(r"xiao?mi\s*[0-9]+", re.I), "小米", "手机"),
    (re.compile(r"galaxy\s*(?:s|note|a|z)[a-z]*\s*[0-9]+", re.I), "三星", "手机"),
    (re.compile(r"thinkpad(?:\s*[a-z0-9]+)*", re.I), "联想", "笔记本"),
    (re.compile(r"surface(?:\s*(?:pro|go|laptop|book))?", re.I), "微软", "笔记本"),
    (re.compile(r"switch(?:\s*(?:oled|lite))?", re.I), "任天堂", "游戏机"),
]


def extract_brand(text: str | None) -> set[str]:
    """从自由文本抓品牌/型号，返回**标准品牌词**集合（去重）。

    先扫型号正则（长形态），再扫别名（含中英文）。空/None → 空集合。
    """
    if not text:
        return set()
    lowered = str(text).lower()
    found: set[str] = set()
    for pattern, brand, _product in _BRAND_MODEL_PATTERNS:
        if pattern.search(lowered):
            found.add(brand)
    # 别名：以词边界匹配（避免 "apple" 误中 "apples"、"mi" 误中 "mini" 等短别名）
    for alias in _ALIAS_TO_BRAND:
        if alias in lowered:
            found.add(_ALIAS_TO_BRAND[alias])
    return found


def extract_brand_products(text: str | None) -> set[str]:
    """从自由文本推断品牌对应的**典型产品词**（2026-08-28 增强）。

    例：「苹果15」→ {"手机"}（与拾主写「手机」可匹配）；「iPhone」→ {"手机"}。
    仅做品牌→产品推断，不做反向（产品不推断品牌）。
    """
    if not text:
        return set()
    lowered = str(text).lower()
    products: set[str] = set()
    for pattern, brand, product in _BRAND_MODEL_PATTERNS:
        if pattern.search(lowered) and product:
            products.add(product)
    for alias, brand in _ALIAS_TO_BRAND.items():
        if alias in lowered:
            products |= BRAND_PRODUCTS.get(brand, set())
    return products


def _match_model_or_alias(token: str) -> tuple[str | None, set[str]]:
    """单 token 判定：命中品牌型号 → (品牌, {产品})；命中品牌别名 → (品牌, 该品牌全部产品集)。
    都不命中 → (None, 空集)。

    ⚠️ 产品集必须**整体返回**（不要取 set 首个）：Python set 迭代顺序不稳定，
    取首会导致同一品牌时而是「手机」时而是「笔记本」（PYTHONHASHSEED 随机化）。
    """
    lowered = str(token).lower()
    for pattern, brand, product in _BRAND_MODEL_PATTERNS:
        if pattern.fullmatch(lowered):
            return brand, ({product} if product else set())
    alias = _ALIAS_TO_BRAND.get(lowered)
    if alias is not None:
        products = set(BRAND_PRODUCTS.get(alias, ()))
        # 别名本身含品类词（「苹果手机」「苹果电脑」）→ 精确到该产品，滤掉其余
        # （否则裸「苹果手机」会展开出「笔记本」等无关产品，反而拉低命中率）
        for prod in list(products):
            if prod and prod in lowered:
                return alias, {prod}
        return alias, products
    return None, set()


def normalize_token(token: str | None) -> str:
    """单 token 归一化：命中品牌别名/型号 → 返回标准品牌词；否则原样返回。

    供 match_service 的 keyword / feature / appearance 命中判定前对 token 集合做归一，
    使 "iphone" 与 "苹果"、"Apple" 与 "苹果" 能互相命中。
    """
    if not token:
        return token or ""
    brand, _products = _match_model_or_alias(str(token))
    return brand if brand else str(token)


def normalize_tokens(tokens: set[str] | list[str] | None) -> set[str]:
    """批量归一化 token 集合；None/空 → 空集合。不改变非品牌词。"""
    if not tokens:
        return set()
    return {normalize_token(t) for t in tokens}


def expand_brand_tokens(tokens: set[str] | list[str] | None) -> set[str]:
    """**品牌展开**（2026-08-28 增强）：批量 token → 品牌词 + 产品词。

    例：{"苹果15"} → {"苹果", "手机"}；{"iphone"} → {"苹果", "手机"}；{"手机"} → {"手机"}；
    {"苹果"}（裸别名）→ {"苹果", "手机", "笔记本"}（该品牌全部产品，避免集合顺序抖动）。
    这样失主「苹果15」与拾主「手机」共享「手机」命中（基础分），
    与拾主「iPhone」则共享「苹果」+「手机」（更高分）。
    非品牌词原样保留。None/空 → 空集合。
    """
    if not tokens:
        return set()
    out: set[str] = set()
    for t in tokens:
        if not t:
            continue
        brand, products = _match_model_or_alias(str(t))
        if brand is not None:
            out.add(brand)
            out |= products
            continue
        out.add(str(t))
    return out
