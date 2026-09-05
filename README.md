# 失物招领 · 智能匹配系统

> 让「丢东西的人」和「捡到东西的人」不再靠人工翻帖子：机器看懂物品长什么样，再用一套可解释的规则把两边自动撮合起来。

一个面向失物/拾物场景的智能匹配 Web 应用。后端 FastAPI，前端 Vue 3 + TypeScript，视觉层用 YOLOv8 做物品识别、CLIP 做图像语义匹配，再叠加七维加权打分引擎完成自动撮合。

---

## 它解决什么

传统失物招领靠人工发帖、人工比对，效率低、易漏配、还容易被冒领。这个项目把「发布 → 识别 → 匹配 → 沟通 → 交接」整条链路数字化：图片自动识别物品类别与属性，匹配引擎综合照片一致性、颜色、数量、地点、状态、关键词与时间衰减给出可解释的匹配分，交接环节用动态交接码 + 二维码 + GPS 防冒领。

## 核心能力

| 模块 | 说明 |
|------|------|
| 视觉识别 | YOLOv8 物品分类 + CLIP 跨模态图像相似度 |
| 智能匹配 | 七维加权打分（照片/颜色/数量/地点/状态/关键词/时间衰减）+ 语义扩展 |
| 用户体系 | 注册/登录/JWT 鉴权 |
| 沟通 | 站内信，失主拾主直接联系 |
| 安全交接 | 动态交接码 + 二维码 + GPS 防冒领 |
| 治理 | 操作审计与导出、管理后台 |
| 演示模式 | 前端无后端也可用 mock 数据运行 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy 2.x + Pydantic |
| 数据库 | SQLite（开发）/ MySQL 8.0（生产） |
| 视觉 | Ultralytics YOLOv8 + CLIP |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus + Pinia |
| 部署 | Docker / docker-compose |
| 测试 | pytest（认证/发布/匹配/视觉/审计/管理端） |

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

1. 发布时上传图片 → YOLOv8 识别物品类别 → 提取颜色、数量、品牌等属性。
2. CLIP 计算「失物图」与「拾物图」的语义相似度。
3. 七维加权：照片一致性、颜色、数量、地点、状态、关键词 + 时间衰减，输出可解释的匹配分。
4. 超过阈值自动进入候选，双方站内信沟通、动态交接码完成安全交接。

## 项目结构

```
├── app/           # FastAPI 后端（core/models/schemas/routers/services/utils）
├── web/           # Vue3 前端（views/components/api/stores）
├── migrations/    # 数据库迁移
├── tests/         # pytest 测试
├── docs/          # 系统设计、流程图、迭代 PRD
├── deploy/        # 部署相关
└── docker-compose.yml
```

## 说明

本项目采用 AI Coding Agent 辅助开发与迭代，项目结构、接口设计与测试体系均按真实工程标准组织。

## 许可证

仓库暂未附 LICENSE 文件；如需公开分发，建议补充 MIT 协议。
