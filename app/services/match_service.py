"""匹配打分引擎（2026-08-06 **v10 评分引擎 v2 + Q10 归一化**）。

## 原始分公式（raw，合计 100）

    raw_total = photo_category(0~20)
              + qty(0~15) + color(0~20) + state(0~10) + place(0~15) + keyword(0~10)   # 文字 70
              + time(0~10)

各子维度档位分值来自 ``scoring_refs.py`` / ``color_family.py`` 模块常量，
七个维度满分来自 ``config.MATCH_W2_*``；打分函数内**不得出现魔法数字**（AC-A11）。

## 归一化（Q10 用户拍板，P0 主路径）

    k     = 100 / max(W_provided, MATCH_NORM_MIN_WEIGHT)
    total = round(clamp(raw_total · k, 0, 100), 2)

``W_provided`` = 失主**实际填写**的维度满分之和。

⚠️ **铁律：k 只由失主侧决定**（R2 §2.2.3）。候选侧永不进分母，理由：
1. 可比性 —— 同一件失物的 N 个候选必须在同一标尺上，否则 ``scored.sort()`` 的顺序无意义；
2. 单调性 —— k 对该失物是常数，归一化是严格单调变换，**不改变候选相对排序**；
3. 性能 —— k 每件失物只算一次。

``MATCH_NORM_MIN_WEIGHT``(50.0) 是防爆护栏：没有它时「只填类目」的纯图失物 k=5.0，
任意同类目候选 raw=20 → total=100 直接误报为疑似。

``MATCH_NORMALIZE=False`` 时 k≡1.0，退回纯 raw 分（kill switch / AB / 回滚）。

## 相对 flow-v2 的行为变更

- 五维标量公式（15·photo + 20·category + 50·text + 10·location + 5·time）**下线**；
  `photo_sim_factor*` / `location_factor` / `text_match_rate` 等保留为 deprecated 工具方法，
  不再参与总分（感知哈希 / CLIP 降级为 P2 同分 tie-breaker，见需求池）。
- 「其他」类特殊路径（20·photo + 80·tag_match_rate）**取消**（Q7）：统一走 v2 公式，
  双方均为「其他」时 ``photo_category=10``（中性，类目无判别力）。
- ``score_detail`` 新增 10 个键（7 子维度 + signals + raw_total/norm_factor/provided_dims），
  旧键按 R2 §7.1 映射保留，老 JSON 消费者不断裂。

## 沿用不变

- P0-② 语义命中 ``_token_hit``（WordNet + 中文近义词表）；nltk 缺失自动回退纯精确匹配。
- 候选集由 publish_service 以「类目相等 ∪ 共享物品名词 tag」召回，打分只对裁剪后候选运算。
- ``ItemFeatures`` 抽取结果缓存在 **MatchService 实例**上（``_feature_cache``）：
  PublishService 复用同一个 ``self._matcher``，打分 N 个候选时失主侧只抽取一次。
  **不要**改用模块级 ``lru_cache`` —— ORM 对象不可哈希且会跨请求泄漏。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings
from app.services.clip_service import image_similarity as clip_image_similarity
from app.services.color_family import (
    SIGNAL_COLOR_CONFLICT,
    color_score,
    extract_color_words,
)
from app.services.perceptual_hash import PerceptualHash
from app.services.scoring_refs import (
    PHOTO_CAT_APPROX,
    PHOTO_CAT_DIFF,
    PHOTO_CAT_NEUTRAL,
    PHOTO_CAT_SAME,
    PLACE_LEVELS,
    SIGNAL_STATE_CONFLICT,
    STATE_WORDS,
    STOPWORDS_V2,
    TIME_SCORE_NEUTRAL,
    extract_place,
    extract_qty,
    extract_states,
    place_score,
    qty_score,
    state_score,
)
from app.services.tagging_service import COLOR_WORDS, LOCATION_WORDS, NOUN_SET
from app.utils import text as text_util
from app.utils.time_decay import delta_days, time_decay

# 颜色词集合（O(1) 判定某 tag 是否为颜色，供颜色软化使用）
_COLOR_SET: set[str] = set(COLOR_WORDS)
# 地点词集合（O(1) 判定某 token 是否为地点词，供 text 词集保留使用）
_LOCATION_SET: set[str] = set(LOCATION_WORDS)

# 自由文本分隔符（外观/特征/地点字段按逗号/空白/标点分词成属性集合）
_ATTR_SPLIT_RE = re.compile(r"[\s,，。；;、/]+")

# 2026-08-05 flow-v2：text 词集去停用词（无判别力词，可维护）
_STOPWORDS: set[str] = {
    "的", "了", "在", "和", "与", "看见", "一个", "一把", "捡到", "丢失", "我的", "位于",
    "发现", "上面", "里面", "比较", "有", "是", "很", "就", "这个", "那个", "东西", "物品",
}
# 数量词切分：前缀（"两个行李箱" → "两个"+"行李箱"）与后缀（"行李箱两个" → "行李箱"+"两个"）。
# 注：设计文档常量仅给前缀且带 `$`（整词匹配），但其自带示例（PRD §5.2 可测断言：
# 拾取物2 "行李箱两个，黄色的和粉色" 命中 4/5 含 "两个"）同时要求后缀切分，故按前缀+后缀实现。
_QTY_PREFIX_RE = re.compile(r"^([一二两三四五六七八九十百千万0-9]+)(个|把|张|只|条|部|串|双|对|辆|台|本|支|根|件|枚)")
_QTY_SUFFIX_RE = re.compile(r"^(.+?)([一二两三四五六七八九十百千万0-9]+(?:个|把|张|只|条|部|串|双|对|辆|台|本|支|根|件|枚))$")


# ---------------------------------------------------------------------------
# P0-② 语义匹配：WordNet 同义扩展（兼容性铁律：缺失则回退纯精确 containment）
# ---------------------------------------------------------------------------
# 模块内开关（不改动 config.py）。
# 仅探测「nltk 包是否可导入」，不在导入期触碰任何语料 —— 语料缺失不应关闭语义扩展，
# 语料在进程启动后由 _ensure_wordnet() 懒加载激活。nltk 包本身缺失/离线 → False → 精确回退。
try:  # pragma: no cover - 依赖可用性在运行环境决定
    import nltk as _nltk

    USE_WORDNET = True
except Exception:  # nltk 未安装 / 离线 / 导入失败 → 关闭语义扩展
    USE_WORDNET = False
    _nltk = None

_wordnet_ready = False   # 运行期语料是否就绪（懒加载成功后置 True，作为语义路径缓存）
_wordnet_failed = False  # 本进程内已尝试激活且失败（负缓存，见 _ensure_wordnet 说明）
_wn = None                # 懒加载成功后由 _ensure_wordnet() 写入 wordnet 模块对象


def _ensure_wordnet() -> bool:
    """首次使用时静默下载并激活 wordnet 语料（仅当 USE_WORDNET 开启）。

    兼容性铁律：nltk 包本身不可导入时 USE_WORDNET=False，本函数直接返回 False，
    绝不触碰任何语料/网络；语料缺失时静默尝试下载，失败（离线/无网络）也返回 False，
    由调用方回退为纯精确 containment。下载成功后再导入 corpus 模块并写入模块级 ``_wn``，
    置 ``_wordnet_ready=True``，后续调用直接命中缓存，不再重复下载/导入。

    ⚠️ **负缓存 ``_wordnet_failed``（v10 修复）**：原实现失败后不记忆，导致每个 token 的
    每次语义命中判定都会重新发起两次 ``nltk.download`` 网络请求 —— 离线环境下打一次分
    可产生上百次网络超时，是严重的线上延迟隐患（离线 CI 里整套用例慢数倍）。
    失败一次后本进程不再重试；行为（返回 False → 回退纯精确匹配）完全不变。

    Returns:
        True 表示 wordnet 已就绪可用；False 表示不可用（已静默失败）。
    """
    global _wordnet_ready, _wordnet_failed
    if not USE_WORDNET or _nltk is None:
        return False
    if _wordnet_ready:
        return True
    if _wordnet_failed:
        return False
    try:  # pragma: no cover - 依赖网络/语料，CI/离线环境静默失败
        _nltk.download("wordnet", quiet=True)
        _nltk.download("omw-1.4", quiet=True)
        import nltk.corpus.wordnet as _wn_mod  # noqa: F401

        globals()["_wn"] = _wn_mod
        _wordnet_ready = True
        return True
    except Exception:
        _wordnet_failed = True
        return False


def _wordnet_synonyms(token: str) -> set[str]:
    """取 token 的 WordNet 同义词 lemma 集合（小写）。

    仅当 USE_WORDNET 开启且 wordnet 语料已就绪（_wordnet_ready）时有效；
    否则（nltk 缺失 / 语料缺失 / 离线）返回空集合，回退为纯精确匹配。
    """
    if not USE_WORDNET or not token:
        return set()
    # 语料尚未就绪时尝试懒加载激活；失败则回退空集合（纯精确 containment）。
    if not _wordnet_ready and not _ensure_wordnet():
        return set()
    try:
        syns: set[str] = set()
        for syn in _wn.synsets(token):
            for lemma in syn.lemmas():
                syns.add(lemma.name().lower())
        return syns
    except Exception:
        return set()


# 中文轻量同义/近义词表（校园失物常见物品）。仅作为语义增强的互补，解决 WordNet
# 仅覆盖英文、无法处理中文词形的问题（如"钥匙"↔"钥匙扣"、"水杯"↔"水壶"）。
# 仅在 USE_WORDNET 开启（语义模式）时生效，保证 nltk 缺失的回退路径与历史精确行为完全一致。
_ZH_SYNONYMS: dict[str, list[str]] = {
    "钥匙": ["钥匙扣", "钥匙串", "钥匙链"],
    "钥匙扣": ["钥匙", "钥匙串", "钥匙链"],
    "钥匙串": ["钥匙", "钥匙扣", "钥匙链"],
    "钥匙链": ["钥匙", "钥匙扣", "钥匙串"],
    "水杯": ["水壶", "水瓶", "杯子", "保温杯"],
    "水壶": ["水杯", "水瓶", "杯子", "保温杯"],
    "水瓶": ["水杯", "水壶", "杯子", "保温杯"],
    "杯子": ["水杯", "水壶", "水瓶", "保温杯"],
    "保温杯": ["水杯", "水壶", "水瓶", "杯子"],
    "雨伞": ["伞", "雨具"],
    "伞": ["雨伞", "雨具"],
    "书包": ["背包", "双肩包"],
    "背包": ["书包", "双肩包"],
    "双肩包": ["书包", "背包"],
    "手机": ["电话", "移动电话"],
    "钱包": ["皮夹", "钱夹"],
    "眼镜": ["墨镜", "镜"],
    "笔记本": ["本子", "记事本", "作业本"],
    "本子": ["笔记本", "记事本", "作业本"],
    "记事本": ["笔记本", "本子", "作业本"],
    "作业本": ["笔记本", "本子", "记事本"],
    "校园卡": ["饭卡", "学生卡", "一卡通"],
    "饭卡": ["校园卡", "学生卡", "一卡通"],
    "学生卡": ["校园卡", "饭卡", "一卡通"],
    "一卡通": ["校园卡", "饭卡", "学生卡"],
    "行李箱": ["箱子", "拉杆箱", "旅行箱"],
    "箱子": ["行李箱", "拉杆箱", "旅行箱"],
    "拉杆箱": ["行李箱", "箱子", "旅行箱"],
    "旅行箱": ["行李箱", "箱子", "拉杆箱"],
    "笔记本电脑": ["电脑", "笔记本电", "笔电"],
    "电脑": ["笔记本电脑", "笔电"],
    "笔电": ["笔记本电脑", "电脑"],
}


def _zh_synonyms(token: str) -> set[str]:
    """中文近义词集合（仅在语义模式 USE_WORDNET 下由调用方使用）。"""
    if not USE_WORDNET or not token:
        return set()
    return set(_ZH_SYNONYMS.get(token, []))


def _token_hit(token: str, candidate_tokens: set[str]) -> bool:
    """失物侧某 token 是否命中候选 token 集合（精确 + 语义同义）。

    - 精确：token 直接出现在候选集合。
    - 语义（仅 USE_WORDNET 开启）：token 的任意 WordNet 同义词或中文近义词出现在候选集合。
    nltk 缺失（USE_WORDNET=False）时仅做精确命中，与历史 containment 行为完全一致。
    """
    if token in candidate_tokens:
        return True
    if USE_WORDNET:
        for syn in _wordnet_synonyms(token):
            if syn in candidate_tokens:
                return True
        for syn in _zh_synonyms(token):
            if syn in candidate_tokens:
                return True
    return False


# ===========================================================================
# v10 评分引擎 v2：维度定义 / 特征容器 / 残余分词
# ===========================================================================
# 七个子维度的**规范顺序**。`provided_dims` 与前端展示均按此序，保证输出确定性。
V2_DIMENSIONS: tuple[str, ...] = (
    "photo_category", "qty", "color", "state", "place", "keyword", "time",
)


def dim_max_scores() -> dict[str, float]:
    """七个子维度的满分表（读 ``config.MATCH_W2_*``）。

    用于计算 ``W_provided``（归一化分母）与前端「该维度得了 x/满分」展示。

    ⚠️ 维护约定：本表的值必须与 ``scoring_refs`` / ``color_family`` 中各维度的**最高档位**
    保持一致（默认 20/15/20/10/15/10/10）。改档位分值时须同步改 config，否则
    「满分候选」的归一化后总分会偏离 100。

    Returns:
        `{"photo_category": 20.0, ...}`，键顺序与 ``V2_DIMENSIONS`` 一致。
    """
    return {
        "photo_category": float(settings.MATCH_W2_PHOTO_CAT),
        "qty": float(settings.MATCH_W2_QTY),
        "color": float(settings.MATCH_W2_COLOR),
        "state": float(settings.MATCH_W2_STATE),
        "place": float(settings.MATCH_W2_PLACE),
        "keyword": float(settings.MATCH_W2_KEYWORD),
        "time": float(settings.MATCH_W2_TIME),
    }


@dataclass
class ItemFeatures:
    """一侧物品经抽取流水线（R2 §2.3）产出的结构化特征。

    Attributes:
        category_id: 类目 id（可为 None）。
        category_name: 归一化后的类目名（去空白；缺失为空串）。
        qty: `(数量, 量词)` 二元组集合，如 `{(1, "串")}`。
        colors: 命中的颜色词集合（原词，色系换算交给 ``color_family``）。
        states: 命中的状态词集合。
        place: 四级地点 dict，键恒为 ``PLACE_LEVELS``。
        keywords: 扣除量词/颜色/状态/地点/名词/类目名/停用词后的残余 token 集合。
        residual_text: 全部消费步骤后的剩余原文（调试与回归定位用）。
    """

    category_id: Optional[int] = None
    category_name: str = ""
    qty: set[tuple[int, str]] = field(default_factory=set)
    colors: set[str] = field(default_factory=set)
    states: set[str] = field(default_factory=set)
    place: dict[str, set[str]] = field(default_factory=dict)
    keywords: set[str] = field(default_factory=set)
    residual_text: str = ""

    @property
    def has_category(self) -> bool:
        """类目是否提供（``category_name`` 非空或 ``category_id`` 非 None）。"""
        return bool(self.category_name) or self.category_id is not None

    @property
    def has_qty(self) -> bool:
        """是否抽出至少一个 (数量, 量词) 二元组。"""
        return bool(self.qty)

    @property
    def has_color(self) -> bool:
        """是否抽出至少一个颜色词。"""
        return bool(self.colors)

    @property
    def has_state(self) -> bool:
        """是否抽出至少一个状态词。"""
        return bool(self.states)

    @property
    def has_place(self) -> bool:
        """四级地点中是否有任一层级非空。"""
        return any(bool(v) for v in self.place.values())

    @property
    def has_keyword(self) -> bool:
        """残余 token 集合是否非空。"""
        return bool(self.keywords)


def _residual_tokens(text: str) -> set[str]:
    """残余文本分词（**纯标点/空白切分，刻意不使用 jieba**）。

    jieba 未在 ``requirements.txt`` 声明（仅 ``attribute_extractor`` 惰性使用），
    装与不装会切出不同粒度的 token，进而改变 ``keyword`` 维度的分母与
    ``provided_dims``——归一化系数 k 会随环境漂移，黄金用例不可复现。
    因此本函数与 flow-v2 的 ``_split_attrs`` 同口径，保证**跨环境确定性**。

    Args:
        text: 已扣除地点/颜色/量词/状态片段的剩余文本。

    Returns:
        去空后的 token 集合。
    """
    if not text:
        return set()
    return {p.strip() for p in _ATTR_SPLIT_RE.split(str(text)) if p.strip()}


class MatchService:
    """v10 评分引擎 v2（七子维度 + Q10 归一化）。

    实例持有 ``_feature_cache``：同一个 matcher 对同一件物品只抽取一次特征。
    PublishService / ``build_match_outs`` 均复用单个实例，因此打分 N 个候选时
    失主侧流水线只跑一遍。**不要**改成模块级 ``lru_cache``（ORM 对象不可哈希，
    且会跨请求泄漏已 detach 的实例）。
    """

    def __init__(self) -> None:
        """初始化实例级特征缓存。

        缓存键为 ``(is_lost, id(item))``，值为 ``(item, features)``：
        同时存物品强引用，避免 ``id()`` 被 GC 回收后复用导致读到错误特征。
        """
        self._feature_cache: dict[tuple[bool, int], tuple[object, ItemFeatures]] = {}

    # ---------------- v10：特征抽取流水线（R2 §2.3） ----------------
    @staticmethod
    def _raw_text(item, is_lost: bool) -> str:
        """拼装一侧物品的原始文本（title 仅失物侧有）。

        Args:
            item: LostItem / FoundItem 或任意具备同名属性的对象。
            is_lost: 是否为失主侧（决定是否并入 ``title``）。

        Returns:
            以空格连接的原始文本；缺失字段按空串处理，绝不抛异常。
        """
        parts: list[str] = []
        if is_lost:
            parts.append(str(getattr(item, "title", None) or ""))
        parts.append(str(getattr(item, "description", None) or ""))
        parts.extend(str(t) for t in (getattr(item, "tags", None) or []))
        parts.append(str(getattr(item, "appearance", None) or ""))
        parts.append(str(getattr(item, "features", None) or ""))
        parts.append(str(getattr(item, "location", None) or ""))
        return " ".join(p for p in parts if p)

    def extract_features(self, item, is_lost: bool) -> ItemFeatures:
        """按 R2 §2.3 的**消费式单次流水线**抽取结构化特征（带实例级缓存）。

        顺序不可调换（每一步都从文本中扣除已命中的片段，防止重复计分）::

            房间号 → 校区 → 楼/场所 → 楼层   (extract_place)
            → 颜色词（长词优先）             (extract_color_words)
            → 量词 (数量, 量词)              (extract_qty)
            → 状态词                         (extract_states)
            → 残余 token（扣 NOUN_SET ∪ category_name ∪ STOPWORDS_V2）

        Args:
            item: 物品对象。
            is_lost: 是否为失主侧。

        Returns:
            ``ItemFeatures``；``item`` 为 None 时返回全空特征（不抛异常）。
        """
        if item is None:
            return ItemFeatures(place={lvl: set() for lvl in PLACE_LEVELS})

        cache_key = (is_lost, id(item))
        cached = self._feature_cache.get(cache_key)
        if cached is not None and cached[0] is item:
            return cached[1]

        category_name = str(getattr(item, "category_name", None) or "").strip()
        category_id = getattr(item, "category_id", None)

        text = self._raw_text(item, is_lost)
        place, rest = extract_place(text)
        colors, rest = extract_color_words(rest)
        qty, rest = extract_qty(rest)
        # 单字状态词需要「整 token」判定，故先按残余文本切一次
        states, rest = extract_states(rest, _residual_tokens(rest))

        keywords = self._residual_keywords(rest, category_name)

        features = ItemFeatures(
            category_id=category_id if isinstance(category_id, int) else None,
            category_name=category_name,
            qty=qty,
            colors=colors,
            states=states,
            place=place,
            keywords=keywords,
            residual_text=rest,
        )
        self._feature_cache[cache_key] = (item, features)
        return features

    @staticmethod
    def _residual_keywords(rest: str, category_name: str) -> set[str]:
        """从残余文本中筛出「其他关键词」token（PRD §A.3.7）。

        排除项（缺一不可，否则黄金用例分母从 80 变 90）：

        1. ``NOUN_SET``（物品名词，判别力已由 photo_category 20 分表达）；
        2. ``category_name`` 本身及其片段（类目名同理，见下方「⚠️ 单向包含」）；
        3. ``STOPWORDS_V2``（无判别力动词/模糊限定语）；
        4. 颜色/地点/状态词残留（防御性兜底，正常流程已被消费）；
        5. 纯标点、纯数字、长度 <2 的碎片（无判别力且噪声大）。

        ⚠️ **单向包含（设计 R2 §2.3 铁律，勿改回双向）**：类目排除只允许
        ``tok == cat``（相等）与 ``tok in cat``（token 是类目名的片段）两个方向，
        **绝不能加 ``cat in tok``**。反向包含会让「类目名恰好是某 token 子串」的
        一侧凭空丢掉该 token，而另一侧保留 → 抽取结果**左右不对称**，
        ``_score_keyword`` 因「任一侧为空即 0」而永久失效。

        典型踩坑（v10 回归实测）：双方都带融合标签 ``融合:钥匙``，
        失主类目 ``银色钥匙``（无包含关系→保留）、拾获方类目 ``钥匙``
        （``cat in tok`` 成立→被丢弃）→ ``keyword`` 维度恒为 0，
        同色钥匙分数被压在阈值下，破坏 v8 AC1「同色钥匙应达疑似」。

        Args:
            rest: 已扣除四类结构化信息的剩余文本。
            category_name: 该侧类目名（用于排除）。

        Returns:
            残余关键词集合。
        """
        keywords: set[str] = set()
        cat = (category_name or "").strip()
        for tok in _residual_tokens(rest):
            if len(tok) < 2:
                continue
            if tok in STOPWORDS_V2 or tok in NOUN_SET:
                continue
            # 只做单向包含：相等 / token 是类目名片段。禁止 `cat in tok`（见 docstring）
            if cat and (tok == cat or tok in cat):
                continue
            if tok in _COLOR_SET or tok in _LOCATION_SET or tok in STATE_WORDS:
                continue
            if re.fullmatch(r"[\W_]+", tok) or tok.isdigit():
                continue
            keywords.add(tok)
        return keywords

    # ---------------- v10：七个子维度打分（档位全部来自模块常量，AC-A11） ----------------
    @staticmethod
    def _score_photo_category(
        lost_f: ItemFeatures, found_f: ItemFeatures, exact_category: bool = True
    ) -> float:
        """照片 / 系统分类一致性（0–20，PRD §A.3.2）。

        同类目 20；父子级或近似 10；不同 0；任一侧缺失或**双方均为「其他」** 10（中性，Q7）。
        ``exact_category=False`` 时把「同类目」降档为近似，沿用 flow-v2
        ``category_hit(exact=False)`` 的调用口径。
        """
        if not lost_f.has_category or not found_f.has_category:
            return PHOTO_CAT_NEUTRAL

        other = settings.OTHER_CATEGORY_NAME
        if lost_f.category_name == other and found_f.category_name == other:
            # Q7：双方都是「其他」，类目无判别力 → 中性，不再走 20·photo+80·tag 特殊路径
            return PHOTO_CAT_NEUTRAL

        same = False
        if lost_f.category_id is not None and found_f.category_id is not None:
            same = lost_f.category_id == found_f.category_id
        if not same and lost_f.category_name and found_f.category_name:
            same = lost_f.category_name == found_f.category_name
        if same:
            return PHOTO_CAT_SAME if exact_category else PHOTO_CAT_APPROX

        # 父子级 / 近似：一方类目名是另一方的子串（如「证件」vs「学生证件」）
        if lost_f.category_name and found_f.category_name and (
            lost_f.category_name in found_f.category_name
            or found_f.category_name in lost_f.category_name
        ):
            return PHOTO_CAT_APPROX
        return PHOTO_CAT_DIFF

    @staticmethod
    def _score_keyword(lost_f: ItemFeatures, found_f: ItemFeatures) -> tuple[float, list[str]]:
        """其他关键词命中率（0–10，PRD §A.3.7）。

        ``score = MATCH_W2_KEYWORD × 命中数 / 失主侧残余 token 数``；
        命中判定复用 ``_token_hit``（精确 + WordNet + 中文近义词表）。
        失主侧残余为空 → 0（该维度 provided=False，也不进分母）。

        Returns:
            `(score, 命中的关键词列表)`，命中列表已排序，供可解释展示。
        """
        lost_kw = lost_f.keywords
        if not lost_kw:
            return 0.0, []
        found_kw = found_f.keywords
        if not found_kw:
            return 0.0, []
        hits = sorted(t for t in lost_kw if _token_hit(t, found_kw))
        if not hits:
            return 0.0, []
        return float(settings.MATCH_W2_KEYWORD) * len(hits) / len(lost_kw), hits

    @staticmethod
    def _score_time(lost, found) -> tuple[float, bool]:
        """时间衰减（0–10，PRD §A.3.8 + R2 §2.2.3 铁律）。

        - `lost_time` 缺失 → `(0.0, False)`，**不进分母**；
        - `lost_time` 有、`found_time` 缺失 → `(TIME_SCORE_NEUTRAL, True)`，
          进分母但给中性分（候选没填不该改变失主的标尺）；
        - 双方都有 → `(MATCH_W2_TIME · exp(-Δd/MATCH_TIME_TAU_DAYS), True)`。

        Returns:
            `(score, provided)`。
        """
        lost_time = getattr(lost, "lost_time", None)
        if lost_time is None:
            return 0.0, False
        found_time = getattr(found, "found_time", None)
        if found_time is None:
            return TIME_SCORE_NEUTRAL, True
        decay = time_decay(delta_days(lost_time, found_time), settings.MATCH_TIME_TAU_DAYS)
        return float(settings.MATCH_W2_TIME) * decay, True

    # ---------------- v10：归一化（R2 §2.2） ----------------
    @staticmethod
    def _provided_weight(provided: dict[str, bool]) -> float:
        """``W_provided`` = Σ(该维度 provided ? 该维度满分 : 0)。"""
        maxima = dim_max_scores()
        return sum(maxima[d] for d in V2_DIMENSIONS if provided.get(d))

    @staticmethod
    def _normalize_factor(provided_weight: float) -> float:
        """归一化系数 ``k = 100 / max(W_provided, MATCH_NORM_MIN_WEIGHT)``。

        ⚠️ 调用方必须只传**失主侧**推导出的 ``provided_weight``（R2 §2.2.3 铁律）。

        降级：``MATCH_NORMALIZE=False``（kill switch / AB / 回滚）或
        ``W_provided <= 0``（理论不出现）时返回 1.0，退回纯 raw 分。
        """
        if not settings.MATCH_NORMALIZE:
            return 1.0
        if provided_weight <= 0:
            return 1.0
        return 100.0 / max(provided_weight, float(settings.MATCH_NORM_MIN_WEIGHT))

    def _evaluate(self, lost, found, exact_category: bool = True) -> dict:
        """核心求值：一次算出七个子维度、信号、raw_total、k 与归一化 total。

        ``score()`` 与 ``score_detail()`` 均走本函数，杜绝两条实现漂移。

        Args:
            lost: 失物对象。
            found: 拾物对象。
            exact_category: 类目是否按精确命中计（False 时同类目降为近似档）。

        Returns:
            含 ``dims`` / ``provided`` / ``signals`` / ``keyword_hits`` /
            ``raw_total`` / ``norm_factor`` / ``total`` 的字典。
        """
        lost_f = self.extract_features(lost, is_lost=True)
        found_f = self.extract_features(found, is_lost=False)

        photo_category = self._score_photo_category(lost_f, found_f, exact_category)
        qty = qty_score(lost_f.qty, found_f.qty)
        color, color_conflict = color_score(lost_f.colors, found_f.colors)
        state, state_conflict = state_score(lost_f.states, found_f.states)
        place = place_score(lost_f.place, found_f.place)
        keyword, keyword_hits = self._score_keyword(lost_f, found_f)
        time_score, time_provided = self._score_time(lost, found)

        dims: dict[str, float] = {
            "photo_category": photo_category,
            "qty": qty,
            "color": color,
            "state": state,
            "place": place,
            "keyword": keyword,
            "time": time_score,
        }
        # provided 只看失主侧（R2 §2.2.2 判定表）
        provided: dict[str, bool] = {
            "photo_category": lost_f.has_category,
            "qty": lost_f.has_qty,
            "color": lost_f.has_color,
            "state": lost_f.has_state,
            "place": lost_f.has_place,
            "keyword": lost_f.has_keyword,
            "time": time_provided,
        }
        signals: list[str] = []
        if color_conflict:
            signals.append(SIGNAL_COLOR_CONFLICT)
        if state_conflict:
            signals.append(SIGNAL_STATE_CONFLICT)

        raw_total = sum(dims[d] for d in V2_DIMENSIONS)
        norm_factor = self._normalize_factor(self._provided_weight(provided))
        total = min(max(raw_total * norm_factor, 0.0), 100.0)

        return {
            "dims": dims,
            "provided": provided,
            "provided_dims": [d for d in V2_DIMENSIONS if provided.get(d)],
            "signals": signals,
            "keyword_hits": keyword_hits,
            "raw_total": round(raw_total, 2),
            "norm_factor": round(norm_factor, 4),
            "total": round(total, 2),
        }

    # ---------------- 文本工具 ----------------
    @staticmethod
    def _split_attrs(text: str | None) -> set[str]:
        """把自由文本（逗号/空白/标点分词）切成属性 token 集合（去空）。"""
        if not text:
            return set()
        return {p.strip() for p in _ATTR_SPLIT_RE.split(str(text)) if p.strip()}

    @staticmethod
    def _color_set(item) -> set[str]:
        """抽取物品的颜色词集合：优先取自 tags（COLOR_WORDS 精确匹配），

        并补充自 appearance 文本（子串匹配），覆盖用户把颜色写进外观字段的情况。
        """
        colors: set[str] = set()
        for t in (getattr(item, "tags", None) or []):
            if t in _COLOR_SET:
                colors.add(t)
        appearance = getattr(item, "appearance", None)
        if appearance:
            for c in COLOR_WORDS:
                if c and c in str(appearance):
                    colors.add(c)
        return colors

    @staticmethod
    def _material_shape_set(item) -> set[str]:
        """材质/形状属性集合：appearance 字段分词后排除颜色词（颜色单独处理）。"""
        toks = MatchService._split_attrs(getattr(item, "appearance", None))
        return toks - _COLOR_SET

    # ---------------- flow-v2：text 词集与文字覆盖率（R4 核心） ----------------
    @staticmethod
    def _text_token_set(item, is_lost: bool) -> set[str]:
        """构造一侧物品的 text 词集（R4 词集口径，PRD §5.2）。

        原始文本 = title（仅失物侧）+ description + tags + appearance + features + location，
        按 ``_ATTR_SPLIT_RE`` 分词；对每个 raw token 依次处理：

        a. **子串抽取**：遍历 COLOR_WORDS / LOCATION_WORDS，若为 token 子串则加入
           （如 "在教学楼看见" → "教学楼"；"黄色的" → "黄色"）；被抽取的 raw token 视为
           「已分解」，不再整词保留（保证词集不含拼接冗余，如 PRD 5 词示例）。
        b. **数量词前缀切分**：``_QTY_RE`` 命中开头则把数量部分与剩余部分各自作为 token
           （"两个行李箱" → "两个" + "行李箱"），同样视为已分解。
        c. **过滤**：丢弃停用词、纯标点、空串。
        d. **保留**：NOUN_SET 词、COLOR_WORDS 词、LOCATION_WORDS 词、数量词，
           以及其余长度 ≥2 且非停用词的 token（品牌/特殊标记兜底，如 "Apple"）。
        """
        parts: list[str] = []
        if is_lost:
            parts.append(str(getattr(item, "title", None) or ""))
        parts.append(str(getattr(item, "description", None) or ""))
        parts.extend(str(t) for t in (getattr(item, "tags", None) or []))
        parts.append(str(getattr(item, "appearance", None) or ""))
        parts.append(str(getattr(item, "features", None) or ""))
        parts.append(str(getattr(item, "location", None) or ""))

        raw_tokens: set[str] = set()
        for p in parts:
            raw_tokens |= MatchService._split_attrs(p)

        tokens: set[str] = set()
        for tok in raw_tokens:
            if not tok:
                continue
            decomposed = False
            # a. 颜色 / 地点子串抽取（命中即认为 raw token 已分解）
            for color in COLOR_WORDS:
                if color and color in tok:
                    tokens.add(color)
                    decomposed = True
            for loc in LOCATION_WORDS:
                if loc and loc in tok:
                    tokens.add(loc)
                    decomposed = True
            # b. 数量词切分（前缀或后缀，命中即认为 raw token 已分解；数量词=数量+量词，如 "两个"）
            m_pre = _QTY_PREFIX_RE.match(tok)
            if m_pre:
                qty = m_pre.group(1) + m_pre.group(2)
                tokens.add(qty)
                rest = tok[m_pre.end():]
                if rest:
                    tokens.add(rest)
                decomposed = True
            else:
                m_suf = _QTY_SUFFIX_RE.match(tok)
                if m_suf:
                    tokens.add(m_suf.group(2))
                    rest = m_suf.group(1)
                    if rest:
                        tokens.add(rest)
                    decomposed = True
            if decomposed:
                continue
            # c. 停用词 / 纯标点过滤
            if tok in _STOPWORDS:
                continue
            if re.fullmatch(r"[\W_]+", tok):
                continue
            # d. 保留：名词 / 颜色 / 地点 / 数量词 / 长度≥2 非停用词兜底
            if tok in NOUN_SET or tok in _COLOR_SET or tok in _LOCATION_SET:
                tokens.add(tok)
                continue
            if len(tok) >= 2 and tok not in _STOPWORDS:
                tokens.add(tok)
        return tokens

    @staticmethod
    def text_match_rate(lost, found) -> float:
        """文字词覆盖率（R4 主维度，50 分权重）。

        rate = hit / |lost_text_tokens|，分母固定失物侧（containment 口径）；
        命中判定复用 ``_token_hit``（精确 + WordNet + 中文近义词表）。

        边界（Q6）：
        - 失物侧词集为空（纯图失物）→ 中性 0.5（text 贡献 25 分，不惩罚）；
        - 拾物侧词集为空且失物有词 → 0.0（有文字失物对无文字拾物得 0）。
        """
        lost_tokens = MatchService._text_token_set(lost, is_lost=True)
        if not lost_tokens:
            return 0.5
        found_tokens = MatchService._text_token_set(found, is_lost=False)
        if not found_tokens:
            return 0.0
        hit = sum(1 for t in lost_tokens if _token_hit(t, found_tokens))
        return hit / len(lost_tokens)

    @staticmethod
    def shared_text_tokens(lost, found) -> list[str]:
        """失物词集中被 ``_token_hit`` 命中的词（排序，供 MatchOut.shared_text 可解释展示）。"""
        lost_tokens = MatchService._text_token_set(lost, is_lost=True)
        found_tokens = MatchService._text_token_set(found, is_lost=False)
        if not lost_tokens or not found_tokens:
            return []
        return sorted(t for t in lost_tokens if _token_hit(t, found_tokens))

    # ---------------- 原子因子 ----------------
    @staticmethod
    def category_hit(exact: bool = True) -> float:
        """类目命中：精确 1.0 / 父级 0.5。"""
        return 1.0 if exact else 0.5

    @staticmethod
    def time_decay_factor(lost_time, found_time) -> float:
        """时间衰减因子 (0,1]。

        R3/Q6：任一时间缺失 → 中性 0.5（不报错、不惩罚、不奖励）；双方都有值沿用指数衰减。
        """
        if lost_time is None or found_time is None:
            return 0.5
        dt = delta_days(lost_time, found_time)
        return time_decay(dt, settings.TIME_DECAY_TAU_DAYS)

    @staticmethod
    def photo_sim_factor(image_hash_a: str | None, image_hash_b: str | None) -> float:
        """照片相似度因子（v3）：感知哈希 Hamming 相似度 ∈ [0,1]；任一缺失降级 0.0。"""
        return PerceptualHash.hamming_sim(image_hash_a, image_hash_b)

    @staticmethod
    def photo_sim_factor_with_bytes(
        image_hash_a: str | None,
        image_hash_b: str | None,
        bytes_a: bytes | None = None,
        bytes_b: bytes | None = None,
    ) -> float:
        """照片相似度因子（P0-③）：感知哈希 + CLIP 跨模态混合。

        - 基础值 phash_sim = 感知哈希 Hamming 相似度。
        - 若双方均提供图片字节且 CLIP 返回非 None：
              photo = clamp(0.5·phash_sim + 0.5·clip_sim, 0, 1)
          否则（CLIP 缺失 / 字节缺失 / 异常）沿用 phash_sim，保持确定性。
        """
        phash_sim = PerceptualHash.hamming_sim(image_hash_a, image_hash_b)
        clip_sim = clip_image_similarity(bytes_a, bytes_b) if (bytes_a and bytes_b) else None
        if clip_sim is not None:
            blended = 0.5 * phash_sim + 0.5 * clip_sim
            return max(0.0, min(1.0, blended))
        return phash_sim

    # ---- v8 新增原子因子（P0-② 已升级为语义命中） ----

    @staticmethod
    def appearance_factor(lost, found) -> float:
        """外观相似度（颜色 + 材质/形状，命中率口径，P0-② 语义化）。

        颜色冲突（双方都显式指定颜色且不相交）仅使颜色属性计 0，材质/形状仍参与（软化），
        不再整条置零。命中率 = 失物侧属性被候选命中的个数 / 失物侧属性个数（语义同义也计命中）；
        lost_attrs 为空（无任何外观信息）时降级 0.0（不报错、不计分）。
        nltk 缺失时退化为纯精确命中，与历史行为一致。
        """
        lost_colors = MatchService._color_set(lost)
        found_colors = MatchService._color_set(found)
        lost_ms = MatchService._material_shape_set(lost)
        found_ms = MatchService._material_shape_set(found)

        lost_attrs = lost_colors | lost_ms
        if not lost_attrs:
            return 0.0
        found_attrs = found_colors | found_ms
        # 语义命中计数：失物侧每个属性只要精确/同义命中候选任一属性即计 1。
        hit = sum(1 for t in lost_attrs if _token_hit(t, found_attrs))
        return hit / len(lost_attrs)

    @staticmethod
    def feature_factor(lost, found) -> float:
        """特征相似度（品牌 + 数量 + 特殊标记，命中率口径，P0-② 语义化）。

        features 字段分词为属性集合，命中率 = 失物侧特征被候选命中的个数 / 失物侧特征个数
        （语义同义也计命中）；失物无特征信息时降级 0.0。
        """
        lost_feat = MatchService._split_attrs(getattr(lost, "features", None))
        found_feat = MatchService._split_attrs(getattr(found, "features", None))
        if not lost_feat:
            return 0.0
        hit = sum(1 for t in lost_feat if _token_hit(t, found_feat))
        return hit / len(lost_feat)

    @staticmethod
    def location_factor(lost, found) -> float:
        """地点相似度（包含 + 编辑距离阈值双判，基于标准库 difflib，无新增依赖）。

        - 任一方缺失 → 0.5（Q6：中性，不惩罚；原 0.0，行为变化）。
        - 完全相同 / 一方包含另一方 → 1.0。
        - 否则用 difflib.SequenceMatcher 计算编辑距离相似度，>= 阈值(0.6) 按相似度计，< 阈值计 0。
        """
        a = (getattr(lost, "location", None) or "").strip()
        b = (getattr(found, "location", None) or "").strip()
        if not a or not b:
            return 0.5
        if a == b:
            return 1.0
        if a in b or b in a:
            return 1.0
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        return ratio if ratio >= 0.6 else 0.0

    @staticmethod
    def semantic_tag_match_rate(lost, found) -> float:
        """「其他」类专用：语义标签命中率（2026-08-05 升级为与 text_match_rate 同口径）。

        失物侧词集 = ``_text_token_set(lost, is_lost=True)``（title ∪ description ∪ tags ∪
        appearance ∪ features ∪ location 分词并集，description 首次进打分）；
        命中率 = 失物侧词集中被候选命中的 token 数 / 失物侧词集数（分母固定失物侧）；
        失物侧词集为空 → 0.5（中性，原 0.0，行为变化）。

        兼容性铁律：USE_WORDNET=False（nltk 缺失/离线）时仅做精确 containment；
        USE_WORDNET=True 时额外叠加 WordNet 同义 + 中文近义召回。
        """
        # 尝试激活 wordnet 语料；结果忽略，语义路径统一依赖 _wordnet_ready 缓存。
        _ensure_wordnet()

        lost_union = MatchService._text_token_set(lost, is_lost=True)
        if not lost_union:
            return 0.5
        found_union = MatchService._text_token_set(found, is_lost=False)
        hit = sum(1 for t in lost_union if _token_hit(t, found_union))
        return hit / len(lost_union)

    @staticmethod
    def tag_match_rate(lost, found) -> float:
        """「其他」类专用标签命中率（P0-② 已切换为语义版本）。

        语义版本在 nltk 缺失时与历史精确 containment 完全一致；可用时叠加同义召回。
        接口与原方法签名一致，供 score / score_detail 与存量测试直接复用。
        """
        return MatchService.semantic_tag_match_rate(lost, found)

    # ---------------- deprecated 兼容方法（不被 score 调用，仅保留以保持引用兼容） ----------------
    @staticmethod
    def tag_jaccard_factor(tags_a, tags_b) -> float:
        """标签 Jaccard 因子（v3 deprecated）：仅保留兼容，不被 score 调用。"""
        return text_util.tag_jaccard(tags_a, tags_b)

    @staticmethod
    def tag_containment_factor(lost_tags, found_tags) -> float:
        """标签 containment 因子（v4）：失物查询命中率。

        containment = |lost.tags ∩ found.tags| / |lost.tags|。
        分母固定为**失物**标签数，使「标签更少」的纯文字失物（如仅 ``["钥匙"]``）也能对命中
        候选得到 1.0 满命中，根治 AC1/AC2 的纯文字失物漏检问题。失物无标签（罕见）时降级 0.0。
        v8 中复用于「其他」类的 tag_match_rate 计算（tags 子集口径）。
        """
        lost = set(lost_tags or [])
        if not lost:
            return 0.0
        found = set(found_tags or [])
        return len(lost & found) / len(lost)

    @staticmethod
    def color_conflict(lost_tags, found_tags) -> bool:
        """[deprecated] v4 颜色消歧硬门控判定。

        v8 已删除「冲突 → score 整条置零」逻辑（改由 appearance_factor 软化），
        本方法仅保留供外部/历史测试引用，不再被 score 调用。
        """
        lost_colors = {t for t in (lost_tags or []) if t in _COLOR_SET}
        found_colors = {t for t in (found_tags or []) if t in _COLOR_SET}
        if not lost_colors or not found_colors:
            return False
        return lost_colors.isdisjoint(found_colors)

    @staticmethod
    def location_hit_factor(lost_location: str | None, found_location: str | None) -> float:
        """[deprecated] v2 地点文本相似度因子；v3 已移除地点列，v8 改用 location_factor。"""
        from app.utils import location as location_util

        return location_util.location_similarity(lost_location, found_location)

    @staticmethod
    def keyword_jaccard_factor(lost_text: str | None, found_text: str | None) -> float:
        """[deprecated] v2 关键词 Jaccard；v3 由 `tag_jaccard_factor` 取代。"""
        return text_util.keyword_jaccard(lost_text, found_text)

    # ---------------- 综合打分 ----------------
    @staticmethod
    def _is_other(lost, found) -> bool:
        """任一侧类目为「其他」类即走特殊路径（按名称解析，避免硬编码 id 耦合）。"""
        name = settings.OTHER_CATEGORY_NAME
        return (
            getattr(lost, "category_name", None) == name
            or getattr(found, "category_name", None) == name
        )

    def score(self, lost, found, exact_category: bool = True) -> float:
        """对失物/拾物候选对计算匹配度（0–100，**归一化后**）。

        v10 v2 公式::

            raw_total = photo_category + qty + color + state + place + keyword + time
            total     = round(clamp(raw_total × k, 0, 100), 2)
            k         = 100 / max(W_provided, MATCH_NORM_MIN_WEIGHT)   # 只由失主侧决定

        Args:
            lost: 失物对象。
            found: 拾物对象。
            exact_category: 类目是否按精确命中计（False 时同类目降为近似档 10）。

        Returns:
            归一化后的总分，保留两位小数。
        """
        return self._evaluate(lost, found, exact_category)["total"]

    def score_detail(self, lost, found, exact_category: bool = True) -> dict:
        """返回各维度明细（R2 §7.1 唯一权威表：7 新键 + 3 元信息键 + 旧键映射）。

        新键（**均为归一化前的原始分**，便于前端同时展示「各维度得了多少」与
        「你的描述完整度把上限抬到了多少」）：

        ``photo_category`` / ``qty`` / ``color`` / ``state`` / ``place`` / ``keyword``
        / ``signals`` / ``raw_total`` / ``norm_factor`` / ``provided_dims``。

        旧键映射（老 JSON 消费者不断裂）：``photo`` = ``photo_category``、
        ``category`` 恒 0.0、``text`` = qty+color+state+place+keyword、
        ``text_match_rate`` = text/70（**语义变更**）、``location`` = ``place``、
        ``time`` 不变、``appearance``/``feature`` 恒 0.0、``total`` = 归一化后总分。

        Args:
            lost: 失物对象。
            found: 拾物对象。
            exact_category: 类目是否按精确命中计。

        Returns:
            明细字典。
        """
        result = self._evaluate(lost, found, exact_category)
        dims = result["dims"]

        # 旧键 text = 文字五子维度之和（满分 70）
        text_max = (
            float(settings.MATCH_W2_QTY)
            + float(settings.MATCH_W2_COLOR)
            + float(settings.MATCH_W2_STATE)
            + float(settings.MATCH_W2_PLACE)
            + float(settings.MATCH_W2_KEYWORD)
        )
        text = dims["qty"] + dims["color"] + dims["state"] + dims["place"] + dims["keyword"]

        is_other = self._is_other(lost, found)
        return {
            # ---- v10 新键（原始分） ----
            "photo_category": round(dims["photo_category"], 2),
            "qty": round(dims["qty"], 2),
            "color": round(dims["color"], 2),
            "state": round(dims["state"], 2),
            "place": round(dims["place"], 2),
            "keyword": round(dims["keyword"], 2),
            "signals": list(result["signals"]),
            "raw_total": result["raw_total"],
            "norm_factor": result["norm_factor"],
            "provided_dims": list(result["provided_dims"]),
            # ---- 旧键映射（R2 §7.1） ----
            "photo": round(dims["photo_category"], 2),
            "category": 0.0,          # [deprecated] 已并入 photo_category
            "text": round(text, 2),
            "text_match_rate": round(text / text_max, 4) if text_max > 0 else None,
            "appearance": 0.0,        # [deprecated] 旧六维占位
            "feature": 0.0,           # [deprecated] 旧六维占位
            "time": round(dims["time"], 2),
            "location": round(dims["place"], 2),   # = place，前端注明「已含在文字 70 内」
            "tag_match_rate": round(self.tag_match_rate(lost, found), 4) if is_other else None,
            "is_other": is_other,     # Q7：为 True 也不再走特殊公式，仅作展示标记
            "shared_text": self.shared_text_tokens(lost, found),
            "total": result["total"],
        }

    @staticmethod
    def is_suspected(score: float) -> bool:
        """是否达到疑似匹配阈值。"""
        return score >= settings.MATCH_THRESHOLD


# 模块级便捷函数
def compute_score(lost, found, exact_category: bool = True) -> float:
    return MatchService().score(lost, found, exact_category)


def build_match_outs(db, matches) -> list:
    """将 match_record 列表构造为 MatchOut（含失物/拾物与类目名 + 维度明细），按 score 降序。

    v10：明细由 ``MatchService.score_detail`` 计算，**同时透传 v2 七子维度新键**
    （``photo_category``/``qty``/``color``/``state``/``place``/``keyword``/``signals``/
    ``raw_total``/``norm_factor``/``provided_dims``）与全部旧键，老前端只读旧键不受影响。

    单个 ``MatchService`` 实例贯穿整个循环：同一件失物在多条 match 中只抽取一次特征
    （``_feature_cache`` 命中），避免 N 次重复跑流水线。
    """
    from app.models.item import FoundItem, LostItem
    from app.schemas.match import MatchOut

    matcher = MatchService()
    outs = []
    for m in matches:
        lost = db.get(LostItem, m.lost_id)
        found = db.get(FoundItem, m.found_id)
        lost_name = lost.category_name if lost else None
        found_name = found.category_name if found else None
        detail = matcher.score_detail(lost, found) if lost and found else {}
        outs.append(
            MatchOut.from_model(
                m,
                lost_item=lost,
                found_item=found,
                lost_name=lost_name,
                found_name=found_name,
                threshold=settings.MATCH_THRESHOLD,
                photo=detail.get("photo"),
                category=detail.get("category"),
                appearance=detail.get("appearance"),
                feature=detail.get("feature"),
                time=detail.get("time"),
                location=detail.get("location"),
                total=detail.get("total"),
                text=detail.get("text"),
                text_match_rate=detail.get("text_match_rate"),
                shared_text=detail.get("shared_text") or [],
                # ---- v10 新增 10 个字段 ----
                photo_category=detail.get("photo_category"),
                qty=detail.get("qty"),
                color=detail.get("color"),
                state=detail.get("state"),
                place=detail.get("place"),
                keyword=detail.get("keyword"),
                signals=detail.get("signals") or [],
                raw_total=detail.get("raw_total"),
                norm_factor=detail.get("norm_factor"),
                provided_dims=detail.get("provided_dims") or [],
            )
        )
    outs.sort(key=lambda o: o.match_score, reverse=True)
    return outs
