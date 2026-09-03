"""评分参考数据（v10 评分引擎 v2 的**量词 / 状态 / 地点 / 停用词单一事实源**）。

与 `color_family.py` 并列：颜色归 `color_family.py`，其余四类子维度的词表、正则与
**档位分值**全部归本模块。打分函数（`match_service.py`）里不得出现魔法数字（AC-A11）。

包含：
- 量词：`QTY_CLASSIFIERS` / `CN_NUM_MAP` / `QTY_RE` + `extract_qty()` + 五档分值
- 状态：`STATE_WORD_PAIRS`（反义对）/ `STATE_WORDS` + `extract_states()` + `state_score()`
- 地点：`ROOM_RE` / `CAMPUS_RE` / `LOCATION_LEVELS` + `extract_place()` + `place_score()` + 四级分值
- 停用词：`STOPWORDS_V2`（在 flow-v2 `_STOPWORDS` 基础上扩充无判别力动词短语）
"""
from __future__ import annotations

import re

from app.services.tagging_service import LOCATION_WORDS, normalize_location_text

# ===========================================================================
# 一、量词（PRD §A.3.3）
# ===========================================================================
# 量词字符类，沿用 flow-v2 `_QTY_PREFIX_RE` 的既有集合，保证抽词行为一致
QTY_CLASSIFIERS: str = "个把张只条部串双对辆台本支根件枚"

# 中文数字 → int。「两」与「二」等价；「十」单独出现记 10。
CN_NUM_MAP: dict[str, int] = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# (数量, 量词) 二元组抽取正则。数量部分允许中文数字串或阿拉伯数字。
QTY_RE = re.compile(rf"([一二两三四五六七八九十百千万\d]+)([{QTY_CLASSIFIERS}])")

# 量词五档分值（U3：用户锁定 15 / 5 两档，其余为架构默认值，可在此单点调整）
QTY_SCORE_SAME_CLS_SAME_NUM: float = 15.0   # 一串 vs 一串
QTY_SCORE_SAME_CLS_DIFF_NUM: float = 8.0    # 一把 vs 两把
QTY_SCORE_DIFF_CLS_SAME_NUM: float = 5.0    # 一串 vs 一把
QTY_SCORE_DIFF_CLS_DIFF_NUM: float = 2.0    # 一串 vs 两把
QTY_SCORE_FOUND_MISSING: float = 3.0        # 失主有量词、候选侧无量词
QTY_SCORE_LOST_MISSING: float = 0.0         # 失主侧无量词（共性规则 A.3.1）


def parse_cn_number(raw: str) -> int:
    """把数量串解析为 int（支持阿拉伯数字与常见中文数字）。

    支持：`"3"` → 3、`"一"` → 1、`"两"` → 2、`"十"` → 10、`"十二"` → 12、`"二十"` → 20、
    `"二十三"` → 23。无法解析时返回 1（「一个」的隐含语义），保证打分不因脏数据抛异常。

    Args:
        raw: 数量子串。

    Returns:
        解析出的正整数；失败降级为 1。
    """
    text = (raw or "").strip()
    if not text:
        return 1
    if text.isdigit():
        try:
            return int(text)
        except ValueError:      # pragma: no cover - isdigit 已保证可转
            return 1
    # 中文数字：处理 十 / 十X / X十 / X十Y 四种常见形态
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = CN_NUM_MAP.get(head, 1) if head else 1
        ones = CN_NUM_MAP.get(tail, 0) if tail else 0
        return tens * 10 + ones
    total = 0
    matched = False
    for ch in text:
        if ch in CN_NUM_MAP:
            total = total * 10 + CN_NUM_MAP[ch]
            matched = True
    return total if matched else 1


def extract_qty(text: str) -> tuple[set[tuple[int, str]], str]:
    """从文本中**消费式**抽取 (数量, 量词) 二元组。

    Args:
        text: 待抽取文本（应已扣除地点/颜色片段，见 `match_service` 流水线顺序）。

    Returns:
        `({(1, "串"), ...}, 扣除命中片段后的剩余文本)`。
    """
    if not text:
        return set(), text or ""
    pairs: set[tuple[int, str]] = set()
    for m in QTY_RE.finditer(str(text)):
        pairs.add((parse_cn_number(m.group(1)), m.group(2)))
    remaining = QTY_RE.sub(" ", str(text))
    return pairs, remaining


def qty_score(lost_pairs, found_pairs) -> float:
    """量词一致性打分（0–15，PRD §A.3.3）。

    多组量词取**最佳配对**（与颜色维度同口径）：遍历失主×候选全部组合取最高档。

    Args:
        lost_pairs: 失主侧 (数量, 量词) 集合。
        found_pairs: 候选侧 (数量, 量词) 集合。

    Returns:
        五档分值之一。
    """
    lost = set(lost_pairs or ())
    if not lost:
        return QTY_SCORE_LOST_MISSING
    found = set(found_pairs or ())
    if not found:
        return QTY_SCORE_FOUND_MISSING

    best = QTY_SCORE_DIFF_CLS_DIFF_NUM
    for lnum, lcls in lost:
        for fnum, fcls in found:
            if lcls == fcls and lnum == fnum:
                return QTY_SCORE_SAME_CLS_SAME_NUM     # 已是最高档，可提前返回
            if lcls == fcls:
                best = max(best, QTY_SCORE_SAME_CLS_DIFF_NUM)
            elif lnum == fnum:
                best = max(best, QTY_SCORE_DIFF_CLS_SAME_NUM)
    return best


# ===========================================================================
# 二、状态 / 形容词（PRD §A.3.5）
# ===========================================================================
# 反义词对：每组内**任意跨组配对**即视为冲突。词已归一到「标准词」形态。
STATE_WORD_PAIRS: tuple[tuple[frozenset[str], frozenset[str]], ...] = (
    (frozenset({"新", "全新", "崭新"}), frozenset({"旧", "陈旧", "老旧"})),
    (frozenset({"完好", "完整", "没坏"}), frozenset({"破损", "损坏", "开裂", "碎", "破裂", "摔坏"})),
    (frozenset({"干净", "整洁"}), frozenset({"脏", "污渍", "有污渍", "脏污"})),
    (frozenset({"大"}), frozenset({"小"})),
    (frozenset({"厚"}), frozenset({"薄"})),
    (frozenset({"满"}), frozenset({"空"})),
)

# 全部状态词（抽取用），长度降序保证长词优先（崭新 先于 新）
STATE_WORDS: tuple[str, ...] = tuple(
    sorted(
        {w for a, b in STATE_WORD_PAIRS for w in (a | b)},
        key=lambda w: (-len(w), w),
    )
)

# 状态词 → 其所在反义组编号（用于 O(1) 冲突判定）
_STATE_GROUP: dict[str, tuple[int, int]] = {}
for _gi, (_left, _right) in enumerate(STATE_WORD_PAIRS):
    for _w in _left:
        _STATE_GROUP[_w] = (_gi, 0)
    for _w in _right:
        _STATE_GROUP[_w] = (_gi, 1)

STATE_SCORE_FULL: float = 10.0        # 失主状态词全部命中
STATE_SCORE_CONFLICT: float = 0.0     # 存在反义冲突 → 0 + state_conflict
STATE_SCORE_MISSING: float = 0.0      # 失主侧无状态词

SIGNAL_STATE_CONFLICT: str = "state_conflict"

# 单字状态词（新/旧/大/小/厚/薄/满/空/碎/脏）若做裸子串匹配极易误命中
# （「新生」「空调」「大门」），故要求它们只能以「独立 token（可带程度副词/语气助词）」形态命中。
_DEGREE_PREFIX = "很|挺|超|非常|特别|比较|有点|略"
_TAIL_PARTICLE = "的|了|些"


def _single_char_state_re(word: str) -> re.Pattern[str]:
    """构造单字状态词的**整 token** 匹配正则（允许程度副词前缀与语气助词后缀）。"""
    return re.compile(rf"^(?:{_DEGREE_PREFIX})?{re.escape(word)}(?:{_TAIL_PARTICLE})?$")


_SINGLE_CHAR_STATE_RE: dict[str, re.Pattern[str]] = {
    w: _single_char_state_re(w) for w in STATE_WORDS if len(w) == 1
}


def extract_states(text: str, tokens) -> tuple[set[str], str]:
    """抽取状态词。

    多字状态词按**子串**匹配并消费；单字状态词只在 `tokens` 中做**整 token** 匹配
    （见 `_SINGLE_CHAR_STATE_RE` 的说明），不消费原文（因为它们本就在独立 token 里）。

    Args:
        text: 待抽取文本（应已扣除地点/颜色/量词片段）。
        tokens: 该侧已切分好的 token 集合，用于单字状态词的整词判定。

    Returns:
        `(状态词集合, 扣除多字命中片段后的剩余文本)`。
    """
    remaining = str(text or "")
    hits: set[str] = set()
    for word in STATE_WORDS:
        if len(word) == 1:
            continue
        if word and word in remaining:
            hits.add(word)
            remaining = remaining.replace(word, " ")
    for word, pattern in _SINGLE_CHAR_STATE_RE.items():
        for tok in tokens or ():
            if pattern.match(str(tok)):
                hits.add(word)
                break
    return hits, remaining


def state_score(lost_states, found_states) -> tuple[float, bool]:
    """状态/形容词打分（0–10）+ 冲突信号（PRD §A.3.5）。

    Args:
        lost_states: 失主侧状态词集合。
        found_states: 候选侧状态词集合。

    Returns:
        `(score, conflict)`。冲突优先于命中率：只要存在一对反义词就直接 0 + `state_conflict`。
    """
    lost = set(lost_states or ())
    if not lost:
        return STATE_SCORE_MISSING, False
    found = set(found_states or ())

    # 反义冲突优先判定（新 vs 旧）
    for lw in lost:
        lg = _STATE_GROUP.get(lw)
        if lg is None:
            continue
        for fw in found:
            fg = _STATE_GROUP.get(fw)
            if fg is None:
                continue
            if fg[0] == lg[0] and fg[1] != lg[1]:
                return STATE_SCORE_CONFLICT, True

    if not found:
        return STATE_SCORE_MISSING, False

    # 命中判定：同词，或同一反义组的**同侧**词（新 ≈ 全新 ≈ 崭新）
    hit = 0
    for lw in lost:
        lg = _STATE_GROUP.get(lw)
        if lw in found:
            hit += 1
            continue
        if lg is not None and any(_STATE_GROUP.get(fw) == lg for fw in found):
            hit += 1
    if hit == 0:
        return STATE_SCORE_MISSING, False
    return STATE_SCORE_FULL * hit / len(lost), False


# ===========================================================================
# 三、地点四级（PRD §A.3.6）
# ===========================================================================
# 房间号：可选一位字母前缀 + 3~4 位数字（402 / A402 / 1203）。
# 用 (?<!\d) / (?!\d) 边界避免从长数字串（手机号、学号）中间截出假房间号。
ROOM_RE = re.compile(r"(?<![0-9A-Za-z])([A-Za-z]?[0-9]{3,4})(?![0-9])")

# 校区：`XX校区`（PRD 标注为「缺，需扩表」，此处用模式匹配而非枚举，避免维护 N 所学校的校区名）
CAMPUS_RE = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9]{1,8}(?:校区|分校|校园))")

# 楼层词：从既有 `LOCATION_WORDS` 中按「X楼 / X层」形态切出（一楼~十二楼、一层~十二层）
_FLOOR_SUFFIXES = ("楼", "层")
_FLOOR_NUM_HEADS = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二")
FLOOR_WORDS: tuple[str, ...] = tuple(
    sorted(
        {
            w
            for w in LOCATION_WORDS
            if len(w) >= 2
            and w[-1] in _FLOOR_SUFFIXES
            and w[:-1] in _FLOOR_NUM_HEADS
        },
        key=lambda w: (-len(w), w),
    )
)

# 楼/场所词：`LOCATION_WORDS` 中除楼层词以外的全部通用地点词（教学楼/图书馆/食堂/宿舍…）
BUILDING_WORDS: tuple[str, ...] = tuple(
    sorted(set(LOCATION_WORDS) - set(FLOOR_WORDS), key=lambda w: (-len(w), w))
)

# 四级层级名（由深到浅，`place_score` 依赖该顺序判定「最深命中层级」）
PLACE_LEVELS: tuple[str, ...] = ("room", "floor", "building", "campus")

# 地点四级分值（PRD §A.3.6）
PLACE_SCORE_ALL_HIT: float = 15.0     # 失主提供的所有层级全部命中
PLACE_SCORE_ROOM: float = 14.0        # 最深命中 = 房间号
PLACE_SCORE_FLOOR: float = 13.0       # 最深命中 = 楼层
PLACE_SCORE_BUILDING: float = 10.0    # 最深命中 = 楼/场所
PLACE_SCORE_CAMPUS: float = 6.0       # 最深命中 = 校区
PLACE_SCORE_NONE: float = 0.0         # 无任何层级命中 / 失主侧无地点

_PLACE_LEVEL_SCORE: dict[str, float] = {
    "room": PLACE_SCORE_ROOM,
    "floor": PLACE_SCORE_FLOOR,
    "building": PLACE_SCORE_BUILDING,
    "campus": PLACE_SCORE_CAMPUS,
}


def extract_place(text: str) -> tuple[dict[str, set[str]], str]:
    """从文本中**消费式**抽取四级地点。

    抽取顺序（不可调换）：房间号 → 校区 → 楼/场所 → 楼层。
    房间号必须最先抽，否则 `402` 里的数字会被后续步骤当成量词数量；
    楼/场所必须先于楼层，否则「教学楼」会被「X楼」形态误伤（当前词表下无此风险，仍保持保守顺序）。

    Args:
        text: 待抽取文本。

    Returns:
        `({"room": {...}, "floor": {...}, "building": {...}, "campus": {...}}, 剩余文本)`。
        未命中的层级为空集合（键恒存在，调用方无需 `.get`）。
    """
    place: dict[str, set[str]] = {lvl: set() for lvl in PLACE_LEVELS}
    # 2026-08-27：地点归一化（三教→第三教学楼、3楼→三楼），口语表达也能命中词表
    remaining = normalize_location_text(text)
    if not remaining:
        return place, remaining

    # 1) 房间号
    for m in ROOM_RE.finditer(remaining):
        place["room"].add(m.group(1).upper())
    remaining = ROOM_RE.sub(" ", remaining)

    # 2) 校区
    for m in CAMPUS_RE.finditer(remaining):
        place["campus"].add(m.group(1))
    remaining = CAMPUS_RE.sub(" ", remaining)

    # 3) 楼 / 场所（长词优先）
    for word in BUILDING_WORDS:
        if word and word in remaining:
            place["building"].add(word)
            remaining = remaining.replace(word, " ")

    # 4) 楼层（长词优先：十二楼 先于 二楼）
    for word in FLOOR_WORDS:
        if word and word in remaining:
            place["floor"].add(word)
            remaining = remaining.replace(word, " ")

    return place, remaining


def place_score(lost_place, found_place) -> float:
    """地点命中打分（0–15，PRD §A.3.6）。

    规则：失主提供的层级**全部**命中 → 15；否则按**最深命中层级**给基础分
    （房间 14 / 楼层 13 / 楼场所 10 / 校区 6）；无任何命中或失主侧无地点 → 0。

    Args:
        lost_place: 失主侧四级地点 dict（`extract_place` 的返回值）。
        found_place: 候选侧四级地点 dict。

    Returns:
        分值。
    """
    lost = lost_place or {}
    found = found_place or {}
    provided_levels = [lvl for lvl in PLACE_LEVELS if lost.get(lvl)]
    if not provided_levels:
        return PLACE_SCORE_NONE

    hit_levels = [lvl for lvl in provided_levels if lost.get(lvl, set()) & found.get(lvl, set())]
    if not hit_levels:
        return PLACE_SCORE_NONE
    if len(hit_levels) == len(provided_levels):
        return PLACE_SCORE_ALL_HIT
    # PLACE_LEVELS 已按由深到浅排列，第一个命中的即最深层级
    for lvl in PLACE_LEVELS:
        if lvl in hit_levels:
            return _PLACE_LEVEL_SCORE[lvl]
    return PLACE_SCORE_NONE     # pragma: no cover - 上面循环必然命中


# ===========================================================================
# 四、照片 / 系统分类（PRD §A.3.2）与时间（PRD §A.3.8）档位
# ===========================================================================
PHOTO_CAT_SAME: float = 20.0        # 双方类目相同（category_id 相等或归一化 category_name 相等）
PHOTO_CAT_APPROX: float = 10.0      # 父子级 / 近似类目（沿用 category_hit(exact=False) 口径）
PHOTO_CAT_DIFF: float = 0.0         # 类目不同
PHOTO_CAT_NEUTRAL: float = 10.0     # 任一侧类目缺失，或双方均为「其他」类（类目无判别力，Q7）

# 时间：失主有 lost_time、候选无 found_time → 中性分（U6）。
# 注意该情形 **provided=True 仍进分母** —— 候选没填不该改变失主的标尺（R2 §2.2.3 铁律）。
TIME_SCORE_NEUTRAL: float = 5.0


# ===========================================================================
# 五、停用词（PRD §A.3.7 / R2 §2.3）
# ===========================================================================
# 在 flow-v2 `match_service._STOPWORDS` 基础上**必须**扩充无判别力的动词短语，
# 否则黄金用例失主侧 keyword 维度会被误判为 provided，分母从 80 变 90 → 全部断言失配。
STOPWORDS_V2: frozenset[str] = frozenset({
    # flow-v2 既有
    "的", "了", "在", "和", "与", "看见", "一个", "一把", "捡到", "丢失", "我的", "位于",
    "发现", "上面", "里面", "比较", "有", "是", "很", "就", "这个", "那个", "东西", "物品",
    # v10 扩充：无判别力动词 / 模糊限定语
    "掉落", "掉了", "丢了", "不见了", "落在", "遗失", "遗落", "大概", "好像", "附近",
    "左右", "大约", "可能", "应该", "记得", "捡的", "拾到", "捡", "找到", "疑似",
    "谢谢", "急", "求助", "联系我", "请联系", "如果", "麻烦", "帮忙",
})
