# 部署文档（Production Deployment Guide）

> 系统：基于 YOLOv8 的校园失物招领智能匹配系统（FastAPI + Vue 3）
> 最后核对：2026-09-24（v16 / 审查 P2 后口径）。测试基线：411 用例（409 通过 / 2 跳过，CI 门禁）。
> 部署形态两种：**Docker Compose 一键起**（推荐，见 §5）或**裸机分步部署**（§1–§4）。
> 历史版本（2026-08 的本机环境快照）中机器特定路径/约束已抽象为通用流程，存档见 git 历史。

---

## 0. 组件与端口总览

| 组件 | 端口 | 说明 |
| --- | --- | --- |
| 前端（nginx 容器） | 80 | 静态资源 + 反代 `/api`、`/uploads` |
| 后端（uvicorn） | 8000 | FastAPI，`app.main:app` |
| MySQL 8.0 | 3306 | 生产库（开发可用 SQLite） |
| Redis | 6379 | 可选：JWT 吊销 / 限流 / 验证码 KV；无服务时进程内内存兜底 |

---

## 1. 后端依赖（裸机）

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate

# 1) 先装 CPU 版 torch（避免拉取 CUDA 体积，约省 1GB+；有 GPU 需求另配）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
# 2) 再装其余依赖（含锁 commit 的 CLIP）
pip install -r requirements.txt
# 3) 验证关键依赖
python -c "import torch, ultralytics, cv2, numpy; print('ok', torch.__version__)"
```

依赖说明：torch/ultralytics 仅视觉推理用，缺失时视觉服务自动降级（业务不中断）；
WordNet 语料首次使用时由 `match_service` 懒加载下载（离线环境自动回退精确匹配）。

## 2. 视觉权重（不入 git，严禁落系统盘）

```bash
python scripts/download_models.py   # 下载 yolov8s-world.pt 等；已存在自动跳过
```

```
models/weights/best.pt           # 自训 12 类校园失物 YOLO 权重（22MB，私有产物）
models/weights/yolov8s-world.pt  # YOLO-World 开放词表权重（27MB）
weights/clip/                    # CLIP 权重（首次调用自动下载 ViT-B/32）
```

- 自有校园权重直接放入 `models/weights/` 即可切换（`YOLO_MODEL_DIR` 预留）。
- 缺权重时系统照常运行：发布/预识别降级为「其他」类，CLIP 精排自动跳过。

## 3. 数据库

- 开发：SQLite（`DATABASE_URL=sqlite:///./dev.db`），零配置。
- 生产：MySQL 8.0。建库 + 迁移（Alembic 是唯一入口）：

```sql
CREATE DATABASE lostfound DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'lf'@'%' IDENTIFIED BY '<强口令>';
GRANT ALL ON lostfound.* TO 'lf'@'%';
```

```bash
PYTHONUTF8=1 alembic -c migrations/alembic.ini upgrade head
```

## 4. 环境变量

```bash
cp .env.example .env   # 逐项修改；密钥纪律见文件头注释
```

关键项（全部有启动校验，配错直接拒绝启动）：
- `JWT_SECRET`：必填随机 64 位 hex（`python -c "import secrets;print(secrets.token_hex(32))"`），留空 / `dev-` 开头 / 占位符值均拒启；
- `ADMIN_APPLY_CODE`：留空 = 管理员邀请通道禁用；启用必须强口令；
- `DATABASE_URL` / `REDIS_URL` / `SHOW_SMS_CODE=false`（公网必须）；
- `RATE_LIMIT_ENABLED=true`（默认生效，与 DEBUG 解耦）。

完整字段与语义见 `.env.example`（与 `app/core/config.py` 逐项对照，含已停用字段的标注）。

## 5. Docker Compose（推荐）

```bash
cp .env.example .env       # 按上节修改；compose 强制校验关键变量（${VAR:?} 缺省即报错）
docker compose up -d --build
```

拓扑：nginx(80) → backend(8000, 不对外) → mysql/redis（仅绑 127.0.0.1）。
健康检查、非 root 容器、`.dockerignore` 排除 `.env`/`models`/`uploads` 均已配置。

## 6. 前端

```bash
cd web
npm ci            # 按 lockfile 安装（Docker 构建同口径）
npm run build     # 产物 dist/；按需引入后主 chunk gzip ≈195KB（2026-09-24 基线）
```

`VITE_API_BASE` 默认 `/api/v1`（nginx 反代同源）；跨域部署时改为后端绝对地址并
在后端 CORS 白名单（`app/main.py`）加入前端源。

## 7. 上线验证清单

1. `curl http://<host>/health` → `{"code":0,...}`；
2. 前端登录页注册一个账号（验证码短信走日志；`SHOW_SMS_CODE=true` 的回显仅限内网调试）；
3. 发布失物 + 拾物各一 → 匹配列表出现候选（视觉降级时类目走手填，打分仍可用）；
4. 管理员 `GET /api/v1/admin/users` 确认审计已落库；
5. `docker compose logs backend` 无启动安检告警（弱密钥/占位符会直接拒启）；
6. （可选）跑通一遍交接：生成动态交接码 → 双端验证 → 状态流转至已完成。
