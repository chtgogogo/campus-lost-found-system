"""颜色合类表（v10 评分引擎 v2 的**颜色维度单一事实源**）。

架构约定（R2 §10.3）：颜色归类只有这一份实现。
禁止在 `match_service.py` / `tagging_service.py` / 前端再各写一份 —— 前端如需展示色系，
一律通过 `score_detail.signals` 与后端明细，**不自行判色**。

三类词：
- **普通色系词**：归入 `COLOR_FAMILY` 的 13 个色系之一（PRD §A.3.4 表）。
  须同时兼容「带色字」（黑色）与「裸色字」（黑）两种写法 —— 演算示例 C 用的就是裸字「黑」。
- **通配词**（`WILDCARD_WORDS`，如「彩色」）：与任意色系**都不冲突**，给近似分（U4）。
- **多归属词**（`MULTI_FAMILY_WORDS`，如「黑白」）：同时归入多个色系，任一命中即算同系（U4）。

⚠️ **长词优先铁律**（R2 §10.14）：`COLOR_WORDS_V2` 已按「长度降序 + 特殊词前置」排好序，
遍历必须使用该顺序，否则 `黑白`→`黑`、`银灰`→`银`、`浅蓝`→`蓝` 会被误切成错误色系。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 13 色系（PRD §A.3.4，色系名 → 归入词集合）
# ---------------------------------------------------------------------------
COLOR_FAMILY: dict[str, frozenset[str]] = {
    "黑系": frozenset({"黑", "黑色", "乌", "乌黑", "墨", "漆黑"}),
    "白系": frozenset({"白", "白色", "米白", "奶白", "米色", "乳白"}),
    "灰银系": frozenset({"灰", "灰色", "银灰", "银", "银白", "银色", "浅灰", "深灰"}),
    "棕系": frozenset({"棕", "棕色", "咖啡", "咖啡色", "卡其", "卡其色", "驼", "驼色", "栗", "栗色", "褐", "褐色"}),
    "红系": frozenset({"红", "红色", "朱红", "橙红", "酒红", "玫红", "大红", "深红"}),
    "橙系": frozenset({"橙", "橙色", "橘", "橘色", "橘黄"}),
    "黄系": frozenset({"黄", "黄色", "鹅黄", "金黄", "淡黄", "浅黄"}),
    "绿系": frozenset({"绿", "绿色", "草绿", "墨绿", "浅绿", "深绿", "军绿"}),
    # PRD 明确：青归蓝系
    "蓝系": frozenset({"蓝", "蓝色", "青", "青色", "湖蓝", "天蓝", "浅蓝", "深蓝", "藏青", "宝蓝"}),
    "粉系": frozenset({"粉", "粉色", "粉红", "桃粉", "浅红", "浅粉"}),
    "紫系": frozenset({"紫", "紫色", "紫罗兰", "藕荷", "浅紫", "深紫"}),
    "金系": frozenset({"金", "金色", "香槟金", "土豪金"}),
    "透明系": frozenset({"透明", "无色", "全透明", "半透明"}),
}

# ---------------------------------------------------------------------------
# 通配词（U4）：与任意色系都不冲突，只给近似分，绝不置 color_conflict
# ---------------------------------------------------------------------------
WILDCARD_WORDS: frozenset[str] = frozenset({"彩色", "多色", "花色", "混色", "撞色"})

# ---------------------------------------------------------------------------
# 多归属词（U4）：一个词同时属于多个色系，任一命中即算同系
# ---------------------------------------------------------------------------
MULTI_FAMILY_WORDS: dict[str, frozenset[str]] = {
    "黑白": frozenset({"黑系", "白系"}),
    "黑白色": frozenset({"黑系", "白系"}),
}

# ---------------------------------------------------------------------------
# 邻接色系（U4）：视觉上易混淆，给近似分而非判冲突。
# 「灰↔银」在 R2 已合并为同一「灰银系」，故此处只保留 灰银↔白、棕↔黄、粉↔红、紫↔蓝、金↔黄。
# 下方 _ADJACENCY 会自动补齐对称方向，声明时只需写一次。
# ---------------------------------------------------------------------------
_ADJACENT_PAIRS: tuple[tuple[str, str], ...] = (
    ("灰银系", "白系"),
    ("棕系", "黄系"),
    ("粉系", "红系"),
    ("紫系", "蓝系"),
    ("金系", "黄系"),
)


def _build_adjacency() -> dict[str, frozenset[str]]:
    """由 `_ADJACENT_PAIRS` 构建**对称**邻接表，避免手写两遍导致单向遗漏。"""
    acc: dict[str, set[str]] = {name: set() for name in COLOR_FAMILY}
    for a, b in _ADJACENT_PAIRS:
        acc.setdefault(a, set()).add(b)
        acc.setdefault(b, set()).add(a)
    return {k: frozenset(v) for k, v in acc.items()}


ADJACENT_FAMILIES: dict[str, frozenset[str]] = _build_adjacency()

# ---------------------------------------------------------------------------
# 词 → 色系集合 的反向索引（多归属词映射到多个色系；通配词映射到空集 + 单独标记）
# ---------------------------------------------------------------------------
_WORD_TO_FAMILIES: dict[str, frozenset[str]] = {}
for _family, _words in COLOR_FAMILY.items():
    for _w in _words:
        # 同一个词若被两张表同时收录，取并集（当前表无此情况，防御性写法）
        _WORD_TO_FAMILIES[_w] = _WORD_TO_FAMILIES.get(_w, frozenset()) | frozenset({_family})
        # ⚠️ 自动补「+色」变体（如 银灰 → 银灰色、深蓝 → 深蓝色）。
        # 必须有：否则 `银灰色` 会被同长度、字典序更靠前的 `灰色` 先切走，残留的 `银`
        # 再被单字规则命中，结果虽仍落在「灰银系」但抽词结果错误；换成 `军绿色`
        # （`绿色` 先命中）等组合时更会污染 keyword 残余集合。
        # 逐词枚举 3 字形态易漏，故在此由 2 字词统一派生，保证长词优先铁律真正生效。
        if not _w.endswith("色"):
            _plus = _w + "色"
            _WORD_TO_FAMILIES[_plus] = _WORD_TO_FAMILIES.get(_plus, frozenset()) | frozenset({_family})
for _w, _fams in MULTI_FAMILY_WORDS.items():
    _WORD_TO_FAMILIES[_w] = _WORD_TO_FAMILIES.get(_w, frozenset()) | _fams

# ---------------------------------------------------------------------------
# 全部颜色词，**长度降序**（长词优先铁律）。同长度时按字典序保证确定性。
# 通配词也在其中，抽取时一并消费，避免「彩色」残留进 keyword 残余集合。
# ---------------------------------------------------------------------------
COLOR_WORDS_V2: tuple[str, ...] = tuple(
    sorted(set(_WORD_TO_FAMILIES) | set(WILDCARD_WORDS), key=lambda w: (-len(w), w))
)

# ---------------------------------------------------------------------------
# 颜色维度档位分值（AC-A11：无魔法数字，全部来自模块常量）
# ---------------------------------------------------------------------------
COLOR_SCORE_SAME: float = 20.0        # 同色系（黑 vs 黑色、青 vs 蓝）
COLOR_SCORE_ADJACENT: float = 10.0    # 近似色系（邻接表命中）
COLOR_SCORE_WILDCARD: float = 10.0    # 任一侧为通配词「彩色」
COLOR_SCORE_CONFLICT: float = 0.0     # 跨系冲突（黑 vs 粉）→ 0 + color_conflict
COLOR_SCORE_MISSING: float = 0.0      # 任一侧无颜色 → 0，且**不判冲突**

# 冲突信号名（与 score_detail.signals / 前端红色角标约定一致）
SIGNAL_COLOR_CONFLICT: str = "color_conflict"


def color_families_of(words) -> tuple[set[str], bool]:
    """把一组颜色词映射为「色系集合 + 是否含通配词」。

    Args:
        words: 任意可迭代的颜色词（如 `{"黑色", "彩色"}`）。非颜色词会被静默忽略。

    Returns:
        `(families, has_wildcard)`：
        - `families`：命中的色系名集合，如 `{"黑系"}`；`黑白` 会展开成 `{"黑系", "白系"}`。
        - `has_wildcard`：是否出现「彩色」这类通配词。
    """
    families: set[str] = set()
    has_wildcard = False
    for w in words or ():
        token = str(w).strip()
        if not token:
            continue
        if token in WILDCARD_WORDS:
            has_wildcard = True
            continue
        fams = _WORD_TO_FAMILIES.get(token)
        if fams:
            families |= set(fams)
    return families, has_wildcard


def extract_color_words(text: str) -> tuple[set[str], str]:
    """从文本中**消费式**抽取颜色词（长词优先）。

    「消费式」= 命中的片段会被替换为空格从返回文本中移除，避免同一片段
    在后续量词/状态/关键词阶段被重复计分（R2 §2.3 流水线不可乱序的原因）。

    Args:
        text: 待抽取文本。

    Returns:
        `(命中的颜色词集合, 扣除命中片段后的剩余文本)`。
    """
    if not text:
        return set(), text or ""
    remaining = str(text)
    hits: set[str] = set()
    for word in COLOR_WORDS_V2:
        if word and word in remaining:
            hits.add(word)
            remaining = remaining.replace(word, " ")
    return hits, remaining


def color_score(lost_words, found_words) -> tuple[float, bool]:
    """颜色一致性打分（0–20）+ 冲突信号（PRD §A.3.4）。

    多色 vs 多色取**最佳配对**：任一对同系 → 20；否则任一对近似/通配 → 10；全部跨系 → 0 + 冲突。

    Args:
        lost_words: 失主侧颜色词集合。
        found_words: 候选侧颜色词集合。

    Returns:
        `(score, conflict)`。`conflict=True` 时 `score` 恒为 `COLOR_SCORE_CONFLICT`(0)，
        调用方须把 `SIGNAL_COLOR_CONFLICT` 写入 `score_detail.signals`。
        **不做整条置零**（沿用 flow-v2「软化」原则，避免误伤）。
    """
    lost_fams, lost_wild = color_families_of(lost_words)
    found_fams, found_wild = color_families_of(found_words)

    # 失主侧无颜色 → 该维度 provided=False，得 0 且不判冲突（共性规则 A.3.1）
    if not lost_fams and not lost_wild:
        return COLOR_SCORE_MISSING, False
    # 候选侧无颜色 → 0 分但**不判冲突**（候选没写不等于颜色不同）
    if not found_fams and not found_wild:
        return COLOR_SCORE_MISSING, False

    # 同色系（含 黑白 的任一分支命中）
    if lost_fams & found_fams:
        return COLOR_SCORE_SAME, False

    # 通配词「彩色」：与任意色系都不冲突，给近似分
    if lost_wild or found_wild:
        return COLOR_SCORE_WILDCARD, False

    # 邻接色系
    for fam in lost_fams:
        if ADJACENT_FAMILIES.get(fam, frozenset()) & found_fams:
            return COLOR_SCORE_ADJACENT, False

    # 全部跨系 → 冲突
    return COLOR_SCORE_CONFLICT, True
