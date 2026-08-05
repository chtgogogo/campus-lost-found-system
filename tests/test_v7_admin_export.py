"""v7 管理后台取证导出测试。

- 非管理员导出 / 列表 403
- 管理员导出 CSV 列完整（含双方明文 student_no / phone）
- 导出包含双方账号与对话文本、completed_at
- 非法 format 400（code=9001）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from conftest import API, PNG, auth_header, register_and_login  # noqa: E402

from app.models.im import IMMessage, IMSession  # noqa: E402
from app.models.item import FoundItem, LostItem  # noqa: E402
from app.models.match import MatchRecord  # noqa: E402
from app.models.user import User  # noqa: E402


def _promote_to_admin(client, db):
    token, _, _, _, user_id = register_and_login(client, "adm_exp")
    u = db.get(User, user_id)
    u.role = 1
    db.commit()
    return token


def test_export_requires_admin(client):
    token, _, _, _, _ = register_and_login(client, "ae_nad")
    r = client.post(f"{API}/admin/export", headers=auth_header(token), json={"ids": [1], "format": "csv"})
    assert r.status_code == 403
    assert r.json()["code"] == 7001


def test_list_admin_matches_requires_admin(client):
    token, _, _, _, _ = register_and_login(client, "ae_nad2")
    r = client.get(f"{API}/admin/matches", headers=auth_header(token))
    assert r.status_code == 403


def test_export_invalid_format_400(client, db):
    admin = _promote_to_admin(client, db)
    r = client.post(f"{API}/admin/export", headers=auth_header(admin), json={"ids": [1], "format": "xml"})
    assert r.status_code == 400
    assert r.json()["code"] == 9001


def test_export_csv_columns_and_accounts(client, db):
    admin = _promote_to_admin(client, db)
    token_a, _, _, _, uid_a = register_and_login(client, "ae_a")
    token_b, _, _, _, uid_b = register_and_login(client, "ae_b")

    # 失物走纯文字（不附图）：测试环境视觉桩对所有图片一律识别为「钥匙」，
    # 失物附图会与拾物（附图同样含「钥匙」）共享名词 tag，在新 top10 含低分行为下
    # 自动生成低分候选 → manual 会被 409 拒绝，无法创建 status=4 供 self-complete。
    rl = client.post(
        f"{API}/lost-items",
        headers=auth_header(token_a),
        data={"title": "导出测试失物", "description": "desc", "category_name": "书包", "lost_time": "2026-07-16T10:00:00"},
    )
    lid = rl.json()["data"]["item"]["id"]
    rf = client.post(
        f"{API}/found-items",
        headers=auth_header(token_b),
        data={"keep_status": "0", "category_name": "水杯", "description": "捡到水杯", "contact_allowed": "1"},
        files={"images": ("f.png", PNG, "image/png")},
    )
    fid = rf.json()["data"]["item"]["id"]

    # 手动匹配（status=4）→ self-complete 完成，得到 completed_at
    rm = client.post(f"{API}/matches/manual", headers=auth_header(token_a), json={"lost_id": lid, "found_id": fid})
    assert rm.status_code == 200, rm.text
    mid = rm.json()["data"]["id"]
    rc = client.post(f"{API}/matches/{mid}/self-complete", headers=auth_header(token_a), json={})
    assert rc.status_code == 200

    # 关联 IM 会话 + 消息（用于对话文本）
    rs = client.post(f"{API}/im/sessions", headers=auth_header(token_a), json={"match_id": mid})
    assert rs.status_code == 200, rs.text
    sid = rs.json()["data"]["id"]
    client.post(
        f"{API}/im/sessions/{sid}/messages",
        headers=auth_header(token_a),
        json={"content": "你好，这是我的失物"},
    )

    r = client.post(f"{API}/admin/export", headers=auth_header(admin), json={"ids": [mid], "format": "csv"})
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("content-type", "")
    text = r.text

    # 列完整（与后端 _FORENSIC_FIELDS 对齐）
    header = text.splitlines()[0]
    for col in (
        "match_id",
        "lost_item_id",
        "found_item_id",
        "lost_student_no",
        "lost_phone",
        "found_student_no",
        "found_phone",
        "completed_at",
        "conversation",
    ):
        assert col in header, f"导出缺少列 {col}"
    # v7 收尾修复①：FoundItem 无 title 字段，导出列不应含 found_title
    # （后端若仍引用 found.title 会 500；此处显式断言该笔误已被剔除）
    assert "found_title" not in header, "导出列不应含 found_title（FoundItem 无 title 字段，引用会 500）"

    # 双方明文账号（student_no / phone 来自真实用户，未脱敏）
    ua = db.get(User, uid_a)
    ub = db.get(User, uid_b)
    assert ua.student_no in text, "导出应含失主明文 student_no"
    assert ua.phone in text, "导出应含失主明文 phone"
    assert ub.student_no in text, "导出应含拾主明文 student_no"
    assert ub.phone in text, "导出应含拾主明文 phone"

    # 对话文本
    assert "你好，这是我的失物" in text, "导出应含 IM 对话文本"
