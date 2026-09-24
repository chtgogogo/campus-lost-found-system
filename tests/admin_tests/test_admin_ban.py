"""管理端封禁/解封闭环测试（审查 P0-5，2026-09-24）。

背景：deps.get_current_user 一直校验 user.status==1（封禁态拒绝请求），但 admin
路由没有任何封禁/解封端点 —— 封禁只能改库，风控闭环缺失。本轮补齐：
- POST /api/v1/admin/users/{id}/ban
- POST /api/v1/admin/users/{id}/unban
均由 require_admin 守卫，动作落审计（action=ban / unban）。
"""
from __future__ import annotations

from app.core.config import settings
from conftest import API, _fresh_phone, _rand, auth_header


def _register_raw(client, tag: str, admin_code=None) -> dict:
    """注册一个用户，可选携带 admin_code，返回完整响应 JSON（不做断言）。"""
    phone = _fresh_phone()
    r = client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    assert r.status_code == 200, r.text
    dev_code = r.json()["data"]["dev_code"]
    payload = {
        "student_no": _rand(f"{tag}_"),
        "phone": phone,
        "sms_code": dev_code,
        "password": "Passw0rd!",
        "real_name": tag,
    }
    if admin_code is not None:
        payload["admin_code"] = admin_code
    r = client.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _make_admin(client, tag: str = "banadm") -> str:
    """注册一个管理员并返回其 access_token。"""
    body = _register_raw(client, tag, admin_code=settings.ADMIN_APPLY_CODE)
    assert body["data"]["user"]["role"] == 1
    return body["data"]["token"]["access_token"]


def test_ban_then_unban_roundtrip(client):
    """封禁 → 业务接口 403/重登录被拒 → 解封 → 全部恢复。"""
    admin_token = _make_admin(client)
    body = _register_raw(client, "victim")
    user_id = body["data"]["user"]["id"]
    student_no = body["data"]["user"]["student_no"]
    user_token = body["data"]["token"]["access_token"]

    # 封禁：响应回传最新状态
    r = client.post(f"{API}/admin/users/{user_id}/ban", headers=auth_header(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 1

    # 封禁即时生效：业务接口 403（2003），重新登录也被拒
    r = client.get(f"{API}/users/me", headers=auth_header(user_token))
    assert r.status_code == 403, r.text
    assert r.json()["code"] == 2003
    r = client.post(
        f"{API}/auth/login", json={"student_no": student_no, "password": "Passw0rd!"}
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == 2003

    # 解封后全部恢复
    r = client.post(f"{API}/admin/users/{user_id}/unban", headers=auth_header(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 0
    r = client.get(f"{API}/users/me", headers=auth_header(user_token))
    assert r.status_code == 200, r.text


def test_ban_writes_audit(client, db):
    """封禁动作必须落审计黑匣子（action=ban，target_id=被封用户）。"""
    from app.models import AuditLog

    admin_token = _make_admin(client, "banadm2")
    body = _register_raw(client, "victim2")
    user_id = body["data"]["user"]["id"]
    r = client.post(f"{API}/admin/users/{user_id}/ban", headers=auth_header(admin_token))
    assert r.status_code == 200, r.text
    row = (
        db.query(AuditLog)
        .filter(AuditLog.action == "ban", AuditLog.target_id == user_id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None, "封禁应落审计"


def test_ban_nonexistent_user_404(client):
    admin_token = _make_admin(client, "banadm3")
    r = client.post(f"{API}/admin/users/999999/ban", headers=auth_header(admin_token))
    assert r.status_code == 404, r.text
    r = client.post(f"{API}/admin/users/999999/unban", headers=auth_header(admin_token))
    assert r.status_code == 404, r.text


def test_cannot_ban_admin_account(client):
    """管理员账号不可被封禁（防误操作锁死管理端；如需封禁管理员应走线下流程）。"""
    admin_token = _make_admin(client, "banadm4")
    other_admin = _register_raw(client, "adm2", admin_code=settings.ADMIN_APPLY_CODE)
    other_id = other_admin["data"]["user"]["id"]
    r = client.post(f"{API}/admin/users/{other_id}/ban", headers=auth_header(admin_token))
    assert r.status_code == 400, r.text
    # 未被实际改动
    r = client.get(f"{API}/users/me", headers=auth_header(other_admin["data"]["token"]["access_token"]))
    assert r.status_code == 200, r.text


def test_non_admin_cannot_ban(client):
    normal = _register_raw(client, "notadm")
    victim = _register_raw(client, "victim3")
    r = client.post(
        f"{API}/admin/users/{victim['data']['user']['id']}/ban",
        headers=auth_header(normal["data"]["token"]["access_token"]),
    )
    assert r.status_code == 403, r.text
