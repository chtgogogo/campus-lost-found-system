"""标签抽取服务（v3 基础 + v4 名词典增强）。

采用**中文规则**（词典 / 子串匹配，零推理成本）：
- 颜色词表 `COLOR_WORDS`：覆盖常见物品颜色。
- 地点词表 `LOCATION_WORDS`：通用地点词 + 楼层词占位（Q11 拍板，预留 admin 维护入口）。
- 物品名词典 `ITEM_NOUN_WORDS`（**v4 新增**）：与视觉 seed 类目名对齐的校园常见物品名词，
  作为「匹配主信号」优先抽取。
- 视觉 label（即 `category.name`，来自 VisionService.predict）作为类目标签（仅真实识别时传入）。

抽取顺序（v13）：**地点（消费式）→ 名词（消费式）→ 颜色 → 品牌 → 视觉 label → 属性**。
地点先于名词：长词先消费，防止「图书馆」被名词层拆出假名词「书」（词边界修复）。

降级铁律：`extract` 永不抛异常；任何输入缺失只返回已能抽取到的标签（可能为空数组）。
"""
from __future__ import annotations

from app.core.attribute_extractor import AttributeExtractor
from app.services.brand_dict import extract_brand, extract_brand_products

# 颜色词表（中文规则抽取，可维护）
COLOR_WORDS: list[str] = [
    "黑色", "白色", "红色", "蓝色", "绿色", "黄色", "灰色",
    "粉色", "紫色", "橙色", "棕色", "金色", "银色", "彩色", "透明",
    "黑白", "银灰", "浅蓝", "深蓝", "米色", "卡其色",
]

# 地点词表（通用地点 + 楼层，占位；Q11 拍板后续由 admin 维护）
# 楼层词从长到短排列，优先匹配更具体的表达。
LOCATION_WORDS: list[str] = [
    # 通用地点（校园常见）
    "图书馆", "教学楼", "实验楼", "行政楼", "食堂", "学生食堂", "超市",
    "宿舍", "宿舍楼", "操场", "田径场", "体育馆", "校门", "校门口",
    "快递", "快递站", "驿站", "自习室", "阅览室", "报告厅", "礼堂",
    "停车场", "湖边", "河边", "花园", "食堂门口", "教学楼A区", "教学楼B区",
    # v10：校区级地点（`scoring_refs.CAMPUS_RE` 负责通用 `XX校区` 模式抽取，
    # 此处仅补最常见的固定写法，使其也能被 TaggingService 抽成 tag）
    "东校区", "西校区", "南校区", "北校区", "老校区", "新校区", "本部",
    # 楼层词（长 → 短，减少误匹配）
    "十二楼", "十一楼", "十楼", "九楼", "八楼", "七楼", "六楼", "五楼",
    "四楼", "三楼", "二楼", "一楼",
    "十二层", "十一层", "十层", "九层", "八层", "七层", "六层", "五层",
    "四层", "三层", "二层", "一层",
]

# 物品名词典（v4 新增）：与视觉 seed 类目名对齐的校园常见物品名词，可维护。
# 抽取优先级：地点 > 名词 > 颜色 > 视觉 label；名词作为匹配主信号。
# v13：补「笔记本电脑」——「笔记本」的子串关系靠长词优先 + 消费式抽取消解。
ITEM_NOUN_WORDS: list[str] = [
    "钥匙", "校园卡", "玩偶", "本子", "水杯", "雨伞", "手机", "钱包",
    "书包", "书", "笔记本", "眼镜", "耳机", "充电宝", "饭卡", "学生证",
    "证件", "身份证", "衣物", "外套", "雨衣", "数据线", "雨靴", "钥匙串",
    "卡套", "课本", "作业本", "笔记本电脑",
]

# 名词按长度降序，保证「最长子串优先」（如「钥匙串」优先于「钥匙」），
# 避免部分匹配残留（"一串钥匙" 只命中「钥匙」而非「钥匙串」）。
_NOUN_ORDER: list[str] = sorted(ITEM_NOUN_WORDS, key=len, reverse=True)

# 名词集合（O(1) 判定某 tag 是否为物品名词，供匹配候选召回使用）
NOUN_SET: set[str] = set(ITEM_NOUN_WORDS)

# 地点词长词优先序（v13：抽取时按此序消费，防止「快递站」被拆出「快递」）
_LOCATION_ORDER: list[str] = sorted(set(LOCATION_WORDS), key=len, reverse=True)

# ===========================================================================
# 地点归一化（2026-08-27 新增，⑥）：别名 → 标准表达，让地点四级抽取更稳。
# 场景：校园口语「三教」vs 标准「第三教学楼」、「图书馆3楼」vs「图书馆三楼」。
# 数字楼层归一：3楼/3层 → 三楼/三层（FLOOR_WORDS 只认中文数字楼层）。
# ===========================================================================
LOCATION_ALIASES: dict[str, str] = {
    # 教学楼简称 → 标准表达（可被子串抽取「教学楼」）
    "三教": "第三教学楼", "二教": "第二教学楼", "一教": "第一教学楼",
    "四教": "第四教学楼", "五教": "第五教学楼",
    # v15.1（P2-a）：数字形式教学楼简称（真实用户常写「5教401」而非「五教」）
    "12教": "第十二教学楼", "11教": "第十一教学楼", "10教": "第十教学楼",
    "9教": "第九教学楼", "8教": "第八教学楼", "7教": "第七教学楼",
    "6教": "第六教学楼", "5教": "第五教学楼", "4教": "第四教学楼",
    "3教": "第三教学楼", "2教": "第二教学楼", "1教": "第一教学楼",
    # 数字楼层 → 中文楼层
    "3楼": "三楼", "3层": "三层", "2楼": "二楼", "2层": "二层",
    "4楼": "四楼", "4层": "四层", "5楼": "五楼", "5层": "五层",
    "6楼": "六楼", "6层": "六层", "7楼": "七楼", "7层": "七层",
    "8楼": "八楼", "8层": "八层", "9楼": "九楼", "9层": "九层",
    "10楼": "十楼", "10层": "十层", "11楼": "十一楼", "11层": "十一层",
    "12楼": "十二楼", "12层": "十二层",
    # 图书馆数字楼层（先于数字楼层规则，避免拆成「图书馆」+「三楼」以外的形态）
    "图书馆3楼": "图书馆三楼", "图书馆3层": "图书馆三层",
    "图书馆2楼": "图书馆二楼", "图书馆2层": "图书馆二层",
    "图书馆4楼": "图书馆四楼", "图书馆4层": "图书馆四层",
}
# 按长度降序替换，保证「图书馆3楼」先于「3楼」命中
_LOCATION_ALIAS_ORDER: list[tuple[str, str]] = sorted(
    LOCATION_ALIASES.items(), key=lambda kv: -len(kv[0])
)


def normalize_location_text(text: str | None) -> str:
    """把地点别名替换为标准表达（长词优先，只替换仍保留原语义的形态）。

    兼容性铁律：永不抛异常；None/空 → 原样返回。仅影响「本来抽不到或半命中」的
    地点表达，已命中的标准表达不受影响。
    """
    if not text:
        return text or ""
    out = str(text)
    for alias, standard in _LOCATION_ALIAS_ORDER:
        if alias in out:
            out = out.replace(alias, standard)
    return out


class TaggingService:
    """中文规则标签抽取（纯函数式，无状态）。"""

    COLOR_WORDS: list[str] = COLOR_WORDS
    LOCATION_WORDS: list[str] = LOCATION_WORDS
    ITEM_NOUN_WORDS: list[str] = ITEM_NOUN_WORDS
    NOUN_SET: set[str] = NOUN_SET
    _NOUN_ORDER: list[str] = _NOUN_ORDER

    @classmethod
    def extract(
        cls,
        title: str | None = None,
        description: str | None = None,
        vision_label: str | None = None,
        category_name: str | None = None,
    ) -> list[str]:
        """抽取结构化标签列表（v4：名词优先）。

        Args:
            title: 失物标题（拾物无标题，传 None）。
            description: 描述文本（地点语义已并入此处）。
            vision_label: 视觉识别 label（即 category.name）；仅当为**真实识别**
                （confidence>0）时由调用方传入，降级占位 label 不应传入以免污染标签。
            category_name: 用户填写的规范分类名（v4 作为规范名词注入，优先级最高）。

        Returns:
            保序去重后的标签数组，如 ["钥匙", "银色"]；
            无任何命中返回空数组 `[]`（不返回 None，便于 JSON 持久化）。
        """
        try:
            text_blob = " ".join(str(x) for x in (title, description) if x)
            tags: list[str] = []
            seen: set[str] = set()

            def _add(tag: str) -> None:
                if tag and tag not in seen:
                    seen.add(tag)
                    tags.append(tag)

            # v13 词边界修复：地点**先抽并消费**（长词优先）。此前名词层先跑且不消费，
            # 「图书馆」「快递站」会被子串匹配拆出假名词「书」「快递」，污染召回。
            working = normalize_location_text(text_blob)
            for loc in _LOCATION_ORDER:
                if loc and loc in working:
                    _add(loc)
                    working = working.replace(loc, " ")

            # 2) 物品名词（v13 起消费式：命中长词后消掉原文，不再拆出嵌套短词；
            #    如「钥匙串」命中后不再重复产出「钥匙」——同族召回由 category_service 家族表兜底）
            if category_name:
                for noun in cls._NOUN_ORDER:
                    if noun and noun in str(category_name):
                        _add(noun)
            for noun in cls._NOUN_ORDER:
                if noun and noun in working:
                    _add(noun)
                    working = working.replace(noun, " ")

            # 3) 颜色词（子串匹配，维持原行为）
            for color in cls.COLOR_WORDS:
                if color and color in text_blob:
                    _add(color)

            # 4) 品牌/型号（词典+正则归一为标准品牌词注入 tags；基于已扣地点/名词的残余文本）
            for brand in sorted(extract_brand(working)):
                _add(brand)

            # 5) 品牌→产品推断（「苹果15」→ 注入「手机」）：
            #    使失主写品牌型号、拾主写物品通名（如「手机」）也能互相匹配，
            #    且该产品词 ∈ NOUN_SET 时还能参与候选召回与类目解析兜底。
            for prod in sorted(extract_brand_products(working)):
                _add(prod)

            # 6) 视觉 label（类目），放最后（名词阶段可能已含，去重）
            if vision_label and vision_label not in seen:
                _add(str(vision_label))

            # 7) 属性抽取（三重融合匹配）：图案/内含物/尺寸 + 颜色口语归一化
            #    由 AttributeExtractor(jieba + 同义词) 抽成带前缀标签，汇入现有 tag 体系，
            #    由 MatchService 现有打分引擎自然完成"文本重合度"融合。
            #    v13：跳过裸名词形态的属性标签（jieba 把「钥匙串」切出「钥匙」这类），
            #    名词层已消费式抽取，裸名词只会是切分残留噪声。
            try:
                for at in AttributeExtractor.to_tags(
                    AttributeExtractor.extract(description=description)
                ):
                    if at in NOUN_SET:
                        continue
                    _add(at)
            except Exception:
                pass  # 抽取失败不影响发布

            return tags
        except Exception:
            # 极端情况降级为空数组，绝不阻断发布
            return []
