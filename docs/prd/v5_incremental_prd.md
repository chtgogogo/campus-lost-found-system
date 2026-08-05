# v5 增量产品需求文档（Incremental PRD v5）

| 项 | 内容 |
| --- | --- |
| 系统名称 | 基于 YOLOv8 的校园失物招领智能匹配系统 |
| 文档定位 | 在**已落地 v4** 之上定义 v5 增量变更（仅描述变更部分；不含任何实现代码、不修改源文件）；需求层文档 |
| 文档版本 | v5.0（增量·简单 PRD） |
| 产品经理 | 许清楚（Xu） |
| 技术栈（沿用，禁止更换） | 前端 **Vue3 + Element Plus + Vite + Pinia + Axios**；后端 **FastAPI + SQLAlchemy 2.x + SQLite/MySQL + JWT**；IM 沿用**前端轮询**（非 WebSocket）；非默认 React/MUI（既有系统增量改造） |
| 状态 | 待架构师与工程评审 |

---

## 0. 增量基线（v4 已落地事实 + 本次起点）

> 以下为 v4 已上线现状（实地 Read 于 `app/`、`web/src/`，行号见正文 F 标注），所有 v5 变更**必须基于这些事实**。

- **IM 路由现状（F-IM1）**：`app/routers/im.py` 仅有 `POST /im/sessions`（建/复用）、`GET /im/sessions/{id}/messages`（轮询）、`POST /im/sessions/{id}/messages`（发消息）。**缺一个「列出当前用户所有会话」的 GET 端点**——这是 v5 后端必补项。
- **IMSession 模型（F-IM2）**：`app/models/im.py:22-66`，字段 `id / match_id(可空) / found_id(可空, v4 加) / lost_user_id / finder_user_id / status / created_at / last_message_at(可空) / expires_at`。
  - **关键事实**：`status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)`（注释 `0 开启 / 1 关闭`，见 `app/models/im.py:49`）。**软删字段已存在** → v5 软删**零迁移**，直接复用 `status=1` 隐藏。
- **IMSessionOut 现状（F-IM3）**：`app/schemas/im.py:21-32`，仅含 `id/match_id/found_id/lost_user_id/finder_user_id/status/created_at/last_message_at/expires_at`，**不含对方用户、会话标题、未读标记**。v5 列表端点需富化。
- **MatchStatus（F-M1）**：`app/schemas/common.py:71-76`，`0 待认领 / 1 认领中 / 2 已完成 / 3 已拒绝 / 4 待自取(MANUAL_PENDING)`。
- **match 路由现状（F-M2）**：`app/routers/match.py` 已有 `POST /matches/manual`、`POST /matches/{id}/self-complete`；**无删除/放弃端点**。
- **外键约束（F-M3）**：`IMSession.match_id` 以 `ForeignKey("match_record.id", ondelete="RESTRICT")` 引用 `MatchRecord`（`app/models/im.py:28-32`）。**物理删除 MatchRecord 会触发 RESTRICT 冲突**——「未能找回」硬删需谨慎（见 §5 Q5）。
- **保留期（F-C1）**：`IM_RETENTION_DAYS = 30`（`app/core/config.py:94`，注释 `v3 Q7：7 → 30`）。注意：任务描述所引「7 天」与现状不符，v5 软删保留期**建议沿用现状 30 天**（见 §5 Q7）。
- **前端导航（F-W1）**：`web/src/router/index.ts:13-20` 的 `NAV_ITEMS` 现有 6 项（公示栏/发布/我的匹配/我的发布/交接确认/管理后台），**无「我的消息」**；`web/src/layouts/AppLayout.vue:54-59,69-80` 侧边栏与底部 tabbar 均只读 `NAV_ITEMS` → 加项即两处同步渲染。
- **发布表单（F-W2）**：`web/src/views/PublishView.vue:19-32`，保管状态 `el-radio-group`（暂为保管/未挪动）下挂一个 `keep-tip` 块，**未下沉到各 radio 选项下方**——这正是 v5 块 A 的排版修复点。
- **我的匹配操作区（F-W3）**：`web/src/views/MatchesView.vue:58-119`，失主侧 `status==4` 有「完成匹配」、通用「联系对方」；**缺「未能找回」**。
- **联系对话框（F-W4）**：`web/src/views/ContactDialog.vue` 已支持 `found`/`foundId` 建会话（v4），标题形如 `联系对方 · {category_name}（拾物 #{foundId}）`（`:104-109`）。
- **物品标题字段（F-W5）**：`FoundItem`（`app/models/item.py:68-102`）**无 `title` 字段**，仅 `category_name` + `description`；`LostItem`（`:31-65`）有 `title`。会话标题拼装需据此选择来源（见 §5 Q6）。

### 0.1 已拍板决策（主理人代用户定，v5 直接采用）

- **拍板 1（未能找回·显示范围）**：**所有匹配卡片**（status 0/1/2/3/4 均显示）都显示「未能找回」。
- **拍板 2（未能找回·行为）**：点击「未能找回」→ **撤销该 MatchRecord**，并把关联失物 `LostItem.status` **重置为待匹配(0)**，使其重新进入自动匹配 + 重新出现在拾物栏手动候选（即"重新归入匹配池子"）。该操作对**失主侧**生效（失主主动申请没找到，重新发起到池子）。
- **拍板 3（招领成功）**：「招领成功」→ **软删对话**（`IMSession.status=1` 隐藏，后台保留）+ **关联 MatchRecord 置 `COMPLETED=2` 归档**（语义与 v4 自取完成一致）。

---

## 1. 产品目标与范围边界

### 1.1 产品目标（一句话）

> **v5 在 v4 基础上补齐三处体验闭环——（A）修复发布页保管状态提示排版；（B）我的匹配新增「未能找回」让失主可把没找到的匹配退回匹配池；（C）新增「我的消息」会话列表，统一聚合收发消息、支持续聊、删除与「招领成功」归档。**

### 1.2 本期范围边界

**做（Scope In）**
- A. 发布页保管状态提示排版修复（纯前端）。
- B. 「未能找回」按钮（失主侧全状态显示）+ 后端撤销匹配 + 失物退回待匹配池。
- C. 「我的消息」栏：左侧导航新入口 + 会话列表（后端新端点）+ 会话详情复用现有 IM 收发 + 「删除此对话」软删 + 「招领成功」软删并归档。

**不做（Scope Out）**
- 不新增 IM 实时机制（仍前端轮询，沿用 v3/v4）。
- 不引入新前端框架、不新建核心闭环以外的服务。
- 不改动 v4 已交付的匹配公式 / 手动匹配 / 双码交接逻辑主体。
- 不改动 `KeepStatus` / `contact_allowed` 既有约束（v4 已定）。
- 「未能找回」不做物理销毁式删除（受 RESTRICT 外键约束，采用软删，见 §5 Q5）。

---

## 2. 用户故事（角色 / 场景 / 价值）

> 格式：`As a [角色], I want [功能] so that [价值]`。

### A. 拾得者发布时看到排版正确的保管提示（块 A）

- **拾得者**：As a 拾得者，我希望在选「暂为保管」/「未挪动」时，对应的说明文字各自**换行显示在该选项下方**，so that 我能清楚理解每种保管方式的含义，不会被挤在一行里看不清。

### B. 失主申请匹配后没找到 → 点「未能找回」重新入池（块 B）

- **失主**：As a 失主，我希望在我发起的匹配（进行中或已完成）里点「未能找回」，so that 这条匹配被撤销、我的失物回到待匹配池，可重新被自动/手动匹配，不用重新发布。
- **失主**：As a 失主，我希望「未能找回」在我**所有**匹配卡片上都可用（无论 status），so that 即使我已「完成匹配」后发现东西没找回，也能退回重来。

### C. 双方互发消息，在「我的消息」可见且可续聊（块 C）

- **失主**：As a 失主，我希望「我的消息」里能看到我和对方的所有会话（不论是我联系对方还是被对方联系），so that 我能在一个入口集中管理对话。
- **拾得者**：As a 拾得者，我希望对方未回时也能在「我的消息」点开继续发，so that 不丢失联系线索。
- **双方**：As a 用户，我希望会话标题是「联系对方 · 物品标题」这种一眼能认出的形式，so that 我知道这是关于哪件物品的对话。

### D. 完成匹配后「招领成功」或「删除」对话（块 C）

- **用户**：As a 用户，我在「我的消息」里某会话已达成招领，我希望点「招领成功」→ 对话自动隐藏且该匹配归档为已完成，so that 我的消息列表保持干净且招领结果被记录。
- **用户**：As a 用户，我希望对不再需要的对话点「删除此对话」→ 隐藏（后台保留一段时间），so that 我能清理列表而不丢后台数据。

---

## 3. 需求池（P0 / P1 / P2，标注需求字母）

> 优先级：**P0 = 必做（阻塞上线）｜P1 = 应做（工程化必需）｜P2 = 体验优化**。
> 标记：`[复用]` 沿用既有；`[新增]` 需新增表/字段/服务/端点；`[变更]` 既有字段/逻辑需修改。

### P0 — 必做（阻塞上线）

| ID | 需求 | 描述 | 标记 | 关联模块 | 验收标准 |
| --- | --- | --- | --- | --- | --- |
| P0-A1 | A | 保管提示排版修复：`PublishView` 把「暂为保管」对应提示与「未挪动」对应提示**分别下沉到各自 radio 选项下方**（各占新行、block 级），不再挤在 radio 同行后。保留原语义与文案。 | `[变更]`前端 | `web/src/views/PublishView.vue:19-32` | ① 两提示各在对应 radio 下方独立成行；② 文案与现 `keep-tip` 一致（暂为保管："已代为保管：将强制开启"允许联系"，失主可联系你取回。"；未挪动："物品原地未动：失主可"申请匹配"自取，你也可开启联系。"）。 |
| P0-B1 | B | 「未能找回」按钮（失主侧·全状态）：`MatchesView` 失主侧**所有 status(0/1/2/3/4)** 卡片显示「未能找回」按钮，与「完成匹配」「联系对方」并列（拍板 1）。拾得者侧不显示（拍板 2 注）。 | `[变更]`前端 | `web/src/views/MatchesView.vue:58-119` | ① 失主侧每张卡片均见该按钮；② 拾得者侧不显示；③ 与既有按钮并列。 |
| P0-B2 | B | 「未能找回」后端（撤销匹配 + 重置失物）：新增端点，校验**仅失主**（当前用户 = `lost.publisher_id`）；撤销该匹配并把 `LostItem.status` 置 **0（待匹配）**。受 RESTRICT 外键约束，采用软删（见 §5 Q5）。 | `[新增]`端点+逻辑 | `app/routers/match.py`、新增 `POST /matches/{id}/giveup` | ① 点击后该匹配从「我的匹配」活跃视图消失；② `LostItem.status=0`；③ 失物重新可参与自动匹配 + 出现在拾物栏手动候选。 |
| P0-C1 | C | 「我的消息」入口：路由新增 `/messages` + `NAV_ITEMS` 加「我的消息」（icon 建议 `ChatDotRound`），`AppLayout` 侧边栏与 tabbar 自动渲染；新增 `MessagesView.vue`。 | `[新增]`路由+前端 | `web/src/router/index.ts`、`web/src/layouts/AppLayout.vue`、`web/src/views/MessagesView.vue` | ① 左侧栏/底部 tabbar 出现「我的消息」；② 点击进入会话列表页。 |
| P0-C2 | C | 会话列表后端（`GET /im/sessions`）：返回**当前用户参与且 `status=0`** 的会话列表，富化字段（会话 id、对方用户摘要、关联物品标题拼装、最后消息时间、未读/对方未回标记）。 | `[新增]`端点+schema | `app/routers/im.py`、新增 `IMSessionListItem` schema | ① 返回当前用户全部活跃会话；② 每条带可拼标题的信息；③ 隐藏 `status=1` 的会话。 |
| P0-C3 | C | 会话详情收发（复用 IM）：`MessagesView` 点击会话打开对话面板，复用现有 IM 轮询收发（`createSession`/`getMessages`/`sendMessage` 逻辑，源自 `ContactDialog.vue`）。 | `[复用+变更]`前端 | `web/src/views/MessagesView.vue`、`web/src/api/im.ts` | ① 可在「我的消息」内发消息、轮询收消息；② 对方未回也可续发。 |
| P0-C4 | C | 删除此对话（软删）：新增端点将 `IMSession.status` 置 **1**（隐藏），后台按 `expires_at` / `IM_RETENTION_DAYS` 保留。 | `[新增]`端点 | `app/routers/im.py`、新增 `DELETE /im/sessions/{id}` | ① 删除后该会话从列表消失；② `IMSession.status=1`；③ 后台数据保留至保留期。 |
| P0-C5 | C | 招领成功（软删 + 归档，拍板 3）：新增端点将 `IMSession.status` 置 **1**，且若关联 `MatchRecord` 未完成（`status∈{0,1,4}`）则置 `COMPLETED(2)` + 双端物品已解决；无 match 则仅软删。 | `[新增]`端点+逻辑 | `app/routers/im.py`、新增 `POST /im/sessions/{id}/success` | ① 点击后对话隐藏；② 关联未完成 match → `MatchRecord=2` 且 `LostItem.status=3`/`FoundItem.status=1`；③ 已终态(2/3)或无 match 则仅软删。 |

### P1 — 应做（工程化必需）

| ID | 需求 | 描述 | 标记 | 关联模块 | 验收标准 |
| --- | --- | --- | --- | --- | --- |
| P1-C1 | C | 会话标题拼装规则：前缀统一「联系对方 · 」+ 物品标题（`found_item.category_name` 或 `lost_item.title`）；建议在后端富化时拼好返回（见 §5 Q6）。 | `[变更]`schema/前端 | `app/schemas/im.py`、`MessagesView.vue` | ① 列表项标题形如「联系对方 · 钥匙」；② 前缀统一。 |
| P1-C2 | C | 未读/对方未回态：列表展示未读标记（粗粒度：最近消息来自对方，或 `last_message_at` 存在；精确未读见 §5 Q10）。 | `[变更]`前端+可选后端 | `MessagesView.vue`、`IMSessionListItem` | ① 有未读/对方未回的会话有视觉标记；② 进入后标记清除（粗粒度可前端维护）。 |
| P1-C3 | C | 二次确认：删除 / 招领成功为破坏性操作，弹 `ElMessageBox.confirm` 二次确认。 | `[变更]`前端 | `MessagesView.vue` | ① 两操作均有二次确认；② 取消不生效。 |
| P1-B3 | B | 放弃后是否即时重跑匹配（可选）：「未能找回」后是否立即对 `LostItem` 重跑一次反向匹配（复用 `publish_lost` 的 `_reverse_match_lost`）；建议仅重置 `status=0`，不自动重跑（轻量，见 §5 Q8）。 | `[可选]`逻辑 | `app/services/publish_service.py` | ① 默认仅重置 `status=0`；② 如需即时再匹配，作为 P2 补充。 |
| P1-C4 | C | 关联匹配跳转：若会话关联 `match`，提供「查看匹配」跳转至 `/matches` 对应卡片。 | `[变更]`前端 | `MessagesView.vue` | ① 有 match 的会话可跳转；② 无 match（纯 found_id 联系）不显示。 |

### P2 — 体验优化（Nice to have）

| ID | 需求 | 描述 | 标记 | 关联模块 | 验收标准 |
| --- | --- | --- | --- | --- | --- |
| P2-A1 | A | 保管方式差异说明（呼应 v4 P2-K1）：`keep-tip` 可补充一句「是否动过物品」的差异说明。 | `[变更]`前端 | `PublishView.vue` | ① 用户更易理解两者差别。 |
| P2-C1 | C | 会话最后一条消息预览：列表项展示最后消息摘要（需后端返回 `last_message` 或前端首条拉取）。 | `[变更]`前端+可选后端 | `MessagesView.vue`、`IMSessionListItem` | ① 列表项可见最后一句；② 截断合理。 |
| P2-C2 | C | 未读角标：左侧栏「我的消息」显示未读数量角标（`NAV_ITEMS` 项可带 `badge`）。 | `[变更]`前端 | `AppLayout.vue`、`router/index.ts` | ① 有未读时导航项显示角标。 |
| P2-C3 | C | 招领成功反馈：点击后提示「已归档至我的匹配-已完成」。 | `[变更]`前端 | `MessagesView.vue` | ① 用户明确知道结果去向。 |

---

## 4. UI 设计稿（文字 + 草图要点）

### 4.1 发布表单·保管状态提示（块 A 修复后，ASCII 草图）

```
┌──────────────────────────────────────────────────┐
│  保管状态（必填）                                   │
│  (●) 暂为保管                                       │
│      ┌─────────────────────────────────────────┐  │
│      │ 已代为保管：将强制开启"允许联系"，      │  │  ← 下沉到 radio 下方（新行）
│      │ 失主可联系你取回。                       │  │
│      └─────────────────────────────────────────┘  │
│  ( ) 未挪动                                         │
│      ┌─────────────────────────────────────────┐  │
│      │ 物品原地未动：失主可"申请匹配"自取，    │  │  ← 下沉到 radio 下方（新行）
│      │ 你也可开启联系。                         │  │
│      └─────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

**要点**：每个 radio 选项独立成块，提示文字以 `block` 级（新行、缩进、浅色小字）渲染在对应选项**正下方**，不再与 radio 同行。文案一字不改。

### 4.2 「我的匹配」操作区（块 B，失主侧加「未能找回」，ASCII 草图）

```
┌──────────────────────────────────────────────────┐
│  我的匹配 · 进行中（失主视角，status 任意）         │
│ [图] 银色钥匙   标签: 钥匙 银色                     │
│      [完成匹配]   [联系对方]   [未能找回]           │   ← 三按钮并列（拍板1：全状态显示）
│ ─────────────────────────────────────────────── │
│ [图] 黑色书包   标签: 书包 黑色                     │
│      [联系对方]   [未能找回]                       │   ← status≠4 时同样显示未能找回
└──────────────────────────────────────────────────┘
```

- 拾得者侧**不显示**「未能找回」（拍板 2 注：该操作对失主侧生效）。

### 4.3 「我的消息」（块 C，QQ 式双栏，ASCII 草图）

```
┌──────────────────────────────┬──────────────────────────────────┐
│  我的消息                      │  联系对方 · 一把银色钥匙          │
│ ┌──────────────────────────┐ │ ──────────────────────────────── │
│ │ ● 联系对方 · 钥匙        │ │                                   │
│ │   对方还没回…  09:12  ●   │ │          请问还在原位吗?          │
│ ├──────────────────────────┤ │                      对的没动过    │
│ │ ● 联系对方 · 银色水杯    │ │                                   │
│ │   好的我来取   昨天       │ │ ──────────────────────────────── │
│ ├──────────────────────────┤ │ [ 输入消息…… ]            [发送] │
│ │ ○ 联系对方 · 校园卡      │ │                                   │
│ │   已归档            周一  │ │ [删除此对话]  [招领成功]          │
│ └──────────────────────────┘ │                                   │
└──────────────────────────────┴──────────────────────────────────┘
```

- 左列表来自 `GET /im/sessions`（`status=0` 且参与者含当前用户）；点击 → 右面板复用现有 IM 收发（轮询 + 发送）。
- 右面板底部两个操作：「删除此对话」（软删）、「招领成功」（软删 + 归档，拍板 3）。

### 4.4 会话操作条（删除 / 招领成功）

- 「删除此对话」：弹二次确认 → `DELETE /im/sessions/{id}`（软删 `status=1`）。
- 「招领成功」：弹二次确认 → `POST /im/sessions/{id}/success`（软删 `status=1` + 关联未完成 match → `COMPLETED(2)` 归档）。
- 二者均不物理删除，后台按 `IM_RETENTION_DAYS` 保留（F-C1）。

---

## 5. 待确认问题（需架构师 / 工程拍板，附建议默认）

### 5.1 阻塞细化（建议尽快确认）

- **Q1 软删字段现状（已确认事实）**：`IMSession.status` **已存在**（`SmallInt`，默认 0，注释 `0 开启 / 1 关闭`，`app/models/im.py:49`），v4 即具备。→ **建议直接复用 `status=1` 作隐藏，v5 软删零迁移**，无需新增字段。请确认采用（默认采用）。

- **Q2 `GET /im/sessions` 返回字段（建议默认）**：建议返回新建 `IMSessionListItem` 富化 schema，字段含：
  - `id`（会话 id）、`match_id`、`found_id`
  - `peer_user`（对方用户摘要：`{id, real_name/student_no, avatar}`）
  - `item_title`（后端拼好的「联系对方 · {物品标题}」，见 Q6）
  - `last_message_at`、`last_message_preview`（可选，P2-C1）
  - `unread`（bool / 对方未回标记，粗粒度，见 Q10）
  - `status`
  - 建议**新建 `IMSessionListItem`** 而非在既有 `IMSessionOut` 上扩展，避免污染现有端点契约。是否接受新建 schema，还是并入 `IMSessionOut`？

- **Q3 「招领成功」端点契约（建议默认）**：建议 `POST /im/sessions/{id}/success`（或 `/close`），请求体空。
  - 副作用：`IMSession.status=1` + 若关联 `MatchRecord` 未完成（`status∈{0,1,4}`）则置 `COMPLETED(2)` + `LostItem.status=3` + `FoundItem.status=1`（与 v4 `self-complete` 语义一致）；无 match（纯 `found_id` 联系会话）则仅软删。
  - 权限：会话**参与者均可**（失主/拾得者均可触发，拍板 3 未限定角色）。
  - 终态保护：若 match 已 `COMPLETED(2)`/`REJECTED(3)`，仅软删对话，不改动 match（见 Q9）。
  - 命名请拍板：`/success`（语义清晰）vs `/close`（通用关闭）。默认推荐 `/success`。

- **Q4 「删除此对话」端点契约（建议默认）**：建议 `DELETE /im/sessions/{id}`（软删 `status=1`，虽是软删但用 DELETE 表达资源删除语义）；权限：会话参与者。替代方案：`POST /im/sessions/{id}/close`。默认推荐 `DELETE`。

- **Q5 「未能找回」端点契约 + 外键冲突（建议默认·重点）**：建议 `POST /matches/{id}/giveup`。
  - **关键约束**：`IMSession.match_id` 以 `ondelete="RESTRICT"` 引用 `MatchRecord`（`app/models/im.py:28-32`），**物理删除 MatchRecord 会触发外键冲突**。
  - **建议采用软删**：`MatchRecord.status` 新增 `5 = GIVEN_UP（已放弃/退回池）`（SmallInt 零迁移，仅枚举加值），同时 `LostItem.status=0`。关联 IM 会话不物理断链（保留 `match_id` 溯源）。
  - 替代：若坚持物理删除 MatchRecord，须先将该会话 `match_id` 置 `NULL` 再删；但会丢失审计溯源，不推荐。
  - 权限：**仅失主**（当前用户 = `lost.publisher_id`，拍板 2 注）。
  - 请主理人/架构师拍板：软删 `status=5`（推荐）vs 复用 `REJECTED=3`（语义近似但混淆"被拒"与"主动放弃"）vs 物理删除（需先清 FK）。

- **Q6 会话标题前缀规则与来源字段（建议默认）**：用户示例「联系对方 · 一把银色钥匙」。
  - 前缀：建议**统一「联系对方 · 」**（不区分"我联系对方/对方联系我"，简单一致）。
  - 物品标题来源：`FoundItem` **无 `title` 字段**（F-W5），仅 `category_name`/`description`；`LostItem` 有 `title`。建议：
    - 会话含 `found_id` 或 `match→found_item` → 取 `found_item.category_name`（稳定、结构化）；
    - 若希望标题更贴近「一把银色钥匙」式（含颜色/描述），可截取 `found_item.description` 前 N 字拼接 `category_name`。
  - 默认推荐：**前缀「联系对方 · 」+ `found_item.category_name`**（简洁稳定）。请确认是「category_name」还是「含 description 摘要」。

- **Q7 软删后列表过滤 & 保留期（建议默认）**：
  - 列表过滤：`status=0` 且（`lost_user_id==当前用户` OR `finder_user_id==当前用户`）。
  - 保留期：现状 `IM_RETENTION_DAYS=30`（`app/core/config.py:94`，v3 已 `7 → 30`）。任务所引"7 天"与现状不符，**建议沿用现状 30 天**，不强行改回 7；物理清除仍由既有清理任务按 `expires_at` 执行（v4 设计沿用）。请确认保留期取值（默认 30，复用配置）。

- **Q8 「未能找回」是否触发即时重跑匹配（建议默认）**：拍板 2 说"重新进入自动匹配"。
  - 建议：**仅重置 `LostItem.status=0`**（轻量，失物回到活跃池；后续新拾物发布 / 失主手动申请时可再匹配），**不立即重跑全量匹配扫描**。
  - 若需即时再匹配：建议 P2 补一次反向匹配（复用 `publish_lost` 的 `_reverse_match_lost`）。
  - 请确认 v5 是否做即时重跑（默认：仅重置 `status=0`）。

- **Q9 「招领成功」对终态 match 的处理（建议默认）**：若会话关联 match 已 `COMPLETED(2)`/`REJECTED(3)`（终态），点「招领成功」**仅软删对话**，不再改动 match（避免复活已拒绝匹配 / 重复归档）。默认推荐如此。请确认。

- **Q10 未读态实现方式（P1，建议默认）**：`IMMessage` 无 `read` 字段（`app/models/im.py:69-95`）。
  - 建议 v5 **粗粒度**：以「会话最近一条消息 `sender_id != 当前用户`」推导"对方未回/未读"，**不新增表**；前端进入会话即视为已读（本地清除标记）。
  - 若需精确未读计数：P2 加 `im_message.read` 列或 `session_read` 游标表（需迁移）。请确认 v5 是否做精确未读（默认：粗粒度，零迁移）。

- **Q11 「我的消息」聚合范围（建议默认）**：本期**仅做 IM 会话聚合**（联系对方 / 被联系），不含系统通知 / 匹配结果通知。请确认范围（默认：仅 IM 会话）。

### 5.2 风险与缓解

- **R1 外键破坏（重点）**：「未能找回」物理删 MatchRecord 触发 `im_session.match_id` RESTRICT → 缓解：采用软删 `status=5`（Q5 默认）。
- **R2 标题来源不一致**：`FoundItem` 无 `title`、丢失/拾物字段不对称 → 缓解：统一以 `category_name` 拼标题（Q6 默认），避免空标题。
- **R3 软删泄漏**：列表若忘记过滤 `status=1` 会显示已删对话 → 缓解：`GET /im/sessions` 强制 `status=0`（P0-C2）。
- **R4 招领成功误归档**：对终态/无 match 会话误置 COMPLETED → 缓解：终态保护（Q9）+ 无 match 仅软删（P0-C5）。
- **R5 未读态误导**：粗粒度未读可能与实际已读不符 → 缓解：进入即清除 + 明确其为"对方未回"提示（Q10）。

---

## 6. 字段 / 表 / 状态对照（v5 增量）

| 项 | 类型 | v4→v5 变化 | 标记 |
| --- | --- | --- | --- |
| `IMSession.status` | 字段 | **复用**（0 开启 / 1 关闭，v4 已存在）；v5 以 `1` 作软删隐藏 | **[复用]** |
| `GET /im/sessions` | 端点 | **新增**：列出当前用户 `status=0` 且参与的会话（富化 `IMSessionListItem`） | **[新增]** |
| `DELETE /im/sessions/{id}` | 端点 | **新增**：删除此对话（软删 `status=1`） | **[新增]** |
| `POST /im/sessions/{id}/success` | 端点 | **新增**：招领成功（软删 `status=1` + 关联未完成 match → `COMPLETED(2)` 归档） | **[新增]** |
| `POST /matches/{id}/giveup` | 端点 | **新增**：未能找回（撤销匹配 + `LostItem.status=0`）；软删（见 Q5） | **[新增]** |
| `MatchRecord.status` | 枚举 | 建议**新增 `5 = GIVEN_UP（已放弃/退回池）`**（SmallInt 零迁移）；或复用 `3`（待拍板，Q5） | **[新增·建议]** |
| `IMSessionListItem` | schema | **新增**：富化列表项（`peer_user` / `item_title` / `last_message_at` / `unread` 等，Q2） | **[新增]** |
| `web/src/router/index.ts` | 前端 | `NAV_ITEMS` 加「我的消息」+ 新增 `/messages` 路由 | **[变更]** |
| `web/src/layouts/AppLayout.vue` | 前端 | 侧边栏 + tabbar 读 `NAV_ITEMS`（加项即同步，无需改渲染逻辑） | **[复用]** |
| `web/src/views/MessagesView.vue` | 前端 | **新增**：我的消息双栏（列表 + 对话面板，复用 IM 收发） | **[新增]** |
| `web/src/views/MatchesView.vue` | 前端 | 失主侧全部状态加「未能找回」按钮 | **[变更]** |
| `web/src/views/PublishView.vue` | 前端 | 保管提示下沉到各 radio 选项下方（块 A 排版修复） | **[变更]** |
| `web/src/api/im.ts` | 前端 | 加 `listSessions` / `deleteSession` / `successSession` | **[变更]** |
| `web/src/views/ContactDialog.vue` | 前端 | 收发逻辑可被 `MessagesView` 复用（建议抽取共享 `ChatPanel` 或内联复用，架构师定） | **[复用]** |
| `IM_RETENTION_DAYS` | 配置 | **复用现状 30**（v3 已 7→30；不强行改回 7，Q7） | **[复用]** |

**状态机要点（v5）**
- **未能找回（失主）**：`MatchRecord` → `GIVEN_UP(5)`（或软删）；`LostItem.status`：原值 → **0（待匹配）**，重新归入活跃匹配池。
- **招领成功**：`IMSession.status`：0 → **1（隐藏）**；`MatchRecord`（若未完成 `0/1/4`）→ **COMPLETED(2)**，`LostItem.status`→3，`FoundItem.status`→1；已终态(2/3)/无 match 则仅软删。
- **删除此对话**：`IMSession.status`：0 → **1（隐藏）**；后台按 `expires_at` / `IM_RETENTION_DAYS` 保留。
- 软删统一语义：`status=1` 的会话不出现在「我的消息」列表（`GET /im/sessions` 过滤 `status=0`），但物理数据保留至保留期，供审计溯源。
