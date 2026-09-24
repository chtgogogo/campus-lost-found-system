"""v18 演示随机登录测试：账号池 seed（幂等/格式/可复现）+ 端点行为（demo 开关/令牌可用/审计留痕）。"""
from __future__ import annotations

from sqlalchemy import text

from app.core.config import settings
from app.core.seed import DEMO_RANDOM_ACCOUNT_MARK, seed_demo_random_accounts
from conftest import API, auth_header, register_and_login


def test_seed_demo_accounts_idempotent_and_format(db):
    """幂等（连调两次仍 10 个）+ 格式（学号/密码均为 1234567 组合的 7 位、学号不重复）。"""
    from app.models.user import User

    seed_demo_random_accounts(db)
    seed_demo_random_accounts(db)  # 幂等：第二次不应新增
    rows = db.query(User).filter(User.real_name == DEMO_RANDOM_ACCOUNT_MARK).all()
    assert len(rows) == 10, f"演示账号池应恰好 10 个，实际 {len(rows)}"
    nos = [u.student_no for u in rows]
    assert len(set(nos)) == 10, "学号不得重复"
    for u in rows:
        assert len(u.student_no) == 7 and set(u.student_no) <= set("1234567"), u.student_no
        assert int(u.status) == 0 and int(u.role) == 0


def test_seed_demo_accounts_reproducible(db):
    """固定随机种子 → 两次全新生成结果一致（账号清单可复现、可写进文档）。"""
    specs = __import__("app.core.seed", fromlist=["_demo_random_account_specs"])._demo_random_account_specs(10)
    again = __import__("app.core.seed", fromlist=["_demo_random_account_specs"])._demo_random_account_specs(10)
    assert specs == again


def test_demo_login_roundtrip(client, db, monkeypatch):
    """DEMO_MODE=true：随机登录 200 → 令牌可用且确为演示账号；普通用户不会被误选。"""
    from app.models.audit import AuditLog
    from app.models.user import User

    # 先注册一个普通用户：随机登录绝不能选中他（池子按 real_name 标记圈定）
    register_and_login(client, "normaluser")
    seed_demo_random_accounts(db)

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    r = client.post(f"{API}/auth/demo-login")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["user"]["real_name"] == DEMO_RANDOM_ACCOUNT_MARK

    # 令牌真实可用：/users/me 通过
    me = client.get(
        f"{API}/users/me", headers=auth_header(body["token"]["access_token"])
    )
    assert me.status_code == 200, me.text
    assert me.json()["data"]["real_name"] == DEMO_RANDOM_ACCOUNT_MARK

    # 无凭据发令牌必须留痕
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "demo_random_login")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None and log.user_id == body["user"]["id"]


def test_demo_login_disabled_returns_404(client, db, monkeypatch):
    """DEMO_MODE=false（默认/生产）：随机登录口子不存在（404），且不播种账号池。"""
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    r = client.post(f"{API}/auth/demo-login")
    assert r.status_code == 404, r.text
    rows = db.execute(
        text("SELECT COUNT(*) FROM user WHERE real_name = :m"),
        {"m": DEMO_RANDOM_ACCOUNT_MARK},
    ).scalar()
    assert rows == 0, "未开启演示模式不得播种演示账号"
