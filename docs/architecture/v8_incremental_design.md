# v8 增量架构设计：匹配度算法重构

> 文档状态：增量设计（基于 v7 已交付系统）。本版由主理人依据已拍板的权重方案与已确认的设计决策代为落盘（架构师子智能体工具临时故障，工具恢复后补走复核）。所有结论均来自主理人拍板 + 真实代码核对，非凭空生成。

## 0. 引用

- PRD：`docs/prd/v8_match_algo_prd.md`（PM 许清楚）
- 类图：`./v8_class-diagram.mermaid`
- 时序图（匹配打分流程）：`./v8_sequence-diagram.mermaid`
- 现状代码：`app/services/match_service.py`、`app/core/config.py`、`app/models/item.py`、`app/models/category.py`、`app/core/seed.py`、`app/services/publish_service.py`、`app/routers/vision.py`

## 1. 背景与现状（代码事实）

当前打分公式（`app/services/match_service.py::MatchService.score`，v4 落地）：

```
score = 20·photo + 40·containment + 25·cat + 15·time
```

- `photo`：首图感知哈希 Hamming 相似度 ∈[0,1]，无图降级 0
- `containment`：`|lost.tags ∩ found.tags| / |lost.tags|`（标签查询命中率）
- `cat`：类目精确 1.0 / 父级 0.5
- `time`：`exp(-Δt/τ)`，`τ=3` 天
- **颜色消歧硬门控**：双方都显式指定颜色且颜色集合不相交 → `score=0`（整条归零）

**实测缺陷（用户反馈 + 代码核对）**：
1. demo/无图场景下 `photo=0`（20% 权重全废），而"类目对 + 标签对 + 时间近"恰好 `25+40+15=80` 封顶 → 所有达标匹配恒显 80%，照片相似度不起区分作用。
2. 各维度为"全有/全无"，无法体现 A 比 B 更匹配（用户举例：C(钥匙,银色) 应高于 B(校园卡,黑色)，因类目"钥匙"命中）。
3. 颜色硬门控过于粗暴：仅因颜色不同就整条判 0，忽略其它维度。
4. 视觉识别不出既定 11 个常规类目（doll 已移除，不计入）时，fallback 落库到首个活跃类（如 phone），而非独立"其他"类，导致"其他"类物品无法靠中文标签驱动匹配。

## 2. 设计目标

- 匹配度**连续可区分**，照片相似度真实参与运算。
- 标签细分为**外观/特征/时间/地点**四维度，类目权重最高（强判别）。
- 新增"**其他**"特殊类：视觉识别不出既定类时归入，匹配度完全由中文标签对应数量决定。
- 颜色冲突改为**软化**（仅外观维度该属性计 0，不再整条归零）。
- 存量数据兼容（appearance/features/location 为空时降级），确保 156 passed 不退化。

## 3. 最终权重方案（主理人拍板，强制采用）

```
score = 20·photo + 30·category + 20·appearance + 15·feature + 10·time + 5·location   (合计 100)
阈值 MATCH_THRESHOLD 沿用 80
```

| 维度 | 权重 | 计算口径 |
|---|---|---|
| photo | 20 | 首图感知哈希 Hamming 相似度 ∈[0,1]；无图降级 0 |
| category | 30 | 类目精确命中 1.0 / 部分相关 0.5 / 不命中 0（强判别） |
| appearance | 20 | 颜色+材质+形状 属性命中率；颜色冲突时该属性计 0 |
| feature | 15 | 品牌+数量+特殊标记 属性命中率 |
| time | 10 | `exp(-Δt/τ)`，`τ=3` 天（沿用） |
| location | 5 | 结构化地点相似度（字符串包含 / 编辑距离，待定，见 §12） |

**"其他"类特殊规则**：当物品类目为"其他"(id=12) 时，匹配时 `category` 权重不参与（置 0），改用：

```
score = 20·photo + 80·tag_match_rate
```

`tag_match_rate`：跨"外观/特征/时间/地点"四维度标签的命中率（最高可达 1.0 → 该路径最高 100%）。时间维度不计入标签集合，故 tag_match_rate 实际取外观/特征/地点三维度标签的 containment 命中率（与 v4 `containment` 同口径，分母取失物侧标签并集规模）。

> 用户示例验证：失主A(钥匙,黑,三串,7-2,操场) vs 拾得者B(校园卡,黑,7-2,楼道) vs 拾得者C(钥匙,银,7-2)。
> - A–B：category 0（钥匙≠校园卡）→ category 维度 0；颜色同黑 +30 外观、时间近 +10、地点不同 0 → ≈60，未达 80。
> - A–C：category 30（钥匙命中）+ 颜色不同但外观维度仅颜色属性计0（仍计材质/形状若同）+30、时间 +10 → ≥70，且若描述/标签其它重合更高，可越过 80。C 明显 > B，符合预期。

## 4. Schema 改动（Alembic 0005 迁移）

### 4.1 模型字段（`app/models/item.py`）

`LostItem` / `FoundItem` 各新增三列（VARCHAR，可空）：

```python
appearance: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 材质/形状/颜色描述
features:   Mapped[str | None] = mapped_column(String(255), nullable=True)  # 品牌/数量/特殊标记
location:   Mapped[str | None] = mapped_column(String(128), nullable=True)  # 地点
```

颜色词仍走 `tags` 的 `COLOR_WORDS` 机制（不单独建列），并在匹配时并入 `appearance` 维度计算。

### 4.2 Category 种子新增"其他"（`app/models/category.py` + `app/core/seed.py`）

`Category` 表：v7 seed 原 12 类含 `doll`；v8 先移除 `doll` 种子（玩偶归"其他"类），常规类目降为 11 个，再新增第 12 个种子：`("其他", "other", 12, is_active=1)`（id 建议紧随现有 11 类之后，由工程师按现有 seed 自增规则定）。

### 4.3 迁移脚本 `migrations/versions/0005_v8_match.py`

- 参考 0004 写法：`op.batch_alter_table` + `inspect` 幂等；
- 对 `lost_item` / `found_item` 加 `appearance` / `features` / `location` 三列（String，nullable，无回填必要，默认 NULL）；
- 升级写入"其他"类种子（或直接由 `seed.py` 在应用启动时保证存在）；
- **必须提供 `downgrade`**（架构评审硬性要求）。

## 5. 打分引擎重构（`app/services/match_service.py`）

### 5.1 配置常量（`app/core/config.py`）

移除 `MATCH_W_TAG=40`，新增：

```python
MATCH_W_PHOTO: float = 20.0
MATCH_W_CAT:  float = 30.0
MATCH_W_APP:  float = 20.0
MATCH_W_FEAT: float = 15.0
MATCH_W_TIME: float = 10.0
MATCH_W_LOC:  float = 5.0
MATCH_W_OTHER: float = 80.0   # "其他"类：类目权重外移后的剩余权重
MATCH_THRESHOLD: float = 80.0
```

旧 `MATCH_W1~W4` deprecated 常量保留不动（外部兼容）。

### 5.2 原子因子

保留：`photo_sim_factor`、`category_hit`、`time_decay_factor`、`tag_containment_factor`（供"其他"类 tag_match_rate 复用）。

新增：
- `appearance_factor(lost, found)`：解析双方 `appearance` 字段（含 `tags` 中颜色词），计算 颜色/材质/形状 属性命中率；**颜色冲突时仅颜色属性计 0，材质/形状仍参与**。
- `feature_factor(lost, found)`：解析 `features` 字段（品牌/数量/标记）命中率。
- `location_factor(lost, found)`：解析 `location` 字段相似度（实现见 §12 待定）。
- `tag_match_rate(lost, found)`：`|lost_tags ∪ lost_app ∪ lost_feat ∪ lost_loc 等 ∩ found_对应| / |lost_并集|`，用于"其他"类。

### 5.3 新 `score()`

```python
def score(self, lost, found, ...) -> float:
    w = settings
    photo = self.photo_sim_factor(lost.image_hash, found.image_hash)
    if lost.category_id == OTHER_ID or found.category_id == OTHER_ID:
        # "其他"类路径：类目不占权重
        return round(min(100.0, w.MATCH_W_PHOTO * photo + w.MATCH_W_OTHER * self.tag_match_rate(lost, found)), 2)
    cat = self.category_hit(exact_category)
    app = self.appearance_factor(lost, found)      # 内部已处理颜色软化
    feat = self.feature_factor(lost, found)
    td = self.time_decay_factor(lost.lost_time, found.found_time)
    loc = self.location_factor(lost.location, found.location)
    total = (w.MATCH_W_PHOTO*photo + w.MATCH_W_CAT*cat + w.MATCH_W_APP*app
             + w.MATCH_W_FEAT*feat + w.MATCH_W_TIME*td + w.MATCH_W_LOC*loc)
    return round(min(max(total, 0.0), 100.0), 2)
```

**颜色软化**：删除原 `color_conflict → return 0` 硬门控；
`appearance_factor` 内部：若双方颜色不相交，颜色属性命中率记为 0，但材质/形状属性照常计算（不再整条置零）。

### 5.4 维度明细返回

`score()` 或新包装函数返回各维度贡献 dict（供前端展示）：

```python
{"photo":..., "category":..., "appearance":..., "feature":..., "time":..., "location":..., "total":...}
```

## 6. 发布链路改造（`app/services/publish_service.py` + `app/routers/vision.py`）

- **视觉判定点**：`vision.py` 返回 `confidence`；当 `confidence < YOLO_CONF_THRESHOLD(0.25)` 或 YOLO-World 也无匹配时，`category_id = 其他类(id)`，`label="其他"`，且**不把"其他"写入 `tags`**（避免污染标签池）。
- `_resolve_category_id`（名词优先）保持；但 fallback（原取首个活跃类）改为指向"其他"类。
- **采集外观/特征/地点**：`PublishLostDTO` / `PublishFoundDTO` 新增 `appearance` / `features` / `location` 字段；`publish_service` 落库到 `LostItem` / `FoundItem` 对应列。
- 召回候选条件（第241/264行 `category_id` 相等）对"其他"类：两个"其他"类物品之间仍按 `category_id` 相等召回（逻辑一致），再靠 `tag_match_rate` 区分。

## 7. 前端改动（`web/`）

- `web/src/views/PublishView.vue`：失物/拾物发布表单增加「外观」「特征」「地点」三个输入项（复用既有 `tags` 输入风格，逗号分词或独立输入框）。
- 匹配列表/详情组件（如 `web/src/views/MatchView.vue` 或 `ItemCard` 扩展）：展示各维度贡献明细（photo/category/appearance/feature/time/location 条形或百分比）。
- `web/src/api/mockData.ts` / `mockAdapter.ts`：演示数据补充 `appearance/features/location` 字段（T8）。

## 8. 类图

见 [./v8_class-diagram.mermaid](./v8_class-diagram.mermaid)（LostItem/FoundItem 新增字段、MatchService 因子、Category"其他"扩展）。

## 9. 时序图（匹配打分流程）

见 [./v8_sequence-diagram.mermaid](./v8_sequence-diagram.mermaid)（publish → vision/publish_service 落库 → 召回候选 → MatchService.score 六维 → 返回明细）。

## 10. 任务分解（T1–T8，有序 + 依赖）

| 任务 | 内容 | 涉及文件 | 依赖 |
|---|---|---|---|
| **T1** | 配置常量 + 模型字段 + 0005 迁移 + "其他"类种子 | `config.py` / `item.py` / `category.py` / `seed.py` / `migrations/versions/0005_v8_match.py` | — |
| **T2** | 打分六维重构（新原子因子 + tag_match_rate + 颜色软化） | `match_service.py` | T1 |
| **T3** | 发布链路改造（外观/特征/地点采集 + "其他"类判定落库） | `publish_service.py` / `vision.py` / DTO | T1 |
| **T4** | 维度明细 API（匹配结果返回各维度贡献） | `match.py` 路由 / `schemas/match.py` | T2 |
| **T5** | 前端发布表单（外观/特征/地点输入） | `web/src/views/PublishView.vue` | T3 |
| **T6** | 前端匹配明细展示 | `web/src/views/MatchView.vue` 等 | T4 |
| **T7** | 测试回归（各维度加权单测、颜色软化、"其他"类纯标签匹配、存量兼容、确保 156 passed 不退化，目标新增 ≥12 用例 → 168） | `tests/test_v8_*.py` | T2,T3,T4 |
| **T8** | 演示模式覆盖（mock 数据含新字段） | `web/src/api/mockData.ts` / `mockAdapter.ts` | T5,T6 |

## 11. 依赖包

无新增第三方包。感知哈希沿用既有 `imagehash` / `Pillow`；若 location 相似度采用编辑距离，可用标准库 `difflib`，无需新依赖。

## 12. 共享知识（跨文件约定）

- `appearance` / `features` / `location` 存储为逗号分隔自由文本（VARCHAR），匹配时按逗号/空白分词成属性集合。
- 颜色词同时存在于 `tags`（COLOR_WORDS 机制）与 `appearance` 文本；匹配时 `appearance_factor` 优先从 `tags` 抽颜色做冲突判定，再从 `appearance` 文本抽材质/形状。
- `tag_match_rate` 计算口径：失物侧标签并集 = `tags ∪ appearance分词 ∪ features分词 ∪ location分词`；命中率 = `|lost并集 ∩ found并集| / |lost并集|`（分母固定失物侧，与 v4 containment 一致）。
- "其他"类枚举值 `OTHER_ID = 12`（或 seed 实际 id），在 `config` 或 `category` 模块常量统一定义，避免硬编码。
- 时间维度（time）不参与 `tag_match_rate`（非标签），保持 `time_decay_factor` 独立。

## 13. 待明确事项

1. **location 相似度算法**：字符串包含（`操场` ⊂ `操场东侧`）/ 编辑距离（`difflib.SequenceMatcher`）/ 地点分词 + 同义词表？建议先用"包含 + 编辑距离阈值"双判，论文可写"基于编辑距离的模糊匹配"。
2. **appearance/feature 边界**：颜色归 appearance；品牌/数量/标记归 feature；材质/形状归 appearance。是否允许用户在 features 填"三串"这类数量词 → 是。
3. **"其他"类 id**：由工程师按 `seed.py` 现有自增规则定（建议紧随 11 类之后）；同时移除既有 `doll` 种子。
4. **维度明细前端展示形式**：条形图 vs 百分比列表，由前端在 T6 定（建议百分比列表，轻量）。
5. **阈值是否仍为 80**：沿用 80；若实测"其他"类易误匹配，可单独对"其他"路径设更低阈值，待 T7 实验观察。
