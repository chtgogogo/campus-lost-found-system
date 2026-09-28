"""数据库与上传图片备份（v20②：此前全项目零备份，磁盘一坏数据全没）。

用法::

    .venv/Scripts/python.exe scripts/backup.py                 # 默认备份到 ./backups，保留最近 10 份
    .venv/Scripts/python.exe scripts/backup.py --keep 7 --out /data/backups

设计取舍（详见 CHANGELOG v20②）：
- SQLite 用标准库 backup API（在线备份）：不直接 copy 活库文件——WAL 模式下
  copy 可能拿到中间态；backup API 逐页拷贝并自动持锁，备份一致且不阻塞业务；
- MySQL（生产 compose 路径）调 mysqldump：密码经 MYSQL_PWD 环境变量传递，
  不进命令行（防 `ps` 泄露）；输出 gzip 压缩；
- uploads 目录打 tar.gz（增量不做，图片只增不删的场景下全量简单可靠）；
- --keep 轮转：仅按本脚本命名约定（backup-* / uploads-*）清理，不碰其他文件。
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.engine import make_url  # noqa: E402


def backup_sqlite(db_path: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)  # 在线逐页拷贝，WAL 一致性由 API 保证
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def backup_mysql(url: str, dest: Path) -> Path:
    u = make_url(url)
    cmd = [
        "mysqldump",
        "--host", str(u.host),
        "--port", str(u.port or 3306),
        "--user", str(u.username),
        "--single-transaction",
        "--routines",
        "--no-tablespaces",  # MySQL 8.0.21+ 导 tablespaces 需 PROCESS 权限，业务账号无此权限（恢复用不到）
        str(u.database),
    ]
    env = {**os.environ, "MYSQL_PWD": str(u.password)}  # 密码不进命令行
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as raw, subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env) as p:
        assert p.stdout is not None
        with gzip.open(raw, "wb") as gz:
            shutil.copyfileobj(p.stdout, gz)
    if p.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"mysqldump 退出码 {p.returncode}，已删除半成品 {dest.name}")
    return dest


def backup_uploads(upload_dir: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tar:
        for name in sorted(os.listdir(upload_dir)):
            tar.add(upload_dir / name, arcname=name)
    return dest


def rotate(out_dir: Path, prefix: str, keep: int) -> list[str]:
    """按前缀+修改时间只留 keep 份，返回被删除的文件名。"""
    files = sorted(out_dir.glob(f"{prefix}*"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for old in files[keep:]:
        old.unlink()
        removed.append(old.name)
    return removed


def run_backup(db_url: str, upload_dir: Path | str, out_dir: Path | str, keep: int = 10) -> dict:
    """执行一次完整备份，返回摘要 dict（供测试与运维脚本断言）。"""
    out = Path(out_dir)
    keep = max(1, int(keep))  # 至少保留当前这份，防误传 0 把备份清空
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    result: dict = {"kept": keep, "files": [], "removed": []}

    u = make_url(db_url)
    if u.drivername.startswith("sqlite"):
        db_path = Path(u.database)
        if not db_path.exists():
            raise FileNotFoundError(f"SQLite 库不存在：{db_path}")
        f = backup_sqlite(db_path, out / f"backup-{stamp}.db")
    else:
        f = backup_mysql(db_url, out / f"backup-{stamp}.sql.gz")
    result["files"].append({"path": str(f), "bytes": f.stat().st_size})

    up = Path(upload_dir)
    if up.is_dir() and any(up.iterdir()):
        f = backup_uploads(up, out / f"uploads-{stamp}.tar.gz")
        result["files"].append({"path": str(f), "bytes": f.stat().st_size})

    result["removed"] += rotate(out, "backup-", keep)
    result["removed"] += rotate(out, "uploads-", keep)
    return result


def main() -> int:
    from app.core.config import settings

    parser = argparse.ArgumentParser(description="数据库 + uploads 备份（含轮转）")
    parser.add_argument("--out", default="backups", help="备份输出目录（默认 ./backups）")
    parser.add_argument("--keep", type=int, default=10, help="每种备份保留份数（默认 10）")
    args = parser.parse_args()

    started = datetime.now()
    result = run_backup(settings.DATABASE_URL, settings.UPLOAD_DIR, args.out, args.keep)
    for f in result["files"]:
        print(f"[备份] {f['path']}  {f['bytes'] / 1024:.1f} KiB")
    for name in result["removed"]:
        print(f"[轮转] 删除旧备份 {name}")
    print(f"[完成] 耗时 {(datetime.now() - started).total_seconds():.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
