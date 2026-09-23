# 后端镜像：Python 3.12-slim + CPU 版 torch + uvicorn
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# opencv-headless 需要系统级 libGL
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# 先装 CPU 版 torch（避免拉取 CUDA 体积），再装其余依赖
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 安检 L2（卡#9，2026-09-23）：非 root 运行 —— 业务进程不持 root（最小权限基线）。
# uploads/models 为宿主机卷挂载，目标环境需保证 uid=1000 对挂载点可写（部署清单项）。
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 启动前先 seed 分类 + 演示数据，再拉起 uvicorn
CMD ["sh", "-c", "python scripts/seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
