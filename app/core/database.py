"""数据库引擎、会话与声明式基类。

- dev 默认 SQLite（`sqlite:///./dev.db`，项目根，E 盘）。
- 生产切换 `mysql+asyncmy/pymysql://...`（见 §5.6）。
- 提供 `Base`（模型基类）、`engine`、`SessionLocal` 与 `get_db` 依赖。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Session,
    sessionmaker,
)

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""

    pass


# SQLite 需启用外键约束 + 单连接写（开发兜底）
_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    future=True,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：提供请求级数据库会话，自动关闭。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """开发期建表（create_all）。

    生产环境应使用 `migrations/` 下的 Alembic 迁移；此处仅用于本地快速跑通。
    """
    # 导入所有模型，确保已注册到 Base.metadata
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
