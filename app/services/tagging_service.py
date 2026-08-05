"""标签抽取服务（v3 基础 + v4 名词典增强）。

采用**中文规则**（词典 / 子串匹配，零推理成本）：
- 颜色词表 `COLOR_WORDS`：覆盖常见物品颜色。
- 地点词表 `LOCATION_WORDS`：通用地点词 + 楼层词占位（Q11 拍板，预留 admin 维护入口）。
- 物品名词典 `ITEM_NOUN_WORDS`（**v4 新增**）：与视觉 seed 类目名对齐的校园常见物品名词，
  作为「匹配主信号」优先抽取。
- 视觉 label（即 `category.name`，来自 VisionService.predict）作为类目标签（仅真实识别时传入）。

抽取顺序（v4）：**名词 → 颜色 → 地点 → 视觉 label**，保序去重（set 去重，保留首次出现顺序）。
名词优先级最高：先抽 `category_name` 规范名词，再抽标题/描述中的名词子串（最长子串优先）。

降级铁律：`extract` 永不抛异常；任何输入缺失只返回已能抽取到的标签（可能为空数组）。
"""
from __future__ import annotations

from app.core.attribute_extractor import AttributeExtractor

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
# 抽取优先级：名词 > 颜色 > 地点 > 视觉 label；名词作为匹配主信号。
ITEM_NOUN_WORDS: list[str] = [
    "钥匙", "校园卡", "玩偶", "本子", "水杯", "雨伞", "手机", "钱包",
    "书包", "书", "笔记本", "眼镜", "耳机", "充电宝", "饭卡", "学生证",
    "证件", "身份证", "衣物", "外套", "雨衣", "数据线", "雨靴", "钥匙串",
    "卡套", "课本", "作业本",
]

# 名词按长度降序，保证「最长子串优先」（如「钥匙串」优先于「钥匙」），
# 避免部分匹配残留（"一串钥匙" 只命中「钥匙」而非「钥匙串」）。
_NOUN_ORDER: list[str] = sorted(ITEM_NOUN_WORDS, key=len, reverse=True)

# 名词集合（O(1) 判定某 tag 是否为物品名词，供匹配候选召回使用）
NOUN_SET: set[str] = set(ITEM_NOUN_WORDS)


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

            # 1) 物品名词（优先级最高）：先抽 category_name 规范名词，再抽文本名词
            noun_sources: list[str] = []
            if category_name:
                noun_sources.append(str(category_name))
            noun_sources.append(text_blob)
            for source in noun_sources:
                for noun in cls._NOUN_ORDER:
                    if noun and noun in source and noun not in seen:
                        _add(noun)

            # 2) 颜色词（子串匹配）
            for color in cls.COLOR_WORDS:
                if color and color in text_blob:
                    _add(color)

            # 3) 地点词（子串匹配，长词优先已在常量表中排列）
            for loc in cls.LOCATION_WORDS:
                if loc and loc in text_blob:
                    _add(loc)

            # 4) 视觉 label（类目），放最后（名词阶段可能已含，去重）
            if vision_label and vision_label not in seen:
                _add(str(vision_label))

            # 5) 属性抽取（三重融合匹配）：图案/内含物/尺寸 + 颜色口语归一化
            #    由 AttributeExtractor(jieba + 同义词) 抽成带前缀标签，汇入现有 tag 体系，
            #    由 MatchService 现有打分引擎自然完成"文本重合度"融合。
            try:
                for at in AttributeExtractor.to_tags(
                    AttributeExtractor.extract(description=description)
                ):
                    _add(at)
            except Exception:
                pass  # 抽取失败不影响发布

            return tags
        except Exception:
            # 极端情况降级为空数组，绝不阻断发布
            return []
