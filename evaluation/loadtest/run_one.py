"""压测单场景编排器（v17 任务②）：重置环境 → 起服务 → 跑 locust → 收数 → 停服务。

一个命令复现一个数据点（docs/numbers.md 的每条压测数字都给出对应本命令）::

    .venv/Scripts/python.exe evaluation/loadtest/run_one.py \
        --scenario publish --db sqlite --label sqlite_baseline -u 10 -r 5 -t 60

- ``--db sqlite``：独立压测库 evaluation/loadtest/_env/loadtest.db（绝不碰 dev.db）
- ``--db mysql``：连本机 Docker MySQL（docker run -d --name loadtest-mysql
  -e MYSQL_ROOT_PASSWORD=loadtest -e MYSQL_DATABASE=loadtest -p 3307:3306 mysql:8.0）
- 结果：evaluation/loadtest/_results/{label}_{scenario}_stats.csv + .summary.txt
- 服务端日志：evaluation/loadtest/_env/server_{label}.log（统计 database is locked 次数）

压测口径（README 同步声明）：RATE_LIMIT_ENABLED=false（测应用本身而非限流器）、
REDIS_ENABLED=false（KV 走内存兜底，与测试环境同口径）、单 uvicorn 进程。
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
ENV_DIR = _HERE / "_env"
RESULTS_DIR = _HERE / "_results"
PORT = 8010
BASE_URL = f"http://127.0.0.1:{PORT}"

MYSQL_URL = "mysql+pymysql://root:loadtest@127.0.0.1:3307/loadtest?charset=utf8mb4"


def _base_env(db: str) -> dict:
    """构造压测环境变量。**必须写入 os.environ**：seed 在编排进程内 import app，
    只认 os.environ——曾因只传子进程 env 导致进程内 seed 落到默认 dev.db（2026-09-25 事故）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    if db == "sqlite":
        db_file = (ENV_DIR / "loadtest.db").as_posix()
        env["DATABASE_URL"] = f"sqlite:///{db_file}"
    elif db == "mysql":
        env["DATABASE_URL"] = MYSQL_URL
    else:
        raise SystemExit(f"未知 --db: {db}")
    env["UPLOAD_DIR"] = str(ENV_DIR / "uploads")
    env["REDIS_ENABLED"] = "false"
    env["RATE_LIMIT_ENABLED"] = "false"
    env["SHOW_SMS_CODE"] = "false"
    env["SEED_DEMO"] = "false"
    env["DB_ECHO"] = "false"
    env["JWT_SECRET"] = uuid.uuid4().hex + uuid.uuid4().hex
    env["ADMIN_APPLY_CODE"] = ""
    os.environ.clear()
    os.environ.update(env)
    return env


def _reset_env_dir(db: str) -> None:
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if db == "sqlite":
        for suffix in ("", "-wal", "-shm"):
            f = ENV_DIR / f"loadtest.db{suffix}"
            if f.exists():
                f.unlink()
    if (ENV_DIR / "uploads").exists():
        shutil.rmtree(ENV_DIR / "uploads")


def _wait_healthy(timeout: float = 120.0) -> None:
    """轮询 /health；视觉服务预热（YOLO 权重加载）需数秒，超时 120s。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/health", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(1.0)
    raise SystemExit(f"[run_one] 服务 {BASE_URL}/health 在 {timeout}s 内未就绪")


def _parse_stats(prefix: Path, duration: int) -> list[dict]:
    """解析 locust {prefix}_stats.csv → 每行补算 QPS（Request Count / 实际时长）。"""
    stats_file = Path(f"{prefix}_stats.csv")
    if not stats_file.exists():
        raise SystemExit(f"[run_one] 未找到 {stats_file.name}（locust 未产出？看上方输出）")
    rows = []
    with open(stats_file, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            count = int(row["Request Count"])
            failures = int(row["Failure Count"])
            row["_qps"] = count / duration if duration else 0.0
            row["_err_rate"] = (failures / count * 100) if count else 0.0
            rows.append(row)
    return rows


def _count_log_hits(log_file: Path, pattern: str) -> int:
    if not log_file.exists():
        return 0
    return len(re.findall(pattern, log_file.read_text(encoding="utf-8", errors="replace"), re.I))


def main() -> None:
    parser = argparse.ArgumentParser(description="压测单场景编排器")
    parser.add_argument("--scenario", required=True,
                        choices=["list", "publish", "matches", "handover", "mixed"])
    parser.add_argument("--db", default="sqlite", choices=["sqlite", "mysql"])
    parser.add_argument("--label", required=True, help="配置标签（如 sqlite_baseline / sqlite_wal / mysql）")
    parser.add_argument("-u", "--users", type=int, default=10)
    parser.add_argument("-r", "--spawn-rate", type=float, default=5.0)
    parser.add_argument("-t", "--run-time", type=int, default=60)
    args = parser.parse_args()

    env = _base_env(args.db)
    _reset_env_dir(args.db)

    # 1) 播种（进程内：env 已就位，seed_loadtest 自行导入 app）
    sys.path.insert(0, str(_REPO_ROOT))
    from evaluation.loadtest.seed_loadtest import seed_all

    t0 = time.perf_counter()
    seed_all()
    print(f"[run_one] 播种完成 {time.perf_counter() - t0:.1f}s")

    # 2) 起服务（日志落盘，供锁错误统计）
    server_log = ENV_DIR / f"server_{args.label}.log"
    with open(server_log, "w", encoding="utf-8") as lf:
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
            cwd=str(_REPO_ROOT), env=env, stdout=lf, stderr=subprocess.STDOUT,
        )
    try:
        _wait_healthy()
        print(f"[run_one] 服务就绪（{BASE_URL}），场景={args.scenario} 配置={args.label}")

        # 3) locust 无头压测（错误不抬高退出码——500 本身是被测对象，数据照收）
        prefix = RESULTS_DIR / f"{args.label}_{args.scenario}"
        locust_env = dict(env)
        locust_env["LOADTEST_SCENARIO"] = args.scenario
        cmd = [
            sys.executable, "-m", "locust", "-f", str(_HERE / "locustfile.py"),
            "--headless", "--only-summary", "--exit-code-on-error", "0",
            "-u", str(args.users), "-r", str(args.spawn_rate),
            "-t", f"{args.run_time}s", "--host", BASE_URL,
            "--csv", str(prefix),
        ]
        subprocess.run(cmd, env=locust_env, cwd=str(_REPO_ROOT), timeout=args.run_time + 180)
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            server.kill()

    # 4) 收数：CSV + 服务端日志锁错误
    rows = _parse_stats(prefix, args.run_time)
    scenario_rows = [
        r for r in rows if r["Type"] != "Aggregated" and "一次性" not in r["Name"]
    ]
    agg = next((r for r in rows if r["Type"] == "Aggregated"), None)
    lock_hits = _count_log_hits(server_log, r"database is locked")
    err_hits = _count_log_hits(server_log, r"(OperationalError|InternalError|Traceback)")

    lines = [
        f"场景={args.scenario} 配置={args.label} 数据库={args.db} "
        f"用户={args.users} 生成速率={args.spawn_rate}/s 时长={args.run_time}s",
    ]
    for r in scenario_rows:
        lines.append(
            f"接口: {r['Name']}\n"
            f"  请求总数={r['Request Count']}  QPS={r['_qps']:.1f}  "
            f"p95={r.get('95%', 'N/A')}ms  中位={r.get('Median Response Time', 'N/A')}ms  "
            f"平均={r.get('Average Response Time', 'N/A')}ms  "
            f"错误率={r['_err_rate']:.1f}% ({r['Failure Count']}/{r['Request Count']})"
        )
    lines += [
        (f"Aggregated: 总请求={agg['Request Count']} QPS={agg['_qps']:.1f} p95={agg.get('95%', 'N/A')}ms "
         f"错误率={agg['_err_rate']:.1f}%" if agg else ""),
        f"SQLite 锁错误(database is locked)出现次数: {lock_hits}",
        f"服务端日志异常行(OperationalError/InternalError/Traceback): {err_hits}",
        f"服务端日志: {server_log}",
    ]
    lines = [x for x in lines if x]
    summary = "\n".join(lines) + "\n"
    summary_file = Path(f"{prefix}.summary.txt")
    summary_file.write_text(summary, encoding="utf-8")
    print("\n" + summary)


if __name__ == "__main__":
    main()
