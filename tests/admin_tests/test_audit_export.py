"""审计导出 API 测试：GET /api/v1/admin/audit-logs/export?format=csv|json。

- admin：format=csv → 200；format=json → 200
- 非 admin：403
- 非法 format：400（code=9001）
"""
from __future__ import annotations

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


def test_admin_export_csv_200(client, db):
    token = _promote_to_admin(client, db)
    db.add(AuditLog(action="publish_lost", target_type="lost_item", target_id=1, user_id=None))
    db.commit()
    r = client.get(
        f"{API}/admin/audit-logs/export?format=csv",
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("content-type", "")
    assert r.text.lstrip().startswith("id,user_id,action")
    assert "publish_lost" in r.text


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
    assert isinstance(data, list)
    assert any(rec.get("action") == "claim" for rec in data)


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
