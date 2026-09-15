# 失物招领 · 智能匹配系统

丢东西的人和捡到东西的人，以前只能靠人工翻帖子，一张张比对。这个项目让机器先看懂物品长什么样，再用一套能解释的规则把两边撮合起来。

面向校园失物拾物场景的 Web 应用。后端 FastAPI，前端 Vue 3 + TypeScript，视觉层用 YOLOv8 做物品识别、CLIP 做图像语义匹配，再叠一层七维加权打分引擎完成自动撮合。

---

## 它解决什么

失物招领的传统做法是发帖加人工比对。效率低，容易漏配，还防不住冒领，谁都可能说"这是我的"。

这个项目把发布、识别、匹配、沟通、交接这条链路搬到了线上：上传的图片自动识别出物品类别和属性，匹配引擎综合照片一致性、颜色、数量、地点、状态、关键词和时间衰减给出一个可解释的匹配分，交接环节用动态交接码加二维码做防冒领。

## 核心能力

| 模块 | 说明 |
|------|------|
| 视觉识别 | YOLOv8 物品分类 + CLIP 跨模态图像相似度 |
| 智能匹配 | 七维加权打分 + 语义扩展，每一项得分都能追溯到具体依据 |
| 用户体系 | 注册 / 登录 / JWT 鉴权 |
| 沟通 | 站内信，失主和拾得者可以直接联系 |
| 安全交接 | 动态交接码 + 二维码，双码交叉验证后才允许交接 |
| 治理 | 操作审计与导出、管理后台 |
| 演示模式 | 前端不带后端也能用 mock 数据跑起来 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy 2.x + Pydantic |
| 数据库 | SQLite（开发）/ MySQL 8.0（生产） |
| 视觉 | Ultralytics YOLOv8 + CLIP |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus + Pinia |
| 部署 | Docker / docker-compose |
| 测试 | pytest（认证 / 发布 / 匹配 / 视觉 / 审计 / 管理端） |

## 架构

```
Vue3 前端
  │ HTTP /api/v1/*
  ▼
FastAPI 后端
  ├─ routers   接口层（auth / items / match / vision / im / admin）
  ├─ services  业务层（发布 / 匹配 / 视觉 / 交接 / 审计 / 站内信）
  ├─ schemas   Pydantic 校验
  ├─ models    SQLAlchemy 数据模型
  └─ core      配置 / 数据库 / 安全 / Redis 兜底
        │
        ├─ SQLite / MySQL
        ├─ YOLOv8 + CLIP
        └─ Redis / 内存缓存
```

## 本地运行

```bash
# 后端
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 前端（另开终端）
cd web
npm install
npm run dev

# 测试
pytest
```

也可以用 Docker 一键起：`docker compose up -d`。

## 匹配是怎么算的

七个维度，权重合计 100 分：

| 维度 | 权重 |
|------|------|
| 类目 | 20 |
| 颜色 | 20 |
| 数量 | 15 |
| 地点 | 15 |
| 状态 | 10 |
| 关键词 | 10 |
| 时间衰减 | 10 |

实际使用中用户往往填不全信息。所以加了动态归一化，放大系数 `k = 100 / max(已填权重和, 50)`——只填了两三个维度的时候，得分依然有区分度，不会因为信息缺失就全部挤在低分区。综合得分超过 80 分的候选会标成"疑似"，推给用户确认。

完整流程：

1. 发布时上传图片，YOLOv8 识别物品类别，再提取颜色、数量、品牌等属性
2. CLIP 计算失物图与拾物图之间的语义相似度
3. 七个维度加权求和，输出可解释的匹配分
4. 超过阈值的进入候选，双方站内信沟通，动态交接码完成交接

## 评测

`evaluation/dataset.json` 是一份人工标注的标注集，40 对样本，正例和负例各 20 对。调参时拿它跑回归，匹配 F1 从 58.8% 提到 62.9%。每轮改动前后都留了结果文件，见 `evaluation/results-v*.md`。

## 项目结构

```
├── app/           # FastAPI 后端（core/models/schemas/routers/services/utils）
├── web/           # Vue3 前端（views/components/api/stores）
├── migrations/    # 数据库迁移
├── tests/         # pytest 测试，389 个用例
├── docs/          # 系统设计、流程图、迭代 PRD
├── deploy/        # 部署相关
└── docker-compose.yml
```

## 关于开发方式

代码由 AI Coding Agent 辅助生成，需求拆解、接口设计、数据结构和评测标准由我主导。项目按真实工程标准组织：数据库走 Alembic 迁移、测试覆盖六个核心模块、CHANGELOG 记录到 v13。

## 许可证

本仓库尚未添加 LICENSE 文件，默认保留所有权利。
