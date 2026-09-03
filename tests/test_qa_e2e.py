"""QA 独立验证：FastAPI TestClient 真正跑通 MVP 闭环（不依赖工程师 smoke 脚本）。

覆盖：
- 注册→登录→发失物(带图)→查匹配列表(score 降序, 仅含 ≥阈值)→发同类拾物→认领(claim_reason)→
  确认归还→生成交接码→双端验证→状态流转到已解决
- 边界：类别不同无候选不进入打分 / claim_reason 空→400(3002) /
  交接码过期→400(4002) / 非 owner 认领→403(2003)

本文件复用 conftest 的统一隔离环境（独立 SQLite 测试库 + autouse 清理业务表 + 共享会话级 client），
不做任何模块级 reload / 自建 TestClient（避免污染共享 engine / app 状态）；测试间隔离由 conftest 的行级清理保证。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from PIL import Image

# 本文件复用 conftest.py 的统一隔离环境（独立 SQLite 测试库 + autouse 清理业务表 +
# 关闭 Redis + 共享会话级 client fixture）。不做任何模块级 reload / dispose，
# 避免污染其它测试共享的全局 app / engine 状态。
from app.core.database import SessionLocal  # noqa: E402
from app.models.category import Category  # noqa: E402
from app.models.match import HandoverCode  # noqa: E402

API = "/api/v1"


def _png(seed: int) -> bytes:
    """用 seed 改变像素，确保不同图片哈希到不同类别。"""
    buf = BytesIO()
    Image.new(
        "RGB", (2, 2), ((seed * 3) % 256, (seed * 7) % 256, (seed * 13) % 256)
    ).save(buf, "PNG")
    return buf.getvalue()


PNG = _png(1)
PNG2 = _png(2)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _rand(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def _register(client, tag):
    phone = "13" + uuid.uuid4().hex[:9]
    student_no = _rand("s_" + tag + "_")
    r = client.post(
        f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"}
    )
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
    assert r.json()["code"] == 0
    token = r.json()["data"]["token"]["access_token"]
    return token, phone, student_no


def _publish_lost(client, token, png, **extra):
    data = {
        "title": extra.get("title", "黑色书包"),
        "description": extra.get("description", "我在图书馆丢失一个黑色书包"),
        "lost_location": extra.get("lost_location", "图书馆三楼"),
        "category_name": extra.get("category_name", "书包"),
        "lost_time": extra.get(
            "lost_time", datetime(2026, 7, 16, 10, 0, 0).isoformat()
        ),
    }
    files = {"images": ("lost.png", png, "image/png")}
    r = client.post(
        f"{API}/lost-items", headers=_auth(token), data=data, files=files
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _publish_found(client, token, png, **extra):
    data = {
        "keep_status": extra.get("keep_status", "0"),
        "category_name": extra.get("category_name", "书包"),
        "description": extra.get("description", "捡到黑色书包"),
        "found_location": extra.get("found_location", "图书馆三楼"),
        "found_time": extra.get(
            "found_time", datetime(2026, 7, 16, 10, 0, 0).isoformat()
        ),
    }
    files = {"images": ("found.png", png, "image/png")}
    r = client.post(
        f"{API}/found-items", headers=_auth(token), data=data, files=files
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_full_closed_loop(client):
    token_a, _, _ = _register(client, "lostA")
    token_b, _, _ = _register(client, "foundB")

    lost = _publish_lost(
        client, token_a, PNG, description="图书馆丢失黑色书包，内有笔记本和校园卡"
    )
    lost_id = lost["item"]["id"]
    lost_cat = lost["item"]["category_id"]
    assert lost_cat > 0
    assert lost["suspected_matches"] == []  # 暂无拾物

    # 同类拾物（同图→同类）应触发反向匹配；描述高度重叠（含校园卡）使文字维度充分命中
    found = _publish_found(
        client,
        token_b,
        PNG,
        description="图书馆捡到黑色书包，内有笔记本和校园卡",
        found_time=datetime(2026, 7, 16, 10, 0, 0).isoformat(),
    )
    found_id = found["item"]["id"]
    assert found["item"]["category_id"] == lost_cat
    matches = found["suspected_matches"]
    assert len(matches) >= 1
    assert float(matches[0]["match_score"]) >= 80
    match_id = matches[0]["id"]

    # 失物主查看匹配列表：score 降序，仅含 ≥ 阈值
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=_auth(token_a))
    assert r.status_code == 200, r.text
    lst = r.json()["data"]
    assert len(lst) >= 1
    assert lst[0]["match_score"] >= lst[-1]["match_score"]
    for m in lst:
        assert float(m["match_score"]) >= 80

    # 认领（填理由）
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=_auth(token_a),
        json={"claim_reason": "书包内有我的校园卡，特征完全吻合"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 1  # 认领中

    # 确认归还
    r = client.post(
        f"{API}/matches/{match_id}/confirm-return", headers=_auth(token_b)
    )
    assert r.status_code == 200, r.text

    # 生成交接码（失主生成 lost_code）
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate", headers=_auth(token_a)
    )
    assert r.status_code == 200, r.text
    lost_code = r.json()["data"]["code"]
    assert len(lost_code) == 4
    assert r.json()["data"]["role"] == "lost"

    # 拾得者生成 finder_code
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate", headers=_auth(token_b)
    )
    assert r.status_code == 200, r.text
    finder_code = r.json()["data"]["code"]
    assert len(finder_code) == 4
    assert r.json()["data"]["role"] == "finder"

    # 交叉验证：失主输入拾得者的码
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=_auth(token_a),
        json={"code": finder_code, "role": "lost", "gps": "30.1,104.1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["both_verified"] is False
    # 交叉验证：拾得者输入失主的码
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=_auth(token_b),
        json={"code": lost_code, "role": "finder", "gps": "30.2,104.2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["both_verified"] is True

    # 状态流转：失物已解决(3) / 拾物已解决(1) / 匹配已完成(2)
    r = client.get(f"{API}/lost-items/{lost_id}", headers=_auth(token_a))
    assert r.json()["data"]["status"] == 3
    r = client.get(f"{API}/found-items/{found_id}", headers=_auth(token_b))
    assert r.json()["data"]["status"] == 1
    r = client.get(f"{API}/matches", headers=_auth(token_a))
    ids = {m["id"]: m["status"] for m in r.json()["data"]["items"]}
    assert ids.get(match_id) == 2


def test_match_list_sorted_by_score_desc(client):
    token_a, _, _ = _register(client, "lostL")
    token_b, _, _ = _register(client, "foundM")
    lost = _publish_lost(
        client, token_a, PNG, description="图书馆丢失黑色书包，内有笔记本"
    )
    lost_id = lost["item"]["id"]
    lost_cat = lost["item"]["category_id"]

    # found1：同类图 + 文字高度重叠（含校园卡）→ 高评分（88.75）
    _publish_found(
        client,
        token_b,
        PNG,
        description="图书馆捡到黑色书包，内有笔记本和校园卡",
        found_location="图书馆三楼",
        found_time=datetime(2026, 7, 16, 10, 0, 0).isoformat(),
    )
    # found2：同类图 + 文字完全重叠（精确命中失物词集）→ 更高评分（95.0）
    _publish_found(
        client,
        token_b,
        PNG,
        description="图书馆捡到黑色书包，内有笔记本",
        found_location="图书馆二楼",
        found_time=datetime(2026, 7, 16, 10, 0, 0).isoformat(),
    )

    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=_auth(token_a))
    assert r.status_code == 200, r.text
    lst = r.json()["data"]
    assert len(lst) == 2, lst
    # score 降序（flow-v2 文字维度主导排序；地点已并入 description 文本不再独立成列）
    assert lst[0]["match_score"] >= lst[1]["match_score"]
    # 候选均达阈值（文字高重合 → 疑似）
    for m in lst:
        assert float(m["match_score"]) >= 80


def test_claim_reason_empty_returns_3002(client):
    token_a, _, _ = _register(client, "lostC")
    token_b, _, _ = _register(client, "foundD")
    _publish_lost(client, token_a, PNG)
    found = _publish_found(
        client,
        token_b,
        PNG,
        description="捡到黑色书包",
        found_time=datetime(2026, 7, 16, 10, 0, 0).isoformat(),
    )
    match_id = found["suspected_matches"][0]["id"]
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=_auth(token_a),
        json={"claim_reason": ""},
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == 3002


def test_unrelated_found_no_suspected_match(client):
    """v2：类目由视觉内部解析，无法经 API 指定。验证『完全无关』拾物不产生疑似(≥80)匹配。

    mymatch-top10 增量后，top10 候选含低分（score<80 也落库），因此『完全无关』对
    可能以低分候选出现（测试环境视觉桩把所有图片识别为「钥匙」，导致描述无重叠的
    书包/雨伞对仍共享名词 tag 被召回）；但绝不应达到疑似阈值（score≥80 / suspected=true）。
    """
    token_a, _, _ = _register(client, "lostE")
    token_b, _, _ = _register(client, "foundF")
    lost = _publish_lost(
        client, token_a, PNG, description="图书馆丢失黑色书包，内有笔记本和校园卡"
    )
    lost_id = lost["item"]["id"]

    # 完全无关：描述与地点均无重叠（无共同 token、地点相似度 0）
    found = _publish_found(
        client,
        token_b,
        PNG2,
        description="田径场捡到一把雨伞",
        found_location="田径场",
        found_time=datetime(2026, 7, 16, 10, 0, 0).isoformat(),
    )
    # 失物主匹配列表：即使出现候选也必须是低分（非疑似）
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=_auth(token_a))
    assert r.status_code == 200, r.text
    for m in r.json()["data"]:
        assert float(m["match_score"]) < 80.0, f"无关物品不应产生疑似匹配: {m}"
        assert m["suspected"] is False, f"无关物品不应标记疑似: {m}"
    # 拾物侧同样：不得产生疑似(≥80)匹配
    for m in found["suspected_matches"]:
        assert float(m["match_score"]) < 80.0, f"拾物侧不应产生疑似匹配: {m}"
        assert m["suspected"] is False, f"拾物侧不应标记疑似: {m}"


def test_handover_code_expired_returns_4002(client):
    token_a, _, _ = _register(client, "lostG")
    token_b, _, _ = _register(client, "foundH")
    _publish_lost(client, token_a, PNG)
    found = _publish_found(
        client,
        token_b,
        PNG,
        description="捡到黑色书包",
        found_time=datetime(2026, 7, 16, 10, 0, 0).isoformat(),
    )
    match_id = found["suspected_matches"][0]["id"]
    client.post(
        f"{API}/matches/{match_id}/claim",
        headers=_auth(token_a),
        json={"claim_reason": "我的校园卡在书包里"},
    )
    client.post(f"{API}/matches/{match_id}/confirm-return", headers=_auth(token_b))
    # 失主生成 lost_code
    client.post(
        f"{API}/matches/{match_id}/handover/generate", headers=_auth(token_a)
    )
    # 拾得者生成 finder_code
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate", headers=_auth(token_b)
    )
    finder_code = r.json()["data"]["code"]

    # 将 finder_code_expire 置为过去（失主验证时检查 finder_code 的过期时间）
    with SessionLocal() as db:
        hc = db.query(HandoverCode).filter(HandoverCode.finder_code == finder_code).first()
        assert hc is not None
        hc.finder_code_expire = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
        db.commit()

    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=_auth(token_a),
        json={"code": finder_code, "role": "lost"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == 4002


def test_non_owner_cannot_claim(client):
    token_a, _, _ = _register(client, "lostI")
    token_b, _, _ = _register(client, "foundJ")
    token_c, _, _ = _register(client, "otherK")
    _publish_lost(client, token_a, PNG)
    found = _publish_found(
        client,
        token_b,
        PNG,
        description="捡到黑色书包",
        found_time=datetime(2026, 7, 16, 10, 0, 0).isoformat(),
    )
    match_id = found["suspected_matches"][0]["id"]
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=_auth(token_c),
        json={"claim_reason": "其实是我丢的"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == 2003
