# flow-v3 增量 PRD（keep1 回归匹配池 + 低分阈值 60）

## 0. 项目信息

| 项 | 内容 |
| --- | --- |
| Language | 简体中文 |
| Project Name | lostfound_flow_v3 |
| 基线版本 | flow-v2（已交付） |
| 技术栈 | 后端 FastAPI + SQLAlchemy；前端 Vue3 + Element Plus + Vite |
| 文档性质 | **增量 PRD** —— 仅描述相对 flow-v2 的变更，未提及部分一律保持现状 |

### 原始需求复述

1. **变更 A**：keep_status=1（留在原地未挪动）的拾物，之前被整体排除出自动匹配。用户澄清：不进"双向认领闭环" ≠ 不进"匹配池"。keep1 物品仍需被系统智能匹配，命中疑似匹配后要出现在"我的匹配"栏；但认领动作仍保持"申请即完成 + 可撤回"的简化流程。
2. **变更 B**：低分（弱化展示）阈值从 80 下调到 60 —— "匹配度低于 60 才算低"。疑似匹配（suspected）阈值维持 80 不变。

---

## 1. 变更概述

### 变更 A：keep1（留在原地未挪动）重新进入"匹配池"

#### A.1 背景

flow-v2 的 R2-a 需求将 keep1 理解为"退出自动双向匹配"，于是在**召回层**直接把 keep1 拾物剔除。实际用户意图是：

- keep1 **要**参与智能匹配与候选生成（匹配池）；
- keep1 **不**参与交接码、拾得者确认、动态交接码双端确认（双向认领闭环）。

两者被 flow-v2 误合并为同一件事，导致"留在原地"的物品在系统里彻底失联——失主发布失物后，即便原地那件物品高度吻合，也永远不会出现在"我的匹配"。

#### A.2 现状偏差（代码定位，已核对）

| # | 位置 | 现状 | 偏差说明 |
| --- | --- | --- | --- |
| A-1 | `app/services/publish_service.py:289`，位于 **`_recall_lost_candidates`**（失物 → 拾物候选，即正向召回；task 描述中写成 `_recall_found_candidates`，实际以本表为准） | `.filter(FoundItem.keep_status == int(KeepStatus.KEEPING))` | 失物发布 / `refresh_lost_candidates` 刷新候选时，keep1 拾物被基查询过滤掉 |
| A-2 | `app/services/publish_service.py:359-360`，`_reverse_match_found` | `if int(found.keep_status) == int(KeepStatus.NOT_KEEPING): return []` | keep1 拾物发布时不反向匹配任何失物，直接返回空候选 |
| A-3 | `web/src/api/mockAdapter.ts:222`、`:392-394` | mock 侧同口径排除 keep1 | 前端 mock 模式与真实后端行为需同步修正，否则联调/演示口径不一致 |
| A-4 | `app/routers/match.py`（`confirm-return` 分支，约 `:483-495` 上下文） | **无 keep1 守卫** | flow-v2 下 keep1 从不生成候选，因此拾得者永不会看到 keep1 候选；变更 A 放开后，keep1 候选会出现在拾得者侧"我的匹配"，若拾得者点"确认归还"，keep1 就被拉回双向闭环，违背简化流程约束 —— **本轮必须补守卫** |
| A-5 | `web/src/views/MatchesView.vue:181-190` | 拾得者侧 `status===0` 且非低分时渲染「确认归还 / 拒绝」主按钮 | 同 A-4，前端需对 `found_item.keep_status === 1` 的候选屏蔽这两个按钮，改为只读提示 |

> A-4 / A-5 是变更 A 放开召回后**新暴露**的一致性缺口，不在 team-lead 原始清单内，属本 PRD 补充的 P0 项。

#### A.3 期望行为

1. **召回对称放开**：删除 A-1 的 `keep_status` 过滤条件、删除 A-2 的早退分支。keep1 拾物与 keep0 拾物在候选生成上完全等价：
   - 正向：失主发布失物 / 刷新候选时，keep1 拾物可被召回并打分；
   - 反向：keep1 拾物发布时，可反向匹配"待匹配 / 匹配中"的失物，并将命中失物置为 MATCHING。
2. **候选落库口径不变**：keep1 候选同样按五维公式（15 照片 + 20 类别 + 50 文字 + 10 地点 + 5 时间）打分，无论分数高低一律落 `status=0`（待认领），受 `MATCH_TOP_N=10` top10 上限与"单件失物候选数 ≥10 跳过"守卫约束，并出现在双方的"我的匹配"页。
3. **认领流程保持简化（不变）**：失主对 keep1 候选点"申请匹配" → 走 `PublishService.complete_keep1_claim`，一步落终态 `status=2` + `flow_type=1` + `completed_at`，双方物品置已解决，写审计 `keep1_claim_complete`；完成后失主可撤回（`keep1_claim_revoke` → `status=6`）。**不生成交接码，不要求拾得者确认。**
4. **拾得者侧只读**：keep1 候选在拾得者侧不提供"确认归还 / 拒绝"操作入口，前端展示为「留在原地·等待失主自取」类只读提示；后端 `confirm-return` 对 keep1 返回 422，与既有 `claim` 的 422 守卫对称。
5. **不变项**：flow-v2 R1 的"已交接栏只展示拾物 + 去重"逻辑不变；`_exists_match` 排除终态 `{2,3,6}` 的逻辑不变（撤回后可再次申请、可再次生成候选）。

#### A.4 验收标准

| 编号 | 验收点 |
| --- | --- |
| AC-A1 | 发布 keep1 拾物 → 返回的 `suspected_matches` 可以非空；同品类在库失物应被反向匹配并生成 `status=0` 候选，失物 `status` 变为 MATCHING |
| AC-A2 | 发布失物 → 同品类 keep0 与 keep1 拾物**都**出现在候选列表中，排序仍按 (-score, found_id) |
| AC-A3 | `refresh_lost_candidates` 刷新时同样可补入 keep1 拾物候选 |
| AC-A4 | 失主对 keep1 候选调用「申请匹配」→ 一步完成：`status=2`、`flow_type=1`、`completed_at` 非空、lost/found 均置已解决、审计含 `keep1_claim_complete`；全程无交接码生成 |
| AC-A5 | 失主对上述完成记录调用撤回 → `status=6`、审计含 `keep1_claim_revoke`；随后同一对 lost/found 可再次被匹配/申请（`_exists_match` 终态排除生效） |
| AC-A6 | 失主对 keep1 候选调用普通 `claim` → 仍返回 422（既有守卫不回归） |
| AC-A7 | **新增**：拾得者对 keep1 候选调用 `confirm-return` → 返回 422，提示应由失主自取完成 |
| AC-A8 | **新增**：前端"我的匹配"拾得者视角下，keep1 候选不渲染「确认归还 / 拒绝」按钮 |
| AC-A9 | keep0 行为零回归：keep0 候选仍走生成交接码 → 拾得者确认 → 动态交接码双端确认的完整闭环 |
| AC-A10 | 已交接栏仍只展示拾物且已去重（R1 不回归）；top10 上限不被 keep1 候选突破 |

---

### 变更 B：低分阈值下调为 < 60

#### B.1 背景

当前"低分"与"疑似匹配"共用同一个阈值 `MATCH_THRESHOLD = 80.0`：≥80 为疑似匹配（`suspected=true`），<80 一律被判为低分并做弱化展示。用户反馈这个口径过严 —— 70 分左右的候选其实相当有参考价值，却被打上"低匹配度·谨慎申请"的负面标签、加灰色虚线弱化样式，并在申请时被二次确认弹窗劝退，抑制了正常认领。

用户明确要求：**匹配度低于 60 才算低。**

#### B.2 现状偏差

| # | 位置 | 现状 |
| --- | --- | --- |
| B-1 | `app/core/config.py:89` | `MATCH_THRESHOLD: float = 80.0`，注释"疑似匹配阈值（保留仅作 suspected 标记）"；无独立低分常量 |
| B-2 | `app/services/match_service.py:616、:647` | `score >= settings.MATCH_THRESHOLD` 决定 `suspected`；解释体 `threshold` 字段回传 80 |
| B-3 | `web/src/api/constants.ts:93-94` | `export const MATCH_THRESHOLD = 80`，注释直接写"前端低分判定口径：match_score < 80 为低分" |
| B-4 | `web/src/views/MatchesView.vue:292-294` | `isLowScore(m) => m.match_score < MATCH_THRESHOLD` |
| B-5 | `web/src/views/MatchesView.vue:447` | 二次确认文案硬编码 `'该候选匹配度较低（<80），请确认对方物品与你的失物一致后谨慎申请。'` |
| B-6 | `web/src/api/mockAdapter.ts:196` | `suspected: score >= MATCH_THRESHOLD`（此处属 suspected 语义，**不改**） |
| B-7 | `web/src/types/index.ts:124` | 注释"达到疑似阈值（score>=80…）；低分候选 suspected=false，由前端用 match_score<80 派生弱化样式" —— 后半句需改为 60 口径 |
| B-8 | `tests/test_match.py:56` | `assert settings.MATCH_THRESHOLD == 80.0`（保留，另需补 `MATCH_LOW_SCORE == 60.0` 断言） |

#### B.3 期望行为

**核心决策：拆分两个语义独立的阈值，不再复用同一常量。**

| 概念 | 常量 | 值 | 用途 |
| --- | --- | --- | --- |
| 疑似匹配 suspected | `MATCH_THRESHOLD` | 80.0（**不变**） | 后端 `suspected` 字段、解释体 `threshold`、"疑似匹配"语义 |
| 低分弱化 low score | `MATCH_LOW_SCORE` | **60.0（新增）** | 前端弱化标签 / 弱化样式 / 低分二次确认弹窗 |

具体要求：

1. 后端 `app/core/config.py` 新增 `MATCH_LOW_SCORE: float = 60.0`，注释标明"低分视觉阈值，仅驱动前端弱化展示，不影响候选生成与 suspected 判定"。`MATCH_THRESHOLD = 80.0` 原样保留。
2. 后端候选生成、打分、落库、top10 排序**完全不受影响**（现状即"无论分数一律落库"，本次不引入任何按分过滤）。
3. 前端 `web/src/api/constants.ts` 新增 `export const MATCH_LOW_SCORE = 60`，并修正 `MATCH_THRESHOLD` 的注释（删掉"前端低分判定口径：match_score < 80"这句误导性描述）。
4. `MatchesView.vue` 的 `isLowScore` 改为 `m.match_score < MATCH_LOW_SCORE`。
5. `MatchesView.vue:447` 二次确认文案 "（<80）" → "（<60）"。建议同时把数字从模板字符串中提取为 `${MATCH_LOW_SCORE}` 插值，避免后续再次硬编码漂移。
6. `mockAdapter.ts` 中 `suspected: score >= MATCH_THRESHOLD` **保持不变**（属 suspected 语义）；mock 若另有低分派生逻辑一并切到 `MATCH_LOW_SCORE`（现状核查：mock 未独立实现低分判定，低分展示统一由 `MatchesView.isLowScore` 派生，故本项实际改动量为 0，仅需回归确认）。
7. `web/src/types/index.ts:124` 注释更新为："达到疑似阈值（score>=80，语义不变）；弱化展示由前端用 `match_score < 60`（MATCH_LOW_SCORE）派生，与 suspected 解耦"。
8. `tests/test_match.py` 补充 `assert settings.MATCH_LOW_SCORE == 60.0`。

#### B.4 分数区间行为矩阵（改动后）

| 分数区间 | suspected | 前端弱化标签 / 样式 | 失主申请路径 | 拾得者侧主按钮（keep0） |
| --- | --- | --- | --- | --- |
| ≥ 80 | true | 无 | 直接弹认领理由 | 显示「确认归还 / 拒绝」 |
| 60 – 79 | false | **无**（本次变更点：从弱化改为正常展示） | **直接弹认领理由**（不再二次确认） | **显示「确认归还 / 拒绝」**（详见 Q1 决策点） |
| < 60 | false | 有：「低匹配度·谨慎申请」标签 + 灰橙虚线弱化卡片 | 先二次确认（文案 <60）再弹认领理由 | 只读「疑似候选（等待失主申请）」 |

#### B.5 验收标准

| 编号 | 验收点 |
| --- | --- |
| AC-B1 | `settings.MATCH_LOW_SCORE == 60.0` 且 `settings.MATCH_THRESHOLD == 80.0`（两者并存） |
| AC-B2 | 分数 85 的候选：`suspected=true`，无弱化标签，申请无二次确认 |
| AC-B3 | 分数 70 的候选：`suspected=false`（后端语义不变），前端**无**弱化标签、**无**弱化样式、申请**不**触发二次确认 |
| AC-B4 | 分数 45 的候选：前端有「低匹配度·谨慎申请」标签 + 弱化样式，申请触发二次确认且文案为"（<60）" |
| AC-B5 | 全仓检索无残留硬编码 "80" 用于低分判定、无残留 "<80" 文案 |
| AC-B6 | 候选生成数量与排序不因本次改动发生变化（top10、含低分全量落库口径不回归） |

---

## 2. 用户故事

| ID | 用户故事 | 所属变更 |
| --- | --- | --- |
| US-1 | 作为**失主**，我希望即使拾得者选择了"留在原地未挪动"，系统也能把这件物品智能匹配给我并显示在"我的匹配"里，这样我才不会错过明明就在原地的失物。 | A |
| US-2 | 作为**失主**，我希望对 keep1 候选点一次"申请匹配"就直接完成认领（无需交接码、无需等拾得者确认），这样我可以立刻自己去原地取回。 | A |
| US-3 | 作为**失主**，我希望误点申请后能一键撤回，撤回之后这条匹配还能再次申请，这样操作失误不会造成不可逆后果。 | A |
| US-4 | 作为**拾得者**，我发布"留在原地"的拾物后，希望系统仍能帮我匹配到可能的失主并在"我的匹配"里显示进展，这样我知道自己的善意有没有被接住。 | A |
| US-5 | 作为**拾得者**，对于"留在原地"的物品我不希望被要求做"确认归还"的操作（东西根本不在我手上），界面应只让我看到状态而不给我误操作的按钮。 | A |
| US-6 | 作为**失主**，对于匹配度 60–79 的候选，我希望它正常展示、不被打上"低匹配度"负面标签、申请时不被额外弹窗劝阻——它虽然不是系统认定的"疑似匹配"，但仍然值得我认真看一眼。 | B |
| US-7 | 作为**失主**，对于匹配度低于 60 的候选，我希望界面明显弱化并在申请前提醒我"请确认物品一致后谨慎申请"，避免我盲目提交无效认领。 | B |
| US-8 | 作为**平台运营**，我希望"疑似匹配（≥80）"与"低分弱化（<60）"是两个可独立调整的配置项，这样以后调视觉口径时不会误伤匹配算法语义。 | B |

---

## 3. 需求池

### P0（本轮必做）

| ID | 需求 | 涉及文件 |
| --- | --- | --- |
| P0-1 | 移除正向召回中的 keep1 过滤（`_recall_lost_candidates` 的 `keep_status == KEEPING` 条件） | `app/services/publish_service.py:289` |
| P0-2 | 移除反向匹配中的 keep1 早退（`_reverse_match_found` 开头的 `NOT_KEEPING → return []`） | `app/services/publish_service.py:359-360` |
| P0-3 | 同步修正上述两处的中文注释与模块级 docstring（`publish_service.py` 头部关于 R2-a 的描述） | `app/services/publish_service.py` |
| P0-4 | **新增守卫**：`confirm-return` 接口对 `found.keep_status==1` 返回 422（与 `claim` 的 422 守卫对称），文案指向"该物品留在原地，请由失主申请后自取完成" | `app/routers/match.py` |
| P0-5 | 前端拾得者侧对 keep1 候选屏蔽「确认归还 / 拒绝」，改为只读提示（如「留在原地·等待失主自取」） | `web/src/views/MatchesView.vue:181-190` |
| P0-6 | mock 适配器同步放开 keep1 进匹配池（去掉 `f.keep_status === 0` 过滤与 keep1 不生成候选分支） | `web/src/api/mockAdapter.ts:213-222、:392-394` |
| P0-7 | 后端新增 `MATCH_LOW_SCORE: float = 60.0`，`MATCH_THRESHOLD` 保持 80.0 | `app/core/config.py:89` |
| P0-8 | 前端新增 `MATCH_LOW_SCORE = 60` 常量并修正 `MATCH_THRESHOLD` 注释 | `web/src/api/constants.ts:93-94` |
| P0-9 | `isLowScore` 切换到 `MATCH_LOW_SCORE`；二次确认文案 "<80" → "<60"（建议改为常量插值） | `web/src/views/MatchesView.vue:292-294、:447` |
| P0-10 | `types/index.ts:124` 注释更新为 60 口径说明（suspected 与弱化解耦） | `web/src/types/index.ts:124` |
| P0-11 | 用例重写：`tests/test_flow_v2.py` 中 R2-a 相关三条断言（`test_keep1_found_publish_has_no_candidates`、`test_lost_publish_excludes_keep1_candidates` 及其头部 docstring）需**反转期望**为"keep1 进候选" | `tests/test_flow_v2.py:4、:84-103` |
| P0-12 | 新增用例：keep1 反向匹配生成候选、keep1 候选申请即完成、`confirm-return` 对 keep1 返回 422、`MATCH_LOW_SCORE` 常量断言 | `tests/`（新增或就近扩展） |

### P1（本轮建议同步处理）

| ID | 需求 |
| --- | --- |
| P1-1 | 清理其余测试文件中"keep1 退出匹配池"的过时注释（`tests/test_mymatch_top10.py:17`、`tests/test_v3_incremental.py:26`），避免后续维护者被误导 |
| P1-2 | `docs/architecture` 与 flow-v2 PRD（`docs/prd/2026-08-05-flow-v2.md`）中 R2-a 的表述追加"已由 flow-v3 修订"批注，保持文档链可追溯 |
| P1-3 | 低分二次确认文案中的数字改用 `${MATCH_LOW_SCORE}` 插值，杜绝硬编码漂移 |

### P2（可延后）

| ID | 需求 |
| --- | --- |
| P2-1 | 在"我的匹配"卡片上为 keep1 候选增加显式徽标（如「留在原地」），帮助失主提前预期是"自取"而非"当面交接" |
| P2-2 | 将 `MATCH_LOW_SCORE` 提升为可运行时配置（环境变量 / 管理后台），便于运营调参而无需发版 |

### 关联回归点清单（必须回归验证）

1. **已交接栏只展示拾物 + 去重**（flow-v2 R1）：keep1 完成记录进入已交接栏后，仍按拾物维度去重、不重复出现。
2. **撤回后可再申请**：`_exists_match` 排除终态 `{2,3,6}`，keep1 撤回（status=6）后同一对 lost/found 可再次生成候选并再次申请。
3. **top10 上限**：`MATCH_TOP_N=10` 及 `_reverse_match_found` 中"单件失物已有候选 ≥10 则跳过"守卫，在 keep1 大量涌入后仍成立，不出现第 11 条。
4. **keep0 双向闭环零回归**：交接码生成、拾得者确认、动态交接码双端确认全链路不受影响。
5. **`claim` 对 keep1 的 422 拦截**（flow-v2 R2-b）不被放开召回破坏。
6. **manual 手动匹配对 keep1 的一步完成分流**（`app/routers/match.py:423`）仍生效，不生成 status=4 待自取。
7. **软删物品退出候选池**（v7 Q8）：`deleted_at.is_(None)` 过滤不能在删除 keep_status 过滤时被误删。
8. **信用分与审计**：keep1 完成/撤回的 `TrustScoreLog` 与审计动作（`keep1_claim_complete` / `keep1_claim_revoke`）记录完整。
9. **五维明细展示**：keep1 候选卡片同样正确展示 photo/category/text/location/time 五维分值。

---

## 4. UI 变更点清单

### 4.1 常量层

| 文件 | 变更 |
| --- | --- |
| `app/core/config.py` | 新增 `MATCH_LOW_SCORE: float = 60.0`（低分视觉阈值）；`MATCH_THRESHOLD = 80.0` 保留，注释补充"仅用于 suspected 判定，与前端弱化展示解耦" |
| `web/src/api/constants.ts` | 新增 `export const MATCH_LOW_SCORE = 60`；修正 `MATCH_THRESHOLD` 上方注释，删除"前端低分判定口径：match_score < 80 为低分"的过时描述 |
| `web/src/types/index.ts:124` | 注释改为：疑似 `score>=80`（不变）；弱化由 `match_score < 60`（MATCH_LOW_SCORE）派生 |

### 4.2 「我的匹配」页（`web/src/views/MatchesView.vue`）

| 位置 | 变更前 | 变更后 |
| --- | --- | --- |
| `:294` `isLowScore` | `m.match_score < MATCH_THRESHOLD`（<80） | `m.match_score < MATCH_LOW_SCORE`（<60） |
| `:53` 弱化标签「低匹配度·谨慎申请」 | <80 显示 | **<60 才显示**；60–79 不再显示 |
| `:33` / `:624` 卡片弱化样式 `match-card--low`（灰橙虚线边框 + 浅底色） | <80 生效 | **<60 才生效**；60–79 恢复常规卡片样式 |
| `:444-448` 低分二次确认弹窗 | <80 触发，文案"该候选匹配度较低（<80）…" | **<60 触发**，文案"该候选匹配度较低（<60）…"（建议用 `${MATCH_LOW_SCORE}` 插值） |
| `:181-190` 拾得者侧 `status===0` 分支 | 仅按 `isLowScore` 分流：非低分显示「确认归还 / 拒绝」 | **新增 keep1 判定优先级最高**：`found_item.keep_status === 1` → 只读提示「留在原地·等待失主自取」，不渲染任何操作按钮；keep0 再按低分口径分流 |
| `:131` 失主侧「申请匹配」按钮 | 现状 keep1 走 claim-complete | **不变**（keep1 候选现在会真实出现，该分支从"仅存量数据可达"变为"常规路径"，需重点回归） |

### 4.3 Mock 适配器（`web/src/api/mockAdapter.ts`）

| 位置 | 变更 |
| --- | --- |
| `:213-222` | 删除 `f.keep_status === 0` 过滤及 R2-a 注释，keep1 拾物纳入候选召回 |
| `:392-394` | 删除 keep1 拾物不生成反向候选的分支 |
| `:196` `suspected: score >= MATCH_THRESHOLD` | **不变**（suspected 语义仍为 80） |
| `:520-534` keep1 分流守卫（claim 拦截 / claim-complete） | **不变**；另建议补 `confirm-return` 对 keep1 的拦截以与后端 P0-4 对齐 |

### 4.4 交互文案汇总

| 场景 | 文案 |
| --- | --- |
| 候选 <60（失主侧标签） | 「低匹配度·谨慎申请」 |
| 候选 <60（失主申请二次确认） | 「该候选匹配度较低（<60），请确认对方物品与你的失物一致后谨慎申请。」标题「低匹配度申请」 |
| keep1 候选（拾得者侧） | 「留在原地·等待失主自取」（只读，无按钮） |
| keep1 候选 `confirm-return` 被拦截（后端 422） | 「该物品留在原地未挪动，无需你确认归还，请等待失主申请后自行取回」 |

---

## 5. 待确认问题（决策点）

| # | 问题 | 本 PRD 默认取值 | 影响 | 需用户拍板 |
| --- | --- | --- | --- | --- |
| **Q1** | **suspected（疑似匹配）阈值是否也随低分一起下调到 60？** | **保留 80.0 不变**（仅新增独立的 `MATCH_LOW_SCORE=60`） | 若也降到 60，则 60–79 候选会被标记为"疑似匹配"，后端解释体 `threshold` 与既有测试 `test_match.py:56` 需同步改；同时会改变"疑似"这一业务语义的严肃性 | ✅ **请用户确认** |
| **Q2** | 低分阈值下调后，**拾得者侧"低分不打扰"（P1-1）是否也跟随 60 口径？** | **跟随**（即 60–79 的 keep0 候选，拾得者侧将重新出现「确认归还 / 拒绝」主按钮） | 这是 `isLowScore` 被复用于两处的副作用。若希望"不打扰"仍按 80 判定，需再拆一个 `FINDER_QUIET_THRESHOLD=80` 常量 | ✅ **请用户确认** |
| **Q3** | keep1 候选是否需要在"我的匹配"卡片上加显式「留在原地」徽标？ | 本轮不加（列为 P2-1） | 不加则失主可能不清楚为何该候选"申请即完成"、无交接码 | ⭕ 可延后 |
| **Q4** | keep1 拾物的候选是否也占用失主的 top10 名额？ | **占用**（与 keep0 完全等价，共享 `MATCH_TOP_N=10`） | 若 keep1 数量大，可能挤占 keep0 候选位；如需保护可考虑分池配额，但会显著增加复杂度 | ⭕ 建议维持默认 |
| **Q5** | 存量数据是否需要回填？（flow-v2 期间发布、因被排除而从未生成候选的 keep1 拾物） | **建议提供一次性回填脚本**（对 `status=PENDING` 且 `deleted_at IS NULL` 的历史 keep1 拾物重跑反向匹配），但本轮不含 | 不回填则老数据仍"失联"，仅新发布的 keep1 受益 | ✅ **请用户确认是否本轮包含** |
| **Q6** | keep1 候选是否触发消息/通知推送？ | 沿用现有通知机制，不做差异化 | 若现有机制对 keep0 有推送而 keep1 无，需一并对齐 | ⭕ 由架构师核查现状后决定 |

---

## 6. 不做什么（明确排除）

- ❌ 不修改五维匹配公式及各维权重（15/20/50/10/5）。
- ❌ 不修改 `MATCH_TOP_N = 10` 的候选上限。
- ❌ 不修改 keep1 的简化认领流程本身（申请即完成 + 可撤回），仅让它"能被匹配到"。
- ❌ 不修改 keep0 的双向认领闭环（交接码 / 拾得者确认 / 动态交接码双端确认）。
- ❌ 不修改"已交接栏只展示拾物 + 去重"（flow-v2 R1）。
- ❌ 不引入按分数过滤候选的逻辑（低分候选仍需落库展示）。
- ❌ 不改动 `suspected` 的后端计算方式与字段语义（除非 Q1 被否决）。

