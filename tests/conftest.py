"""共享 pytest 配置：隔离测试库 + 公共 fixtures/helpers。

- 在导入 app 之前切换到独立的 SQLite 测试库（tests/_mvp_test.db），避免污染 dev.db。
- 关闭 Redis（REDIS_ENABLED=false），使用进程内内存兜底。
- 提供：client（会话级 TestClient）、db（函数级会话）、register_and_login / publish_pair 等 helper。
- autouse 清理业务表，保证每个测试用例之间数据隔离（分类表保留）。
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

import pytest

# ---- 必须在导入 app 前设置环境 ----
_TEST_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "_mvp_qa.db"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["REDIS_ENABLED"] = "false"
os.environ["DEBUG"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from app.core.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.core.seed import seed_categories  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog,
    FoundItem,
    HandoverCode,
    LostItem,
    MatchRecord,
    TrustScoreLog,
    User,
)
from app.models.category import Category  # noqa: E402
from app.models.im import IMMessage, IMSession  # noqa: E402

API = "/api/v1"
_BUSINESS_TABLES = (
    HandoverCode,
    MatchRecord,
    AuditLog,
    TrustScoreLog,
    IMSession,
    IMMessage,
    LostItem,
    FoundItem,
    User,
)


def _png_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), (120, 80, 200)).save(buf, "PNG")
    return buf.getvalue()


PNG = _png_bytes()


def _rand(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _fresh_phone() -> str:
    # 11 位纯数字手机号（避免 hex 字母干扰脱敏断言与验证码逻辑）
    digits = "".join(str(uuid.uuid4().int) for _ in range(3))
    return "13" + digits[:9]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register_and_login(client: TestClient, tag: str):
    """注册并登录，返回 (access_token, refresh_token, phone, student_no, user_id)。"""
    phone = _fresh_phone()
    student_no = _rand(f"{tag}_")
    r = client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    assert r.status_code == 200, r.text
    dev_code = r.json()["data"]["dev_code"]
    r = client.post(
        f"{API}/auth/register",
        json={
            "student_no": student_no,
            "phone": phone,
            "sms_code": dev_code,
            "password": "Passw0rd!",
            "real_name": tag,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0
    token = body["data"]["token"]["access_token"]
    refresh = body["data"]["token"]["refresh_token"]
    user_id = body["data"]["user"]["id"]
    return token, refresh, phone, student_no, user_id


def publish_pair(client: TestClient):
    """发布失主 A 与拾得者 B 的同类目同地点记录，返回 (token_a, token_b, lost_id, match_id)。"""
    token_a, _, _, _, _ = register_and_login(client, "pa")
    token_b, _, _, _, _ = register_and_login(client, "pb")
    lost_time = datetime(2026, 7, 16, 10, 0, 0).isoformat()
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token_a),
        data={
            "title": "黑色书包",
            "description": "图书馆丢失黑色书包",
            "lost_location": "图书馆三楼",
            "category_name": "书包",
            "lost_time": lost_time,
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    lost_id = r.json()["data"]["item"]["id"]
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token_b),
        data={
            "keep_status": "0",
            "description": "捡到黑色书包看起来像图书馆丢的",
            "found_location": "图书馆二楼",
            "category_name": "书包",
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    matches = r.json()["data"]["suspected_matches"]
    assert matches, "拾物发布应触发反向匹配"
    match_id = matches[0]["id"]
    return token_a, token_b, lost_id, match_id


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    if session.query(Category).count() == 0:
        seed_categories(session)
    # 关闭 setup 阶段 category 计数查询可能开启的只读事务，
    # 避免后续查询在 SQLite 复用连接上读到陈旧快照（导致审计等断言落空）。
    session.commit()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clean_business_tables():
    yield
    s = SessionLocal()
    try:
        for cls in _BUSINESS_TABLES:
            s.query(cls).delete()
        s.commit()
    finally:
        s.close()


def _initial_cleanup() -> None:
    # 每次会话从干净 schema 起步：**先物理删除旧库文件**，再 drop_all + create_all。
    #
    # ⚠️ 删文件这一步不可省（曾被误改为只 drop_all，导致大面积随机 401 /
    # StaleDataError：残留的 SQLite 文件 + 连接池里的陈旧连接会让请求侧读到
    # 「user 行已不存在」的旧快照，症状表现为登录后第 N 个请求突然未认证）。
    # 删文件后再 drop_all 是双保险：文件被占用删不掉时仍能重建 schema。
    try:
        engine.dispose()          # 释放连接池，避免 Windows 下文件被占用删不掉
        if os.path.exists(_TEST_DB):
            os.remove(_TEST_DB)
    except OSError:
        pass
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = SessionLocal()
    try:
        seed_categories(s)
        s.commit()
    finally:
        s.close()


_initial_cleanup()
