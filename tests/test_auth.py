"""认证模块测试：注册/登录/刷新/短信/绑手机/登出 + 统一返回体 + 错误路径。"""
from __future__ import annotations

import re

from conftest import API, PNG, auth_header, register_and_login, _fresh_phone


def _check_ok(resp):
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) >= {"code", "message", "data"}
    assert body["code"] == 0
    assert body["message"] == "success"
    return body


def test_health_unified_body(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert "app" in body["data"]


def test_register_login_success(client):
    token, _, _, student_no, _ = register_and_login(client, "auth")
    assert token
    # 再次登录拿 token（验证可重复登录）
    r = client.post(f"{API}/auth/login", json={"student_no": student_no, "password": "Passw0rd!"})
    body = _check_ok(r)
    # 登录接口仅返回 token（不含 user）
    assert body["data"]["access_token"]
    assert "refresh_token" in body["data"]


def test_send_sms_returns_dev_code_in_debug(client):
    phone = _fresh_phone()
    r = client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    body = _check_ok(r)
    assert body["data"]["sent"] is True
    assert "dev_code" in body["data"]


def test_send_sms_rate_limit(client):
    phone = _fresh_phone()
    client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    r = client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    assert r.status_code == 429, r.text
    assert r.json()["code"] == 6001


def test_register_wrong_sms_code(client):
    phone = _fresh_phone()
    client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    r = client.post(
        f"{API}/auth/register",
        json={
            "student_no": f"u_{phone}",
            "phone": phone,
            "sms_code": "000000",
            "password": "Passw0rd!",
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == 1003  # OtpError


def test_register_duplicate_student_no(client, db):
    from app.core import redis_client

    _, _, _, student_no, _ = register_and_login(client, "dup")
    new_phone = _fresh_phone()
    # 直接写入 OTP，绕过 send-sms 限流（手机号已注册过一次）
    redis_client.kv.set(f"sms:{new_phone}", "111111", ttl_sec=300)
    r = client.post(
        f"{API}/auth/register",
        json={
            "student_no": student_no,
            "phone": new_phone,
            "sms_code": "111111",
            "password": "Passw0rd!",
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == 9001
    assert r.json()["data"] is None


def test_register_duplicate_phone(client, db):
    from app.core import redis_client

    _, _, phone, _, _ = register_and_login(client, "dup2")
    # 用已存在手机号注册新账号：直接写入 OTP 跳过限流
    redis_client.kv.set(f"sms:{phone}", "654321", ttl_sec=300)
    r = client.post(
        f"{API}/auth/register",
        json={
            "student_no": f"other_{phone}",
            "phone": phone,
            "sms_code": "654321",
            "password": "Passw0rd!",
        },
    )
    assert r.status_code == 409
    assert r.json()["code"] == 9001


def test_login_wrong_password(client):
    _, _, _, student_no, _ = register_and_login(client, "wp")
    r = client.post(f"{API}/auth/login", json={"student_no": student_no, "password": "wrongpass"})
    assert r.status_code == 401, r.text
    assert r.json()["code"] == 1002


def test_protected_without_token(client):
    r = client.get(f"{API}/lost-items")
    assert r.status_code == 401, r.text
    assert r.json()["code"] == 1000


def test_protected_invalid_token(client):
    r = client.get(f"{API}/lost-items", headers=auth_header("not-a-valid-jwt"))
    assert r.status_code == 401, r.text
    assert r.json()["code"] == 1000


def test_bind_phone_flow(client):
    token, _, _, _, _ = register_and_login(client, "bind")
    new_phone = _fresh_phone()
    r = client.post(f"{API}/auth/send-sms", json={"phone": new_phone, "purpose": "bind"})
    dev = r.json()["data"]["dev_code"]
    r = client.post(
        f"{API}/auth/bind-phone",
        headers=auth_header(token),
        json={"phone": new_phone, "sms_code": dev},
    )
    body = _check_ok(r)
    expected = re.sub(r"(\d{3})\d{4}(\d{4})", r"\1****\2", new_phone)
    assert body["data"]["phone"] == expected


def test_refresh(client):
    _, refresh, _, student_no, _ = register_and_login(client, "rf")
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
    body = _check_ok(r)
    assert body["data"]["access_token"]
    assert body["data"]["refresh_token"]


def test_logout(client):
    token, refresh, _, _, _ = register_and_login(client, "lo")
    r = client.post(
        f"{API}/auth/logout",
        headers=auth_header(token),
        json={"refresh_token": refresh},
    )
    _check_ok(r)
