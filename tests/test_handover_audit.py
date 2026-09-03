"""交接码 + 审计日志测试：端到端闭环 + 服务级 TTL/冲突/双写 + 审计落库。

双码交叉验证模型：
- 失主生成 lost_code → 拾得者生成 finder_code
- 失主输入拾得者的码（role="lost"）→ finder_code_verified=True
- 拾得者输入失主的码（role="finder"）→ lost_code_verified=True
- 双方验证 → 交接完成
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import MatchProcessedError
from app.models.audit import AuditLog
from app.models.item import FoundItem, LostItem
from app.models.match import HandoverCode, MatchRecord
from app.models.user import User
from app.schemas.common import HandoverStatus, MatchStatus
from app.services.handover_service import (
    HandoverConflictError,
    HandoverExpiredError,
    HandoverInvalidError,
    HandoverService,
)

from conftest import API, PNG, auth_header, publish_pair


# ---------------- 服务级 helper ----------------
def _make_match_with_items(db, status=None):
    """创建 User + LostItem + FoundItem + MatchRecord，供服务级测试使用。"""
    u_lost = User(student_no="svc_lost", phone="13000000021", password_hash="x")
    u_found = User(student_no="svc_found", phone="13000000022", password_hash="x")
    db.add_all([u_lost, u_found])
    db.flush()

    lost = LostItem(
        publisher_id=u_lost.id,
        category_name="书包",
        title="黑色书包",
        description="图书馆丢失黑色书包",
        status=2,
    )
    found = FoundItem(
        finder_id=u_found.id,
        category_name="书包",
        description="捡到黑色书包",
        images=[],
        keep_status=0,
    )
    db.add_all([lost, found])
    db.flush()

    m = MatchRecord(
        lost_id=lost.id,
        found_id=found.id,
        match_score=85.0,
        status=status if status is not None else int(MatchStatus.CLAIMING),
    )
    db.add(m)
    db.flush()
    return m, u_lost, u_found


# ---------------- E2E ----------------
def test_handover_e2e_and_audit(client, db):
    token_a, token_b, lost_id, match_id = publish_pair(client)

    # 认领
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=auth_header(token_a),
        json={"claim_reason": "书包内有我的学生证和笔记本，特征吻合"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 1

    # 确认归还
    r = client.post(f"{API}/matches/{match_id}/confirm-return", headers=auth_header(token_b))
    assert r.status_code == 200

    # 失主生成 lost_code
    r = client.post(f"{API}/matches/{match_id}/handover/generate", headers=auth_header(token_a))
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["role"] == "lost"
    lost_code = body["code"]
    assert re.fullmatch(r"\d{4}", lost_code), lost_code

    # 拾得者生成 finder_code
    r = client.post(f"{API}/matches/{match_id}/handover/generate", headers=auth_header(token_b))
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["role"] == "finder"
    finder_code = body["code"]
    assert re.fullmatch(r"\d{4}", finder_code), finder_code

    # 交叉验证：失主输入拾得者的码
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=auth_header(token_a),
        json={"code": finder_code, "role": "lost", "gps": "30.123,104.456"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["both_verified"] is False
    assert r.json()["data"]["finder_code_verified"] is True

    # 交叉验证：拾得者输入失主的码
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=auth_header(token_b),
        json={"code": lost_code, "role": "finder", "gps": "30.124,104.457"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["both_verified"] is True

    # 状态流转：失物已解决(3)，匹配已完成(2)
    r = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token_a))
    assert r.json()["data"]["status"] == 3

    r = client.get(f"{API}/matches", headers=auth_header(token_a))
    ids = {m["id"]: m["status"] for m in r.json()["data"]["items"]}
    assert ids.get(match_id) == 2

    # 审计落库：关键写操作均有记录
    db.expire_all()
    match_actions = {
        row.action
        for row in db.query(AuditLog)
        .filter(AuditLog.target_id == match_id, AuditLog.target_type == "match")
        .all()
    }
    assert "claim" in match_actions
    assert "handover_generate" in match_actions
    assert "handover_complete" in match_actions

    pub = (
        db.query(AuditLog)
        .filter(AuditLog.action == "publish_lost", AuditLog.target_id == lost_id)
        .first()
    )
    assert pub is not None


def test_handover_generate_before_claim_409(client):
    # 待认领(0) 状态下生成交接码应被拒绝（需先认领进入认领中）
    token_a, _, _, match_id = publish_pair(client)
    r = client.post(f"{API}/matches/{match_id}/handover/generate", headers=auth_header(token_a))
    assert r.status_code == 409, r.text
    assert r.json()["code"] == 3003


def test_handover_verify_invalid_code(client):
    token_a, _, _, match_id = publish_pair(client)
    client.post(
        f"{API}/matches/{match_id}/claim",
        headers=auth_header(token_a),
        json={"claim_reason": "特征吻合"},
    )
    # 失主生成 lost_code（finder_code 尚未生成）
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate",
        headers=auth_header(token_a),
    )
    # 验证 role="lost" 时对方（finder_code）尚未生成 → 4001
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=auth_header(token_a),
        json={"code": "9999", "role": "lost"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == 4001


# ---------------- 服务级（直接调用 HandoverService，db 双写可验证） ----------------
def test_handover_service_generate_success_and_seq(db):
    m, u_lost, u_found = _make_match_with_items(db)
    # 失主生成 → seq=1，lost_code 设置
    hc, role = HandoverService(db).generate_code(m.id, operator_id=u_lost.id)
    assert role == "lost"
    assert re.fullmatch(r"\d{4}", hc.lost_code)
    assert hc.seq == 1
    # 拾得者生成 → 同一行（seq 不变），finder_code 设置
    hc2, role2 = HandoverService(db).generate_code(m.id, operator_id=u_found.id)
    assert role2 == "finder"
    assert re.fullmatch(r"\d{4}", hc2.finder_code)
    assert hc2.seq == 1
    assert hc2.id == hc.id  # 同一行
    # 镜像到 match_record.code（最近一次生成的码）
    db.expire_all()
    refreshed = db.query(MatchRecord).filter(MatchRecord.id == m.id).one()
    assert refreshed.code == hc2.finder_code


def test_handover_service_generate_requires_claiming(db):
    m, u_lost, _ = _make_match_with_items(db, status=int(MatchStatus.PENDING_CLAIM))
    with pytest.raises(MatchProcessedError):
        HandoverService(db).generate_code(m.id, operator_id=u_lost.id)


def test_handover_service_expired(db):
    m, _, _ = _make_match_with_items(db)
    hc = HandoverCode(
        match_id=m.id,
        seq=1,
        finder_code="1234",
        finder_code_expire=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5),
        status=int(HandoverStatus.VALID),
    )
    db.add(hc)
    db.commit()
    with pytest.raises(HandoverExpiredError) as exc:
        HandoverService(db).verify(match_id=m.id, code="1234", role="lost")
    assert exc.value.code == 4002
    assert exc.value.http_status == 400


def test_handover_service_conflict(db):
    m, _, _ = _make_match_with_items(db)
    hc = HandoverCode(
        match_id=m.id,
        seq=1,
        finder_code="1234",
        finder_code_expire=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=30),
        status=int(HandoverStatus.VALID),
    )
    db.add(hc)
    db.commit()
    res = HandoverService(db).verify(match_id=m.id, code="1234", role="lost")
    assert res["finder_code_verified"] is True
    assert res["both_verified"] is False
    with pytest.raises(HandoverConflictError) as exc:
        HandoverService(db).verify(match_id=m.id, code="1234", role="lost")
    assert exc.value.code == 4003
    assert exc.value.http_status == 409


def test_handover_service_invalid_code(db):
    with pytest.raises(HandoverInvalidError):
        HandoverService(db).verify(match_id=99999, code="9999", role="lost")
