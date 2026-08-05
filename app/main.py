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

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.exceptions import register_exception_handlers
from app.core.seed import seed_categories
from app.routers import admin, auth, im, items, match, vision
from app.services.vision_service import get_vision_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 开发期建表（生产请用 Alembic 迁移）
    init_db()
    # 分类为空时自动 seed（保证开箱即用）
    with SessionLocal() as db:
        seed_categories(db)
    # 进程内视觉服务：唯一加载点 get_vision_service() 预热（仅此一处实例化）
    app.state.vision = get_vision_service()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="基于 YOLOv8 的校园失物招领智能匹配系统（后端）",
        lifespan=lifespan,
    )

    # CORS（开发期放行全部；生产按域名收敛）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    return app


app = create_app()
