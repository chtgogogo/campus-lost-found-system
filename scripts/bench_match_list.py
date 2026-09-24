"""匹配列表性能基准（审查 P1 性能改造配套，2026-09-24）。

构造：1 名失主 × 30 件失物 × 每件 10 候选 = 300 条匹配（status=0 待认领），
302 名用户；对 GET /matches 计时并统计**每次请求的 SQL 语句数**（量化 N+1）。

用法::

    .venv/Scripts/python.exe scripts/bench_match_list.py

输出：页大小 20 / 200 两档的平均耗时与平均 SQL 条数。自建独立 SQLite 库，跑完自清理。
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---- 必须在导入 app 前设置环境（与 tests/conftest.py 同口径） ----
_BENCH_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "_bench_match_list.db"))
if os.path.exists(_BENCH_DB):
    os.remove(_BENCH_DB)
os.environ["DATABASE_URL"] = f"sqlite:///{_BENCH_DB}"
os.environ["REDIS_ENABLED"] = "false"
os.environ["DEBUG"] = "true"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["SHOW_SMS_CODE"] = "false"
os.environ["SEED_DEMO"] = "false"
os.environ["JWT_SECRET"] = uuid.uuid4().hex + uuid.uuid4().hex
os.environ["ADMIN_APPLY_CODE"] = "bench-" + uuid.uuid4().hex[:16]

from sqlalchemy import event  # noqa: E402

from app.core.database import SessionLocal, engine, init_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.core.seed import seed_categories  # noqa: E402
from app.main import app  # noqa: E402
from app.models.item import FoundItem, LostItem  # noqa: E402
from app.models.match import MatchRecord  # noqa: E402
from app.models.user import User  # noqa: E402

N_LOST = 30
CAND_PER_LOST = 10
ROUNDS = 10

sql_count = {"n": 0}


def _on_stmt(*args, **kwargs):
    sql_count["n"] += 1


def main() -> None:
    init_db()
    s = SessionLocal()
    seed_categories(s)

    def mk_user(tag: str) -> User:
        u = User(
            student_no=f"bench_{tag}_{uuid.uuid4().hex[:8]}",
            phone="13" + uuid.uuid4().hex[:9],
            real_name=tag,
            password_hash="x",
            role=0,
            credit_score=100,
            status=0,
        )
        s.add(u)
        return u

    owner = mk_user("owner")
    finder = mk_user("finder")
    s.flush()

    now = datetime.utcnow() + timedelta(days=90)
    losts = []
    for i in range(N_LOST):
        it = LostItem(
            title=f"失物{i}",
            description=f"bench lost {i}",
            category_name="书包",
            publisher_id=owner.id,
            location="图书馆",
            lost_time=datetime.utcnow(),
            status=0,
        )
        it.expires_at = now
        s.add(it)
        losts.append(it)
    founds = []
    for i in range(N_LOST * CAND_PER_LOST):
        it = FoundItem(
            description=f"bench found {i}",
            category_name="书包",
            finder_id=finder.id,
            location="操场",
            images=[],
            keep_status=0,
            status=0,
        )
        it.expires_at = now
        s.add(it)
        founds.append(it)
    s.flush()
    for li, lost in enumerate(losts):
        for k in range(CAND_PER_LOST):
            s.add(
                MatchRecord(
                    lost_id=lost.id,
                    found_id=founds[li * CAND_PER_LOST + k].id,
                    match_score=50 + ((li * CAND_PER_LOST + k) % 45),
                    status=0,
                )
            )
    s.commit()
    total_matches = s.query(MatchRecord).count()
    token = create_access_token(owner.id, 0)
    headers = {"Authorization": f"Bearer {token}"}
    s.close()

    event.listen(engine, "before_cursor_execute", _on_stmt)

    from fastapi.testclient import TestClient

    with TestClient(app) as c:  # lifespan：建表/seed/模型预热一次
        print(f"匹配总数={total_matches} 失主=1 拾物={N_LOST * CAND_PER_LOST}")
        for page_size in (20, 200):
            times, sqls = [], []
            for _ in range(ROUNDS):
                sql_count["n"] = 0
                t0 = time.perf_counter()
                r = c.get("/api/v1/matches", params={"page_size": page_size}, headers=headers)
                dt = (time.perf_counter() - t0) * 1000
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["data"]["total"] == total_matches, body["data"]["total"]
                times.append(dt)
                sqls.append(sql_count["n"])
            avg_t = sum(times) / len(times)
            avg_q = sum(sqls) / len(sqls)
            print(
                f"page_size={page_size:>3}  平均耗时={avg_t:8.1f}ms  "
                f"平均SQL语句数={avg_q:7.1f}  min={min(times):.1f}ms  max={max(times):.1f}ms"
            )
    event.remove(engine, "before_cursor_execute", _on_stmt)


if __name__ == "__main__":
    main()
