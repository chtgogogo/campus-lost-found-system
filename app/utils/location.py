"""地点文本相似度（v2 增量设计，决策 Q1 / D2）。

W3 地点因子改为对归一化后的 `lost_location` / `found_location` 文本做相似度计算，
取代旧的 `region_code` 层级命中（§5.3 → §5.3-v2）。

归一化口径（§7.3）：去首尾空格、转小写、合并内部连续空白。
相似度 ∈ [0, 1]，由 `difflib.SequenceMatcher.ratio()` 给出。
- 两者皆为空 → 0.0（无地点信息不给分）。
- 仅其一为空 → 0.0。
"""
from __future__ import annotations

import difflib
import re

_WS_RE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """地点文本归一化：去首尾空格、转小写、合并内部连续空白。"""
    if not text:
        return ""
    return _WS_RE.sub(" ", str(text).strip()).lower()


def location_similarity(a: str | None, b: str | None) -> float:
    """地点文本相似度 ∈ [0, 1]。

    - 两者皆为空 → 0.0
    - 仅其一为空 → 0.0
    - 否则 difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()
    """
    na = normalize(a)
    nb = normalize(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


# 兼容旧调用名（语义一致：对两地点文本计算相似度）。
def text_location_hit(a: str | None, b: str | None) -> float:
    """兼容别名：等同 `location_similarity`。"""
    return location_similarity(a, b)
