# v10 增量 PRD：评分引擎 v2 + 候选排序修正 + 管理员注册与后台

## 0. 项目信息

| 项 | 内容 |
| --- | --- |
| Language | 简体中文 |
| Project Name | lostfound_scoring_admin_v10 |
| 基线版本 | **flow-v3 交付后的代码**（keep1 进匹配池 + 低分阈值 60 + 删除低分不打扰 + keep1 守卫） |
| 技术栈 | 后端 FastAPI + SQLAlchemy 2.0 + Pydantic v2；前端 Vue3 + Element Plus + Vite |
| 文档性质 | **增量 PRD** —— 仅描述相对 flow-v3 的变更；未提及部分一律保持现状 |
| 排期前提 | 工程师在 flow-v3 全部合入后再动本需求代码，**不与 flow-v3 并发改同一文件** |

> **架构设计配套文档**：`docs/architecture/v10_scoring_admin_incremental_design.md`（含 §1.2 五个拍板点定案、§1.3 其余 Q 采纳默认、§2.1 变更 B 单切片等价性证明、§2.3 归一化插入点），及两份 mermaid 图（`v10_scoring_admin_class-diagram.mermaid` / `v10_scoring_admin_sequence-diagram.mermaid`）。本 PRD §8 的状态列与下方各处批注已与架构设计对齐。

### 原始需求复述

1. **变更 A**：评分引擎重构为「照片/系统分类 20 + 文字描述 70 + 时间 10」，文字 70 再拆 5 个子维度（量词 15 / 颜色 20 / 状态 10 / 地点 15 / 其他关键词 10），地点并入文字不再独立占权重；颜色引入标准色系合类表；时间衰减改为 `10·exp(-Δd/15)`。
2. **变更 B**：候选输出规则由「按分降序硬截断前 10」改为「**前 10 条 + 所有 ≥80 的疑似全部追加**」。
3. **变更 C**：注册页增加「管理员邀请码」输入框，与环境变量 `ADMIN_APPLY_CODE`（默认 `110`）比对，命中即注册为管理员。
4. **变更 D**：管理员后台补齐——用户列表、匹配成功记录详情（双方信息 + 对话）、按范围导出 xlsx/md、管理员侧记录留存更久。

### 现状核对结论（已实际阅读代码，非记忆）

| 核对项 | 结论 |
| --- | --- |
| `app/services/match_service.py` | 现为 flow-v2 五维：`15·photo + 20·category + 50·text + 10·location + 5·time`；`_text_token_set` 已具备颜色/地点子串抽取、量词前后缀切分（`_QTY_PREFIX_RE`/`_QTY_SUFFIX_RE`）、停用词过滤；`text_match_rate` 为**失物侧 containment 覆盖率**；`location_factor` 为 difflib 相似度；「其他」类走 `20·photo + 80·tag_match_rate` |
| `app/services/publish_service.py` | 三处 top10 约束：`_reverse_match_lost` 的 `scored[:MATCH_TOP_N]`（L344）、`_reverse_match_found` 的 `if existing >= MATCH_TOP_N: continue`（L378）+ `scored[:MATCH_TOP_N]`（L383）、`refresh_lost_candidates` 的 `if existing >= MATCH_TOP_N: return []`（L405）+ `scored[:MATCH_TOP_N - existing]`（L415） |
| `app/models/user.py` | **`role` 字段已存在**（L34，`SmallInteger`，0 普通 / 1 管理员，含 `idx_user_role` 索引）→ **本轮无需加字段、无需迁移** |
| `app/routers/auth.py` + `app/schemas/user.py` + `app/services/auth_service.py` | 注册链路无 `role`/`invite_code` 入参；`AuthService.register` 硬编码 `role=0`（L72） |
| `app/routers/admin.py` | 现有 4 个接口：`GET /admin/audit-logs/export`、`GET /admin/matches`（带 `expires_at > now-270d` 时间窗）、`POST /admin/export`（仅 csv、无 scope）、`POST /admin/cleanup`；`require_admin` 守卫已就位；`_build_forensic_row` 已能拿双方明文 `student_no/phone` 与对话文本 |
| **无 `RegisterView.vue`** | 注册表单实际在 `web/src/views/LoginView.vue` 的「注册」Tab（`regForm`，L146-168），本 PRD 全部以 `LoginView.vue` 为准 |
| `web/src/api/mockAdapter.ts` | admin mock 已有 `listAdminMatches`/`exportMatches`/`triggerCleanup`/`handleExportAudit`；`handleRegister`（L282）不识别邀请码；`buildMockMatchOut`（L172-206）**按 flow-v2 五维比例填充明细**，需同步改 |
| `app/core/config.py` | **无任何 ADMIN 相关配置位**；有 `MATCH_THRESHOLD=80`、`MATCH_LOW_SCORE=60`、`MATCH_TOP_N=10`、`TIME_DECAY_TAU_DAYS=3.0`、`AUDIT_RETENTION_DAYS=365` |
| `app/services/cleanup.py` | `ADMIN_RETENTION_DAYS = 270` 为**类常量硬编码**（未读 config）；`run_once` 只清理 IM/Match/Item，**从不清理 audit_log** |
| xlsx 依赖 | `openpyxl` 与 `pandas` **均未安装**（已实测 ImportError），`requirements.txt` 中也无 → 需新增依赖 |

---
## 1. 变更 A：评分引擎 v2（多维细化）

### A.1 背景

flow-v2 的五维公式把「文字」压成一个 50 分的**词覆盖率标量**（`hit / |lost_tokens|`），所有词一视同仁：颜色词、量词、地点词、品牌词权重完全相同。实际使用中出现两类偏差：

- **颜色误判不被惩罚**：「黑色钥匙」与「银色钥匙」只是少命中一个词，仍能拿到较高文字分，但对失主而言这基本可判定为两件东西；
- **量词/地点的判别力被稀释**：「一串钥匙 vs 一把钥匙」「四楼 vs 402」这些高信息量差异，在整体覆盖率里只值一两个词。

用户要求把文字拆成可解释的子维度并重新分配权重，同时把「照片」维度的语义从"图像相似度"改为"系统自动分类的准确度"。

### A.2 现状

```
普通类：score = 15·photo(感知哈希/CLIP) + 20·category + 50·text(词覆盖率) + 10·location(difflib) + 5·time(τ=3)
「其他」类：score = 20·photo + 80·tag_match_rate
```

### A.3 期望行为

#### A.3.0 总分构成

```
总分 100 = 照片/系统分类 20 + 文字描述 70 + 时间 10
```

文字 70 内部拆分：

| 子维度 | 分值 |
| --- | --- |
| 量词一致性 | 15 |
| 颜色一致性 | 20 |
| 状态/形容词 | 10 |
| 地点命中 | 15 |
| 其他关键词 | 10 |
| **合计** | **70** |

> **地点不再独立占权重**，它是文字 70 的子项之一。

#### A.3.1 全局共性规则（重要，务必落到实现）

**若失主侧未提供某子维度的信息 → 该子维度记 0 分**（不给中性分、不按比例放大其余维度）。

此口径由用户拍板的演算示例反推确定：失物「一串黑色钥匙，教学楼四楼402掉落」不含状态词、不含品牌/材质词，三个候选的总分（45/69/78）中「状态」与「其他关键词」两项均为 0。

> ⚠️ **产品侧后果（须知悉）**：总分上限受失主描述完整度封顶。示例中 C「一串钥匙，四楼，黑」几乎是完美匹配，也只有 78 分，达不到 `MATCH_THRESHOLD=80` 的疑似线。详见 §6 待确认问题 Q10。

#### A.3.2 照片 / 系统分类（20）

语义变更：**不再直接使用感知哈希 / CLIP 图像相似度作为权重来源**，改为「系统自动分类结果的一致性」。

| 情形 | 分值 |
| --- | --- |
| 双方归一化后 `category_name` 相同（或 `category_id` 相同） | 20 |
| 父子级 / 近似类目（沿用 `category_hit(exact=False)` 口径） | 10 |
| 类目不同 | 0 |
| 任一侧类目缺失（理论不出现，`category_name` 为必填） | 10（中性） |

感知哈希 / CLIP 降级为**同分排序 tie-breaker**（P2，不改总分，见 §4 需求池）。

#### A.3.3 文字 · 量词一致性（15）

抽取：复用现有 `_QTY_PREFIX_RE` / `_QTY_SUFFIX_RE`，但需从合成串（"一串"）中进一步拆出 **(数量, 量词)** 二元组。量词表沿用现有正则字符类：`个 把 张 只 条 部 串 双 对 辆 台 本 支 根 件 枚`。

| 情形 | 分值 | 依据 |
| --- | --- | --- |
| 量词相同 且 数量相同（一串 vs 一串） | **15** | 用户示例锁定 |
| 量词相同 但 数量不同（一把 vs 两把） | 8 | 建议默认，可配（Q5） |
| 量词不同 但 数量相同（一串 vs 一把） | **5** | 用户示例锁定 |
| 量词不同 且 数量不同（一串 vs 两把） | 2 | 建议默认，可配（Q5） |
| 失主侧无量词 | 0 | 共性规则 A.3.1 |
| 失主有量词、候选侧无量词 | 3 | 建议默认，可配（Q5） |

#### A.3.4 文字 · 颜色一致性（20）

新增常量 `COLOR_FAMILY: dict[str, str]`（词 → 色系），**统一落到新建模块 `app/services/scoring_refs.py`**（架构已定，与 `COLOR_ADJACENCY` / `STATE_WORD_PAIRS` / `CAMPUS_WORDS` / `ROOM_RE` 及 5 个子维度分类器同处；`tagging_service.py` 仅保留抽词原始词表被复用）：

| 色系 | 归入词（须同时兼容「带色字」与「不带色字」两种写法） |
| --- | --- |
| 黑系 | 黑、黑色、乌、墨 |
| 白系 | 白、白色、米白、奶白、米色 |
| 灰/银系 | 灰、灰色、银灰、银、银白、银色 |
| 棕系 | 棕、棕色、咖啡、卡其、卡其色、驼、栗 |
| 红系 | 红、红色、朱红、橙红、酒红、玫红 |
| 橙系 | 橙、橙色、橘 |
| 黄系 | 黄、黄色、鹅黄、金黄 |
| 绿系 | 绿、绿色、草绿、墨绿 |
| 蓝系 | 蓝、蓝色、青、湖蓝、天蓝、浅蓝、深蓝（**青归蓝系**） |
| 粉系 | 粉、粉色、桃粉、浅红 |
| 紫系 | 紫、紫色、紫罗兰、藕荷 |
| 金系 | 金、金色、香槟金 |
| 透明/无色 | 透明、无色 |

> 现有 `COLOR_WORDS` 仅收录带「色」字形态 + `黑白/银灰/浅蓝/深蓝/米色/卡其色/彩色`。演算示例 C 用的是裸字「黑」，因此**必须扩表覆盖裸色字**。`彩色`、`黑白` 的归类见 Q6。

评分：

| 情形 | 分值 |
| --- | --- |
| 同色系（黑 vs 黑色、青 vs 蓝） | **20** |
| 近似色系（邻接表命中：灰↔银、棕↔黄、粉↔红、紫↔蓝、金↔黄，可配） | 10 |
| **跨系冲突**（黑 vs 粉） | **0**，并置信号 `color_conflict = true` |
| 失主侧无颜色 | 0（不冲突） |
| 失主有颜色、候选无颜色 | 0（不冲突，不给分） |
| 多色 vs 多色 | 取最佳配对：任一对同系 → 20；否则任一对近似 → 10；全部跨系 → 0 + 冲突 |

`color_conflict = true` 时：
- 在 `score_detail.signals` 中输出 `"color_conflict"`；
- 前端候选卡片展示红色角标「**大概率非同一物品**」；
- **不做整条置零**（沿用 flow-v2「软化」原则，避免误伤）。

#### A.3.5 文字 · 状态/形容词（10）

新增反义词对表 `STATE_WORD_PAIRS`：新↔旧、完好↔破损/损坏/开裂/碎、干净↔脏/有污渍、大↔小、厚↔薄、满↔空。

| 情形 | 分值 |
| --- | --- |
| 失主状态词全部被命中（同词或同义） | 10 |
| 部分命中 | `10 × 命中数 / 失主状态词数` |
| 存在反义冲突（新 vs 旧） | 0，并置 `state_conflict = true` |
| 失主侧无状态词 | 0 |

#### A.3.6 文字 · 地点命中（15）

四级层次：**校区 > 楼/场所 > 楼层 > 房间**。

抽取来源与需补充的能力：

| 层级 | 抽取方式 | 现状 |
| --- | --- | --- |
| 校区 | `LOCATION_WORDS` 中「XX校区」模式 | **缺，需扩表** |
| 楼/场所 | 现有 `LOCATION_WORDS` 通用地点段（教学楼/图书馆/食堂/宿舍…） | 已有 |
| 楼层 | 现有 `LOCATION_WORDS` 楼层段（一楼~十二楼、一层~十二层） | 已有 |
| 房间 | 正则 `\d{3,4}`（如 402、A402） | **缺，需新增** |

评分（**按最深命中层级**给基础分；失主提供的全部层级都命中则满分）：

| 最深命中层级 | 分值 |
| --- | --- |
| 房间号命中 | 14 |
| 楼层命中（房间未命中或失主未提供） | 13 |
| 楼/场所命中 | 10 |
| 仅校区命中 | 6 |
| **失主提供的所有层级全部命中** | **15** |
| 无任何层级命中 / 失主侧无地点 | 0 |

#### A.3.7 文字 · 其他关键词（10）

定义：从失物侧文字词集中**扣除**量词、颜色、状态、地点四类后剩余的 token（品牌、材质、图案、型号等）。

`score = 10 × 命中数 / 失主侧剩余 token 数`，命中判定复用现有 `_token_hit`（精确 + WordNet + 中文近义词表）；失主侧剩余 token 为空 → 0。

> ⚠️ **物品名词本身（如「钥匙」）与类目名必须排除**（`NOUN_SET` ∪ `category_name`），否则演算示例 A/B/C 会额外得分导致总分对不上——名词的判别力已由「照片/系统分类 20」表达。
> ⚠️ 需扩充 `_STOPWORDS`：`掉落 / 丢了 / 不见了 / 落在 / 遗失 / 大概 / 好像` 等无判别力动词短语。

#### A.3.8 时间（10）

```
time_score = 10 × exp(-Δdays / 15)
Δdays = |found_time - lost_time| （天，复用现有 utils.time_decay.delta_days）
```

| Δ天数 | 得分 |
| --- | --- |
| 0 | 10.00 |
| 7 | 6.27 |
| 15 | 3.68 |
| 30 | **1.35** |
| 60 | 0.18 |

> ⚠️ 任务书写「30 天 ≈ 1.8」，按 `10·exp(-30/15)` 实际为 **1.35**（若要 1.8 需 τ≈17.5）。**以公式为准**，除非用户另行拍板（Q9）。

- τ 由**新增配置** `MATCH_TIME_TAU_DAYS: float = 15.0` 提供；**不复用** `TIME_DECAY_TAU_DAYS=3.0`（避免影响其它引用点）。
- 任一侧时间缺失 → 中性 5.0 分（沿用 flow-v2 Q6「中性 0.5」口径，待确认 Q8）。

#### A.3.9 「其他」类路径

建议：**统一走 v2 公式**，其中「照片/系统分类」在双方均为「其他」时记 10（中性，类目无判别力），文字 70 与时间 10 不变。取消 `20·photo + 80·tag_match_rate` 特殊路径。待确认（Q7）。

#### A.3.10 输出契约（`score_detail` / `MatchOut`）

**新增键**：

| 键 | 含义 | 值域 |
| --- | --- | --- |
| `photo_category` | 照片/系统分类得分 | 0–20 |
| `qty` | 量词一致性 | 0–15 |
| `color` | 颜色一致性 | 0–20 |
| `state` | 状态/形容词 | 0–10 |
| `place` | 地点命中 | 0–15 |
| `keyword` | 其他关键词 | 0–10 |
| `signals` | 信号列表 | `["color_conflict", "state_conflict"]` 子集 |

**旧键映射（保持向后兼容，避免 JSON 消费者断裂）**：

| 旧键 | v10 行为 |
| --- | --- |
| `photo` | 等于 `photo_category`（0–20） |
| `category` | 恒 `0.0`（deprecated 占位，已并入 photo） |
| `text` | 文字 70 合计 = `qty+color+state+place+keyword` |
| `text_match_rate` | 改为 `text / 70` |
| `location` | 等于 `place`（0–15）；前端需注明「已含在文字 70 内」 |
| `time` | 0–10 |
| `appearance` / `feature` | 恒 `0.0`（沿用） |
| `total` | 0–100 |

`MatchOut`（`app/schemas/match.py`）需新增上述 7 个可选字段并由 `build_match_outs` 透传。

### A.4 验收标准

| 编号 | 验收点 |
| --- | --- |
| AC-A1 | 失物「一串黑色钥匙，教学楼四楼402掉落」vs A「一把银色钥匙，教学楼」（同日、同类目钥匙）→ 总分 **45**，明细 `qty=5, color=0, state=0, place=10, keyword=0, photo_category=20, time=10`，`signals` 含 `color_conflict` |
| AC-A2 | 同上 vs B「一把黑色钥匙，402」→ 总分 **69**（`qty=5, color=20, place=14, photo=20, time=10`） |
| AC-A3 | 同上 vs C「一串钥匙，四楼，黑」→ 总分 **78**（`qty=15, color=20, place=13, photo=20, time=10`） |
| AC-A4 | 排序结果 C(78) > B(69) > A(45)，三者均 < 80 → 均为普通候选，`suspected=false` |
| AC-A5 | 色系归一：「黑」与「黑色」、「青」与「蓝色」判为同系得 20；「黑」vs「粉」得 0 且 `color_conflict=true` |
| AC-A6 | 时间：Δ=0 → 10.00；Δ=15 → 3.68±0.01；Δ=30 → 1.35±0.01；任一侧时间为 NULL → 5.00 |
| AC-A7 | 地点：候选同时命中「教学楼+四楼+402」→ `place=15`（全链路满分） |
| AC-A8 | 失主未写状态词 / 品牌词 → `state=0`、`keyword=0`（不给中性分） |
| AC-A9 | 「钥匙」等 `NOUN_SET` 词与类目名不计入 `keyword` 分母与分子 |
| AC-A10 | `score_detail` 同时返回新键与旧键，`total` 与 `match_score` 一致，旧键 `category` 恒 0.0 |
| AC-A11 | 所有权重 / τ / 色系表 / 层级分值均可从 `config` 或模块常量读取，无魔法数字散落 |

---
## 2. 变更 B：候选排序修正（疑似全列）

### B.1 背景

现规则「按分降序取前 10」是**硬截断**：若某件失物同时有 12 件高度吻合的拾物（≥80 疑似），第 11、12 件会被静默丢弃，失主永远看不到。用户纠正：**普通候选可以只给 10 条，但疑似匹配必须一条不漏。**

### B.2 现状（代码定位，已核对）

| # | 位置 | 现状代码 | 问题 |
| --- | --- | --- | --- |
| B-1 | `publish_service.py:344` `_reverse_match_lost` | `for score, f in scored[: settings.MATCH_TOP_N]` | 第 11 名起被丢弃，含 ≥80 的疑似 |
| B-2 | `publish_service.py:375-379` `_reverse_match_found` | `existing = count(...); if existing >= settings.MATCH_TOP_N: continue` | 已满 10 条的失物**完全**不再接收新候选，即使新拾物 95 分 |
| B-3 | `publish_service.py:383` `_reverse_match_found` | `scored[: settings.MATCH_TOP_N]` | 同 B-1 |
| B-4 | `publish_service.py:405-406` `refresh_lost_candidates` | `if existing >= settings.MATCH_TOP_N: return []` | 刷新候选时同样把疑似挡在门外 |
| B-5 | `publish_service.py:415` `refresh_lost_candidates` | `scored[: settings.MATCH_TOP_N - existing]` | 同 B-1 |
| B-6 | `web/src/api/mockAdapter.ts:227-235 / 251-259` | mock 侧同款 `slice(0, MATCH_TOP_N)` | 演示态口径需同步 |

### B.3 期望行为

1. **基础过滤（召回层）口径不变**：仍为「同类目 ∪ 共享物品名词 tag」（`_recall_lost_candidates` / `_recall_found_candidates`），与用户描述的「类别相关 或 文字有交集」等价，**本轮不改召回**。
2. **输出规则**：候选按总分降序（同分按 id 升序保持确定性）后，

   ```
   输出集 = scored[:MATCH_TOP_N]  ∪  { p | p.score >= MATCH_THRESHOLD }
   ```

   由于已按分降序，等价于取 `scored[: max(MATCH_TOP_N, 疑似条数)]`——实现上一行代码即可，无需两次遍历。
3. **`MATCH_TOP_N` 语义变更**（架构已定，设计 §1.2）：由「候选硬上限」改为「**普通候选保底条数（疑似全列不受此限）**」。相关注释、docstring、测试命名需同步更新（禁止出现"候选数恒 ≤10"类断言）。
4. **反向路径（B-2）改造**：删除 `if existing >= MATCH_TOP_N: continue` 的无条件跳过，改为：
   - 该失物已有候选数 `>= MATCH_TOP_N` **且** 本对分数 `< MATCH_THRESHOLD` → 跳过（维持"不打扰"）；
   - 本对分数 `>= MATCH_THRESHOLD` → **允许追加**（疑似全列）。
5. **刷新路径（B-4）改造**：`existing >= MATCH_TOP_N` 时不再直接 `return []`，而是**仅补入** `score >= MATCH_THRESHOLD` 的候选。
6. **flow-v3 守卫必须保留**：`_reverse_match_found` 开头的 `keep_status == NOT_KEEPING → return []` 早退**不得删除**；`_recall_lost_candidates` **不得**重新加回 `keep_status` 过滤。
7. **安全阀（P1）**：新增可配上限 `MATCH_SUSPECT_MAX: int = 50`，防止极端数据下单件失物候选数爆炸。

### B.4 验收标准

| 编号 | 验收点 |
| --- | --- |
| AC-B1 | 构造 15 个候选，其中 12 个 ≥80 → 发布失物后生成 **12** 条候选（疑似全列，非 10 条） |
| AC-B2 | 构造 15 个候选，其中 3 个 ≥80、12 个 <80 → 生成 **10** 条（普通保底 10，3 个疑似已含在前 10 内） |
| AC-B3 | 构造 15 个候选，其中 11 个 ≥80、4 个 <80 → 生成 **11** 条 |
| AC-B4 | 某失物已有 10 条候选，新发布一个 95 分 keep0 拾物 → 该失物**新增**第 11 条候选 |
| AC-B5 | 同上，新发布一个 40 分拾物 → **不新增**（不打扰） |
| AC-B6 | `refresh_lost_candidates` 在 existing=10 时仍能补入 ≥80 候选，<80 的不补 |
| AC-B7 | **flow-v3 回归**：keep1 拾物发布仍不反向生成候选（`_reverse_match_found` 早退保留） |
| AC-B8 | **flow-v3 回归**：keep1 拾物仍可被失主侧正向召回并出现在候选中 |
| AC-B9 | 排序稳定性：同分候选按 id 升序，多次执行结果一致 |
| AC-B10 | mock 侧（`mockAdapter.ts`）演示数据行为与后端一致 |

---

## 3. 变更 C：管理员注册（邀请码机制）

### C.1 背景

当前管理员账号只能靠手工改库（`user.role = 1`）产生，演示与验收都不方便。需要一条自助通道，同时避免暴露"管理员入口"给普通用户去试探。

### C.2 现状

- `User.role` 字段**已存在**（`app/models/user.py:34`，`SmallInteger`，0 普通 / 1 管理员）→ **无需加字段、无需 Alembic 迁移**。
- `UserCreate`（`app/schemas/user.py:12-19`）字段：`student_no / phone / sms_code / password / real_name`，**无邀请码**。
- `AuthService.register`（`app/services/auth_service.py:66-74`）硬编码 `role=0`。
- `LoginView.vue` 注册 Tab 的 `regForm`（L147-153）无邀请码字段。
- `config.py` **无任何 ADMIN 配置位**。
- `require_admin`（`app/routers/deps.py:44-48`）已按 `role != 1` 拒绝，无需改。
- 前端路由 `NAV_ITEMS` 中 `/admin` 已带 `roles: ['admin']` 门控。

### C.3 期望行为

1. **配置**：`config.py` 新增

   ```python
   ADMIN_APPLY_CODE: str = "110"   # 管理员申请邀请码；生产必须通过环境变量覆盖为强口令
   ```

2. **请求体**：`UserCreate` 新增 `admin_code: Optional[str] = Field(None, max_length=64, description="管理员邀请码（选填，不校验格式）")`。
   - **不做任何格式校验**（不限长度下限、不限字符集），避免用户通过报错信息反推口令形态。
3. **注册逻辑**（`AuthService.register`）：

   ```
   role = 1 if (admin_code or "").strip() == settings.ADMIN_APPLY_CODE.strip() else 0
   ```

   - 不填 → `role=0`；
   - 填错 → **静默** `role=0`，**不报错、不提示"邀请码错误"**（防试探，安全要求）；
   - 填对 → `role=1`，并写审计 `register_admin`（`target_type="user"`, `target_id=user.id`, `detail="student_no=..."`），便于事后追溯管理员来源。
4. **令牌**：`create_access_token(user.id, user.role)` 已透传 role，无需改；前端 `decodeJwt` 已取 `payload.role`。
5. **前端**（`LoginView.vue` 注册 Tab）：
   - 新增表单项「管理员邀请码（选填）」，`el-input`，**不加任何 `rules`**；
   - placeholder：`无邀请码请留空`；
   - 下方 `lf-muted` 小字提示：`仅管理员需填写；填写错误不影响正常注册`；
   - `onRegister` 提交时带上 `admin_code: regForm.admin_code || null`。
6. **前端类型/API**：`web/src/types/index.ts` 的注册请求类型与 `web/src/api/auth.ts` 的 `register` 入参新增 `admin_code?: string | null`。
7. **Mock**：`mockAdapter.handleRegister`（L282-294）改为 `role: b.admin_code === '110' ? 1 : currentMockRole`，保证演示态可直接注册出管理员。
8. **部署文档**：`docs/deploy.md` 增补一节 —— 生产环境必须设置环境变量 `ADMIN_APPLY_CODE=<强口令>`，默认值 `110` **仅供演示**。

### C.4 验收标准

| 编号 | 验收点 |
| --- | --- |
| AC-C1 | 注册不填 `admin_code` → 返回 `user.role == 0`，可正常登录，访问 `/admin/*` 返回 403 |
| AC-C2 | 注册填 `admin_code="abc乱填"` → **注册成功**（不报错），`user.role == 0` |
| AC-C3 | 注册填 `admin_code="110"` → `user.role == 1`，JWT payload 含 `role=1`，可访问 `/admin/*` |
| AC-C4 | 环境变量 `ADMIN_APPLY_CODE=SuperSecret!2026` 覆盖后，填 `110` 得 `role=0`，填新口令得 `role=1` |
| AC-C5 | 命中邀请码时 `audit_log` 新增一条 `action='register_admin'` |
| AC-C6 | 前端注册页邀请码输入框无红字校验、留空可直接提交 |
| AC-C7 | 前端注册出管理员后，侧边栏出现「管理后台」入口（`roles:['admin']` 门控生效） |
| AC-C8 | 演示模式（mock）下填 `110` 同样得到 `role=1` |
| AC-C9 | 错误邀请码的响应体与不填时**完全一致**（不可通过响应差异区分） |

---
## 4. 变更 D：管理员后台

### D.1 背景

现有后台只有「审计日志时间线 + 未失效匹配列表 + 一键 CSV 导出 + 触发清理」。纠纷取证时管理员实际需要：看**谁**注册了、看某条**匹配成功**记录的**双方真实身份**与**完整聊天记录**、把结果导出成**人能直接看的表格/文档**归档，并且这些记录要比普通用户侧**留存更久**。

### D.2 现状

| # | 位置 | 现状 | 缺口 |
| --- | --- | --- | --- |
| D-1 | `admin.py` | **无 `/admin/users`** | 无法查看注册用户 |
| D-2 | `admin.py:180-209` `GET /admin/matches` | 返回 `MatchOut` 列表，**不含双方用户信息、不含对话** | 详情能力缺失 |
| D-3 | `admin.py:144-171` `_build_forensic_row` | 已能取双方明文 `student_no/phone` + 对话文本（单行字符串） | 能力已有，**未暴露为查询接口**，且对话非结构化 |
| D-4 | `admin.py:212-245` `POST /admin/export` | 仅 `format="csv"`，**无 scope**，非 csv 直接 400 | 无 xlsx / md、无范围勾选 |
| D-5 | `admin.py:191-197` | `cutoff = now - 270d`，强制时间窗过滤 | 管理员看不到更早的历史 |
| D-6 | `cleanup.py:31` | `ADMIN_RETENTION_DAYS = 270` **类常量硬编码**，未读 config | 留存期不可配 |
| D-7 | `cleanup.py:run_once` | **从不清理 `audit_log`**（尽管 `AUDIT_RETENTION_DAYS=365` 存在） | 审计实际已"永久留存"，需文档化 |
| D-8 | `web/src/views/AdminView.vue` | 只有审计时间线 + 匹配表格 + 导出按钮 | 需加用户区块、详情抽屉、导出范围/格式选择 |

### D.3 期望行为

#### D.3.1 `GET /admin/users` — 注册用户列表（P0）

```
GET /api/v1/admin/users?keyword=&role=&status=&page=1&page_size=20
权限：require_admin
```

- `keyword`：对 `student_no` / `phone` / `real_name` 模糊匹配（`LIKE %kw%`）
- `role`：可选，0/1 过滤；`status`：可选，0 正常 / 1 封禁
- 返回 `Page[AdminUserOut]`，按 `id` 降序

**新增 `AdminUserOut`**（`app/schemas/user.py`）：

| 字段 | 说明 |
| --- | --- |
| `id` | 用户 id |
| `student_no` | 学号 |
| `phone` | **明文**（与既有取证导出口径一致，不脱敏） |
| `real_name` | 姓名 |
| `role` | 0 普通 / 1 管理员 |
| `status` | 0 正常 / 1 封禁 |
| `credit_score` | 信誉分 |
| `created_at` | 注册时间 |

> ⚠️ 不要复用 `UserOut`——它在 `from_model` 里做了 `desensitize_phone` 脱敏。
> 隐私口径：管理员侧明文，**每次调用写审计** `admin_list_users`。

#### D.3.2 `GET /admin/matches/{match_id}/detail` — 匹配记录详情（P0）

```
GET /api/v1/admin/matches/{match_id}/detail
权限：require_admin
```

返回：

```jsonc
{
  "match": { /* MatchOut，含分数明细 */ },
  "lost_user":  { "id":1, "student_no":"...", "phone":"...", "real_name":"...", "credit_score":100 },
  "found_user": { "id":2, "student_no":"...", "phone":"...", "real_name":"...", "credit_score":101 },
  "conversation": [
    { "sent_at": "2026-08-01T10:00:00", "sender_role": 0, "role_label": "失主",   "content": "..." },
    { "sent_at": "2026-08-01T10:01:00", "sender_role": 1, "role_label": "拾得者", "content": "..." }
  ]
}
```

- 对话为**结构化数组**（现有 `_build_conversation` 返回的是导出用单行字符串，需并存两种形态：`_build_conversation_rows()` 结构化 + `_build_conversation()` 扁平）；
- 无 IM 会话时 `conversation: []`（不报错）；
- 建议将 `_build_forensic_row` / `_build_conversation*` 抽到 `app/services/admin_export_service.py`，供路由与导出复用；
- 是否限定 `status == 2 COMPLETED` → 见 Q11（建议不硬限制，UI 默认从"已完成"进入）。
- 写审计 `admin_view_match_detail`。

#### D.3.3 `POST /admin/export` — 范围 + 多格式导出（P0）

请求体扩展（**向后兼容**，老调用不传新字段行为不变）：

```jsonc
{
  "ids": [1, 2, 3],
  "scope": "all",        // "profile" | "conversation" | "all"，默认 "all"
  "format": "xlsx"       // "csv" | "xlsx" | "md"，默认 "csv"
}
```

**scope 语义**：

| scope | 内容 |
| --- | --- |
| `profile` | 个人信息：`match_id` + 双方 `student_no/phone/real_name` + 物品摘要（类目/标题/描述）+ `completed_at` |
| `conversation` | 对话记录：`match_id` + 逐条 `[时间] 角色: 内容` |
| `all` | 现有 `_FORENSIC_FIELDS` 全量 + 对话（= 现状行为） |

**format 语义**：

| format | 实现 | 产物 |
| --- | --- | --- |
| `csv` | 沿用现有 `csv.DictWriter` | 单文件，回归兼容 |
| `xlsx` | **openpyxl**（需新增依赖） | 工作簿；`scope=all` 时分 2 个 Sheet：「个人信息」「对话记录」；首行加粗表头、列宽自适应、冻结首行 |
| `md` | **纯 f-string 拼装，不引第三方库** | 每条匹配一个 `## 匹配 #<id>` 小节：个人信息用 Markdown 表格，对话用有序列表 |

- 文件名：`forensic_matches_{scope}_{YYYYMMDD}.{ext}`
- MIME：xlsx → `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`；md → `text/markdown; charset=utf-8`
- 不支持的 `format` / `scope` → 400 + `{"code":9001,...}`（沿用现有错误体）
- 每次导出写审计 `admin_export`（`detail="ids=[...];scope=...;format=..."`）
- **依赖**：`requirements.txt` 新增 `openpyxl>=3.1,<4.0`（已实测未安装；不选 pandas——未安装且体积大，其 Excel 后端本身也是 openpyxl）

#### D.3.4 管理员记录留存更久（P0 + P1）

分两层，**推荐 P0 只做查询层，清理层仅做配置化**（风险最低）：

**P0 · 查询层放开（推荐）**

- `GET /admin/matches` 新增 `all_time: bool = Query(False)` 参数：
  - `all_time=false`（默认）→ 保持现有 `expires_at > now-270d` 时间窗，**v7 既有 AC 不回归**；
  - `all_time=true` → **不加**时间窗过滤，返回全部历史匹配（含超过普通留存窗的）。
- 前端管理后台默认传 `all_time=true`，并提供「仅近 1 年」切换开关。
- `GET /admin/audit-logs/export` 现已无时间窗（全量导出），保持现状。

**P1 · 清理层配置化**

- `config.py` 新增 `ADMIN_RETENTION_DAYS: int = 270`（架构已定，Q4）；
- `CleanupService.ADMIN_RETENTION_DAYS` 由类常量改为读配置（默认值保持 **270 不变**，避免既有 cleanup 测试断言回归）；
- **不**把默认值提到 1095（架构明确否决：会破坏现有 cleanup 单测前提，回归面大）。
- **文档化**：`audit_log` 当前**永不自动清理**（`run_once` 不涉及），即管理员审计天然长期留存；`AUDIT_RETENTION_DAYS=365` 为预留配置，本轮不启用清理逻辑。

> ✅ **Q4 已定**（架构设计 §1.2）：采纳「P0 查询层放开 + P1 清理层配置化」，**不采纳**激进 1095 方案。开工口径以此为准。

### D.4 验收标准

| 编号 | 验收点 |
| --- | --- |
| AC-D1 | 管理员 `GET /admin/users` 返回全部用户，含 `student_no/phone(明文)/real_name/status/credit_score/role`；普通用户调用返回 403 |
| AC-D2 | `keyword` 可按学号/手机/姓名模糊命中；`role`/`status` 过滤生效；分页正确 |
| AC-D3 | `GET /admin/matches/{id}/detail` 返回双方用户明文信息 + 结构化对话数组；无会话时 `conversation: []` |
| AC-D4 | 不存在的 `match_id` → 404 |
| AC-D5 | `POST /admin/export {scope:"profile", format:"xlsx"}` → 下载 .xlsx，仅含个人信息列，可被 Excel/WPS 正常打开 |
| AC-D6 | `POST /admin/export {scope:"conversation", format:"md"}` → 下载 .md，含每条匹配的对话小节 |
| AC-D7 | `POST /admin/export {scope:"all", format:"xlsx"}` → 工作簿含「个人信息」「对话记录」两个 Sheet |
| AC-D8 | `POST /admin/export {ids:[...]}`（不传 scope/format）→ 行为与 v7 完全一致（csv + 全量字段），**老前端不回归** |
| AC-D9 | `format="pdf"` 等非法值 → 400 + code 9001 |
| AC-D10 | `GET /admin/matches?all_time=true` 返回超 270 天窗的历史匹配；`all_time=false`/不传 → 与 v7 结果一致 |
| AC-D11 | 用户列表 / 详情 / 导出三个动作各自在 `audit_log` 留痕 |
| AC-D12 | `openpyxl` 未安装时导出 xlsx 给出明确错误提示而非 500 堆栈（防御性降级） |

---

## 5. 用户故事

| # | 角色 | 故事 |
| --- | --- | --- |
| US-1 | 失主 | As a 失主, I want 候选按「量词/颜色/状态/地点/关键词」细化后的分数排序, so that 最像我丢的那件东西排在最前面，而不是被一堆同类目杂项淹没 |
| US-2 | 失主 | As a 失主, I want 所有匹配度 ≥80 的疑似结果都完整展示（哪怕超过 10 条）, so that 我不会因为系统截断而永远错过真正的那一件 |
| US-3 | 失主 | As a 失主, I want 当候选颜色与我描述跨色系冲突时看到「大概率非同一物品」提示, so that 我不用白跑一趟去认领一件明显不是我的东西 |
| US-4 | 失主 | As a 失主, I want 在候选卡片上看到「分类 20 / 文字 70（含量词·颜色·状态·地点·关键词）/ 时间 10」的分项明细, so that 我能自己判断这个分数为什么高、为什么低 |
| US-5 | 新用户（管理员） | As a 管理员, I want 注册时填入邀请码就能直接获得管理员身份, so that 不需要运维手工改数据库 |
| US-6 | 新用户（普通） | As a 普通用户, I want 即使误填/乱填邀请码也能正常完成注册, so that 我不会被一个我根本不需要的字段挡在门外 |
| US-7 | 管理员 | As a 管理员, I want 在后台看到全部注册用户的学号/手机/姓名/状态/信誉分, so that 我能快速定位到具体的人 |
| US-8 | 管理员 | As a 管理员, I want 打开某条匹配成功记录看到双方真实身份与完整聊天记录, so that 发生纠纷时我有据可查 |
| US-9 | 管理员 | As a 管理员, I want 勾选导出范围（个人信息 / 对话记录 / 全部）并选 xlsx 或 md 下载, so that 我拿到的是能直接给人看、能直接归档的文件而不是原始数据 |
| US-10 | 管理员 | As a 管理员, I want 查询到比普通用户留存窗更早的历史记录, so that 跨学期的旧纠纷也能追溯 |

---
## 6. 需求池

### P0（本轮必做）

| ID | 需求 | 主要落点 |
| --- | --- | --- |
| R-A1 | 评分公式重构为 `20 分类 + 70 文字 + 10 时间` | `match_service.py`、`config.py` |
| R-A2 | 颜色合类表 `COLOR_FAMILY` + 近似邻接表 `COLOR_ADJACENCY` + 跨系冲突信号 | 新建 `app/services/scoring_refs.py` |
| R-A3 | 文字四子维度：量词 15 / 状态 10 / 地点四级 15 / 其他关键词 10 | `match_service.py` |
| R-A4 | 地点抽取补齐「校区」与「房间号」两级；`_STOPWORDS` 扩充 | `tagging_service.py`、`match_service.py` |
| R-A5 | 时间衰减 `10·exp(-Δ/15)`，新增 `MATCH_TIME_TAU_DAYS=15.0` | `config.py`、`match_service.py` |
| R-A6 | `score_detail` / `MatchOut` 契约扩展（7 个新键 + 旧键映射） | `match_service.py`、`schemas/match.py` |
| R-A7 | 前端候选卡片维度明细改版 + 颜色冲突角标 | `MatchesView.vue`、`mockAdapter.ts` |
| R-B1 | 候选输出「基础 10 + 疑似（≥80）全列」，三处守卫改造 | `publish_service.py`、`mockAdapter.ts` |
| R-C1 | `ADMIN_APPLY_CODE` 配置 + `admin_code` 注册链路（后端 + 前端 + mock + 部署文档） | `config.py`、`schemas/user.py`、`auth_service.py`、`LoginView.vue`、`api/auth.ts`、`types/index.ts`、`mockAdapter.ts`、`docs/deploy.md` |
| R-D1 | `GET /admin/users` + `AdminUserOut`（phone 明文） | `admin.py`、`schemas/user.py` |
| R-D2 | `GET /admin/matches/{id}/detail`（双方信息 + 结构化对话） | `admin.py`、新建 `admin_export_service.py` |
| R-D3 | `POST /admin/export` 扩 `scope` + `xlsx` + `md`（csv 保留兼容） | `admin.py`、`admin_export_service.py`、`requirements.txt` |
| R-D4 | `GET /admin/matches?all_time=true` 全量查询 | `admin.py`、`api/admin.ts`、`AdminView.vue` |
| R-D5 | 管理后台 UI：用户区块 + 详情抽屉 + 导出范围/格式选择 | `AdminView.vue`、`api/admin.ts`、`mockAdapter.ts` |
| R-E1 | **回归护栏**：flow-v3 三守卫（keep1 早退 / keep1 正向召回 / confirm-return 422）不被破坏 | 测试 |
| R-E2 | 存量测试断言按 v2 公式全量更新（旧五维用例） | `tests/` |
| R-E3 | 审计埋点：`register_admin` / `admin_list_users` / `admin_view_match_detail` / `admin_export` | `auth_service.py`、`admin.py` |

### P1（应做，可紧随其后）

| ID | 需求 |
| --- | --- |
| R-P1-1 | 颜色合类表 / 近似邻接表 **可配置**（config 或 JSON 资源文件，支持运行时替换而非改代码） |
| R-P1-2 | 时间衰减 τ、各子维度分值全部提到 config，支持不改代码调参 |
| R-P1-3 | 疑似全列硬上限 `MATCH_SUSPECT_MAX = 50`（防候选爆炸） |
| R-P1-4 | 归一化分开关：`MATCH_NORMALIZE = True`（**架构已落地为 config 位 + `score`/`score_detail` 代码骨架，默认开启即生效**，设计 §2.3；用户拍板「启用归一化」→ 默认开启，环境变量 `MATCH_NORMALIZE=false` 可回退降级）。开启后按「失主实际提供的维度」重新归一到 100，解决 §A.3.1 的封顶问题（见 Q10） |
| R-P1-5 | `CleanupService.ADMIN_RETENTION_DAYS` 配置化（默认仍 270） |
| R-P1-6 | 管理后台用户封禁 / 解封动作（`POST /admin/users/{id}/ban`） |
| R-P1-7 | 量词/状态词表可维护化 |
| R-P1-8 | 导出加"导出人 + 导出时间"页脚水印（取证可信度） |

### P2（可选增强）

| ID | 需求 |
| --- | --- |
| R-P2-1 | 感知哈希 / CLIP 作为**同分排序 tie-breaker**（不改总分，保留 P0-③ 投入不浪费） |
| R-P2-2 | 地点抽取升级为可由 admin 维护的校区/楼宇字典（替代硬编码 `LOCATION_WORDS`） |
| R-P2-3 | 导出 PDF |
| R-P2-4 | 管理后台评分调参面板（可视化调整权重并预览排序变化） |
| R-P2-5 | 候选卡片展示"为什么没匹配上"的反向解释（缺失的子维度提示） |

---

## 7. UI 变更点清单

### 7.1 `web/src/views/LoginView.vue`（注册 Tab）

| 变更 | 说明 |
| --- | --- |
| 新增表单项 | 「管理员邀请码（选填）」，位置放在「真实姓名（选填）」**之后**、注册按钮之前 |
| 控件 | `el-input`，`prefix-icon="Key"`，placeholder `无邀请码请留空` |
| 校验 | **无任何 rules**（不校验长度/格式/字符集） |
| 辅助文案 | 下方 `lf-muted` 小字：`仅管理员需填写；填写错误不影响正常注册` |
| 提交 | `onRegister` 携带 `admin_code: regForm.admin_code || null` |

### 7.2 `web/src/views/AdminView.vue`（管理后台）

| 区块 | 变更 |
| --- | --- |
| **新增「注册用户」区块** | 置于页面顶部（审计日志之上）；表格列：学号 / 手机号 / 姓名 / 角色（Tag：普通/管理员）/ 状态（Tag：正常/封禁）/ 信誉分 / 注册时间；顶部关键字搜索框 + 角色/状态下拉 + 分页器 |
| **匹配记录表格** | 新增「操作」列，「查看详情」按钮 |
| **详情抽屉（新增）** | `el-drawer`，左右两栏展示失主/拾得者信息卡（学号/手机/姓名/信誉分）+ 下方对话气泡列表（按时间升序，失主左、拾得者右）+ 匹配分数明细条 |
| **导出区改造** | 勾选行后展开：① 「导出范围」`el-radio-group`（个人信息 / 对话记录 / 全部）② 「导出格式」`el-radio-group`（Excel .xlsx / Markdown .md / CSV）③ 「导出（N）」按钮 |
| **留存开关** | 匹配列表顶部加 `el-switch`「仅看近 1 年」，默认**关闭**（即 `all_time=true`，看全部历史） |
| 提示文案 | 用户区块下方加 `el-alert`（info）：`管理员视图展示明文联系方式，所有查询与导出均已记入审计日志` |

### 7.3 `web/src/views/MatchesView.vue` / 候选卡片

| 变更 | 说明 |
| --- | --- |
| 维度明细改版 | 由「照片 15 / 类别 20 / 文字 50 / 地点 10 / 时间 5」改为「**分类 20** / **文字 70**（量词 · 颜色 · 状态 · 地点 · 关键词）/ **时间 10**」；文字维度可展开看 5 个子项 |
| 颜色冲突角标 | `signals` 含 `color_conflict` → 卡片右上角红色 `el-tag`「大概率非同一物品」 |
| 状态冲突角标 | `signals` 含 `state_conflict` → 橙色 `el-tag`「新旧状态不符」（P1） |
| **不变项** | flow-v3 的低分（<60）弱化展示、虚线卡片、低分二次确认、「删除低分不打扰」逻辑**全部保持原样** |

### 7.4 前端基础设施

| 文件 | 变更 |
| --- | --- |
| `web/src/api/auth.ts` | `register` 入参加 `admin_code?: string \| null` |
| `web/src/types/index.ts` | 注册请求类型加 `admin_code`；`MatchOut` 类型加 7 个新明细字段；新增 `AdminUser` / `AdminMatchDetail` 类型 |
| `web/src/api/admin.ts` | 新增 `listUsers()` / `getMatchDetail(id)`；`exportMatches(ids, scope, format)` 支持三种格式与正确的 MIME/扩展名；`listAdminMatches` 支持 `all_time` |
| `web/src/api/mockAdapter.ts` | ① `handleRegister` 识别 `admin_code==='110'` → `role=1`；② `buildMockMatchOut`（L172-206）明细比例改为 v2（20/70/10 + 5 子项）；③ 候选生成 `slice` 改为「基础 10 + 疑似全列」；④ 新增 `/admin/users`、`/admin/matches/{id}/detail` 两条 mock 路由；⑤ `exportMatches` 支持 scope/format |

---

## 8. 待确认问题

> **架构定案进度**：5 个拍板点（Q2 / Q3 / Q4 / Q13 + 变更 B 简化 + 变更 A 模块归属）已由架构师在 `docs/architecture/v10_scoring_admin_incremental_design.md` §1.2 定案；Q5 / Q6 / Q7 / Q8 / Q9 / Q11 / Q12 按本 PRD 默认建议采纳（设计 §1.3）；**Q10 已由用户拍板（归一到100 / 阈值80保留）**。全部待确认项（Q1–Q13）均已闭环，**可直接开工**。

| # | 问题 | 现状/建议 | 需谁拍板 | 状态 |
| --- | --- | --- | --- | --- |
| Q1 | `role` 字段是否已有？ | **已有**（`user.role` SmallInteger 0/1，含索引）→ 无需迁移 | — | ✅ 关闭（已核实） |
| Q2 | xlsx 用 openpyxl 还是 pandas？ | 实测两者均未安装。架构拍板 **openpyxl>=3.1,<4.0**（写 `requirements.txt`）；**不引 pandas** | 架构师 | ✅ 已定（设计 §1.2） |
| Q3 | md 用内置还是 markdown 库？ | **纯 f-string 拼装**，零新增依赖（"生成"非"解析"） | 架构师 | ✅ 已定（设计 §1.2） |
| Q4 | 「留存更久」策略 | **已定**：P0 仅 `GET /admin/matches?all_time=true` 放开查询（不加时间窗）；P1 清理层配置化 `ADMIN_RETENTION_DAYS=270`（默认不变）；**不提 1095**（会破坏 cleanup 单测） | 架构师 | ✅ 已定（设计 §1.2） |
| Q5 | 量词子维度中间档位 | 同量词数量不同=8 / 量词不同数量不同=2 / 候选缺量词=3 | 用户 | ✅ 采纳默认（设计 §1.3） |
| Q6 | 彩色/黑白归类 + 邻接对 | `彩色`=通配(10) / `黑白`=黑∪白 / 邻接对=灰↔银、棕↔黄、粉↔红、紫↔蓝、金↔黄（写 `COLOR_ADJACENCY`） | 用户 | ✅ 采纳默认（设计 §1.3） |
| Q7 | 「其他」类路径 | 统一走 v2，双方均其他时 `photo_category=10` 中性，删除 `20·photo+80·tag` | 用户/架构师 | ✅ 采纳默认（设计 §1.3） |
| Q8 | 时间缺失中性分 | 任一侧缺时间 → **5.0 中性**（沿用 flow-v2 Q6） | 用户 | ✅ 采纳默认（设计 §1.3） |
| Q9 | 30 天 1.35 vs 1.8 | **以公式为准**：`10·exp(-Δ/15)`，τ=15，30 天=**1.35**，不追 1.8 | 用户 | ✅ 已定（设计 §1.3） |
| Q10 | **疑似阈值 80 是否维持？** | 变更 A 使总分受描述完整度封顶（示例 C 仅 78 < 80）。用户拍板：**启用归一化**——失主未填维度不计入，按已填维度归一到 100；**疑似阈值 80 保留不变**。代码侧 `MATCH_NORMALIZE` 插入点（设计 §2.3）已就位，落地即生效 | 用户 | ✅ 已定（用户拍板：归一到100 / 阈值80保留） |
| Q11 | 详情接口限定 `status==2`？ | **不硬限制**，UI 默认从「已完成」进入 | 用户 | ✅ 采纳默认（设计 §1.3） |
| Q12 | 明文隐私口径 | 管理员侧 `phone` 明文 + 每次查询/导出写审计 + 前端合规提示（与现有取证导出口径一致） | 用户 | ✅ 采纳默认（设计 §1.3） |
| Q13 | `MATCH_TOP_N` 改名？ | **保留变量名**，docstring/注释更新为「普通候选保底条数（疑似全列不受此限）」 | 架构师 | ✅ 已定（设计 §1.2） |

---

## 9. 兼容 / 回归点

### 9.1 flow-v3 不可破坏项（最高优先级）

| # | 保护项 | 具体要求 |
| --- | --- | --- |
| G-1 | **keep1 单向进池** | `_recall_lost_candidates` **不得**重新加回 `keep_status` 过滤；`_reverse_match_found` 开头的 `if keep_status == NOT_KEEPING: return []` 早退**必须保留** |
| G-2 | **keep1 守卫** | `confirm-return` 对 keep1 返回 422、`claim` 对 keep1 返回 422，两条守卫不变；前端拾得者侧不渲染「确认归还/拒绝」 |
| G-3 | **低分阈值 60** | `MATCH_LOW_SCORE = 60.0` 不变；前端弱化展示、虚线卡片、低分二次确认口径不变 |
| G-4 | **删除低分不打扰** | flow-v3 的低分不打扰逻辑不变；变更 B 的「疑似追加」只在 `score >= MATCH_THRESHOLD` 时突破 top10，**低分永远不突破** |
| G-5 | **keep1 申请即完成 / 撤回** | `complete_keep1_claim` / `revoke_keep1_claim` 行为不变；`_exists_match` 排除终态 `{2,3,6}` 不变 |

> ⚠️ 变更 A 会**改变所有候选的分数**，从而改变哪些候选落在 <60 弱化区间。flow-v3 的低分相关**测试夹具分数需重新标定**（逻辑不变，但输入数据要重算，T05）。重标定所需的演算示例精确输入（失物「一串黑色钥匙，教学楼四楼402掉落」vs A/B/C）见 §1 AC-A1~A3，可直接供 QA 复用。

### 9.2 契约向后兼容

| # | 项 | 处理 |
| --- | --- | --- |
| C-1 | `score_detail` 旧键 | `photo/category/text/text_match_rate/location/time/appearance/feature/total` 全部保留，按 §A.3.10 映射；`category`/`appearance`/`feature` 恒 0.0 |
| C-2 | `MatchOut` | 新字段全部 `Optional`，老前端不传/不读不报错 |
| C-3 | `POST /admin/export` | `scope` 默认 `"all"`、`format` 默认 `"csv"` → 老前端只传 `ids` 时行为与 v7 **完全一致** |
| C-4 | `GET /admin/matches` | `all_time` 默认 `False` → 不传时保持 270 天时间窗，v7 AC 不回归 |
| C-5 | `UserCreate.admin_code` | `Optional`，老客户端不传 → `role=0`，注册链路不受影响 |
| C-6 | `UserOut` | 不改（仍脱敏），管理员明文走新的 `AdminUserOut` |
| C-7 | 旧权重配置 | `MATCH_W_PHOTO/CAT/TEXT/LOC/TIME/APP/FEAT/TAG/OTHER` 与 `MATCH_W1~W4` 全部**保留并标 deprecated**，新增 `MATCH_W2_*` 系列，避免外部引用断裂 |
| C-8 | `TIME_DECAY_TAU_DAYS=3.0` | 保留不动，新增 `MATCH_TIME_TAU_DAYS=15.0` 供 v2 使用 |
| C-9 | `utils/time_decay.py` | 通用函数不改（`time_decay(delta, tau)` 签名稳定），仅调用方传新 τ |

### 9.3 必须更新的测试断言

| # | 范围 | 说明 |
| --- | --- | --- |
| T-1 | 五维公式相关全部单测 | 所有断言 `15·photo + 20·category + 50·text + 10·location + 5·time` 的用例需按 v2 重算期望值 |
| T-2 | `text_match_rate` 相关 | 语义从「50 分权重的覆盖率」变为「70 分文字合计 / 70」，断言需改 |
| T-3 | `location_factor` 相关 | difflib 相似度路径被四级层次命中替换，旧断言失效 |
| T-4 | `photo_sim_factor*` / CLIP / phash 相关 | 不再参与总分，相关"照片影响分数"的断言需删除或改为 tie-breaker 测试（P2 前先标 skip） |
| T-5 | `MATCH_TOP_N=10` 硬上限断言 | 「候选数恒 ≤10」类断言需改为「≥80 时可 >10」 |
| T-6 | 「其他」类 `20·photo + 80·tag` 用例 | 按 Q7 决议改写或删除 |
| T-7 | cleanup 相关用例 | **Q4 已定方案 A（查询层放开）** → cleanup 用例**无需改**；P1 配置化仅改 `cleanup.py` 读 `settings.ADMIN_RETENTION_DAYS`（默认值不变，既有单测不回归） |
| T-8 | 新增用例 | §A.4 的 AC-A1~A3 三条演算示例应作为**黄金用例**固化进测试，任何后续调参不得破坏 |

### 9.4 数据 / 部署

| # | 项 | 说明 |
| --- | --- | --- |
| M-1 | Alembic 迁移 | **本轮无 schema 变更**（`role` 字段已存在）→ 不需要新 migration |
| M-2 | 历史 `match_record.match_score` | 存量分数按旧公式计算，与新公式**不可比**。建议：不做批量回算（成本高且无业务价值），在管理后台加一行说明「v10 前的历史分数按旧公式计算」；失主可通过「刷新候选」自然获得新分 |
| M-3 | 新依赖 | `requirements.txt` 新增 `openpyxl>=3.1,<4.0` |
| M-4 | 新环境变量 | `ADMIN_APPLY_CODE`（默认 `110`，生产必须覆盖）、可选 `MATCH_TIME_TAU_DAYS` / `ADMIN_RETENTION_DAYS` |

---

## 10. 交付顺序建议（供架构师拆任务参考）

1. **第 1 批（可并行）**：变更 C（注册邀请码，改动面小、独立）+ 变更 D 的 `GET /admin/users`（纯新增接口）
2. **第 2 批**：变更 A（评分引擎 v2）—— 单文件深改，先落后端 + 黄金用例，再改前端展示与 mock
3. **第 3 批**：变更 B（依赖 A 的分数口径稳定后再改，避免同时调两个变量导致测试无法定位）
4. **第 4 批**：变更 D 剩余（详情接口 + 多格式导出 + all_time + 后台 UI）
5. **第 5 批**：全量回归（重点跑 flow-v3 的 G-1~G-5 护栏用例）

> ✅ **Q10 已定**：用户拍板「按已填维度归一化」——失主未填维度不计入、按已填维度归一到 100、疑似阈值 80 保留不变。全部待确认项（Q1–Q13）均已闭环，v10 可整体开工；归一化实现见架构设计 §2.3（`MATCH_NORMALIZE` 插入点）。




