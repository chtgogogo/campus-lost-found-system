"""数据库测试：MySQL init_db 建表数 + scripts/seed.py 幂等性。

A) test_mysql_init_db_creates_10_tables
   - 连接本机 MySQL（root 空密码，127.0.0.1:3306），建专用测试库；
   - Base.metadata.create_all 后断言存在 10 张表；
   - 结束后 DROP 测试库，保持环境干净；MySQL 不可用时自动 skip。

B) test_seed_idempotency
   - 对 scripts/seed.py 的 seed_categories / seed_admin / seed_demo_users /
     seed_demo_items 各跑两次，断言行数稳定（幂等）。
"""
from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import create_engine, inspect

from app.core.database import Base

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))  # 项目根（scripts 位于此）

MYSQL_TEST_DB = "lostfound_qa_pytest"
# 候选凭据：优先 root 空密码（开发默认），其次 .env.example 中的 lf/lf
_MYSQL_CREDS = [
    ("root", ""),
    ("lf", "lf"),
    ("root", "root"),
]
EXPECTED_TABLES = [
    "user",
    "category",
    "lost_item",
    "found_item",
    "match_record",
    "handover_code",
    "audit_log",
    "im_session",
    "im_message",
    "trust_score_log",
    # v11（2026-08-27）：数据飞轮——用户纠错样本表
    "correction_sample",
]


def _mysql_root_connect():
    """尝试候选凭据连接本机 MySQL，返回首个可用的连接。"""
    import pymysql

    last_err = None
    for user, pwd in _MYSQL_CREDS:
        try:
            return pymysql.connect(
                host="127.0.0.1", port=3306, user=user, password=pwd, connect_timeout=3
            )
        except Exception as e:  # 换下一组凭据重试
            last_err = e
    if last_err:
        raise last_err
    raise RuntimeError("no mysql credentials configured")


def _mysql_available() -> bool:
    try:
        c = _mysql_root_connect()
        c.close()
        return True
    except Exception:
        return False


def test_metadata_registers_10_tables():
    """不依赖真实 MySQL：Base.metadata 即 create_all 的建表依据，断言恰好 11 张表。

    即便本机 MySQL 因鉴权/未启动而跳过，也能保证“11 张表”这一目标本身被覆盖。
    """
    assert len(Base.metadata.tables) == 11, (
        f"期望 11 张表，实际 {len(Base.metadata.tables)}: "
        f"{sorted(Base.metadata.tables.keys())}"
    )
    for expected in EXPECTED_TABLES:
        assert expected in Base.metadata.tables, f"缺少表 {expected}"


@pytest.mark.skipif(not _mysql_available(), reason="本地 MySQL 不可用（root 空密码 / lf/lf 均无法连接 127.0.0.1:3306）")
def test_mysql_init_db_creates_10_tables():
    # 选用首个可用的凭据，保证 create_all 用的是同一组可连接凭据
    import pymysql

    user, pwd = _MYSQL_CREDS[0]
    for u, p in _MYSQL_CREDS:
        try:
            pymysql.connect(host="127.0.0.1", port=3306, user=u, password=p, connect_timeout=3)
            user, pwd = u, p
            break
        except Exception:
            continue
    url = f"mysql+pymysql://{user}:{pwd}@127.0.0.1:3306/{MYSQL_TEST_DB}?charset=utf8mb4"

    root = _mysql_root_connect()
    try:
        cur = root.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {MYSQL_TEST_DB}")
        cur.execute(f"CREATE DATABASE {MYSQL_TEST_DB} CHARACTER SET utf8mb4")
        root.commit()
    finally:
        root.close()

    engine = create_engine(url, pool_pre_ping=True)
    try:
        Base.metadata.create_all(bind=engine)
        table_names = inspect(engine).get_table_names()
        assert len(table_names) == 11, (
            f"期望 11 张表，实际 {len(table_names)}: {table_names}"
        )
        for expected in EXPECTED_TABLES:
            assert expected in table_names, f"缺少表 {expected}"
    finally:
        root2 = _mysql_root_connect()
        try:
            cur2 = root2.cursor()
            cur2.execute(f"DROP DATABASE IF EXISTS {MYSQL_TEST_DB}")
            root2.commit()
        finally:
            root2.close()
        engine.dispose()


def test_seed_idempotency(db):
    from app.core.seed import seed_admin, seed_categories
    from app.models.category import Category
    from app.models.item import FoundItem, LostItem
    from app.models.user import User
    from scripts.seed import seed_demo_items, seed_demo_users

    n1 = seed_categories(db)
    seed_admin(db, "admin001", "13900000000", "admin123456")
    users1 = seed_demo_users(db)
    items1 = seed_demo_items(db)
    db.commit()

    n2 = seed_categories(db)
    seed_admin(db, "admin001", "13900000000", "admin123456")
    users2 = seed_demo_users(db)
    items2 = seed_demo_items(db)
    db.commit()

    # 分类已存在 → 两次均返回 0（幂等跳过），实跑 12 条稳定
    assert n1 == 0 and n2 == 0
    assert db.query(Category).count() == 12
    # 演示用户：首次创建 2，二次跳过 0
    assert len(users1) == 2 and len(users2) == 0
    # 演示物品：首次 5，二次 0
    assert items1 == 5 and items2 == 0
    # 实跑行数稳定（不受重复执行影响）
    assert db.query(User).filter(
        User.student_no.in_(["demo_loser", "demo_finder"])
    ).count() == 2
    assert db.query(LostItem).filter(
        LostItem.description.like("%DEMO_SEED%")
    ).count() == 2
    assert db.query(FoundItem).filter(
        FoundItem.description.like("%DEMO_SEED%")
    ).count() == 3
