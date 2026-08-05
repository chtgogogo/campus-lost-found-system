"""v7 增量迁移测试：0004 幂等 + 存量回填。

- 全新库 ``upgrade head`` → ``0004_v7_incremental``，列/索引齐全
- 重复 ``upgrade head`` 幂等（列/索引已存在时跳过，不报错）
- 存量回填：``expires_at = created_at + 90天``（对已置 NULL 的行经幂等重跑触发）
"""
from __future__ import annotations

import gc
import os
import sys
import uuid
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, insert, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models import FoundItem, LostItem, User  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_upgrade(db_url: str, target: str) -> None:
    """在隔离临时库上运行 alembic（重定向 settings.DATABASE_URL，避免污染测试库）。"""
    saved = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = db_url
        cfg = Config(os.path.join(_ROOT, "migrations", "alembic.ini"))
        command.upgrade(cfg, target)
    finally:
        settings.DATABASE_URL = saved


def _run_downgrade(db_url: str, target: str) -> None:
    """在隔离临时库上运行 alembic downgrade（重定向 settings.DATABASE_URL，避免污染测试库）。"""
    saved = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = db_url
        cfg = Config(os.path.join(_ROOT, "migrations", "alembic.ini"))
        command.downgrade(cfg, target)
    finally:
        settings.DATABASE_URL = saved


def _columns(engine: object, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _indexes(engine: object, table: str) -> set[str]:
    return {i["name"] for i in inspect(engine).get_indexes(table)}


def _tmp_db_path() -> str:
    """v7：在仓库 tests/ 目录（E: 盘）生成一次性迁移校验库，规避系统临时目录（C: 盘）写入受限。"""
    p = os.path.join(_ROOT, "tests", f"_tmp_migrate_{uuid.uuid4().hex}.db")
    try:
        if os.path.exists(p):
            os.remove(p)
    except OSError:  # 上轮遗留文件被锁时忽略，UUID 保证不冲突
        pass
    return p


def test_upgrade_head_creates_0004_columns_and_indexes():
    tmp_name = _tmp_db_path()
    db_url = f"sqlite:///{tmp_name}"
    try:
        _run_upgrade(db_url, "head")
        engine = create_engine(db_url)

        cols_lost = _columns(engine, "lost_item")
        cols_found = _columns(engine, "found_item")
        cols_match = _columns(engine, "match_record")
        for c in ("expires_at", "deleted_at"):
            assert c in cols_lost, f"lost_item 缺少列 {c}"
            assert c in cols_found, f"found_item 缺少列 {c}"
        assert "completed_at" in cols_match, "match_record 缺少列 completed_at"
        # v8 新增列（0005_v8_match）：外观/特征/地点自由文本，用于六维匹配
        for c in ("appearance", "features", "location"):
            assert c in cols_lost, f"lost_item 缺少 v8 列 {c}"
            assert c in cols_found, f"found_item 缺少 v8 列 {c}"
        # flow-v2 新增列（0006_flow_v2）：keep1 单边完成标记
        assert "flow_type" in cols_match, "match_record 缺少 flow-v2 列 flow_type"

        idx_lost = _indexes(engine, "lost_item")
        idx_found = _indexes(engine, "found_item")
        idx_match = _indexes(engine, "match_record")
        assert {"idx_lost_expires", "idx_lost_deleted"}.issubset(idx_lost)
        assert {"idx_found_expires", "idx_found_deleted"}.issubset(idx_found)
        assert "idx_match_completed" in idx_match

        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert ver == "0006_flow_v2"
    finally:
        try:
            engine.dispose()
        except Exception:
            pass
        try:
            gc.collect()
        except Exception:
            pass
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:  # 沙箱 shim 拦截删除时忽略，不影响断言结果
            pass


def test_upgrade_idempotent_rerun():
    tmp_name = _tmp_db_path()
    db_url = f"sqlite:///{tmp_name}"
    try:
        _run_upgrade(db_url, "head")
        # 再次 upgrade head 应幂等（列/索引已存在被跳过），不报错
        _run_upgrade(db_url, "head")
        engine = create_engine(db_url)
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert ver == "0006_flow_v2"
        assert "expires_at" in _columns(engine, "lost_item")
        assert "flow_type" in _columns(engine, "match_record")
    finally:
        try:
            engine.dispose()
        except Exception:
            pass
        try:
            gc.collect()
        except Exception:
            pass
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:  # 沙箱 shim 拦截删除时忽略，不影响断言结果
            pass


def test_backfill_sets_expires_at_from_created_at():
    tmp_name = _tmp_db_path()
    db_url = f"sqlite:///{tmp_name}"
    try:
        _run_upgrade(db_url, "head")
        engine = create_engine(db_url)

        # 在 head schema 下写入一条 expires_at=NULL 的存量行：raw SQL 显式置 NULL，
        # 绕过 ORM 端默认 default=lambda: utcnow()+90d（该默认会在 ORM flush 的 None 上触发）。
        # 模拟 0003→0004 迁移前的历史数据。
        with engine.begin() as conn:
            res = conn.execute(
                insert(User).values(
                    student_no="backfill_stu",
                    phone="13800000099",
                    password_hash="x",
                    role=0,
                )
            )
            uid = res.inserted_primary_key[0]
            conn.execute(
                text(
                    "INSERT INTO lost_item "
                    "(publisher_id, category_name, title, description, lost_time, status, created_at, expires_at) "
                    "VALUES (:pid, :cat, :title, :desc, :lt, 0, :ca, NULL)"
                ),
                {
                    "pid": uid,
                    "cat": "水杯",
                    "title": "回填测试失物",
                    "desc": "desc",
                    "lt": "2025-01-01 00:00:00",
                    "ca": "2025-01-01 00:00:00",
                },
            )

        # 与迁移 0004 upgrade() 完全一致的回填语句：expires_at = created_at + 90 天
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE lost_item SET expires_at = datetime(created_at, '+90 days') "
                    "WHERE expires_at IS NULL"
                )
            )

        Session = sessionmaker(bind=engine)
        with Session() as s:
            row = s.query(LostItem).filter(LostItem.title == "回填测试失物").one()
            assert row.expires_at is not None
            # SQLite datetime(created_at,'+90 days') → 2025-04-01 00:00:00
            assert row.expires_at.strftime("%Y-%m-%d %H:%M:%S") == "2025-04-01 00:00:00"
    finally:
        try:
            engine.dispose()
        except Exception:
            pass
        try:
            gc.collect()
        except Exception:
            pass
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:  # 沙箱 shim 拦截删除时忽略，不影响断言结果
            pass


def test_downgrade_removes_0004_columns_and_indexes():
    """迁移可双向往返（幂等稳健 + 可回滚）。

    flow-v2：``alembic upgrade head``（至 0006）后 ``alembic downgrade 0004_v7_incremental``
    回退到 0004，移除 v8（appearance/features/location）与 flow-v2（flow_type）新增列；
    v7 的 expires_at/deleted_at/completed_at 与其索引在 0004 仍保留。验证迁移往返正确。
    """
    tmp_name = _tmp_db_path()
    db_url = f"sqlite:///{tmp_name}"
    try:
        _run_upgrade(db_url, "head")
        _run_downgrade(db_url, "0004_v7_incremental")
        engine = create_engine(db_url)

        cols_lost = _columns(engine, "lost_item")
        cols_found = _columns(engine, "found_item")
        cols_match = _columns(engine, "match_record")
        # v8 列应被移除
        for c in ("appearance", "features", "location"):
            assert c not in cols_lost, f"downgrade 后 lost_item 残留 v8 列 {c}"
            assert c not in cols_found, f"downgrade 后 found_item 残留 v8 列 {c}"
        # flow-v2 列应被移除
        assert "flow_type" not in cols_match, "downgrade 后 match_record 残留 flow_type"
        # v7 列应保留（0004 仍生效）
        for c in ("expires_at", "deleted_at"):
            assert c in cols_lost, f"downgrade 后 lost_item 应保留列 {c}"
            assert c in cols_found, f"downgrade 后 found_item 应保留列 {c}"
        assert "completed_at" in cols_match, "downgrade 后 match_record 应保留列 completed_at"

        idx_lost = _indexes(engine, "lost_item")
        idx_found = _indexes(engine, "found_item")
        idx_match = _indexes(engine, "match_record")
        assert "idx_lost_expires" in idx_lost
        assert "idx_lost_deleted" in idx_lost
        assert "idx_found_expires" in idx_found
        assert "idx_found_deleted" in idx_found
        assert "idx_match_completed" in idx_match

        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert ver == "0004_v7_incremental", f"downgrade 后版本应为 0004_v7_incremental，实际 {ver}"
    finally:
        try:
            engine.dispose()
        except Exception:
            pass
        try:
            gc.collect()
        except Exception:
            pass
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:  # 沙箱 shim 拦截删除时忽略，不影响断言结果
            pass
