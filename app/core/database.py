"""数据库引擎、会话与声明式基类。

- dev 默认 SQLite（`sqlite:///./dev.db`，项目根，E 盘）。
- 生产切换 `mysql+asyncmy/pymysql://...`（见 §5.6）。
- 提供 `Base`（模型基类）、`engine`、`SessionLocal` 与 `get_db` 依赖。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
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

if settings.DATABASE_URL.startswith("sqlite"):
    # v17 任务②（2026-09-25）：SQLite 并发三件套，逐连接生效（MySQL 生产路径跳过，
    # 由 MySQL 自身 innodb 配置管理）。压测对比数据见 docs/numbers.md。
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        # WAL：读写不互斥（写提交不再阻塞读、读不再阻塞写）。注意 WAL 只解决读写互斥，
        # 不解决写写互斥——所以必须配 busy_timeout，否则并发写照样报 database is locked。
        cursor.execute("PRAGMA journal_mode=WAL")
        # 写冲突等待 5s 再报错（值与压测口径一致；Python sqlite3 驱动默认 5s，此处显式声明防漂移）
        cursor.execute("PRAGMA busy_timeout=5000")
        # WAL 推荐档位：正常吞吐优先，掉电最多丢最后一个事务、不损库完整性
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

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
