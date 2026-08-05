"""种子数据初始化脚本（分类 + 管理员 + 演示用户 + 示例失物/拾物）。

用法：
    python scripts/seed.py
    python scripts/seed.py --admin-no admin001 --admin-phone 13900000000 --admin-pwd admin123456

幂等：分类 / 管理员 / 演示用户 / 示例记录均按存在性判断，可重复执行。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

# 允许以脚本方式直接运行（将项目根加入 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, init_db
from app.core.seed import seed_admin, seed_categories
from app.core.security import hash_password
from app.models.category import Category
from app.models.item import FoundItem, LostItem
from app.models.user import User
from app.schemas.common import FoundItemStatus, LostItemStatus

# 演示数据标记（便于幂等判断与清理）
_DEMO_MARK = "DEMO_SEED"


def seed_demo_users(db) -> list[User]:
    """幂等创建演示用失主 / 拾得者（已存在则跳过）。"""
    created: list[User] = []
    demos = [
        ("demo_loser", "13800000001", "演示失主"),
        ("demo_finder", "13800000002", "演示拾得者"),
    ]
    for student_no, phone, real_name in demos:
        if db.query(User).filter(User.student_no == student_no).first():
            continue
        u = User(
            student_no=student_no,
            phone=phone,
            real_name=real_name,
            password_hash=hash_password("Demo@123456"),
            role=0,
            credit_score=100,
            status=0,
        )
        db.add(u)
        db.flush()
        created.append(u)
    return created


def seed_demo_items(db) -> int:
    """幂等写入示例失物/拾物（覆盖多分类与同校区，便于演示与论文佐证）。"""
    # 幂等：已存在演示数据则跳过
    if db.query(LostItem).filter(LostItem.description.like(f"%{_DEMO_MARK}%")).first():
        return 0
    loser = db.query(User).filter(User.student_no == "demo_loser").first()
    finder = db.query(User).filter(User.student_no == "demo_finder").first()
    if not loser or not finder:
        return 0
    cat = {c.name: c.id for c in db.query(Category).filter(Category.is_active == 1).all()}
    now = datetime.now()
    samples: list[object] = []

    # 失物：书包（与下面拾物书包同校区，可演示匹配）
    if cat.get("书包"):
        samples.append(
            LostItem(
                publisher_id=loser.id,
                category_id=cat["书包"],
                title="演示：黑色双肩背包丢失",
                description=f"图书馆丢失黑色双肩背包（{_DEMO_MARK}）",
                images=[],
                color="黑色",
                category_name="书包",
                lost_time=now - timedelta(days=1),
                status=int(LostItemStatus.PENDING_MATCH),
            )
        )
    # 失物：手机
    if cat.get("手机"):
        samples.append(
            LostItem(
                publisher_id=loser.id,
                category_id=cat["手机"],
                title="演示：黑色手机丢失",
                description=f"食堂丢失黑色手机（{_DEMO_MARK}）",
                images=[],
                color="黑色",
                category_name="手机",
                lost_time=now - timedelta(days=2),
                status=int(LostItemStatus.PENDING_MATCH),
            )
        )
    # 拾物：书包（与失物书包同校区）
    if cat.get("书包"):
        samples.append(
            FoundItem(
                finder_id=finder.id,
                category_id=cat["书包"],
                description=f"图书馆捡到黑色双肩背包（{_DEMO_MARK}）",
                images=[],
                category_name="书包",
                found_time=now - timedelta(hours=20),
                keep_status=0,
                contact_allowed=1,
                status=int(FoundItemStatus.PENDING),
            )
        )
    # 拾物：钥匙
    if cat.get("钥匙"):
        samples.append(
            FoundItem(
                finder_id=finder.id,
                category_id=cat["钥匙"],
                description=f"教学楼捡到一串钥匙（{_DEMO_MARK}）",
                images=[],
                category_name="钥匙",
                found_time=now - timedelta(days=3),
                keep_status=1,
                contact_allowed=0,
                status=int(FoundItemStatus.PENDING),
            )
        )
    # 拾物：校园卡
    if cat.get("校园卡"):
        samples.append(
            FoundItem(
                finder_id=finder.id,
                category_id=cat["校园卡"],
                description=f"食堂门口捡到校园卡（{_DEMO_MARK}）",
                images=[],
                category_name="校园卡",
                found_time=now - timedelta(hours=5),
                keep_status=1,
                contact_allowed=1,
                status=int(FoundItemStatus.PENDING),
            )
        )

    for s in samples:
        db.add(s)
    db.flush()
    return len(samples)


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化分类 / 管理员 / 演示数据")
    parser.add_argument("--admin-no", default="admin001")
    parser.add_argument("--admin-phone", default="13900000000")
    parser.add_argument("--admin-pwd", default="admin123456")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        n = seed_categories(db)
        admin = seed_admin(db, args.admin_no, args.admin_phone, args.admin_pwd)
        demo_users = seed_demo_users(db)
        m = seed_demo_items(db)
        db.commit()
        print(f"[seed] categories inserted: {n}")
        print(f"[seed] admin ready: id={admin.id} student_no={admin.student_no}")
        print(f"[seed] demo users created: {len(demo_users)}")
        print(f"[seed] demo items inserted: {m}")


if __name__ == "__main__":
    main()
