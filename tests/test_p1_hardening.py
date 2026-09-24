"""审查 P1 安全加固回归（2026-09-24）。

覆盖 5 个可行为断言的加固点 + 1 个并发冒烟：
1. 兜底异常处理器：未预期异常 → 统一信封 500/5001（不再是 Starlette 纯文本）
2. 422 校验错误剥离 `input`：不回显用户原始输入
3. 详情与列表同口径：软删/过期物品凭 ID 不可见（lost + found）
4. IM 会话对方学号脱敏
5. 审计导出分页上限
6. 并发注册冒烟（SQLite 并发提交不死锁不串数据）

OTP 恒时比较与 print→logging 为内部实现替换（既有 OTP 用例覆盖行为不变），不单独立用例。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.services.cleanup import CleanupService
from conftest import API, auth_header, publish_pair, register_and_login


def _register_raw(client, tag: str, admin_code=None) -> dict:
    from conftest import _fresh_phone, _rand

    phone = _fresh_phone()
    r = client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    assert r.status_code == 200, r.text
    payload = {
        "student_no": _rand(f"{tag}_"),
        "phone": phone,
        "sms_code": r.json()["data"]["dev_code"],
        "password": "Passw0rd!",
        "real_name": tag,
    }
    if admin_code is not None:
        payload["admin_code"] = admin_code
    r = client.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _make_admin(client, tag: str = "p1adm") -> str:
    from app.core.config import settings

    body = _register_raw(client, tag, admin_code=settings.ADMIN_APPLY_CODE)
    assert body["data"]["user"]["role"] == 1
    return body["data"]["token"]["access_token"]


# ---------------- 1. 兜底异常 ----------------
def test_unhandled_exception_returns_unified_envelope(monkeypatch):
    """未预期异常 → 500 + {code:5001} 统一信封；此前为 Starlette 纯文本 Internal Server Error。

    注：默认 TestClient 会把服务端异常直接抛给测试（raise_server_exceptions=True），
    这里按生产语义用 raise_server_exceptions=False 走 ServerErrorMiddleware 处理器。
    """
    from fastapi.testclient import TestClient

    from app.main import app

    def _boom(self):
        raise ZeroDivisionError("人为注入的未预期异常")

    monkeypatch.setattr(CleanupService, "run_once", _boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        admin = _make_admin(c, "p1boom")
        r = c.post(f"{API}/admin/cleanup", headers=auth_header(admin))
    assert r.status_code == 500, r.text
    body = r.json()
    assert body["code"] == 5001, body
    assert body["message"] == "内部错误"
    assert "data" in body


# ---------------- 2. 422 不回显 input ----------------
def test_422_strips_user_input(client):
    """参数校验失败响应不得回显用户原始输入（此前 exc.errors() 带 input 字段）。"""
    token, _, _, _, _ = register_and_login(client, "p1in")
    r = client.get(f"{API}/lost-items?page=abc", headers=auth_header(token))
    assert r.status_code == 422, r.text
    assert "abc" not in r.text, f"用户输入被回显：{r.text[:300]}"


# ---------------- 3. 详情与列表同口径 ----------------
def test_soft_deleted_detail_hidden(client):
    """软删后的失物详情凭 ID 不可见（此前列表隐藏、详情放行）。失物可纯文字发布。"""
    token, _, _, _, _ = register_and_login(client, "p1dl")
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={"title": "待删失物", "description": "d", "category_name": "书包"},
    )
    assert r.status_code == 200, r.text
    lost_id = r.json()["data"]["item"]["id"]

    r = client.delete(f"{API}/lost-items/{lost_id}", headers=auth_header(token))
    assert r.status_code == 200, r.text

    r = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token))
    assert r.status_code == 404, f"软删物品详情不应可见：{r.text[:200]}"


def test_soft_deleted_found_detail_hidden(client):
    """软删后的拾物详情凭 ID 不可见。"""
    from conftest import PNG

    token, _, _, _, _ = register_and_login(client, "p1df")
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={"keep_status": "0", "description": "捡到待删", "category_name": "水杯"},
        files={"images": ("f.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    found_id = r.json()["data"]["item"]["id"]

    r = client.delete(f"{API}/found-items/{found_id}", headers=auth_header(token))
    assert r.status_code == 200, r.text

    r = client.get(f"{API}/found-items/{found_id}", headers=auth_header(token))
    assert r.status_code == 404, f"软删拾物详情不应可见：{r.text[:200]}"


# ---------------- 4. IM 学号脱敏 ----------------
def test_im_peer_student_no_masked(client):
    """IM 会话列表返回的对方学号必须是脱敏形态（此前明文，可枚举抓取）。"""
    token_a, _token_b, _lost_id, match_id = publish_pair(client)

    r = client.post(f"{API}/im/sessions", headers=auth_header(token_a), json={"match_id": match_id})
    assert r.status_code == 200, r.text
    sessions = client.get(f"{API}/im/sessions", headers=auth_header(token_a)).json()["data"]
    assert sessions, "应至少有一个会话"
    for s in sessions:
        masked = s["peer_user"]["student_no"]
        assert masked == "" or "*" in masked, f"对方学号疑似明文：{masked}"


# ---------------- 5. 审计导出分页 ----------------
def test_audit_export_respects_page_size(client):
    """审计导出按 page_size 截断并回传总记录数（此前全表加载无上限）。"""
    admin = _make_admin(client, "p1exp")
    # 制造 3 条审计：admin_list_users 每次调用落一条
    for _ in range(3):
        r = client.get(f"{API}/admin/users", headers=auth_header(admin))
        assert r.status_code == 200, r.text

    r = client.get(
        f"{API}/admin/audit-logs/export",
        params={"format": "json", "page": 1, "page_size": 2},
        headers=auth_header(admin),
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    meta = payload["_meta"]
    assert meta["记录条数"] <= 2, f"分页未生效：{meta}"
    assert meta["总记录数"] >= 3, f"总记录数应≥3：{meta}"
    assert meta["分页"] == {"page": 1, "page_size": 2}


# ---------------- 6. 并发冒烟 ----------------
def test_concurrent_registration_smoke(client):
    """4 线程并发注册+登录：SQLite 并发提交不死锁、不串数据（冒烟级）。"""
    def _work(i):
        return register_and_login(client, f"p1cc{i}")

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(_work, range(4)))
    assert all(token for token, *_ in results), "并发注册应全部成功"
    student_nos = [r[3] for r in results]
    assert len(set(student_nos)) == 4, "并发注册学号不得串写"
