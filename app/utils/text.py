"""关键词分词与 Jaccard 相似度（纯函数）。

- 英文：小写 + 按非字母数字切分。
- 中文：字符级 unigram + bigram（无需外部分词库，简单可复现）。
- Jaccard = |A∩B| / |A∪B|，值域 [0,1]。
"""
from __future__ import annotations

import re
from typing import Iterable, Set

_ENGLISH_RE = re.compile(r"[a-zA-Z0-9]+")
_CJK_RE = re.compile(r"[一-鿿]")


def tokenize(text: str | None) -> Set[str]:
    """对文本分词，返回 token 集合。"""
    if not text:
        return set()
    lowered = str(text).lower()
    tokens: Set[str] = set()

    # 英文 / 数字
    for m in _ENGLISH_RE.findall(lowered):
        if len(m) >= 2:  # 过滤单字符噪声
            tokens.add(m)

    # 中文：unigram + bigram
    cjk_chars = _CJK_RE.findall(lowered)
    if cjk_chars:
        for ch in cjk_chars:
            tokens.add(ch)
        for i in range(len(cjk_chars) - 1):
            tokens.add(cjk_chars[i] + cjk_chars[i + 1])

    return tokens


def jaccard(set_a: Set[str], set_b: Set[str]) -> float:
    """集合 Jaccard 相似度。"""
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def keyword_jaccard(text_a: str | None, text_b: str | None) -> float:
    """对两段文本做分词后的 Jaccard 相似度。"""
    return jaccard(tokenize(text_a), tokenize(text_b))


def tag_jaccard(tags_a: list[str] | None, tags_b: list[str] | None) -> float:
    """对两段结构化标签列表做集合 Jaccard 相似度（v3 匹配第二路因子）。

    输入为 `TaggingService.extract` 产出的标签数组；空/None 视为空集。
    """
    set_a = set(tags_a or [])
    set_b = set(tags_b or [])
    return jaccard(set_a, set_b)
