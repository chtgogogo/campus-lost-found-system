"""SQLite 存量数据迁移（增量设计 v2）。

变更目标（对齐 `app/models/item.py` 新 schema）：
  1. 删除 `region_code` 列（校区字段全清）。
  2. `category_id` 改为可空（仅作内部匹配键）。
  3. 新增 `category_name` 列（纯自由文本分类，必填），从 `category.name` 回填。

可复跑（幂等）：每步前用 `PRAGMA table_info` 判断列是否存在，已迁移则跳过。

迁移路径：
  - sqlite >= 3.35：直接 `ALTER TABLE ... DROP COLUMN` + `ADD COLUMN` + `UPDATE` 回填。
  - sqlite <  3.35：建新表（去 region_code、加 category_name、category_id 可空）
    → 搬数据（region_code 丢弃，category_name 取 Category.name 或 ''）
    → 删旧表 → 改名 → 重建索引。

快捷替代：直接删除 `dev.db` 后执行 `python scripts/seed.py` 即可按新 schema 重建（等效）。
"""
from __future__ import annotations

import os
import sqlite3
import sys

# 将项目根加入 sys.path，便于按 DATABASE_URL 解析 db 路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.core.config import settings  # noqa: E402

TABLES = ("lost_item", "found_item")


def _resolve_db_path() -> str:
    """从 DATABASE_URL 解析 sqlite 库文件路径（回退到项目根 dev.db）。"""
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        # sqlite:///./dev.db 或 sqlite:////abs/path
        rel = url[len("sqlite:///"):]
        if rel.startswith("/"):
            return rel
        return os.path.join(BASE_DIR, rel.lstrip("./"))
    if url.startswith("sqlite://"):
        return os.path.join(BASE_DIR, url[len("sqlite://"):])
    return os.path.join(BASE_DIR, "dev.db")


def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # PRAGMA 列顺序：cid, name, type, notnull, dflt_value, pk
    return any(r[1] == col for r in rows)


def _indexes_referencing(conn: sqlite3.Connection, table: str, col: str) -> list[str]:
    """返回 table 上引用了 col 的全部索引名（动态探测，避免硬编码索引名差异）。"""
    names: list[str] = []
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        idx_name = row[1]
        for info in conn.execute(f"PRAGMA index_info({idx_name})").fetchall():
            if info[2] == col:
                names.append(idx_name)
                break
    return names


def _migrate_drop_column(conn: sqlite3.Connection, table: str) -> list[str]:
    """sqlite >= 3.35：原地 DROP COLUMN + ADD COLUMN + 回填。"""
    log: list[str] = []
    prefix = table.split("_")[0]  # lost_item -> lost ; found_item -> found
    new_index = f"idx_{prefix}_cat_status"

    # 先删引用 region_code 的旧索引（其定义含 region_code 列，否则 DROP COLUMN 报错），
    # 动态探测，避免硬编码索引名与实际不符。
    for idx in _indexes_referencing(conn, table, "region_code"):
        conn.execute(f"DROP INDEX IF EXISTS {idx}")
        log.append(f"[{table}] DROP INDEX {idx} (refs region_code)")

    if _column_exists(conn, table, "region_code"):
        conn.execute(f"ALTER TABLE {table} DROP COLUMN region_code")
        log.append(f"[{table}] DROP COLUMN region_code")

    if not _column_exists(conn, table, "category_name"):
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN category_name VARCHAR(100) NOT NULL DEFAULT ''"
        )
        log.append(f"[{table}] ADD COLUMN category_name")
        conn.execute(
            f"UPDATE {table} "
            f"SET category_name = COALESCE("
            f"(SELECT name FROM category WHERE category.id = {table}.category_id), '') "
            f"WHERE category_id IS NOT NULL"
        )
        log.append(f"[{table}] backfill category_name from category.name")

    conn.execute(f"DROP INDEX IF EXISTS {new_index}")
    conn.execute(f"CREATE INDEX {new_index} ON {table} (category_id, status)")
    return log


def _migrate_recreate(conn: sqlite3.Connection, table: str) -> list[str]:
    """sqlite < 3.35：建新表 → 搬数据 → 改名。"""
    log: list[str] = []
    new_table = f"{table}_new"
    new_index = f"idx_{table}_cat_status"
    old_index = f"idx_{table}_cat_status_region"

    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # 构造新表列定义（去 region_code；category_id 改可空；加 category_name）
    col_defs: list[str] = []
    select_cols: list[str] = []
    for cid, name, ctype, notnull, dflt, pk in cols:
        if name == "region_code":
            continue
        if name == "category_id":
            col_defs.append(f"{name} {ctype}")
            select_cols.append(name)
            continue
        flags = " PRIMARY KEY AUTOINCREMENT" if pk else ""
        notnull_flag = " NOT NULL" if (notnull and not pk) else ""
        dflt_flag = f" DEFAULT {dflt}" if dflt is not None else ""
        col_defs.append(f"{name} {ctype}{notnull_flag}{dflt_flag}{flags}")
        select_cols.append(name)
    # 追加 category_name
    col_defs.append("category_name VARCHAR(100) NOT NULL DEFAULT ''")
    select_cols.append(
        "COALESCE((SELECT name FROM category WHERE category.id = "
        f"{table}.category_id), '')"
    )

    conn.execute(f"DROP TABLE IF EXISTS {new_table}")
    conn.execute(f"CREATE TABLE {new_table} ({', '.join(col_defs)})")
    # 重新组装：原列 + 计算列
    orig_cols = [c for c in select_cols[:-1]]
    computed = select_cols[-1]
    conn.execute(
        f"INSERT INTO {new_table} ({', '.join(orig_cols)}, category_name) "
        f"SELECT {', '.join(orig_cols)}, {computed} FROM {table}"
    )
    log.append(f"[{table}] recreated with category_name, region_code dropped")

    conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(f"ALTER TABLE {new_table} RENAME TO {table}")
    conn.execute(f"DROP INDEX IF EXISTS {old_index}")
    conn.execute(f"DROP INDEX IF EXISTS {new_index}")
    conn.execute(f"CREATE INDEX {new_index} ON {table} (category_id, status)")
    return log


def migrate() -> None:
    db_path = _resolve_db_path()
    print(f"[migrate_v2] target db: {db_path}")
    if not os.path.exists(db_path):
        print("[migrate_v2] db 不存在，无需迁移（可直接 python scripts/seed.py 初始化）。")
        return

    version = sqlite3.sqlite_version_info
    print(f"[migrate_v2] sqlite_version = {sqlite3.sqlite_version}")
    use_drop = version >= (3, 35, 0)

    conn = sqlite3.connect(db_path)
    # 开启自动提交，避免 DDL（DROP INDEX / DROP COLUMN）被隐式事务回滚
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        all_log: list[str] = []
        for table in TABLES:
            # 幂等：category_name 已存在且无 region_code 则视为已完成
            if _column_exists(conn, table, "category_name") and not _column_exists(
                conn, table, "region_code"
            ):
                print(f"[migrate_v2] {table} 已迁移，跳过。")
                continue
            if use_drop:
                all_log += _migrate_drop_column(conn, table)
            else:
                all_log += _migrate_recreate(conn, table)
        conn.commit()
        if all_log:
            print("[migrate_v2] 迁移摘要：")
            for line in all_log:
                print("  -", line)
        else:
            print("[migrate_v2] 无变更（已是最新 schema）。")
    finally:
        conn.close()

    _verify(db_path)


def _verify(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        for table in TABLES:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            has_region = "region_code" in cols
            has_name = "category_name" in cols
            print(
                f"[verify] {table}: region_code={'YES' if has_region else 'no'}, "
                f"category_name={'YES' if has_name else 'no'}"
            )
            if has_region or not has_name:
                raise SystemExit(f"[verify] FAILED: {table} schema 未达预期")
        print("[verify] OK：所有表已去除 region_code 且含 category_name。")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
