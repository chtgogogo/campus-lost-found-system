"""初始化种子数据：分类（≤12）与管理员账号。

分类：11 个校园失物类（对齐训练 best.pt 的 0-10 索引）+ 1 个「其他」降级类。
"""
from __future__ import annotations

import random
import secrets

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.category import Category
from app.models.user import User

# v18 演示随机账号标记（real_name 固定值，随机登录端点据此从库中挑选）
DEMO_RANDOM_ACCOUNT_MARK = "演示随机账号"

# (name, yolo_class_id, recognition_mode, yolo_prompt)
# yolo_class_id 直接使用 best.pt 的类别索引（0-10）；recognition_mode 全 0（真模型检测）。
# 「其他」类作为降级回退目标（yolo_class_id=None，不参与检测）。
#
# ★ 如何启用 YOLO-World 零样本分支（论文论述项；本次不改动 seed 数据，以免破坏测试）：
#   将某个分类的 recognition_mode 改为 1 并填写 yolo_prompt，例如：
#       ("无人机", None, 1, "drone"),
#   则 vision_service 的 _build_category_map 会收集该 prompt，_load_world 才会加载
#   YOLO-World 并对该 prompt 做零样本检测、融合进 predict()。当前全部 mode=0 →
#   _world_prompts==[] → 分支休眠；test_bestpt_model_loads 断言其为空，请勿改动本表数据。
SEED_CATEGORIES = [
    ("手机", 0, 0, None),
    ("钱包", 1, 0, None),
    ("钥匙", 2, 0, None),
    ("书包", 3, 0, None),
    ("行李箱", 4, 0, None),
    ("笔记本电脑", 5, 0, None),   # best.pt index 5 = laptop
    ("校园卡", 6, 0, None),
    ("眼镜", 7, 0, None),
    ("笔记本", 8, 0, None),       # best.pt index 8 = notebook（本子）
    ("雨伞", 9, 0, None),
    ("水杯", 10, 0, None),
    ("其他", None, 0, None),      # 降级回退目标
]


def seed_categories(db: Session) -> int:
    """若分类表为空则写入种子分类，返回写入数量。"""
    if db.query(Category).count() > 0:
        return 0
    for name, yolo_class_id, mode, prompt in SEED_CATEGORIES:
        db.add(
            Category(
                name=name,
                yolo_class_id=yolo_class_id,
                recognition_mode=mode,
                yolo_prompt=prompt,
                is_active=1,
            )
        )
    db.commit()
    return len(SEED_CATEGORIES)


def seed_admin(db: Session, student_no: str, phone: str, password: str, real_name: str = "管理员") -> User:
    """创建管理员账号（已存在则跳过）。"""
    existing = db.query(User).filter(User.student_no == student_no).first()
    if existing:
        return existing
    admin = User(
        student_no=student_no,
        phone=phone,
        real_name=real_name,
        password_hash=hash_password(password),
        role=1,
        credit_score=100,
        status=0,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


# ---------------- v18 演示随机账号（随机登录按钮的账号池） ----------------

_DEMO_RANDOM_SEED = 1234567       # 固定种子：账号清单可复现（CHANGELOG 可列出）
_DEMO_RANDOM_CHARS = "1234567"    # 学号/密码均由这 7 个数字随机组合（7 位）


def _demo_random_account_specs(count: int) -> list[tuple[str, str]]:
    """生成 count 个不重复的 (学号, 密码)：均为「1234567」随机组合的 7 位数字。

    固定随机种子 → 同一 count 生成结果永远一致（账号清单可写进文档、可复现）。
    """
    rng = random.Random(_DEMO_RANDOM_SEED)
    seen: set[str] = set()
    specs: list[tuple[str, str]] = []
    while len(specs) < count:
        student_no = "".join(rng.choices(_DEMO_RANDOM_CHARS, k=7))
        if student_no in seen:
            continue
        seen.add(student_no)
        password = "".join(rng.choices(_DEMO_RANDOM_CHARS, k=7))
        specs.append((student_no, password))
    return specs


def seed_demo_random_accounts(db: Session, count: int = 10) -> list[User]:
    """演示模式专用：确保库里存在 count 个「演示随机账号」（幂等，已够数即跳过）。

    学号/密码均为 1234567 随机组合的 7 位数字（固定种子可复现）；
    real_name 固定 DEMO_RANDOM_ACCOUNT_MARK，供随机登录端点挑选；
    phone 用 v18 同款占位号（demo-<8位hex>，唯一约束查重重试）。
    """
    existing = (
        db.query(User).filter(User.real_name == DEMO_RANDOM_ACCOUNT_MARK).count()
    )
    if existing >= count:
        return []
    created: list[User] = []
    for student_no, password in _demo_random_account_specs(count):
        if db.query(User).filter(User.student_no == student_no).first():
            continue
        phone = f"demo-{secrets.token_hex(4)}"
        while db.query(User).filter(User.phone == phone).first():
            phone = f"demo-{secrets.token_hex(4)}"
        user = User(
            student_no=student_no,
            phone=phone,
            real_name=DEMO_RANDOM_ACCOUNT_MARK,
            password_hash=hash_password(password),
            role=0,
            credit_score=100,
            status=0,
        )
        db.add(user)
        created.append(user)
    db.commit()
    return created
