"""MVP 端到端冒烟测试：发布→打标→匹配→认领→交接。

使用 FastAPI TestClient（SQLite 测试库，无需启动服务、无需运行 YOLO 服务——
YOLO 不可达时自动降级为按图片哈希确定性打标，同一张图打同一类目，保证闭环可跑通）。

运行：
    .venv/Scripts/python.exe -m pytest tests/test_publish_flow.py -v
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

# 复用 conftest 的统一隔离环境（共享 tests/_mvp_qa.db + 会话级 client fixture）。
# 不再自建 DATABASE_URL / client fixture，避免与共享 harness 分裂数据库、造成偶发 401。
# 注意：本文件不再导入 app——conftest 已在会话启动时完成 app 与 engine 的初始化。

API = "/api/v1"


def _png_bytes() -> bytes:
    """生成一张确定内容的 2x2 PNG（YOLO 降级仅按字节哈希，无需真实图像）。"""
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (120, 80, 200)).save(buf, "PNG")
    return buf.getvalue()


PNG = _png_bytes()


def _rand(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client: TestClient, tag: str):
    """注册并登录，返回 (user_id 暂无, access_token, phone, student_no)。"""
    phone = "13" + uuid.uuid4().hex[:9]
    student_no = _rand("s_" + tag + "_")
    # 1) 发短信（Mock）→ 取 dev_code
    r = client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    assert r.status_code == 200, r.text
    dev_code = r.json()["data"]["dev_code"]

    # 2) 注册
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
    assert r.json()["code"] == 0

    # 3) 登录拿 token
    r = client.post(
        f"{API}/auth/login",
        json={"student_no": student_no, "password": "Passw0rd!"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["data"]["access_token"]
    return token, phone, student_no


def test_publish_match_claim_handover(client: TestClient):
    # ---- 注册失主 A 与拾得者 B ----
    token_a, _, _ = _register_and_login(client, "lost")
    token_b, _, _ = _register_and_login(client, "found")

    lost_time = datetime(2026, 7, 16, 10, 0, 0).isoformat()

    # ---- A 发布失物（带图，YOLO 打标） ----
    r = client.post(
        f"{API}/lost-items",
        headers=_auth_header(token_a),
        data={
            "title": "黑色书包",
            "description": "我在图书馆丢失一个黑色书包，内有笔记本",
            "lost_location": "图书馆三楼",
            "category_name": "书包",
            "lost_time": lost_time,
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    lost_data = r.json()["data"]
    lost_id = lost_data["item"]["id"]
    lost_cat = lost_data["item"]["category_id"]
    assert lost_cat > 0, "YOLO 打标应返回有效 category_id"
    # 此时还没有拾物，无匹配
    assert lost_data["suspected_matches"] == []

    # ---- B 发布拾物（同类图，零门槛，keep_status=0） ----
    r = client.post(
        f"{API}/found-items",
        headers=_auth_header(token_b),
        data={
            "keep_status": "0",
            "description": "捡到一个黑色书包，看起来像图书馆那边丢的",
            "found_location": "图书馆二楼",
            "category_name": "书包",
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    found_data = r.json()["data"]
    found_id = found_data["item"]["id"]
    found_cat = found_data["item"]["category_id"]
    # 同一张图 → 同一类目（降级确定性）
    assert found_cat == lost_cat, "同一图片应打标为同一类目"
    matches = found_data["suspected_matches"]
    assert len(matches) >= 1, "拾物发布应触发反向匹配"
    match0 = matches[0]
    # flow-v2（R4）：score = 15·photo+20·category+50·text+10·location+5·time；
    # 「黑色书包」文字高度重合对约 75.8（同图 15 + 同类 20 + text 33.3 + loc 5 + time 2.5），
    # 仍显著高于无关对（<30），保留"高分匹配"意图，阈值从 v8 的 80 放宽至 70。
    assert float(match0["match_score"]) >= 70, "匹配度应达到高分（flow-v2 阈值口径 ≥70）"
    match_id = match0["id"]

    # ---- A 查看失物的匹配列表（score 降序） ----
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=_auth_header(token_a))
    assert r.status_code == 200, r.text
    my_matches = r.json()["data"]
    assert len(my_matches) >= 1
    assert my_matches[0]["match_score"] >= my_matches[-1]["match_score"]

    # ---- A 认领（填理由） ----
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=_auth_header(token_a),
        json={"claim_reason": "书包内有我的学生证和笔记本，特征吻合"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 1  # 认领中

    # 认领理由必填校验
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=_auth_header(token_a),
        json={"claim_reason": ""},
    )
    assert r.status_code == 400
    assert r.json()["code"] == 3002

    # ---- B 确认归还 ----
    r = client.post(
        f"{API}/matches/{match_id}/confirm-return",
        headers=_auth_header(token_b),
    )
    assert r.status_code == 200, r.text

    # ---- 生成交接码（失主生成 lost_code） ----
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate",
        headers=_auth_header(token_a),
    )
    assert r.status_code == 200, r.text
    lost_code = r.json()["data"]["code"]
    assert len(lost_code) == 4
    assert r.json()["data"]["role"] == "lost"

    # 拾得者生成 finder_code
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate",
        headers=_auth_header(token_b),
    )
    assert r.status_code == 200, r.text
    finder_code = r.json()["data"]["code"]
    assert len(finder_code) == 4
    assert r.json()["data"]["role"] == "finder"

    # ---- 交叉验证：失主输入拾得者的码 ----
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=_auth_header(token_a),
        json={"code": finder_code, "role": "lost", "gps": "30.123,104.456"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["both_verified"] is False

    # 交叉验证：拾得者输入失主的码
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=_auth_header(token_b),
        json={"code": lost_code, "role": "finder", "gps": "30.124,104.457"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["both_verified"] is True

    # ---- 状态流转校验：失物已解决(3)，拾物已解决(1)，匹配已完成(2) ----
    r = client.get(f"{API}/lost-items/{lost_id}", headers=_auth_header(token_a))
    assert r.json()["data"]["status"] == 3, "失物应变为已解决"

    r = client.get(f"{API}/found-items/{found_id}", headers=_auth_header(token_b))
    assert r.json()["data"]["status"] == 1, "拾物应变为已解决"

    r = client.get(f"{API}/matches", headers=_auth_header(token_a))
    ids = {m["id"]: m["status"] for m in r.json()["data"]["items"]}
    assert ids.get(match_id) == 2, "匹配应变为已完成"
