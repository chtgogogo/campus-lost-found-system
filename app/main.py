"""FastAPI 应用工厂。

- CORS 中间件（开发期放行全部来源）。
- 装配路由：auth / items / match / vision / admin。
- 统一异常处理器。
- 静态资源：/uploads 映射本地上传目录。
- lifespan：建表 + 自动 seed 分类 + 预热进程内视觉服务单例（唯一加载点）。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.body_limit import RequestBodyLimitMiddleware
from app.core.config import settings, validate_security_config
from app.core.database import SessionLocal, engine, init_db
from app.core.exceptions import register_exception_handlers
from app.core.observability import (
    ObservabilityMiddleware,
    StatusCaptureMiddleware,
    metrics_snapshot_safe,
    register_demo_slow_route,
    register_slow_sql_listener,
    setup_logging,
)
from app.core.seed import seed_categories, seed_demo_random_accounts
from app.routers import admin, auth, im, items, match, vision
from app.services import recognition_worker
from app.services.vision_service import get_vision_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 开发期建表（生产请用 Alembic 迁移）
    init_db()
    # 分类为空时自动 seed（保证开箱即用）
    with SessionLocal() as db:
        seed_categories(db)
        # v18：演示模式启动时确保「演示随机账号」池就绪（幂等；随机登录按钮的账号来源）
        if settings.DEMO_MODE:
            seed_demo_random_accounts(db)
    # 进程内视觉服务：唯一加载点 get_vision_service() 预热（仅此一处实例化）
    app.state.vision = get_vision_service()
    # v17④：异步识别 worker（单线程消费 recognition_task；测试套件经 conftest 显式关闭）
    if settings.RECOGNITION_WORKER_ENABLED:
        recognition_worker.start()
    yield
    if settings.RECOGNITION_WORKER_ENABLED:
        recognition_worker.stop()


def create_app() -> FastAPI:
    # 安全校验（fail fast，安检 L1-1/L1-2）：JWT_SECRET 弱默认 / 空值直接拒绝启动，
    # ADMIN_APPLY_CODE 为空时日志说明。必须先于任何路由/中间件装配。
    validate_security_config()

    # v17⑤ 可观测层：JSON/可读日志（均携带 request_id）+ 慢 SQL 监听（装配期一次性）
    setup_logging()
    register_slow_sql_listener(engine)

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="基于 YOLOv8 的校园失物招领智能匹配系统（后端）",
        lifespan=lifespan,
    )

    # 请求体大小护栏（安检 L1，2026-09-23）：Content-Length 超限直接 413
    app.add_middleware(
        RequestBodyLimitMiddleware, max_body_mb=settings.REQUEST_BODY_MAX_MB
    )

    # CORS（仅放行本地前端开发端口；生产按域名收敛）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # v17⑤ 可观测层中间件：StatusCapture（捕获状态码给指标）→ Observability（最外层，
    # 尽早设置 request_id，让全部内层日志/慢 SQL 告警携带同一条 trace id）
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(StatusCaptureMiddleware)

    # 路由装配
    app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
    app.include_router(items.router, prefix=settings.API_V1_PREFIX)
    app.include_router(match.router, prefix=settings.API_V1_PREFIX)
    app.include_router(vision.router, prefix=settings.API_V1_PREFIX)
    app.include_router(im.router, prefix=settings.API_V1_PREFIX)
    app.include_router(admin.router, prefix=settings.API_V1_PREFIX)

    # 静态资源（上传图片）
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

    # 统一异常处理器
    register_exception_handlers(app)

    @app.get("/health", tags=["meta"])
    def health():
        return {"code": 0, "message": "ok", "data": {"app": settings.APP_NAME}}

    @app.get("/metrics", tags=["meta"])
    def metrics_endpoint():
        """v17⑤ 自研进程内指标：按路由聚合 QPS / p95 / 错误率（零外部依赖）。"""
        return {"code": 0, "message": "ok", "data": metrics_snapshot_safe()}

    if settings.OBS_DEMO_ENDPOINT:
        # 演示端点（默认关闭）：人为慢接口 + 慢 SQL，展示 request_id 全链路定位。
        register_demo_slow_route(app)

    return app


app = create_app()
