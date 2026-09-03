"""审计导出 API 测试：GET /api/v1/admin/audit-logs/export?format=csv|json。

v8（2026-08-20）导出格式变更为长表：整张文件 = 一张表
`[记录ID, 字段, 值, 说明]`，不再有单独的"审计日志字段说明"块。

- admin：format=csv → 200；format=json → 200
- 非 admin：403
- 非法 format：400（code=9001）
"""
from __future__ import annotations

import csv as _csv
import io
import os
import sys

import pytest

from app.models.audit import AuditLog
from app.models.user import User

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))
from conftest import API, auth_header, register_and_login  # noqa: E402


def _promote_to_admin(client, db):
    token, _, _, _, user_id = register_and_login(client, "adm")
    u = db.query(User).filter(User.id == user_id).one()
    u.role = 1
    db.commit()
    db.refresh(u)
    return token


def _long_table_lines(text: str) -> list[str]:
    """剥离 CSV 顶部的 `# ...` 注释，返回长表的所有 CSV 行（含表头）。"""
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


def test_admin_export_csv_200(client, db):
    token = _promote_to_admin(client, db)
    db.add(AuditLog(action="publish_lost", target_type="lost", target_id=1, user_id=None))
    db.commit()
    r = client.get(
        f"{API}/admin/audit-logs/export?format=csv",
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("content-type", "")
    # v8 长表：仅一张表，表头必须是 记录ID,字段,值,说明
    body = _long_table_lines(r.text)
    assert body, "导出 CSV 应至少包含表头一行"
    header = body[0]
    assert header.startswith("记录ID,字段,值,说明"), f"长表表头不符：{header!r}"
    # 数据包含我们写入的 action
    assert "publish_lost" in r.text
    # v9：编码字段的「说明」应直接解出该值的具体含义（而非只写字段名）
    assert "publish_lost=发布失物" in r.text, "action 说明应解出具体含义"
    assert "lost=失物条目" in r.text, "target_type 说明应解出具体含义"
    # 不应再有「字段说明」之类的单独块
    assert "字段说明" not in r.text


def test_admin_export_json_200(client, db):
    token = _promote_to_admin(client, db)
    db.add(AuditLog(action="claim", target_type="match", target_id=2, user_id=None))
    db.commit()
    r = client.get(
        f"{API}/admin/audit-logs/export?format=json",
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # v8 长表：JSON 顶层是 {_meta, rows: [...]}，rows 是长表行
    assert isinstance(data, dict), "v8 JSON 顶层应是对象（_meta + rows）"
    assert "rows" in data and isinstance(data["rows"], list), "JSON 应含 rows 数组"
    assert any(
        item.get("字段") == "action" and item.get("值") == "claim"
        for item in data["rows"]
    ), "长表里应能找到 action=claim 的行"


def test_admin_export_non_admin_403(client):
    token, _, _, _, _ = register_and_login(client, "nad")
    r = client.get(
        f"{API}/admin/audit-logs/export?format=csv",
        headers=auth_header(token),
    )
    assert r.status_code == 403
    assert r.json()["code"] == 7001


def test_admin_export_invalid_format_400(client, db):
    token = _promote_to_admin(client, db)
    r = client.get(
        f"{API}/admin/audit-logs/export?format=xml",
        headers=auth_header(token),
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == 9001


def test_admin_export_long_table_groups_by_record_id(client, db):
    """v8 长表：同一记录的所有字段共享同一记录 ID，方便 Excel 按 ID 分组。"""
    token = _promote_to_admin(client, db)
    db.add(AuditLog(action="publish_found", target_type="found", target_id=99, user_id=None))
    db.commit()
    r = client.get(
        f"{API}/admin/audit-logs/export?format=csv",
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    body = _long_table_lines(r.text)
    reader = _csv.DictReader(io.StringIO("\n".join(body)))
    rows = list(reader)
    assert rows, "长表至少应有数据行"
    # 取第一个记录 ID
    rid = rows[0]["记录ID"]
    # 该记录的所有行：字段集合 = _EXPORT_FIELDS
    same_record = [r for r in rows if r["记录ID"] == rid]
    fields = {r["字段"] for r in same_record}
    for col in (
        "id", "user_id", "action", "target_type", "target_id",
        "ip", "ua", "session_id", "gps", "detail", "created_at",
    ):
        assert col in fields, f"长表缺少字段 {col}"
    # 说明列非空：每个字段都应带说明
    no_meaning = [r for r in same_record if not r.get("说明")]
    assert not no_meaning, f"以下字段缺少说明：{[r['字段'] for r in no_meaning]}"