"""临时诊断：401/StaleDataError 根因定位（验证完毕即删）。"""
from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.models.user import User
from conftest import API, PNG, auth_header, register_and_login


def test_diag(client):
    print("\n=== DIAG ===")
    print("DATABASE_URL(settings) =", settings.DATABASE_URL)
    print("engine.url             =", engine.url)

    token, _, phone, student_no, uid = register_and_login(client, "diag")
    print("registered uid =", uid, "student_no =", student_no)

    s = SessionLocal()
    try:
        rows = s.query(User).all()
        print("users in DB after register:", [(u.id, u.student_no, u.role) for u in rows])
        print("db.get(User, uid) ->", s.get(User, uid))
    finally:
        s.close()

    r = client.get(f"{API}/users/me", headers=auth_header(token))
    print("GET /users/me ->", r.status_code, r.text[:200])

    r2 = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": "黑色钥匙",
            "description": "教学楼四楼402掉落",
            "category_name": "钥匙",
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    print("POST /lost-items ->", r2.status_code, r2.text[:300])

    s2 = SessionLocal()
    try:
        rows = s2.query(User).all()
        print("users in DB after publish:", [(u.id, u.student_no, u.role) for u in rows])
    finally:
        s2.close()
    print("=== /DIAG ===")


def test_diag2_soft_delete_sequence(client, db):
    """复刻 test_v7_soft_delete.py::test_soft_delete_sets_deleted_at 的精确序列。"""
    print("\n=== DIAG2 ===")
    token, _, _, _, uid = register_and_login(client, "sdx")
    print("uid =", uid)
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={"title": "失物", "description": "丢失", "category_name": "书包",
              "appearance": "黑色", "lost_time": "2026-07-16T10:00:00"},
        files={"images": ("l.png", PNG, "image/png")},
    )
    print("publish ->", r.status_code)
    lid = r.json()["data"]["item"]["id"]
    print("users now:", [(u.id, u.student_no) for u in db.query(User).all()])
    r2 = client.delete(f"{API}/lost-items/{lid}", headers=auth_header(token))
    print("delete ->", r2.status_code, r2.text[:160])
    s = SessionLocal()
    try:
        print("users after delete (fresh session):", [(u.id, u.student_no) for u in s.query(User).all()])
    finally:
        s.close()
    print("=== /DIAG2 ===")
