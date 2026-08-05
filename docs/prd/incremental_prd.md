# 增量产品需求文档（Incremental PRD）

| 项 | 内容 |
| --- | --- |
| 系统名称 | 基于 YOLOv8 的校园失物招领智能匹配系统（四川大学锦江学院本科毕设） |
| 文档定位 | 在**已审计落地系统**之上做增量需求定义：真 YOLOv8 视觉识别上线 + 生产级工程化。**本文档仅定义需求，不含任何实现代码，不修改任何项目源文件。** |
| 文档版本 | v1.0（增量） |
| 产品经理 | 许清楚（Xu） |
| 关联决策 | 见 §0.3 三项已确认决策（用户已拍板，PRD 必须遵守） |
| 状态 | 待架构师（高见远）与工程（寇豆码）评审 |

---

## 0. 增量基线（已审计事实）

> 以下为已落地且经审计的现状，所有增量需求**必须基于这些事实**，不得凭空新造能力。

### 0.1 后端（FastAPI + SQLAlchemy，56 个测试全绿）
- 已 seed **10 张表**：`user / category / lost_item / found_item / match_record / handover_code / audit_log / credit_log / im_session / im_message`。
- **唯一假点（桩）**：`app/services/vision_service.py`，接口 `predict(image_bytes: bytes) -> dict` 返回 `{category_id, label, confidence}`。当前实现：按图片字节哈希**确定性选一个已启用分类**、置信度写死 `0.91`、**完全不加载任何模型**。
- 发布链路：`app/services/publish_service.py` 调用 `get_vision_service().predict(image_bytes)` 给失物/拾物图片打标（`category_id`）。
- 匹配：`app/services/match_service.py` 加权打分 = `类目命中(W1=40) + 时间衰减(W2=25) + 地点层级命中(W3=20) + 关键词 Jaccard(W4=15)`，阈值 `80`，时间衰减 `τ=3 天`。
- 配置 `app/core/config.py` 已预留：`YOLO_DEVICE`(cpu)、`YOLO_MODEL_DIR`、`YOLO_FALLBACK_CATEGORY_ID`、`MATCH_W1~W4`、`MATCH_THRESHOLD`、`REDIS_ENABLED`、`DATABASE_URL`(默认 `sqlite:///./dev.db`) 等。
- 短信（SMS）当前为 mock：控制台 print，DEBUG 模式返回 `dev_code`。
- Redis 当前 `REDIS_ENABLED=False`，`app/core/redis_client.py` 有进程内内存兜底。
- 数据库默认 SQLite（`sqlite:///./dev.db`）。

### 0.2 前端（Vue3 + Element Plus + Vite，已构建，6 个页面）
- 页面：登录/注册、公示栏(Board)、发布(Publish，双 Tab 零门槛)、我的匹配(Matches)、交接确认(Handover，双端)、管理后台(Admin，审计时间线)。
- `src/api/mockAdapter.ts`：后端不可达时**自动启用演示模式**（mock 数据），无需后端即可渲染。
- `src/stores/demo.ts` / `src/utils/demo.ts`：演示模式开关逻辑。

### 0.3 三项已确认决策（PRD 强制遵守）
1. **AI 视觉 = 真·YOLOv8 推理**：安装 `ultralytics` + `torch`，用官方预训练 **YOLOv8n（COCO 9 类）+ YOLO-World（零样本识别校园专属类：校园卡 / 钥匙 / 玩偶 / 本子）** 对上传图片真实推理，输出 `category_id / label / confidence`。权重下载到 `models/weights/`，之后用户把训练好的校园权重丢进去即可切换（`config` 已预留 `YOLO_MODEL_DIR`）。**≤12 个分类**（COCO 通用 9 类 + 校园专属零样本 4 类）。
2. **数据库 = MySQL 8.0**：全量工程化已覆盖 SQLite 选项，统一用 MySQL。本地 MySQL 服务可用，路径 `/e/gongjuruanjian/MYSQL/bin/`（含 `mysql` / `mysqld`）。
3. **完成范围 = 全量工程化**：真视觉接入 + MySQL 8.0 + Redis（启用配置，本机无 Redis 服务，靠内存兜底；部署用 Docker 带 redis 容器）+ **Docker 容器化**（docker-compose 编排 mysql/redis/backend/frontend）+ **种子数据** + **部署文档** + **前端切真实 API**（去掉强制 mock 兜底，但保留后端不可达时的演示降级）+ 端到端跑通。

---

## 1. 增量产品目标

呼应论文标题《基于 YOLOv8 的校园失物招领智能匹配系统》与两个核心创新点：**① 拾得者零门槛发布**；**② 防冒领溯源闭环**。

- **G1｜视觉识别真实化**：将 `vision_service` 桩替换为真 YOLOv8n（COCO 9 类）+ YOLO-World（校园专属零样本 4 类）推理，输出可信 `category_id / label / confidence`，支撑创新点①"拍照即发布"。保留 `YOLO_FALLBACK_CATEGORY_ID` 降级能力。
- **G2｜工程化生产级**：数据库从 SQLite 迁 MySQL 8.0；Redis 启用配置（本机内存兜底，部署带 redis 容器）；Docker 容器化编排；可重复执行的种子数据；配套部署文档。让系统可真正部署上线，而非仅本地 demo。
- **G3｜前端可信联调**：前端从"强制演示模式"改为"真实 API 优先、后端不可达降级演示"，发布链路用真实推理结果打标，端到端跑通核心流程（发布→匹配→交接→审计）。

> 三个目标互相正交：G1 解决"识别可信"，G2 解决"运行可部署"，G3 解决"联调可信"。

---

## 2. 用户故事增量（按角色）

> 每条注明**涉及的改动模块**，供架构师与工程师定位。

### 失主（Loser / Claimer）
- 作为失主，我希望我发布的失物图片能被**真实 AI 识别出类别**（而非随机桩），以便系统更准地匹配到拾得者发布的同物。——涉及：`vision_service`(真推理)、`publish_service`、前端 Publish 页。
- 作为失主，我希望在"我的匹配"看到基于**真实识别类别**算出的匹配结果，且匹配逻辑与之前一致。——涉及：`match_service`（打分公式不变）、前端 Matches 页。
- 作为失主，我希望交接确认仍通过**动态交接码双端确认**完成，且记录持久化到 MySQL 供溯源。——涉及：`handover_code`、前端 Handover 页、MySQL。

### 拾得者（Finder）
- 作为拾得者，我希望**零门槛发布**（仅拍照 + 选保管状态二选一）时，系统**自动真识别物品类别**，无需我手动填表或选类。——涉及：前端 Publish 双 Tab、后端 `vision_service`/`publish_service`。
- 作为拾得者，我希望若 AI 识别不准，可在发布页**看到识别结果（含置信度）并手动纠正**，避免错类导致漏匹配。——涉及：前端 Publish 交互、`category` 表。
- 作为拾得者，我希望交接时生成的交接码在 MySQL 中可查、可审计，防止冒领。——涉及：`handover_code`、`audit_log`、前端 Handover。

### 管理员（Admin）
- 作为管理员，我希望系统在 MySQL 持久化后，管理后台能看到**完整、可追溯的审计时间线**（黑匣子）。——涉及：`audit_log`、前端 Admin 页、MySQL。
- 作为管理员，我希望能**一键初始化/重置种子数据**（分类、演示用户、示例失物拾物），便于演示与回归。——涉及：seed 脚本（10 张表）、`category` ≤12 类对齐。
- （P2）作为管理员，我希望能把审计日志**导出为 CSV/JSON**，用于归档与论文佐证。——涉及：前端 Admin 导出、后端导出接口。

### 游客（Guest）
- 作为游客，我希望前端**默认走真实 API**，看到真实公示栏数据；当后端不可达时仍能通过**演示降级**浏览界面，不白屏。——涉及：`mockAdapter.ts`、`stores/demo.ts`、`utils/demo.ts`、前端 Board 页。
- 作为游客，我希望发布/登录等需要身份的入口在演示降级下给出明确提示，而非静默失败。——涉及：前端全局降级提示。

---

## 3. 需求池（P0 / P1 / P2）

> 优先级定义：**P0 = Must have（阻塞上线）｜P1 = Should have（工程化必需）｜P2 = Nice to have（增强）**。
> 关联模块列引用现有源码路径，便于工程师直接定位。

### P0 — 必须（阻塞上线）

| 需求ID | 描述 | 优先级 | 关联模块 | 验收标准 |
| --- | --- | --- | --- | --- |
| **P0-01** | 真 YOLOv8 推理接入 `vision_service`：用官方预训练 **YOLOv8n（COCO 9 类）** 对上传图片真实推理，输出 `{category_id, label, confidence}`；`predict()` 签名保持不变，对上层零侵入。 | P0 | `app/services/vision_service.py`、`app/core/config.py`(`YOLO_DEVICE`/`YOLO_MODEL_DIR`/`YOLO_FALLBACK_CATEGORY_ID`) | ① 进程启动时按 `YOLO_MODEL_DIR` 真实加载权重（仅一次）；② `predict()` 返回真实置信度（非写死 0.91）；③ 权重落 **E 盘 `models/weights/`**，不写 C 盘；④ `YOLO_FALLBACK_CATEGORY_ID` 在模型不可用时仍生效。 |
| **P0-02** | 校园专属零样本识别（**YOLO-World**）：识别 4 类校园专属物品（校园卡 / 钥匙 / 玩偶 / 本子），与 COCO 9 类合并，**总分类 ≤12**。 | P0 | `app/services/vision_service.py`、`category` 表(seed) | ① YOLO-World 可识别上述 4 类并返回 label/confidence；② 分类总数不超过 12（`category` 表 seed 对齐）；③ 用户后续丢入训练好的校园权重至 `models/weights/` 即可切换，无需改代码。 |
| **P0-03** | 数据库切换 **MySQL 8.0**：`DATABASE_URL` 由 SQLite 改为 MySQL；提供建库/建表与迁移脚本，10 张表全量落地。 | P0 | `app/core/config.py`(`DATABASE_URL`)、SQLAlchemy engine、`migrations/`、`scripts/` | ① 本地 MySQL（`/e/gongjuruanjian/MYSQL/bin/`）**真建库真跑通**；② 56 个测试**仍全绿**；③ 建表/迁移脚本可**重复执行**（幂等）；④ 不向 C 盘写任何数据。 |
| **P0-04** | 前端真实 API 对接（去强制 mock）：从"强制演示模式"改为"真实 API 优先、后端不可达降级演示"。 | P0 | `src/api/mockAdapter.ts`、`src/stores/demo.ts`、`src/utils/demo.ts`、各页面 api 调用 | ① 后端可达时全部走真实接口；② 后端不可达时**自动降级**为演示模式（不白屏）；③ 发布页图片打标使用真实推理返回结果。 |
| **P0-05** | 核心回归不破 + 端到端跑通：匹配打分公式/阈值不变，发布→匹配→交接→审计全链路在 MySQL 下跑通。 | P0 | 全部模块、`tests/` | ① 匹配公式仍为 `W1=40+W2=25+W3=20+W4=15`，阈值 `80`，`τ=3 天`；② 56 测试全绿；③ 核心流程端到端验证通过（含动态交接码双端确认、审计黑匣子写入）。 |

### P1 — 应该（工程化必需）

| 需求ID | 描述 | 优先级 | 关联模块 | 验收标准 |
| --- | --- | --- | --- | --- |
| **P1-01** | Redis **启用配置**：`REDIS_ENABLED` 置 `True` 配置化；本机无 Redis 服务时仍靠内存兜底，保证功能不崩。 | P1 | `app/core/config.py`(`REDIS_ENABLED`)、`app/core/redis_client.py` | ① 通过配置即可启用 Redis；② 本机无服务时**自动降级**内存兜底，接口行为一致；③ 部署 compose 中带 redis 容器。 |
| **P1-02** | **Docker 容器化**：编写 `docker-compose.yml` 编排 `mysql / redis / backend / frontend` 四服务，含 `Dockerfile`。 | P1 | `docker-compose.yml`、`Dockerfile`(backend/frontend)、`deploy/` | ① yml 与 Dockerfile **作为交付物写出**且语法正确；② 编排含 mysql/redis/backend/frontend 四服务、网络与卷；③ 注：本机无 docker，**无法 `docker compose up` 真验证**，需用户在自有机器/服务器运行（见 §5）。 |
| **P1-03** | **种子数据**：提供 MySQL 下可执行的种子脚本，10 张表初始化，分类与 ≤12 类对齐。 | P1 | `scripts/`(seed)、`category` 表 | ① seed 在 MySQL 下可重复执行（幂等）；② `category` 含 COCO 9 类 + 校园专属 4 类（≤12）；③ 含演示用户、示例失物/拾物，便于联调与论文演示。 |
| **P1-04** | **部署文档**：覆盖 MySQL 建库、Redis、Docker 编排、权重下载与切换、前端真实 API 切换、端到端验证步骤。 | P1 | `docs/`（部署文档） | ① 文档含环境准备、依赖安装（torch/ultralytics/opencv/numpy 约 2GB，落 E 盘）、数据库初始化、启动与验证清单；② 明确"本机无 docker / 无 redis 服务"的应对。 |

### P2 — 增强（Nice to have）

| 需求ID | 描述 | 优先级 | 关联模块 | 验收标准 |
| --- | --- | --- | --- | --- |
| **P2-01** | SMS 接**真实短信网关**（当前为 mock：控制台 print / dev_code）。 | P2 | SMS 服务模块、`app/core/config.py` | ① 可配置真实网关（需用户提供账号，见 §5）；② 保留 DEBUG `dev_code` 走开发路径；③ 不阻断核心流程。 |
| **P2-02** | **EXIF/GPS 定位**：Web 端读取照片 EXIF/GPS 用于地点层级命中。——**PRD 标注为"降级方案"**：浏览器安全限制导致 Web 端不可行。 | P2 | 发布链路、`match_service`(地点层级 W3) | ① 明确标注 Web 端 EXIF/GPS **不可行**（降级）；② 当前采用"用户手动选地点层级"作为替代；③ 未来移动端可补 EXIF/GPS。 |
| **P2-03** | 管理员**审计导出**：审计时间线支持导出 CSV/JSON。 | P2 | 前端 Admin 导出、后端导出接口、`audit_log` | ① 管理员可导出审计日志；② 导出格式 CSV/JSON 任选；③ 数据来自 MySQL `audit_log`。 |

---

## 4. UI 改动点

> 核心变化：**前端从"强制演示模式"改为"真实 API 优先、后端不可达降级演示"**。

| 页面 | 改动前 | 改动后（增量） |
| --- | --- | --- |
| 全局（mockAdapter / demo store） | 后端不可达时才启用演示；默认即依赖 mock 兜底。 | **真实 API 优先**：默认走真实后端；仅当请求失败/不可达时**自动降级**为演示模式，并给出"当前为演示模式"提示。 |
| 登录/注册 | 可能直接走 mock。 | 优先真实鉴权；不可达时降级演示并提示需后端。 |
| 公示栏 Board | 演示数据为主。 | 优先展示 **MySQL 真实数据**；降级时展示演示数据并标注。 |
| 发布 Publish（双 Tab 零门槛） | 上传图片后由桩打标（写死 0.91，类别随机）。 | 上传后由**真实 YOLOv8/YOLO-World 推理**返回 `label + confidence`，**展示识别结果并允许手动纠正**；保管状态二选一保持不变（创新点①）。 |
| 我的匹配 Matches | 基于桩类别匹配。 | 基于**真实识别类别**匹配，匹配逻辑与展示不变。 |
| 交接确认 Handover（双端） | 动态交接码双端确认。 | 行为不变；数据来源由 SQLite 改为 **MySQL**，可审计。 |
| 管理后台 Admin（审计时间线） | 审计时间线来自 SQLite。 | 来自 **MySQL**；新增（P2）**审计导出**按钮。 |

**交互新增点**：发布页增加"AI 识别结果卡片"（label + 置信度进度条 + 可手动改类）；全局新增"演示模式"状态标识，避免用户混淆真实/演示数据。

---

## 5. 待确认问题 / 风险

### 5.1 环境约束（影响需求可行性，已在需求中体现降级）
| 项 | 现状 | 对需求的影响 | 是否需用户提供 |
| --- | --- | --- | --- |
| **Docker 不可用** | 本机 `docker` 命令不存在。 | `docker-compose.yml`/Dockerfile **作为交付物写出但无法本机真验证**；需用户在自有机器/服务器 `docker compose up`。 | 否（用户自跑） |
| **MySQL 本地有** | `/e/gongjuruanjian/MYSQL/bin/` 含 mysql/mysqld，可真建库。 | P0-03 可本机真跑通。 | 否 |
| **Redis 本地无服务** | `REDIS_ENABLED=False`，靠内存兜底。 | P1-01 启用配置但功能靠内存兜底；compose 带 redis 容器供部署。 | 否 |
| **磁盘/E 盘** | E 盘剩约 52GB。 | 权重与上传文件必须落 **E 盘**（`models/weights`、`uploads`），严禁写 C 盘。 | 否 |
| **Python 依赖未装** | venv 未装 `torch/ultralytics/opencv/numpy`（约 2GB）。 | 部署文档需含安装步骤；安装落 E 盘。 | 否（用户执行安装） |
| **Web EXIF/GPS 不可行** | 浏览器安全限制，Web 端无法读照片 GPS。 | P2-02 标注为**降级方案**，改用"用户手动选地点层级"。 | 否（未来移动端补） |

### 5.2 需用户后续提供（阻塞 P2 / 可选增强）
- **训练好的校园权重**（可选）：用户把训练好的校园专属权重丢入 `models/weights/` 即可切换，无需改代码（P0-02 已预留切换能力，但"更优权重"需用户训练/提供）。
- **真实短信网关账号**（P2-01）：如要接真实 SMS，需用户提供网关 API Key / 签名 / 模板；否则保持 dev_code 开发路径。

### 5.3 风险与缓解
- **R1 模型推理性能/精度**：YOLOv8n + YOLO-World 在 CPU 下推理耗时可能影响发布体验 → 缓解：异步推理 + 加载兜底类；可在 `YOLO_DEVICE` 切 cuda。
- **R2 分类映射一致性**：COCO 9 类 + YOLO-World 4 类需稳定映射到 `category` 表 `category_id` → 缓解：seed 固化映射，推理输出 label→id 查表。
- **R3 Docker 未真验证**：compose 仅静态交付 → 缓解：部署文档写明验证清单，由用户在目标环境执行。
- **R4 回归破坏**：换 DB/视觉可能破坏 56 测试 → 缓解：P0-05 强制 56 测试全绿 + 端到端跑通作为验收闸门。

---

## 6. 范围与边界（明确"不做什么"）
- **不做**：任何新业务功能（如推荐、社交）；移动端 App；独立推理微服务（维持进程内 `VisionService` 单例，符合现有设计）。
- **不做**：修改匹配打分公式/阈值（保持论文算法一致性，仅替换打标来源）。
- **不做**：往 C 盘写入任何权重/数据（硬性约束）。
- **仅交付**：本文档（需求定义）；**不含任何实现代码、不修改项目源文件**。实现由工程师（寇豆码）按本 PRD 与架构师（高见远）的架构文档执行。
