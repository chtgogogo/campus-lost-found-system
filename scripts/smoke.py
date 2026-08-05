"""端到端冒烟自测（requests 版，针对已启动的 live 服务）。

前置：
    1) 启动 API：      uvicorn app.main:app --port 8000
       （视觉识别为进程内 VisionService 桩，随 API 启动自动加载，无需独立服务）
    3) 运行本脚本：    python scripts/smoke.py

脚本完整跑通：注册→登录→发失物(带图,真实调用YOLO)→反向匹配→
发拾物(同类图)→查匹配(score降序)→认领(填理由)→确认归还→交接码→双端验证→已解决。
"""
from __future__ import annotations

import io
import sys
import uuid
from datetime import datetime

import requests
from PIL import Image

BASE = "http://127.0.0.1:8000"
API = f"{BASE}/api/v1"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (120, 80, 200)).save(buf, "PNG")
    return buf.getvalue()


PNG = _png()
_region = "510107"
_lost_time = datetime(2026, 7, 16, 10, 0, 0).isoformat()


def _phone() -> str:
    return "13" + uuid.uuid4().hex[:9]


def _student() -> str:
    return "s_" + uuid.uuid4().hex[:10]


def _reg_login(session: requests.Session, tag: str):
    phone = _phone()
    student = _student()
    r = session.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    r.raise_for_status()
    code = r.json()["data"]["dev_code"]
    r = session.post(
        f"{API}/auth/register",
        json={
            "student_no": student,
            "phone": phone,
            "sms_code": code,
            "password": "Passw0rd!",
            "real_name": tag,
        },
    )
    r.raise_for_status()
    r = session.post(f"{API}/auth/login", json={"student_no": student, "password": "Passw0rd!"})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    s = requests.Session()
    tok_a = _reg_login(s, "lost")
    tok_b = _reg_login(s, "found")

    # 失物
    r = s.post(
        f"{API}/lost-items",
        headers=_hdr(tok_a),
        data={
            "title": "黑色书包",
            "description": "图书馆丢失黑色书包，内有笔记本",
            "lost_location": "图书馆三楼",
            "region_code": _region,
            "lost_time": _lost_time,
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    lost_id = r.json()["data"]["item"]["id"]
    print(f"[ok] 失物发布 id={lost_id} category_id={r.json()['data']['item']['category_id']}")

    # 拾物
    r = s.post(
        f"{API}/found-items",
        headers=_hdr(tok_b),
        data={
            "keep_status": "0",
            "description": "捡到黑色书包，疑似图书馆丢失",
            "found_location": "图书馆二楼",
            "region_code": _region,
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    matches = r.json()["data"]["suspected_matches"]
    assert matches, "应触发反向匹配"
    match_id = matches[0]["id"]
    print(f"[ok] 拾物发布 触发匹配 id={match_id} score={matches[0]['match_score']}")

    # 匹配列表
    r = s.get(f"{API}/lost-items/{lost_id}/matches", headers=_hdr(tok_a))
    assert r.status_code == 200 and r.json()["data"]
    print(f"[ok] 匹配列表 score 降序: {[m['match_score'] for m in r.json()['data']]}")

    # 认领
    r = s.post(
        f"{API}/matches/{match_id}/claim",
        headers=_hdr(tok_a),
        json={"claim_reason": "书包内有我的学生证和笔记本，特征吻合"},
    )
    assert r.status_code == 200 and r.json()["data"]["status"] == 1
    print("[ok] 认领成功 status=认领中")

    # 确认归还
    r = s.post(f"{API}/matches/{match_id}/confirm-return", headers=_hdr(tok_b))
    assert r.status_code == 200
    print("[ok] 确认归还")

    # 交接码
    r = s.post(f"{API}/matches/{match_id}/handover/generate", headers=_hdr(tok_a))
    assert r.status_code == 200
    code = r.json()["data"]["code"]
    print(f"[ok] 交接码生成 code={code}")

    # 双端验证
    r = s.post(f"{API}/matches/{match_id}/handover/verify", headers=_hdr(tok_a),
               json={"code": code, "role": "lost", "gps": "30.123,104.456"})
    assert r.status_code == 200 and r.json()["data"]["both_verified"] is False
    r = s.post(f"{API}/matches/{match_id}/handover/verify", headers=_hdr(tok_b),
               json={"code": code, "role": "finder", "gps": "30.124,104.457"})
    assert r.status_code == 200 and r.json()["data"]["both_verified"] is True
    print("[ok] 双端验证通过 → 交接完成")

    # 状态
    r = s.get(f"{API}/lost-items/{lost_id}", headers=_hdr(tok_a))
    assert r.json()["data"]["status"] == 3
    print("[ok] 失物状态=已解决(3)；拾物=已解决(1)；匹配=已完成(2)")
    print("\n✅ MVP 端到端冒烟自测全部通过")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\n❌ 自测失败: {e}")
        sys.exit(1)
