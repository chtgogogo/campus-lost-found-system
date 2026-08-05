# 基于 YOLOv8 的校园失物招领智能匹配系统 — 后端架构设计 + 实现任务分解

> 文档性质：架构设计 + 任务分解（**仅设计，不含实现代码**）。
> 技术栈（已定稿，不可更改）：Python 3.12 / FastAPI / SQLAlchemy 2.x / MySQL 8.0（开发期 SQLite 兜底）/ Redis（仅动态交接码 + 限流）/ WebSocket / YOLOv8n + YOLO-World（独立推理服务）。所有 API 纯 JSON、平台无关（Web / 小程序共用）。
> 设计依据：`任务书_优化版`、`需求规格与验收标准(EARS)`、`数据库设计与架构图`、`系统讲解`、`创新点与参考文献校核`、`ER图.svg`、`架构图.svg`。

---

## 1. 后端项目文件树（FastAPI 分层）

```
失物招领系统/                                   # 项目根（E:\xuexixiangguan\pythonProject\gongcheng\失物招领系统）
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 应用工厂：中间件(CORS/信任代理)、Router 装配、lifespan、异常处理器、静态资源
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py           # Pydantic Settings：DB URL、Redis、JWT、YOLO 服务地址、权重/阈值/τ/TTL 全外置
│   │   ├── database.py         # SQLAlchemy engine / SessionLocal / Base / get_db 依赖（MySQL 8.0；dev 可切 SQLite）
│   │   ├── security.py         # 密码哈希(passlib/bcrypt)、JWT 签发/校验、双因子(短信OTP)辅助
│   │   ├── redis_client.py     # Redis 连接池：交接码读写+30min TTL、短信限流计数器
│   │   └── exceptions.py       # 业务异常基类 + 统一错误码映射 + 异常→响应处理器
│   ├── models/                 # SQLAlchemy 声明式模型（表结构见 §2）
│   │   ├── __init__.py         # 汇总 import，供 Alembic / create_all 使用
│   │   ├── user.py             # User、TrustScoreLog（信誉流水账）
│   │   ├── category.py         # Category（含 recognition_mode / yolo_prompt）
│   │   ├── item.py             # LostItem、FoundItem
│   │   ├── match.py            # MatchRecord、HandoverCode
│   │   ├── im.py               # IMSession、IMMessage
│   │   └── audit.py            # AuditLog（按月 RANGE 分区）
│   ├── schemas/                # Pydantic v2 请求/响应模型（含统一响应包装见 §5）
│   │   ├── __init__.py
│   │   ├── common.py           # StandardResponse / Page / ErrorResponse / 统一枚举
│   │   ├── user.py             # UserCreate/Login/BindPhone/Token/UserOut
│   │   ├── category.py         # CategoryCreate/CategoryOut
│   │   ├── item.py             # LostItemCreate/Out、FoundItemCreate/Out
│   │   ├── match.py            # MatchOut、ClaimCreate、HandoverGenerate/Verify
│   │   └── im.py               # IMSessionOut、IMMessageCreate/Out
│   ├── routers/                # 路由层（薄，仅参数校验 + 调 service + 包装响应）
│   │   ├── __init__.py
│   │   ├── auth.py             # 注册/登录/刷新/发短信/绑手机/登出
│   │   ├── users.py            # 个人资料/信誉查询（用户侧）
│   │   ├── items.py            # 失物发布、拾物发布、列表、详情、撤销
│   │   ├── match.py            # 匹配列表、认领申请、确认归还、交接码生成/验证、申诉
│   │   ├── im.py               # WebSocket 端点 + 会话/历史 REST
│   │   ├── public.py           # 已解决公示栏（脱敏）+ 公示申诉入口
│   │   └── admin.py            # 审计时间线、用户封禁、分类标签管理、管理员 seed
│   ├── services/               # 业务逻辑层（核心，不依赖路由）
│   │   ├── __init__.py
│   │   ├── yolo_service.py     # HTTP 调 YOLO 服务 + 类别映射 + YOLO-World 兜底 + 降级
│   │   ├── match_service.py    # 打分引擎：时间衰减 + 地点层级 + Jaccard + 权重（§5.4）
│   │   ├── publish_service.py  # 发布编排：上传→YOLO打标→写入→反向主动匹配→疑似提醒
│   │   ├── handover_service.py # 交接码生成/双端验证（Redis TTL + MySQL 镜像 + GPS 记录）
│   │   ├── im_service.py       # 会话创建、消息落库、7 天清理定时任务
│   │   ├── audit_service.py    # 审计日志写入（黑匣子）
│   │   └── appeal_service.py   # 冒领申诉初筛（与认领理由文本相似度）
│   ├── utils/                  # 无状态工具（纯函数，易测）
│   │   ├── __init__.py
│   │   ├── region.py           # region_code 解析 + 层级命中规则（§5.3）
│   │   ├── text.py             # 关键词分词 + Jaccard 相似度
│   │   ├── time_decay.py       # 时间衰减函数 exp(-Δt/τ)
│   │   ├── exif.py             # 图片 EXIF 时间/GPS 提取（失败兜底）
│   │   ├── desensitize.py      # 手机号/姓名脱敏（张**）
│   │   └── storage.py          # 图片上传（本地磁盘/MinIO/OSS）返回 URL
│   └── websockets/
│       ├── __init__.py
│       └── connection.py       # WS 连接注册表（匿名但持 JWT）、消息广播、模板白名单
├── migrations/                 # Alembic
│   ├── env.py / alembic.ini
│   └── versions/               # 各迁移脚本（含审计分区、索引、外键）
├── models/weights/             # 真实 YOLO 权重目录（T-DEP 放置 YOLOv8n+YOLO-World 权重；E 盘，严禁 C 盘）
├── app/services/vision_service.py  # 进程内视觉推理 VisionService（启动时挂载 app.state；MVP 桩确定性返回类别，T-DEP 接真实双路推理）
├── tests/                      # 单元 + 端到端（MVP 闭环）
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_match.py           # 打分单测（权重/衰减/地点/Jaccard）
│   ├── test_publish_flow.py    # MVP 端到端：发布→打标→匹配→认领→交接
│   └── test_im.py
├── deploy/
│   ├── Dockerfile.api          # FastAPI 镜像
│   ├── Dockerfile.yolo         # YOLO 服务镜像（GPU base）
│   ├── docker-compose.yml      # api + yolo + mysql + redis + (minio)
│   ├── nginx.conf
│   └── mysql/
│       └── init.sql            # 建库、DDL、索引、审计分区、region_code 规则注释
├── .env.example                # 配置样例（密钥/URL/权重/阈值）
├── requirements.txt            # 后端依赖
├── pyproject.toml              # 构建/工具配置
└── README.md
```

**分层职责边界**
- `routers` 仅做：鉴权依赖注入、`Request`/`Response` 模型校验、调 `services`、用 `StandardResponse` 包装。不写业务。
- `services` 仅做：业务编排、跨模型事务、调用 `yolo_service` / `redis_client` / `utils`；通过 `get_db` 拿 Session。
- `models` 仅做：表结构 + 关系 + 索引声明；不写逻辑。
- `utils` 仅做：纯函数，无 DB/IO 副作用（IO 类如 storage/exif 明确标注）。

---

## 2. 数据库 Schema 完整定义（MySQL 8.0 / InnoDB / utf8mb4）

> 通用约定：所有表 `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci`；时间字段统一 `TIMESTAMP`（已含时区归一为 UTC 存储，见 §5.2）；外键 `ON DELETE RESTRICT`（审计/业务完整性优先）。
> **region_code（6 位行政区划，GB/T 2260）层级规则**（§5.3）：`前2位=省`、`前4位=市`、`前6位=区/县`。示例：`51`=四川省，`5101`=成都市，`510107`=成都市武侯区（文档默认校区码，待 §6 确认实际校区码）。

### 2.1 user（用户表）
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | PK | |
| student_no | VARCHAR(32) | ✓ | — | **UNIQUE** | 学号/工号，登录账号 |
| phone | VARCHAR(20) | ✓ | — | **UNIQUE** | 绑定双因子；限流键 |
| real_name | VARCHAR(50) | ✗ | NULL | — | 真实姓名（仅管理员可见） |
| password_hash | VARCHAR(100) | ✓ | — | — | bcrypt 哈希 |
| role | TINYINT | ✓ | 0 | idx | 0 普通 / 1 管理员 |
| credit_score | INT | ✓ | 100 | — | 信誉分（运行总值，明细见 trust_score_log） |
| status | TINYINT | ✓ | 0 | idx | 0 正常 / 1 封禁 |
| created_at | TIMESTAMP | ✓ | CURRENT_TIMESTAMP | — | |

### 2.2 category（物品分类表）— 增加识别模式字段
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | PK | |
| name | VARCHAR(50) | ✓ | — | idx(name) | 类别名（校园卡/钥匙/箱包…） |
| yolo_class_id | INT | ✗ | NULL | — | 对齐 COCO 类 id（YOLO-World 类为 NULL） |
| recognition_mode | TINYINT | ✓ | 0 | — | **0=YOLOv8-COCO / 1=YOLO-World 零样本** |
| yolo_prompt | VARCHAR(120) | ✗ | NULL | — | YOLO-World 文本提示词（mode=1 必填） |
| parent_id | BIGINT UNSIGNED | ✗ | NULL | idx | 父级 id，NULL 为一级（预留层级） |
| is_active | TINYINT | ✓ | 1 | idx | 是否启用（下架类别不动主链路） |

> 推荐 ≤12 类（配置可扩）：COCO 复用 9 类（书包24/手提包26/行李箱28/雨伞25/水杯39/手机67/笔记本63/书籍73/球类32），YOLO-World 3 类（校园卡/钥匙/玩偶）。`yolo_prompt` 如 `"campus card, student ID"`、`"keychain with keys"`、`"plush doll toy"`。

### 2.3 lost_item（失物信息表）
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | PK | |
| publisher_id | BIGINT UNSIGNED | ✓ | — | FK→user(id) | 失主 |
| category_id | BIGINT UNSIGNED | ✓ | — | FK→category(id)；**复合索引** | YOLO 打标结果 |
| title | VARCHAR(100) | ✓ | — | — | 物品名称（必填） |
| description | TEXT | ✓ | — | — | 品牌/颜色等（必填，可检索） |
| images | JSON | ✗ | NULL | — | ≤9 张图片 URL |
| color | VARCHAR(30) | ✗ | NULL | — | 颜色（加权特征） |
| lost_location | VARCHAR(200) | ✓ | — | — | 丢失精确地点 |
| region_code | CHAR(6) | ✓ | — | **复合索引** | 6 位行政区划 |
| lost_time | DATETIME | ✓ | — | — | 丢失时间 |
| status | TINYINT | ✓ | 0 | **复合索引** | 0 待匹配/1 匹配中/2 待认领/3 已解决 |
| created_at | TIMESTAMP | ✓ | CURRENT_TIMESTAMP | — | |

### 2.4 found_item（拾物信息表）
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | PK | |
| finder_id | BIGINT UNSIGNED | ✓ | — | FK→user(id) | 拾得者 |
| category_id | BIGINT UNSIGNED | ✓ | — | FK→category(id)；**复合索引** | |
| description | TEXT | ✗ | NULL | — | 描述（选填） |
| images | JSON | ✓ | — | — | 照片 URL（拾物必含≥1张） |
| found_location | VARCHAR(200) | ✗ | NULL | — | 发现地点（EXIF/手动） |
| region_code | CHAR(6) | ✗ | NULL | **复合索引** | 6 位（可空，未定位时回退） |
| found_time | DATETIME | ✗ | NULL | — | EXIF 或手动 |
| keep_status | TINYINT | ✓ | — | — | **0 暂为保管 / 1 未保管**（二选一必选） |
| contact_allowed | TINYINT | ✓ | 1 | — | 是否愿接收联系 |
| status | TINYINT | ✓ | 0 | **复合索引** | 0 待认领 / 1 已解决 |
| created_at | TIMESTAMP | ✓ | CURRENT_TIMESTAMP | — | |

### 2.5 match_record（匹配记录表）
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | PK | |
| lost_id | BIGINT UNSIGNED | ✓ | — | FK→lost_item(id)；**idx** | |
| found_id | BIGINT UNSIGNED | ✓ | — | FK→found_item(id)；**idx** | |
| match_score | DECIMAL(5,2) | ✓ | — | — | 规则加权匹配度（0–100） |
| status | TINYINT | ✓ | 0 | idx | 0 待认领/1 认领中/2 已完成/3 已拒绝 |
| claim_reason | TEXT | ✗ | NULL | — | 独有凭证/认领理由（必填，入库审计） |
| code | VARCHAR(12) | ✗ | NULL | — | 交接动态码（**镜像自 handover_code**，主存 Redis） |
| code_expire | DATETIME | ✗ | NULL | — | 30 分钟过期（镜像） |
| created_at | TIMESTAMP | ✓ | CURRENT_TIMESTAMP | — | |

### 2.6 handover_code（动态交接码表 — 新增，审计镜像）
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | PK | |
| match_id | BIGINT UNSIGNED | ✓ | — | FK→match_record(id)；UNIQUE(match_id, seq) | 关联匹配 |
| seq | SMALLINT | ✓ | 1 | — | 同一匹配可多次重发，序号递增 |
| code | VARCHAR(12) | ✓ | — | idx | 6 位随机码（Redis 为活性存储） |
| qr_token | VARCHAR(64) | ✓ | — | — | 动态二维码载荷（签发时生成） |
| status | TINYINT | ✓ | 0 | idx | 0 有效 / 1 已验证 / 2 已过期 |
| verified_by_lost | TINYINT | ✓ | 0 | — | 失主端确认 |
| verified_by_finder | TINYINT | ✓ | 0 | — | 拾得者端确认 |
| gps_lost | VARCHAR(50) | ✗ | NULL | — | 失主扫码 GPS（Web=IP 粗位） |
| gps_finder | VARCHAR(50) | ✗ | NULL | — | 拾得者扫码 GPS |
| generated_at | TIMESTAMP | ✓ | CURRENT_TIMESTAMP | — | |
| expire_at | DATETIME | ✓ | — | idx(expire_at) | 生成+30min |

> **Redis 为主活性存储**（TTL=30min，作并发唯一+自动失效+限流）；MySQL `handover_code` 为**不可变审计镜像**（每次生成/验证事件落一行），交接完成由 `status` 演进 + `audit_log` 留痕。两者最终一致（验证成功后写 MySQL + 删除/过期 Redis）。

### 2.7 im_session（IM 会话表 — 新增）
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | PK | |
| match_id | BIGINT UNSIGNED | ✗ | NULL | FK→match_record(id)；idx | 关联匹配（可空，独立会话） |
| lost_user_id | BIGINT UNSIGNED | ✓ | — | FK→user(id)；idx | 失主（匿名映射） |
| finder_user_id | BIGINT UNSIGNED | ✓ | — | FK→user(id)；idx | 拾得者 |
| status | TINYINT | ✓ | 0 | idx | 0 开启 / 1 关闭 |
| created_at | TIMESTAMP | ✓ | CURRENT_TIMESTAMP | — | |
| last_message_at | DATETIME | ✗ | NULL | — | |
| expires_at | DATETIME | ✓ | — | idx(expires_at) | created_at+7天（清理键） |

### 2.8 im_message（IM 消息表 — 新增）
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | PK | |
| session_id | BIGINT UNSIGNED | ✓ | — | FK→im_session(id)；**idx(session_id, sent_at)** | |
| sender_id | BIGINT UNSIGNED | ✓ | — | FK→user(id) | 发送方（匿名，仅会话内标识） |
| sender_role | TINYINT | ✓ | — | — | 0 失主 / 1 拾得者 |
| content_type | TINYINT | ✓ | 0 | — | 0 文字 / 1 预设模板 |
| content | VARCHAR(500) | ✓ | — | — | 文本（禁链接，服务端过滤） |
| sent_at | DATETIME | ✓ | CURRENT_TIMESTAMP | — | |

> 7 天清理：定时任务 `DELETE FROM im_message WHERE session_id IN (SELECT id FROM im_session WHERE expires_at < NOW())`，并删对应 session（物理删除，与审计日志 365 天分离，见 §6-Q12）。

### 2.9 trust_score_log（信誉流水账 — 新增）
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | PK | |
| user_id | BIGINT UNSIGNED | ✓ | — | FK→user(id)；idx(user_id,created_at) | |
| delta | INT | ✓ | — | — | 变更值（+1 暂为保管等） |
| reason | VARCHAR(50) | ✓ | — | — | 变更原因枚举 |
| ref_type | VARCHAR(20) | ✗ | NULL | — | 关联对象（found_item 等） |
| ref_id | BIGINT UNSIGNED | ✗ | NULL | — | |
| created_at | TIMESTAMP | ✓ | CURRENT_TIMESTAMP | — | |

> `user.credit_score` 为运行总值；本表为可审计流水（如“暂为保管”隐式 +1）。

### 2.10 audit_log（审计日志表 — 按月分区）
| 字段 | 类型 | 必填 | 默认 | 索引/约束 | 说明 |
|---|---|---|---|---|---|
| id | BIGINT UNSIGNED | ✓ | AUTO_INCREMENT | **PK(id, created_at)**（分区键须入 PK） | |
| user_id | BIGINT UNSIGNED | ✗ | NULL | FK→user(id)（游客可空）；idx(user_id,created_at) | |
| action | VARCHAR(50) | ✓ | — | — | 操作类型枚举（publish/claim/handover/appeal/ban…） |
| target_type | VARCHAR(20) | ✗ | NULL | idx(target_type,target_id) | lost/found/match/user |
| target_id | BIGINT UNSIGNED | ✗ | NULL | — | 关联对象 id |
| ip | VARCHAR(45) | ✗ | NULL | — | 请求 IP |
| ua | VARCHAR(255) | ✗ | NULL | — | 设备 UA |
| session_id | VARCHAR(64) | ✗ | NULL | — | 登录会话 id |
| gps | VARCHAR(50) | ✗ | NULL | — | 交接 GPS（Web=IP 粗位） |
| detail | TEXT | ✗ | NULL | — | 操作原文（认领理由等） |
| created_at | TIMESTAMP | ✓ | CURRENT_TIMESTAMP | **RANGE COLUMNS 分区键（按月）** | 保留 365 天 |

**关键索引汇总**
```
user:            UNIQUE(student_no), UNIQUE(phone), idx(role), idx(status)
category:        idx(name), idx(parent_id), idx(is_active), idx(recognition_mode)
lost_item:       idx(category_id, status, region_code)   ← 匹配主检索
found_item:      idx(category_id, status, region_code)   ← 匹配主检索
match_record:    idx(lost_id), idx(found_id), idx(status)
handover_code:   UNIQUE(match_id, seq), idx(code), idx(status), idx(expire_at)
im_session:      idx(match_id), idx(lost_user_id), idx(finder_user_id), idx(status), idx(expires_at)
im_message:      idx(session_id, sent_at)
trust_score_log: idx(user_id, created_at)
audit_log:       idx(target_type, target_id), idx(user_id, created_at)  + 按月分区
```
**外键**：lost_item.publisher_id→user；found_item.finder_id→user；*_item.category_id→category；match_record.(lost_id,found_id)；handover_code.match_id→match_record；im_session.(match_id,lost_user_id,finder_user_id)；im_message.session_id→im_session；trust_score_log.user_id→user；audit_log.user_id→user（均 RESTRICT）。

**审计按月分区 DDL 要点**
```sql
CREATE TABLE audit_log ( ... ,
  PRIMARY KEY (id, created_at)            -- 分区键必须进主键
) ENGINE=InnoDB
PARTITION BY RANGE COLUMNS (created_at) (
  PARTITION p202601 VALUES LESS THAN ('2026-02-01'),
  PARTITION p202602 VALUES LESS THAN ('2026-03-01'),
  ... -- 由迁移脚本按月份预建 + 定时新增分区
  PARTITION pmax VALUES LESS THAN (MAXVALUE)
);
```
> 365 天归档：定时任务将 `created_at < NOW()-365d` 迁移至 `audit_log_cold`（冷备份，前端不可查，管理员可申请调取）。归档表结构与索引同构。

---

## 3. RESTful API 端点清单（纯 JSON，平台无关）

> 前缀 `/api/v1`。鉴权级别：**Public**（游客）/ **User**（JWT）/ **Admin**（JWT+role=1）。
> 统一响应包装见 §5.1；错误码见 §5.2。WebSocket 见 §3.7。

### 3.1 认证 auth（Public/User）
| 方法 | 路径 | 请求体 | 响应 | 鉴权 |
|---|---|---|---|---|
| POST | `/auth/register` | {student_no, phone, sms_code, password, real_name?} | UserOut + Token | Public（需短信OTP） |
| POST | `/auth/login` | {student_no, password} | Token{access,refresh} | Public |
| POST | `/auth/refresh` | {refresh_token} | Token | Public |
| POST | `/auth/send-sms` | {phone, purpose: register\|bind\|login} | {sent:true} | Public（限流） |
| POST | `/auth/bind-phone` | {phone, sms_code} | UserOut | User |
| POST | `/auth/logout` | {refresh_token} | {ok:true} | User |

### 3.2 用户 users（User）
| 方法 | 路径 | 请求体 | 响应 | 鉴权 |
|---|---|---|---|---|
| GET | `/users/me` | — | UserOut（脱敏） | User |
| PATCH | `/users/me` | {password?, ...} | UserOut | User |
| GET | `/users/me/credit` | — | {credit_score, logs[]} | User |
| GET | `/users/me/items` | {type:lost\|found} | Page[ItemOut] | User |

### 3.3 物品 items（User 发布；Public 仅公示读）
| 方法 | 路径 | 请求体 | 响应 | 鉴权 |
|---|---|---|---|---|
| POST | `/lost-items` | multipart(images≤9)+{title,description,color?,lost_location,region_code,lost_time,category_id?} | LostItemOut（含 yolo 标签） | User |
| GET | `/lost-items/{id}` | — | LostItemOut | User/Public(脱敏) |
| GET | `/lost-items` | {category_id?,region_code?,status?,page} | Page[LostItemOut] | User |
| PATCH/DELETE | `/lost-items/{id}` | — | LostItemOut | User(owner) |
| POST | `/found-items` | multipart(images≥1)+{keep_status(0\|1),category_id?,description?,found_location?,region_code?,found_time?,contact_allowed?} | FoundItemOut | User |
| GET | `/found-items/{id}` | — | FoundItemOut | User/Public(脱敏) |
| GET | `/found-items` | {category_id?,region_code?,status?,page} | Page[FoundItemOut] | User |
| PATCH/DELETE | `/found-items/{id}` | — | FoundItemOut | User(owner) |

### 3.4 匹配 match（User）
| 方法 | 路径 | 请求体 | 响应 | 鉴权 |
|---|---|---|---|---|
| GET | `/lost-items/{id}/matches` | — | Page[MatchOut]（按 score 降序） | User(owner) |
| GET | `/matches` | {status?} | Page[MatchOut]（我的） | User |
| POST | `/matches/{id}/claim` | {claim_reason(必填), unique_proof?} | MatchOut | User(失主) |
| POST | `/matches/{id}/confirm-return` | — | MatchOut | User(拾得者) |
| POST | `/matches/{id}/handover/generate` | — | {code, qr_token, expire_at} | User(双方) |
| POST | `/matches/{id}/handover/verify` | {code, role:lost\|finder, gps?} | {both_verified:bool} | User |
| POST | `/matches/{id}/reject` | {reason?} | MatchOut | User(拾得者) |
| POST | `/matches/{id}/appeal` | {detail(必填)} | {appeal_id, risk_level} | User(真失主) |

### 3.5 即时通讯 im（User）
| 方法 | 路径 | 请求体 | 响应 | 鉴权 |
|---|---|---|---|---|
| POST | `/im/sessions` | {match_id} | IMSessionOut | User |
| GET | `/im/sessions` | — | Page[IMSessionOut] | User |
| GET | `/im/sessions/{id}/messages` | {page} | Page[IMMessageOut] | User(会话成员) |
| WS | `/im/ws?session_id={id}&token={jwt}` | 帧：{type:text\|template, content} | 帧回显 | User(会话成员) |

### 3.6 公示 public（Public/User）
| 方法 | 路径 | 请求体 | 响应 | 鉴权 |
|---|---|---|---|---|
| GET | `/public/resolved` | {category_id?,region_code?,page} | Page[ResolvedOut]（脱敏：张**同学） | Public |
| POST | `/public/resolved/{id}/appeal` | {detail(必填)} | {appeal_id, risk_level} | User |

### 3.7 WebSocket IM 协议（轻量）
- 建连：`WS /api/v1/im/ws?session_id=S&token=JWT`；服务端校验 JWT + 会话成员资格 → 否则 1008 关闭。
- 上行帧：`{"type":"text","content":"..."}` 或 `{"type":"template","content":"template_id"}`；服务端过滤 URL/链接字符，超长截断 500。
- 下行帧：`{"type":"text","sender_role":0,"content":"...","sent_at":"..."}`。
- 7 天到期自动关闭并清理（见 §2.8）。

### 3.8 后台 admin（Admin）
| 方法 | 路径 | 请求体 | 响应 | 鉴权 |
|---|---|---|---|---|
| GET | `/admin/audit-logs` | {user_id?,target_type?,target_id?,start?,end?,page} | Page[AuditOut] | Admin |
| GET | `/admin/audit-logs/timeline` | {target_type,target_id} | [AuditOut]（完整时间线） | Admin |
| POST | `/admin/users/{id}/ban` | {ban:true\|false, reason} | UserOut | Admin（操作自身写审计） |
| GET | `/admin/categories` | — | [CategoryOut] | Admin |
| POST/PUT/DELETE | `/admin/categories[/{id}]` | CategoryCreate | CategoryOut | Admin |
| POST | `/admin/seed` | {student_no,phone,password} | UserOut(role=1) | Admin（或初始化脚本） |

---

## 4. 有序实现任务列表（按依赖；P0/P1/P2；MVP 标记）

> **MVP 最小闭环**＝「发布→YOLO 打标→匹配→认领→交接」端到端可跑通。MVP 用 SQLite + YOLO 服务 **桩（stub 返回固定标签）** 即可跑通，随后替换真实 YOLO 服务。

### 4.1 高层分组（符合 ≤5 上限，每组 ≥3 文件，T01=基础设施）
| Task | 名称 | 源文件（≥3） | 依赖 | 优先级 |
|---|---|---|---|---|
| **T01** | 项目基础设施 | `requirements.txt`, `.env.example`, `app/main.py`, `app/core/{config,database,security,redis_client,exceptions}.py` | — | P0 |
| **T02** | 数据层（模型+迁移+Schema） | `app/models/*`(user,category,item,match,im,audit), `migrations/*`(DDL/索引/分区), `app/schemas/*` | T01 | P0 |
| **T03** | 核心服务层 | `app/services/*`(yolo,match,publish,handover,audit,im,appeal), `app/utils/*` | T01（模型契约定后可与 T02 并行） | P0/P1 |
| **T04** | API 路由层 | `app/routers/*`(auth,users,items,match,im,public,admin), `app/websockets/connection.py` | T01, T03 | P0/P1 |
| **T05** | 部署与测试 | `yolo_service/*`, `deploy/*`(Docker/compose/nginx/mysql init), `tests/*` | T01 | P1/P2 |

> 依赖尽量扁平：T02/T03 在 T01 后并行（先冻结 models/schemas 契约）；T04 依赖 T03；T05 仅依赖 T01（独立可先行容器化）。

### 4.2 详细有序清单（P0/P1/P2 + MVP 标记）
**阶段 0 — 脚手架**
- **[P0][MVP] T-INF-1** 项目脚手架：`requirements.txt`、`.env.example`、`app/main.py`、`app/core/config.py`、`database.py`、`security.py`、`redis_client.py`、`exceptions.py`。
- **[P0][MVP] T-INF-2** YOLO 服务骨架：`yolo_service/app.py`、`inference.py`、`category_map.py`（MVP 可用 stub 返回固定标签）。

**阶段 1 — 数据层**
- **[P0][MVP] T-MDL-1** 模型：`app/models/{user,category,item,match,im,audit}.py`（含 §2 全部字段/关系/索引）。
- **[P0][MVP] T-MDL-2** 迁移与 DDL：`migrations/env.py`+首版迁移（建表/索引/审计分区/region 注释），`deploy/mysql/init.sql`；dev 可 `create_all` 跑 SQLite。
- **[P0][MVP] T-MDL-3** Schema：`app/schemas/{common,user,category,item,match,im}.py`（含 `StandardResponse`）。

**阶段 2 — 核心服务**
- **[P0][MVP] T-SVC-1** `yolo_service.py`：HTTP 客户端 + 类别映射 + YOLO-World 兜底 + 服务降级（失败不阻塞发布）。
- **[P0][MVP] T-SVC-2** `match_service.py`：打分引擎（时间衰减/地点层级/Jaccard/权重，读 config）。
- **[P0][MVP] T-SVC-3** `publish_service.py`：发布编排（上传→打标→写入→反向主动匹配→疑似提醒）。
- **[P0][MVP] T-SVC-4** `handover_service.py`：交接码生成/双端验证（Redis TTL + MySQL 镜像 + GPS）。
- **[P0][MVP] T-SVC-5** `audit_service.py` + `utils/{region,text,time_decay,exif,desensitize,storage}.py`。
- **[P1] T-SVC-6** `im_service.py`：会话创建、消息落库、7 天清理定时任务。
- **[P1] T-SVC-7** `appeal_service.py`：申诉初筛（与认领理由文本相似度，高危标记）。

**阶段 3 — API 路由**
- **[P0][MVP] T-API-1** `routers/auth.py`：注册/登录/刷新/发短信/绑手机/登出。
- **[P0][MVP] T-API-2** `routers/items.py`：失物/拾物发布 + 列表/详情。
- **[P0][MVP] T-API-3** `routers/match.py`：匹配列表/认领/确认归还/交接码生成验证。
- **[P1] T-API-4** `routers/im.py` + `websockets/connection.py`：WS + 会话/历史。
- **[P1] T-API-5** `routers/public.py`：公示栏（脱敏）+ 公示申诉。
- **[P1] T-API-6** `routers/admin.py`：审计时间线/封禁/分类管理/seed。

**阶段 4 — 部署与测试**
- **[P1] T-TEST-1** `tests/`：打分单测、MVP 端到端（`test_publish_flow.py`）、IM 测试。
- **[P2] T-DEP-1** `deploy/`：Dockerfile(s)/compose/nginx/mysql init/CI；真实 YOLO 服务替换 stub。

> **MVP 闭环文件集合**（跑通端到端）：T-INF-1、T-INF-2、T-MDL-1/2/3、T-SVC-1~5、T-API-1~3。其余（IM/公示/Admin/部署）为增量，不阻塞闭环。

### 4.3 任务依赖图
```mermaid
graph TD
  T01[T01 基础设施] --> T02[T02 数据层]
  T01 --> T03[T03 核心服务层]
  T01 --> T04[T04 API 路由层]
  T01 --> T05[T05 部署与测试]
  T02 -.契约冻结后并行.-> T03
  T03 --> T04
```

---

## 5. 共享约定（跨模块，工程师必读）

### 5.1 统一响应包装
```jsonc
// 成功
{ "code": 0, "message": "success", "data": { ... } }
// 分页
{ "code": 0, "message": "success",
  "data": { "items": [ ... ], "total": 120, "page": 1, "page_size": 20 } }
// 失败（错误码见 §5.2）
{ "code": 4001, "message": "item not found", "data": null }
```
- 所有路由经依赖统一包装；`StandardResponse[DataT]` 泛型。`code=0` 成功，`code>0` 业务/系统错误。
- 时间字段统一 ISO-8601 UTC（`Z` 后缀）；分页默认 `page=1,page_size=20`，上限 100。

### 5.2 统一错误码表
| code | 含义 | HTTP |
|---|---|---|
| 0 | 成功 | 200 |
| 1000 | 未认证/令牌缺失 | 401 |
| 1001 | 令牌过期 | 401 |
| 1002 | 凭证错误（学号/密码） | 401 |
| 1003 | 手机号未绑定/OTP 错误 | 400 |
| 1004 | 刷新令牌无效 | 401 |
| 2001 | 物品不存在 | 404 |
| 2002 | 分类不存在/未启用 | 400 |
| 2003 | 无权操作该资源（非 owner） | 403 |
| 3001 | 匹配度低于阈值（无疑似） | 200（正常返回空） |
| 3002 | 认领理由必填 | 400 |
| 3003 | 该匹配已处理（非待认领） | 409 |
| 4001 | 交接码无效 | 400 |
| 4002 | 交接码已过期（请重生成） | 400 |
| 4003 | 交接码已验证/待对方确认 | 409 |
| 5000 | YOLO 服务不可用（已降级） | 200（降级标签） |
| 5001 | 内部错误 | 500 |
| 6001 | 触发限流（短信/接口） | 429 |
| 7001 | 权限不足（需管理员） | 403 |
| 8001 | 申诉已提交（初筛中） | 200 |
| 9001 | 参数校验失败 | 422 |

### 5.3 地点层级命中规则（region_code）
- 编码：GB/T 2260，6 位。`51`=省，`5101`=市，`510107`=区/县（文档默认校区码，实际见 §6-Q2）。
- `location_hit(a, b)`：
  - `a[0:6]==b[0:6]`（同区）→ **1.0**
  - `a[0:4]==b[0:4]`（同市）→ **0.6**
  - `a[0:2]==b[0:2]`（同省）→ **0.3**
  - 否则 → **0**
- 滑动范围检索：校园=精确 6 位；市=前 4 位 `LIKE '5101%'`；省=前 2 位；全国=全表（SQL 用 `region_code LIKE ?` 前缀匹配，复用复合索引左前缀）。

### 5.4 加权打分公式（默认权重初值）
```
score = w1·category_hit + w2·time_decay + w3·location_hit + w4·keyword_jaccard   // 0–100 分制
```
- `category_hit`：精确类目匹配 = **1.0**；父级类目匹配 = **0.5**；否则不进入打分（主键检索已过滤）。
- `time_decay(Δt)` = `exp(-Δt / τ)`，`τ = 3 天`（配置项），`Δt = |lost_time - found_time|`（天），值域 (0,1]。
- `location_hit`：见 §5.3（1.0 / 0.6 / 0.3 / 0）。
- `keyword_jaccard`：对 `title+description` 分词（中文 jieba / 英文简单切分）取集合，Jaccard = |A∩B| / |A∪B|，值域 [0,1]。
- **默认权重初值（须由验证集实验确定，论文给出依据）**：
  - `w1 = 40`（类目命中，主检索键，权重最高）
  - `w2 = 25`（时间衰减）
  - `w3 = 20`（地点层级命中）
  - `w4 = 15`（关键词 Jaccard）
  - 合计 = 100；**阈值 `threshold = 80`（初设 80%，须实验调参）**。
- 说明：因类目为一级检索键，候选集已同目，`w1` 多为常数偏置；排序主要由 `w2/w3/w4` 决定。阈值 80 意为：同类目 +（时间衰减强 + 地点同区 + 关键词高）方触发「疑似匹配提醒」。所有 `w*`、`τ`、`threshold` 外置配置（§5.6），可复现实验。

### 5.5 JWT 用法与过期策略
- 算法 HS256（密钥 `JWT_SECRET` 取自配置/环境变量，生产用强随机；可升级 RS256）。
- Payload：`{sub: user_id, role: 0|1, jti, exp, iat}`。
- **Access Token TTL = 120 min**（配置 `ACCESS_TOKEN_EXPIRE_MIN`）；**Refresh Token TTL = 7 d**，哈希存 Redis（键 `rt:{jti}`，登出/封禁即删，支持吊销）。
- 双因子：注册/绑手机须短信 OTP（`phone + sms_code`，Redis 限流）；登录 = `student_no + password` 换取 Token（身份=学号且已绑定手机）。管理员独立账号 `role=1`，后台接口加 `require_admin` 依赖。
- 中间件从 `Authorization: Bearer <token>` 解析；WS 从 query `token` 解析。

### 5.6 配置文件位置
- 主配置：`app/core/config.py`（Pydantic `Settings`，读项目根 `.env`）。
- 样例：`E:/.../失物招领系统/.env.example`（提交，不含真实密钥）。
- 外置可调参数清单（均可在 `.env` 覆盖）：
  ```
  DATABASE_URL=mysql+asyncmy://user:pwd@host:3306/lostfound   # dev: sqlite:///./dev.db
  REDIS_URL=redis://host:6379/0
  JWT_SECRET=***  ACCESS_TOKEN_EXPIRE_MIN=120  REFRESH_TOKEN_EXPIRE_DAYS=7
  YOLO_DEVICE=cpu            # 推理设备（cpu/cuda）；视觉模型在 API 进程内启动加载，无独立服务、无 HTTP 跳转
  YOLO_MODEL_DIR=models/weights   # 真实权重目录（项目内，严禁 C 盘）；T-DEP 阶段放置 YOLOv8n+YOLO-World 权重
  YOLO_FALLBACK_CATEGORY_ID=0  # 推理不可用时的兜底类别
  HANDOVER_TTL_MIN=30
  SMS_RATE_LIMIT=5/min
  MATCH_W1=40  MATCH_W2=25  MATCH_W3=20  MATCH_W4=15
  MATCH_THRESHOLD=80  TIME_DECAY_TAU_DAYS=3
  DEFAULT_REGION_CODE=510107
  IM_RETENTION_DAYS=7  AUDIT_RETENTION_DAYS=365
  IMG_MAX_COUNT=9  IMG_MAX_SIZE_MB=10  IMG_STORAGE=local|minio|oss
  ```
- 部署配置：`deploy/` 下 `docker-compose.yml` / `nginx.conf` / `mysql/init.sql`。

---

## 6. 待明确事项清单（需用户/导师拍板）

1. **双因子形态**：登录每次都需短信码，还是仅注册/绑手机需 OTP、登录用密码？（当前设计=后者，请确认。）
2. **region_code 颗粒度**：校园是单一 6 位码，还是按校区/楼栋细分多码？影响地点层级命中与默认码（当前用文档示例 `510107`）。
3. **交接码存储双写**：Redis 活性存储（TTL）+ MySQL `handover_code` 审计镜像，是否接受双写？还是仅 Redis、审计靠 `audit_log`？
4. **信誉分建模**：`user.credit_score`（运行值）+ `trust_score_log`（流水账）是否符合预期？是否需独立 `trust_score` 表而非日志？
5. **YOLO-World 部署**：与 YOLOv8n 同 Flask 服务内双路，还是独立服务？提示词库由谁维护（config / 管理后台）？
6. **权重/阈值初值**：`w1..w4=40/25/20/15`、`τ=3d`、阈值 80 仅为初值，需验证集实验定稿（论文须给 PR/混淆矩阵依据）。
7. **短信服务**：供应商 + 限流/防爆破策略（当前 Redis 计数 + 60s 重发间隔）。
8. **图片存储**：本地磁盘 / MinIO / 云 OSS？`images` 存 URL，需定存储后端与回源。
9. **WebSocket 匿名与鉴权**：持 JWT 入会话但不泄露手机号/真名；双方身份用 `sender_role` 映射，是否需端到端加密（当前明文经 TLS）。
10. **审计归档**：365 天迁 `audit_log_cold` 的触发方式（定时任务/事件）与冷表查询授权流程。
11. **管理员初始账号**：首个注册转管理员、还是 `admin/seed` 脚本/接口创建？
12. **IM 7 天清理 vs 审计 365 天**：IM 物理删除（不可溯）与审计黑匣子（365 天）分离是否接受？争议溯源是否需保留 IM 摘要入 `audit_log`？
13. **分页/排序默认**：默认 `page_size=20`、上限 100，匹配列表按 `score` 降序——是否需用户自定义排序维度？
14. **多图/大图约束**：上传 ≤9 张、单图 ≤10MB、是否服务端压缩/缩略图（影响存储与展示）。

---

## 附：图表（另存于同目录 .mermaid 文件）
- 类图：`class-diagram.mermaid`
- 时序图（发布→打标→匹配→认领→交接）：`sequence-diagram.mermaid`
