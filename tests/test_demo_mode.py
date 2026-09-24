"""v18 DEMO_MODE 演示模式（2026-09-24）。

覆盖：注册免手机号/验证码 + demo- 占位号唯一 + 中文 ID + 重名 409 + 公开配置端点 +
管理员列表手机号脱敏 + 真实模式缺失字段仍拒绝（行为不回退）。
"""
from __future__ import annotations

import uuid

import pytest

from app.core.config import settings

API = "/api/v1"


def _register(client, student_no: str, **overrides):
    body = {"student_no": student_no, "password": "Demo@123", **overrides}
    return client.post(f"{API}/auth/register", json=body)


def _make_admin(client, student_no: str):
    """用邀请码注册管理员（conftest 已随机注入 ADMIN_APPLY_CODE）。

    真实模式 OTP 生效：走 send-sms → dev_code 回显 → 带码注册的完整流程。
    """
    phone = f"138{uuid.uuid4().int % 10**8:08d}"
    code = client.post(
        f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"}
    ).json()["data"]["dev_code"]
    r = _register(
        client,
        student_no,
        phone=phone,
        sms_code=code,
        admin_code=settings.ADMIN_APPLY_CODE,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["token"]["access_token"]


@pytest.fixture()
def demo_on(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)


class TestDemoRegister:
    def test_register_without_phone_and_code(self, client, demo_on):
        """演示模式：只填 ID+密码即可注册成功。

        响应 UserOut 手机号经既有脱敏链路输出——占位号 demo-xxxx 显示为 dem****xx 形态
        （含 * 即证明：a) 占位号已生成 b) 普通用户输出脱敏对占位号同样生效不崩）。
        """
        r = _register(client, "demo_user_a")
        assert r.status_code == 200, r.text
        user = r.json()["data"]["user"]
        assert "*" in user["phone"]
        # 占位号用户可正常登录（student_no + password 全链路通）
        r2 = client.post(
            f"{API}/auth/login",
            json={"student_no": "demo_user_a", "password": "Demo@123"},
        )
        assert r2.status_code == 200, r2.text

    def test_register_with_chinese_id(self, client, demo_on):
        """演示模式：ID 支持中文/数字/字母混合（schema 无字符白名单）。"""
        r = _register(client, "小明A1")
        assert r.status_code == 200, r.text

    def test_duplicate_id_rejected(self, client, demo_on):
        """演示模式：重名 ID 拒绝（student_no 唯一约束语义保留）。"""
        assert _register(client, "dup_id").status_code == 200
        r = _register(client, "dup_id")
        assert r.status_code == 409

    def test_placeholder_phones_unique(self, client, demo_on):
        """两个不带手机号的注册，占位号互不相同。"""
        u1 = _register(client, "ph_a").json()["data"]["user"]["phone"]
        u2 = _register(client, "ph_b").json()["data"]["user"]["phone"]
        assert u1 != u2

    def test_real_mode_still_requires_phone_and_code(self, client, monkeypatch):
        """真实模式（DEMO_MODE=false）缺手机号/验证码必须被拒绝——行为不回退。"""
        monkeypatch.setattr(settings, "DEMO_MODE", False)
        r = _register(client, f"real_{uuid.uuid4().hex[:6]}")
        assert r.status_code == 422


class TestPublicConfig:
    def test_public_config_reflects_demo_mode(self, client, demo_on):
        r = client.get(f"{API}/auth/public-config")
        assert r.status_code == 200
        assert r.json()["data"]["demo_mode"] is True

    def test_public_config_false_by_default(self, client):
        r = client.get(f"{API}/auth/public-config")
        assert r.json()["data"]["demo_mode"] is False


class TestAdminPhoneMasking:
    def test_admin_list_masked_in_demo_mode(self, client, demo_on):
        """演示模式：管理员用户列表手机号脱敏（demo- 占位号与真实号码都不明文）。"""
        # 先造一个真实号码用户（演示模式下显式带 phone 注册也允许）
        r = _register(client, "victim_1", phone="13911112222")
        assert r.status_code == 200, r.text
        admin_token = _make_admin(client, f"admin_{uuid.uuid4().hex[:6]}")
        r = client.get(
            f"{API}/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        phones = [u["phone"] for u in r.json()["data"]["items"]]
        assert all("13911112222" != p for p in phones)  # 真实号码不明文
        masked = next(p for p in phones if "139" in p)
        assert "****" in masked  # 139****2222 形态

    def test_admin_list_plaintext_in_real_mode(self, client, monkeypatch):
        """真实模式：管理员列表保持明文（取证能力不回退）。"""
        monkeypatch.setattr(settings, "DEMO_MODE", False)
        # 真实模式注册走完整 OTP 流程（SHOW_SMS_CODE=true 由 conftest 开启，dev_code 回显取码）
        phone = "13866667777"
        code = client.post(
            f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"}
        ).json()["data"]["dev_code"]
        r = _register(client, "plain_1", phone=phone, sms_code=code)
        assert r.status_code == 200, r.text
        admin_token = _make_admin(client, f"admin_{uuid.uuid4().hex[:6]}")
        r = client.get(
            f"{API}/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        phones = [u["phone"] for u in r.json()["data"]["items"]]
        assert "13866667777" in phones
