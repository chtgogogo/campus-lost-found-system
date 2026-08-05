"""初始化种子数据：分类（≤12）与管理员账号。

分类：11 个校园失物类（对齐训练 best.pt 的 0-10 索引）+ 1 个「其他」降级类。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.category import Category
from app.models.user import User

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
