# 校园失物招领智能匹配系统

基于 YOLOv8 视觉识别、CLIP 图像语义匹配和六维加权打分算法的校园失物招领 Web 应用。
失主和拾主分别发布失物/拾物信息，系统自动识别物品类别、提取属性，并通过智能匹配引擎把「丢失的物品」和「捡到的物品」自动撮合。

## 技术栈

- 后端：FastAPI + SQLAlchemy 2.x + Pydantic
- 数据库：SQLite（开发）/ MySQL 8.0（生产）
- 视觉识别：Ultralytics YOLOv8 + CLIP
- 智能匹配：六维加权打分 + 语义扩展 + 时间衰减
- 前端：Vue 3 + Vite + TypeScript + Element Plus + Pinia
- 部署：Docker / docker-compose
- 测试：pytest（覆盖认证、发布、匹配、视觉、审计、管理端等模块）

## 核心功能

- 用户注册 / 登录 / JWT 鉴权
- 失物与拾物发布（支持图片上传）
- YOLOv8 物品分类与 CLIP 跨模态图像相似度
- 六维加权智能匹配：照片一致性、颜色、数量、地点、状态、关键词、时间衰减
- 站内信沟通
- 动态交接码 + 二维码 + GPS 防冒领
- 操作审计与导出
- 管理后台
- 演示模式：前端无后端也可通过 mock 数据运行

## 架构简图

`	ext
Vue3 前端
  │ HTTP /api/v1/*
  ▼
FastAPI 后端
  ├─ routers（接口层）
  ├─ services（业务层：发布、匹配、视觉、交接、审计）
  ├─ schemas（Pydantic 校验）
  ├─ models（SQLAlchemy 数据模型）
  └─ core（配置、数据库、安全、Redis/内存兜底）
        │
        ├─ SQLite / MySQL
        ├─ YOLOv8 + CLIP 模型
        └─ Redis / 内存缓存
`

## 本地运行

### 后端

`ash
cd 失物招领系统
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
`

### 前端

`ash
cd web
npm install
npm run dev
`

### 测试

`ash
pytest
`

## 说明

本项目使用 AI Coding Agent 辅助开发与迭代，项目结构、接口设计和测试体系均按真实工程标准组织。
