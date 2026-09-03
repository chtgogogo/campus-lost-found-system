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

    # v8 长表（2026-08-20）：表头必须是 记录ID,字段,值,说明，且整张文件就这一张表
    header_line = text.splitlines()[0]
    # 兼容"# ..."取证声明注释行：剥掉注释行后再取表头
    non_comment = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert non_comment, "CSV 应至少包含表头一行"
    header = non_comment[0]
    assert header.startswith("记录ID,字段,值,说明"), f"长表表头不符：{header!r}"
    # 不应再有「字段说明」之类的单独块
    assert "字段说明" not in text, "v8 已移除独立的字段说明块，整张 CSV 仅为一张长表"
    assert "found_title" not in text, "FoundItem 无 title 字段，导出不应引用"

    # 解析长表，按记录 ID + 字段 索引
    import csv as _csv
    import io as _io

    reader = _csv.DictReader(_io.StringIO("\n".join(non_comment)))
    long_rows = list(reader)
    assert long_rows, "长表至少应有数据行"
    by_field: dict[str, list[dict]] = {}
    for row in long_rows:
        by_field.setdefault(row["字段"], []).append(row)

    # 列完整（与后端 PROFILE_FIELDS 对齐）
    # v8 长表只含匹配记录字段；对话已抽离为独立流水（见下方对话断言）。
    for col in (
        "match_id",
        "lost_item_id",
        "lost_category",
        "lost_title",
        "lost_student_no",
        "lost_phone",
        "lost_real_name",
        "found_item_id",
        "found_category",
        "found_student_no",
        "found_phone",
        "found_real_name",
        "match_score",
        "status",
        "completed_at",
    ):
        assert col in by_field, f"导出缺少字段 {col}"

    # 双方明文账号（student_no / phone 来自真实用户，未脱敏）
    ua = db.get(User, uid_a)
    ub = db.get(User, uid_b)
    assert ua.student_no in text, "导出应含失主明文 student_no"
    assert ua.phone in text, "导出应含失主明文 phone"
    assert ub.student_no in text, "导出应含拾主明文 student_no"
    assert ub.phone in text, "导出应含拾主明文 phone"

    # 对话：独立于长表的可读流水（时间 + 角色 + 内容），呈现双方完整说话流程
    assert "# ===== 对话记录" in text, "导出应含独立对话流水区块"
    assert "失主：你好，这是我的失物" in text, "导出应含对话文本（时间 角色：内容 形式）"

    # 编码字段「说明」直接解出该值的具体含义（而非只写字段名）
    status_row = next(r for r in long_rows if r["字段"] == "status")
    assert "匹配状态：" in status_row["说明"], "status 说明应解出具体状态含义"
    assert "已完成" in status_row["说明"], "status=已完成 的说明应直接写明含义"
