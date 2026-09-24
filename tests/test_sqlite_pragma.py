"""v17 任务②：SQLite PRAGMA 调优单测（WAL + busy_timeout + synchronous）。

应用每个 SQLite 连接建立时由 ``app.core.database`` 的 connect 事件监听器统一设置：
- ``journal_mode=WAL``：读写不互斥（写不再被读阻塞，读不再阻塞写）；
- ``busy_timeout=5000``：写冲突时等待而非立即报 database is locked（**必须配 WAL**，
  否则并发写照样秒锁死——WAL 只解决读写互斥，不解决写写互斥）；
- ``synchronous=NORMAL``：WAL 下的推荐档位（掉电最多丢最后事务，不损库完整性）。

MySQL 路径（生产候选）不加 PRAGMA，由 MySQL 自身 innodb 配置管——该分支无法在
SQLite 单测里直测，CI 的 MySQL 实连用例只验证「连接监听器对 MySQL 不报错」。
"""
from __future__ import annotations

from sqlalchemy import text

from app.core.database import engine


def test_sqlite_wal_enabled_on_new_connections():
    if not engine.url.drivername.startswith("sqlite"):
        return  # MySQL 环境（CI service container）跳过
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert str(mode).lower() == "wal", f"journal_mode 应为 wal，实际 {mode}"


def test_sqlite_busy_timeout_5000():
    if not engine.url.drivername.startswith("sqlite"):
        return
    with engine.connect() as conn:
        ms = conn.execute(text("PRAGMA busy_timeout")).scalar()
        assert int(ms) == 5000, f"busy_timeout 应为 5000ms，实际 {ms}"


def test_sqlite_synchronous_normal():
    if not engine.url.drivername.startswith("sqlite"):
        return
    with engine.connect() as conn:
        # 0=OFF 1=NORMAL 2=FULL 3=EXTRA
        level = conn.execute(text("PRAGMA synchronous")).scalar()
        assert int(level) == 1, f"synchronous 应为 NORMAL(1)，实际 {level}"
