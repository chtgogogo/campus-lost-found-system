"""压测环境播种（v17 任务②）。

在**独立压测库**（SQLite 文件或 MySQL 专用库 loadtest）里构造四个场景所需数据：

- 用户 ×2（真实 bcrypt 口令，可走 /auth/login）：
  - ``load_list``：拥有 200 件失物 + 200 件拾物 + 2000 条候选匹配（10/失物），
    供「物品列表 / 匹配列表」场景；
  - ``load_hand``：拥有 100 件失物 × 100 件拾物的全配对 10000 条 CLAIMING 匹配 +
    对应 HandoverCode 行（双码固定 1111/2222，未过期），供「交接码验证」场景。
- 「交接码验证」场景走**错码路径**（输入 "0000"）：每请求 = 码行查询（行锁）+ 恒时比较
  + attempts 计数写提交；错满 5 次才锁定，10000 匹配 × 5 = 5 万次错误尝试内路径不变，
  60 秒压测远达不到，保证各配置（SQLite 基线 / WAL / MySQL）测的是同一段代码路径。
  正确码路径为一次性流转语义（验证即置位），不可重复压测——README 与数字表均如实标注。

用法（一般由 run_one.py 编排调用，也可单独跑）::

    DATABASE_URL=sqlite:///.../loadtest.db python evaluation/loadtest/seed_loadtest.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import settings  # noqa: E402
from app.core.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.seed import seed_categories  # noqa: E402
from app.models.item import FoundItem, LostItem  # noqa: E402
from app.models.match import HandoverCode, MatchRecord  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.common import FoundItemStatus, HandoverStatus, LostItemStatus, MatchStatus  # noqa: E402

ENV_DIR = Path(__file__).resolve().parent / "_env"
MANIFEST = ENV_DIR / "seed_manifest.json"

PASSWORD = "loadtest-1234"
N_LIST_LOST = 200      # load_list 用户的失物数
N_LIST_FOUND = 200     # load_list 用户的拾物数（每失物 10 候选 → 2000 匹配）
CAND_PER_LOST = 10
N_HAND_PAIRS = 100     # load_hand 用户 100×100 全配对 = 10000 匹配
HAND_LOST_CODE = "1111"
HAND_FINDER_CODE = "2222"


def _mk_user(db: SessionLocal, tag: str) -> User:
    u = User(
        student_no=f"loadtest_{tag}",
        phone="13" + uuid.uuid4().hex[:9],
        real_name=f"压测{tag}",
        password_hash=hash_password(PASSWORD),
        role=0,
        credit_score=100,
        status=0,
    )
    db.add(u)
    return u


def _mk_lost(db: SessionLocal, publisher_id: int, name: str, status: int) -> LostItem:
    it = LostItem(
        title=f"压测失物-{name}",
        description=f"loadtest lost {name}",
        category_name="书包",
        publisher_id=publisher_id,
        location="图书馆",
        lost_time=datetime.utcnow(),
        status=status,
    )
    it.expires_at = datetime.utcnow() + timedelta(days=90)
    db.add(it)
    return it


def _mk_found(db: SessionLocal, finder_id: int, name: str) -> FoundItem:
    it = FoundItem(
        description=f"loadtest found {name}",
        category_name="书包",
        finder_id=finder_id,
        location="操场",
        images=[],
        keep_status=0,
        status=int(FoundItemStatus.PENDING),
    )
    it.expires_at = datetime.utcnow() + timedelta(days=90)
    db.add(it)
    return it


def seed_all() -> dict:
    """重置压测库并播种。返回 manifest dict（含两个账号与交接码匹配 id 列表）。"""
    # 硬护栏：本函数会 drop_all——绝不允许落在压测库之外的任何库上
    # （2026-09-25 事故：编排脚本 env 只传子进程，进程内 import 读到默认 dev.db）
    if "loadtest" not in settings.DATABASE_URL:
        raise SystemExit(
            f"[拒绝播种] DATABASE_URL 不是压测专用库（{settings.DATABASE_URL}）。"
            f"压测播种只允许落在路径含 loadtest 的库，防止 drop_all 误清开发库。"
        )
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    # drop_all + create_all：压测库专用（loadtest.db / loadtest schema），不碰 dev.db
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    try:
        seed_categories(db)

        u_list = _mk_user(db, "list")
        u_hand = _mk_user(db, "hand")
        db.flush()

        # ---- load_list：物品列表 / 匹配列表场景 ----
        list_losts = [_mk_lost(db, u_list.id, f"L{i}", int(LostItemStatus.PENDING_MATCH)) for i in range(N_LIST_LOST)]
        list_founds = [_mk_found(db, u_list.id, f"F{i}") for i in range(N_LIST_FOUND)]
        db.flush()
        list_match_ids: list[int] = []
        for li, lost in enumerate(list_losts):
            for k in range(CAND_PER_LOST):
                m = MatchRecord(
                    lost_id=lost.id,
                    found_id=list_founds[(li * CAND_PER_LOST + k) % len(list_founds)].id,
                    match_score=50 + ((li * CAND_PER_LOST + k) % 45),
                    status=int(MatchStatus.PENDING_CLAIM),
                )
                db.add(m)
                list_match_ids.append(m)
        db.flush()

        # ---- load_hand：交接码验证场景（100×100 全配对，全部 CLAIMING + 有效码行）----
        hand_losts = [_mk_lost(db, u_hand.id, f"H{i}", int(LostItemStatus.MATCHING)) for i in range(N_HAND_PAIRS)]
        hand_founds = [_mk_found(db, u_hand.id, f"G{i}") for i in range(N_HAND_PAIRS)]
        db.flush()
        hand_match_ids: list[int] = []
        expire = datetime.utcnow() + timedelta(hours=1)
        for i, lost in enumerate(hand_losts):
            for j, found in enumerate(hand_founds):
                m = MatchRecord(
                    lost_id=lost.id,
                    found_id=found.id,
                    match_score=60,
                    status=int(MatchStatus.CLAIMING),
                )
                db.add(m)
                db.flush()
                hand_match_ids.append(m.id)
                db.add(
                    HandoverCode(
                        match_id=m.id,
                        seq=1,
                        lost_code=HAND_LOST_CODE,
                        finder_code=HAND_FINDER_CODE,
                        lost_code_expire=expire,
                        finder_code_expire=expire,
                        status=int(HandoverStatus.VALID),
                        attempts=0,
                    )
                )
        db.commit()

        manifest = {
            "student_no_list": u_list.student_no,
            "student_no_hand": u_hand.student_no,
            "password": PASSWORD,
            "list_match_count": len(list_match_ids),
            "hand_match_ids": hand_match_ids,
            "hand_match_count": len(hand_match_ids),
            "seeded_at": datetime.utcnow().isoformat(),
        }
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        print(
            f"[seed] 用户×2 失物{len(list_losts)+len(hand_losts)} 拾物{len(list_founds)+len(hand_founds)} "
            f"候选匹配{len(list_match_ids)} 交接码匹配{len(hand_match_ids)} → {MANIFEST.name}"
        )
        return manifest
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()
