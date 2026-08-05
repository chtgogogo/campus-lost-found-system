# 部署文档（Production Deployment Guide）

> 系统：基于 YOLOv8 的校园失物招领智能匹配系统
> 覆盖范围：依赖安装（torch/ultralytics/opencv/numpy 约 2GB，落 E 盘）→ 权重下载 → MySQL 建库（本机 9.5 / Docker）→ Redis 启用 → Docker 编排 → 前端真实 API 切换 → 端到端验证清单。
> 明确标注：**本机无 docker、无 redis 服务** 的应对方案。

---

## 0. 环境约束速览

| 项 | 现状 | 应对 |
| --- | --- | --- |
| Python 依赖未装 | venv 未装 `torch/ultralytics/opencv/numpy`（约 2GB） | 见 §1 安装，落 E 盘 venv |
| MySQL 本地有 | `/e/gongjuruanjian/MYSQL/bin/` 含 mysql/mysqld | 见 §3 本机真建库 |
| Redis 无服务 | 本机无 Redis 进程 | 见 §4：配置启用 + 内存兜底（功能不崩） |
| Docker 不可用 | 本机 `docker` 命令不存在 | 见 §5：仅交付 Dockerfile/compose，在自有机器运行 |
| 磁盘/E 盘 | 权重与上传必须落 E 盘 | `models/weights`、`uploads` 已在 config 预留，严禁 C 盘 |
| Web EXIF/GPS | 浏览器安全限制，Web 端不可行 | 降级为「用户手动选地点层级」（决策 P2-02，无代码任务） |

---

## 1. 后端依赖安装（落 E 盘）

```bash
cd E:/xuexixiangguan/pythonProject/gongcheng/失物招领系统
python -m venv .venv
.venv\Scripts\activate        # Windows；Linux/macOS: source .venv/bin/activate

# 1) 先装 CPU 版 torch（避免拉取 CUDA 体积，约省 1GB+）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 2) 安装其余依赖（含 ultralytics / opencv-headless / numpy）
pip install -r requirements.txt

# 3) 验证关键依赖
python -c "import torch, ultralytics, cv2, numpy; print('ok', torch.__version__)"
```

> 说明：`requirements.txt` 已标注 torch 使用 CPU 索引。`ultralytics` 会自动拉取 `opencv-python`/`numpy`/`pyyaml`；我们用 `opencv-python-headless` 避免 GUI 依赖。

---

## 2. 视觉权重下载（落 `models/weights/`，严禁 C 盘）

```bash
# 下载 yolov8n.pt（COCO 9 类）与 yolov8s-world.pt（YOLO-World 零样本）到 models/weights/
python scripts/download_models.py
```

- 若 `models/weights/` 已存在权重则自动跳过（可重跑）。
- 若未下载，应用启动时 `VisionService` 也会尝试自动下载（优雅降级，不阻塞启动）。
- **用户自有校园权重**：直接丢入 `models/weights/` 即可切换，无需改代码（已由 `YOLO_MODEL_DIR` 预留）。

---

## 3. 数据库：MySQL 8.0 / 9.5

### 3.1 本机真建库（推荐，可真验证）

```bash
# 1) 试连（若已运行可跳过初始化）
E:\gongjuruanjian\MYSQL\bin\mysql.exe -h127.0.0.1 -P3306 -uroot -e "select 1"
```

若连接被拒，初始化并启动（数据目录选 E 盘某空目录，如 `E:/mysql-data`）：

```bash
E:\gongjuruanjian\MYSQL\bin\mysqld.exe --initialize-insecure --datadir=E:/mysql-data
E:\gongjuruanjian\MYSQL\bin\mysqld.exe --datadir=E:/mysql-data
# 另开终端建库 + 建用户
E:\gongjuruanjian\MYSQL\bin\mysql.exe -h127.0.0.1 -P3306 -uroot -e ^
  "CREATE DATABASE IF NOT EXISTS lostfound CHARACTER SET utf8mb4; ^
   CREATE USER IF NOT EXISTS 'lf'@'127.0.0.1' IDENTIFIED BY 'lf'; ^
   GRANT ALL PRIVILEGES ON lostfound.* TO 'lf'@'127.0.0.1'; FLUSH PRIVILEGES;"
```

### 3.2 配置 `.env` 切换到 MySQL

复制 `.env.example` 为 `.env`，确认：

```ini
DATABASE_URL=mysql+pymysql://lf:lf@127.0.0.1:3306/lostfound
```

### 3.3 建表（幂等 `create_all`）+ 种子

```bash
# 建 10 张表（init_db 的 create_all，幂等，可重复执行）
# 启动应用即自动建表；也可显式 seed：
python scripts/seed.py
```

`scripts/seed.py` 会：seed 12 分类 → 管理员 → 演示用户（失主/拾得者）→ 示例失物/拾物（幂等，重复运行不冲突）。

> 决策 B：本迭代使用 `create_all` 落地 MySQL（零迁移风险、本机可真验证）。`migrations/0001_initial.py`（Alembic）与 `deploy/mysql/init.sql` 仅作生产迁移/DBA 参考，非本迭代主路径。

---

## 4. Redis 启用（本机无服务 → 内存兜底）

`.env`：

```ini
REDIS_ENABLED=true
REDIS_URL=redis://127.0.0.1:6379/0
```

- 若本机有 Redis 服务：正常连接，`RedisClient.available=True`。
- 若本机无 Redis（本机现状）：`RedisClient` 自动 `available=False`，走进程内 `_MemoryStore` 兜底，**接口行为一致，功能不崩**。

Docker 部署时 compose 已带 `redis` 服务（见 §5）。

---

## 5. Docker 容器化（交付物，本机不验证）

> 本机 `docker` 命令不存在，以下文件仅作为交付物写出；请在自有机器/服务器执行 `docker compose up`。

```bash
docker compose up -d --build
# 访问：前端 http://localhost:8080 ，后端 http://localhost:8000/health
```

编排四服务：`mysql` / `redis` / `backend` / `frontend`，含网络与卷（mysql 数据、`uploads`、`models/weights` 挂载）。

- 后端 `Dockerfile`：python:3.12-slim + CPU torch + uvicorn，启动即 `seed.py` + uvicorn。
- 前端 `web/Dockerfile`：node 构建 → nginx 静态服务；`web/nginx.conf` 反代 `/api` `/uploads` `/health` 到 backend。
- 校验语法（有 docker 的机器）：`docker compose config`。

---

## 6. 前端：真实 API 优先 + 不可达降级

前端（`web/`）默认走真实后端（`getDemo()` 默认 `false`）：

- 后端可达：所有接口走真实后端（含发布页 AI 识别结果卡片）。
- 后端不可达：自动切演示模式 + 全局 Banner 提示，不白屏。
- 本地开发：`npm run dev`（vite 代理 `/api`、`/uploads`、`/health` 到 `localhost:8000`）。
- Docker 部署：`VITE_API_BASE` 保持默认 `/api/v1`，由 nginx 反代到 backend。

```bash
cd web
npm install
npm run dev        # 开发
npm run build      # 产物到 web/dist
```

### 6.1 发布页 AI 识别卡片

上传照片后前端调用 `POST /api/v1/vision/predict` 预识别，渲染「识别类别 + 置信度进度条 + 手动改类」卡片；确认或纠偏后提交发布。演示模式下由 `mockAdapter` 返回确定性占位识别。

---

## 7. 端到端验证清单

### 7.1 回归闸门（SQLite，56 绿，与 DB 无关）

```bash
# 测试环境强制 SQLite + REDIS_ENABLED=false（tests/conftest.py 已固化）
.venv/Scripts/python.exe -m pytest -q
# 期望：56 passed
```

> 关键：换真推理后仍 56 绿 —— 因为 `VisionService.predict` 永不抛异常，无权重时降级为有效活跃分类 + `confidence=0.0`。

### 7.2 MySQL 端到端（smoke.py）

以 MySQL 启动应用后运行：

```bash
# 1) 启动 API（进程内真推理预热）
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# 2) 另终端跑端到端冒烟（注册→登录→发失物(真推理打标)→反向匹配→
#     发拾物→查匹配→认领→确认归还→交接码双端验证→已解决→审计黑匣子）
.venv/Scripts/python.exe scripts/smoke.py
```

### 7.3 审计导出（P2-03）

管理员登录后访问：

```
GET /api/v1/admin/audit-logs/export?format=csv
GET /api/v1/admin/audit-logs/export?format=json
```

前端管理后台「审计日志」页提供导出按钮。

---

## 8. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 启动慢 / 首次推理慢 | 首次下载权重 / CPU 推理 | 耐心等待；或预先 `download_models.py` |
| 识别置信度恒为 0.0 | 权重缺失 / 图片无目标 | 正常降级，系统仍可用；检查 `models/weights/` |
| 发布后类别不对 | 图片特征模糊 | 发布页可手动改类（AI 卡片） |
| 连不上 MySQL | 服务未起 / 账号错 | 见 §3 启动 mysqld 并建库 |
| Redis 报错 | 本机无服务 | 正常，已内存兜底（§4） |
| 前端白屏 | 后端不可达且未降级 | 检查 `/health` 探测；应自动切演示 + Banner |

---

## 9. 后续可选增强（非本迭代范围）

- **T12 真实短信网关**：需用户提供阿里云/腾讯云短信 API Key、签名、模板；当前保留 `DEBUG` 下 `dev_code` 开发路径。
- **Alembic 生产迁移**：本迭代用 `create_all`；上生产后再补 Alembic 全量迁移并真机验证。
- **EXIF/GPS 定位**：Web 端不可行（浏览器安全限制），维持「用户手动选地点层级」；未来移动端可补。
