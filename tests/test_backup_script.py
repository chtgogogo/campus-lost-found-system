"""v20② 备份脚本测试（2026-09-28）。

覆盖：SQLite 在线备份一致性（行数对齐）、uploads 打包含文件、
keep 轮转删旧留新、keep 下限保护、WAL 活库备份一致性。
"""
from __future__ import annotations

import sqlite3
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.backup import run_backup


def _make_db(path: Path, rows: int) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);"
        f"INSERT INTO t (v) VALUES {','.join(f"('row{i}')" for i in range(rows))}"
    )
    conn.commit()
    conn.close()


def test_sqlite_backup_consistent(tmp_path):
    db = tmp_path / "dev.db"
    _make_db(db, 5)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "a.png").write_bytes(b"\x89PNG fake")

    result = run_backup(f"sqlite:///{db}", uploads, tmp_path / "backups", keep=10)

    backup_files = [f for f in result["files"] if f["path"].endswith(".db")]
    assert len(backup_files) == 1
    conn = sqlite3.connect(backup_files[0]["path"])
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 5
    conn.close()


def test_uploads_tarball_contains_files(tmp_path):
    db = tmp_path / "dev.db"
    _make_db(db, 1)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "x.png").write_bytes(b"img1")
    (uploads / "sub").mkdir()
    (uploads / "sub" / "y.png").write_bytes(b"img2")

    result = run_backup(f"sqlite:///{db}", uploads, tmp_path / "out", keep=10)
    tar_path = next(f["path"] for f in result["files"] if f["path"].endswith(".tar.gz"))
    with tarfile.open(tar_path) as tar:
        names = tar.getnames()
    assert "x.png" in names and "sub/y.png" in names


def test_rotate_keeps_newest(tmp_path):
    db = tmp_path / "dev.db"
    _make_db(db, 1)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "a.png").write_bytes(b"x")

    run_backup(f"sqlite:///{db}", uploads, tmp_path / "bk", keep=1)
    time.sleep(1.1)  # 文件名精确到秒，隔开两份
    result = run_backup(f"sqlite:///{db}", uploads, tmp_path / "bk", keep=1)

    assert result["removed"], "第二次备份应触发轮转删除"
    remaining = list((tmp_path / "bk").glob("backup-*.db"))
    assert len(remaining) == 1, "keep=1 只留最新一份"
    # 剩下的是第二次的（更新、行数一致）
    conn = sqlite3.connect(str(remaining[0]))
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    conn.close()


def test_keep_floor_never_wipes(tmp_path):
    db = tmp_path / "dev.db"
    _make_db(db, 1)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    result = run_backup(f"sqlite:///{db}", uploads, tmp_path / "bk", keep=0)
    assert any(f["path"].endswith(".db") for f in result["files"])
    assert len(list((tmp_path / "bk").glob("backup-*.db"))) == 1


def test_wal_mode_live_backup(tmp_path):
    """模拟生产：源库开 WAL 且有未 checkpoint 内容，备份仍一致。"""
    db = tmp_path / "dev.db"
    _make_db(db, 2)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("INSERT INTO t (v) VALUES ('wal-row')")  # 写入尚未 checkpoint
    conn.commit()

    result = run_backup(f"sqlite:///{db}", tmp_path / "empty_uploads", tmp_path / "bk", keep=5)
    conn.close()
    backup = next(f["path"] for f in result["files"] if f["path"].endswith(".db"))
    conn = sqlite3.connect(backup)
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    conn.close()
