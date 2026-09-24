"""v17⑥ 业务漏斗看板测试：端点数字与 DB 实查**逐项对照一致**（执行指令⑥验收项）。

播种已知数据（2 失物 1 完成 / 4 候选 2 认领 / 指定类目分布），
先调 GET /api/v1/admin/stats/funnel，再用**原始 SQL** 直查同一库逐项对照——
看板数字必须与实查一致，不许端点自己算一套。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.config import settings
from app.models.item import LostItem
from conftest import API, _fresh_phone, _rand, auth_header, register_and_login


def _make_admin(client) -> str:
    phone = _fresh_phone()
    r = client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    dev_code = r.json()["data"]["dev_code"]
    r = client.post(
        f"{API}/auth/register",
        json={
            "student_no": _rand("funneladm_"),
            "phone": phone,
            "sms_code": dev_code,
            "password": "Passw0rd!",
            "real_name": "funnel-admin",
            "admin_code": settings.ADMIN_APPLY_CODE,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["user"]["role"] == 1
    return r.json()["data"]["token"]["access_token"]


def _publish_lost(client, token: str, category: str, title: str) -> int:
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={"title": title, "description": f"{title} 描述", "category_name": category},
        files={"images": ("lost.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), (10, 120, 30)).save(buf, "PNG")
    return buf.getvalue()


def _seed_funnel_data(client, db):
    """播种：失主 2 件失物（书包/雨伞）、拾物 2 件、候选 4 条、认领 2 条、完成 1 条。"""
    from app.models.item import FoundItem
    from app.models.match import MatchRecord
    from app.models.user import User

    _, _, _, _, loser_id = register_and_login(client, "flost")
    token_b, _, _, _, finder_id = register_and_login(client, "ffind")

    # 直接 ORM 播种（精确控制漏斗各级数量）
    lost1 = LostItem(
        publisher_id=loser_id, category_name="书包", title="书包1",
        description="d", category_id=None, status=3, images=[],
    )
    lost1.expires_at = datetime.utcnow() + timedelta(days=90)
    lost2 = LostItem(
        publisher_id=loser_id, category_name="雨伞", title="雨伞1",
        description="d", category_id=None, status=0, images=[],
    )
    lost2.expires_at = datetime.utcnow() + timedelta(days=90)
    db.add_all([lost1, lost2])
    db.flush()
    f1 = FoundItem(
        finder_id=finder_id, category_name="书包", description="d", images=[],
        keep_status=0, status=0,
    )
    f1.expires_at = datetime.utcnow() + timedelta(days=90)
    f2 = FoundItem(
        finder_id=finder_id, category_name="雨伞", description="d", images=[],
        keep_status=0, status=0,
    )
    f2.expires_at = datetime.utcnow() + timedelta(days=90)
    db.add_all([f1, f2])
    db.flush()
    # 候选：1 完成(2) / 1 认领中(1) / 1 待认领(0) / 1 已拒绝(3)
    db.add_all(
        [
            MatchRecord(lost_id=lost1.id, found_id=f1.id, match_score=80, status=2),
            MatchRecord(lost_id=lost2.id, found_id=f2.id, match_score=60, status=1),
            MatchRecord(lost_id=lost2.id, found_id=f1.id, match_score=50, status=0),
            MatchRecord(lost_id=lost1.id, found_id=f2.id, match_score=40, status=3),
        ]
    )
    db.commit()
    return lost1.id, lost2.id, loser_id, finder_id


def test_funnel_numbers_match_raw_sql(client, db):
    from app.models.match import MatchRecord

    admin_token = _make_admin(client)
    lost1_id, lost2_id, _, _ = _seed_funnel_data(client, db)

    r = client.get(f"{API}/admin/stats/funnel", headers=auth_header(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    # ---- 原始 SQL 实查同一库（对照口径） ----
    lost_pub_sql = db.execute(
        text("SELECT COUNT(*) FROM lost_item WHERE deleted_at IS NULL")
    ).scalar()
    found_pub_sql = db.execute(
        text("SELECT COUNT(*) FROM found_item WHERE deleted_at IS NULL")
    ).scalar()
    match_sql = db.execute(text("SELECT COUNT(*) FROM match_record")).scalar()
    claimed_sql = db.execute(
        text("SELECT COUNT(*) FROM match_record WHERE status IN (1, 2, 4)")
    ).scalar()
    completed_sql = db.execute(
        text("SELECT COUNT(DISTINCT lost_id) FROM match_record WHERE status = 2")
    ).scalar()
    stale_sql = db.execute(
        text(
            "SELECT category_name, COUNT(*) AS cnt FROM lost_item "
            "WHERE deleted_at IS NULL AND status != 3 "
            "GROUP BY category_name ORDER BY cnt DESC, category_name LIMIT 5"
        )
    ).fetchall()

    funnel = data["funnel"]
    # ---- 端点数字 vs 原始 SQL 逐项对照（看板必须与 DB 实查一致） ----
    assert funnel["published"] == lost_pub_sql, f"发布数不一致: {funnel['published']} vs {lost_pub_sql}"
    assert funnel["match_created"] == match_sql, f"候选数不一致: {funnel['match_created']} vs {match_sql}"
    assert funnel["claimed"] == claimed_sql, f"认领数不一致: {funnel['claimed']} vs {claimed_sql}"
    assert funnel["completed"] == completed_sql, f"完成数不一致: {funnel['completed']} vs {completed_sql}"
    assert data["found_published"] == found_pub_sql
    assert data["recovery_rate"] == round(completed_sql / lost_pub_sql, 4), "找回率口径不一致"
    assert [(x["category"], x["count"]) for x in data["stale_by_category"]] == [
        (name, cnt) for name, cnt in stale_sql
    ], "滞留 Top 类别与 SQL 实查不一致"

    # ---- 播种数据的业务语义断言 ----
    assert funnel["published"] == 2, "2 件未软删失物"
    assert funnel["match_created"] == 4, "4 条候选（含终态）"
    assert funnel["claimed"] == 2, "仅完成+认领中计入认领（待认领/拒绝不算）"
    assert funnel["completed"] == 1, "1 条失物完成交接（去重后）"
    assert data["recovery_rate"] == 0.5, "找回率 = 1/2"
    assert data["stale_by_category"][0] == {"category": "雨伞", "count": 1}, "已解决失物不进滞留榜"


def test_funnel_requires_admin(client):
    """非管理员访问看板必须被拒（require_admin 守卫）。"""
    token, _, _, _, _ = register_and_login(client, "fnoadm")
    r = client.get(f"{API}/admin/stats/funnel", headers=auth_header(token))
    assert r.status_code == 403, r.text


def test_funnel_empty_database_zeros(client, db):
    """空库看板：全 0 + 找回率 0（不除零）。"""
    admin_token = _make_admin(client)
    r = client.get(f"{API}/admin/stats/funnel", headers=auth_header(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["funnel"] == {"published": 0, "match_created": 0, "claimed": 0, "completed": 0}
    assert data["recovery_rate"] == 0.0
    assert data["stale_by_category"] == []
