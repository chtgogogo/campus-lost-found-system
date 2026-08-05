"""交接码 + 审计日志测试：端到端闭环 + 服务级 TTL/冲突/双写 + 审计落库。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import MatchProcessedError
from app.models.audit import AuditLog
from app.models.match import HandoverCode, MatchRecord
from app.schemas.common import HandoverStatus, MatchStatus
from app.services.handover_service import (
    HandoverConflictError,
    HandoverExpiredError,
    HandoverInvalidError,
    HandoverService,
)

from conftest import API, PNG, auth_header, publish_pair


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

    # 生成交接码
    r = client.post(f"{API}/matches/{match_id}/handover/generate", headers=auth_header(token_a))
    assert r.status_code == 200, r.text
    body = r.json()
    code = body["data"]["code"]
    assert re.fullmatch(r"[A-Z2-9]{6}", code), code
    assert len(body["data"]["qr_token"]) == 64

    # 双端验证（先失主，后拾得者）
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=auth_header(token_a),
        json={"code": code, "role": "lost", "gps": "30.123,104.456"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["both_verified"] is False

    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=auth_header(token_b),
        json={"code": code, "role": "finder", "gps": "30.124,104.457"},
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
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate",
        headers=auth_header(token_a),
    )
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=auth_header(token_a),
        json={"code": "ZZZZZZ", "role": "lost"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == 4001


# ---------------- 服务级（直接调用 HandoverService，db 双写可验证） ----------------
def test_handover_service_generate_success_and_seq(db):
    m = MatchRecord(lost_id=1, found_id=1, match_score=85.0, status=int(MatchStatus.CLAIMING))
    db.add(m)
    db.flush()
    hc = HandoverService(db).generate_code(m.id)
    assert re.fullmatch(r"[A-Z2-9]{6}", hc.code)
    assert hc.seq == 1
    # 再次生成 seq 自增（双写镜像到 match_record.code）
    hc2 = HandoverService(db).generate_code(m.id)
    assert hc2.seq == 2
    db.expire_all()
    refreshed = db.query(MatchRecord).filter(MatchRecord.id == m.id).one()
    assert refreshed.code == hc2.code


def test_handover_service_generate_requires_claiming(db):
    m = MatchRecord(
        lost_id=1, found_id=1, match_score=85.0, status=int(MatchStatus.PENDING_CLAIM)
    )
    db.add(m)
    db.flush()
    with pytest.raises(MatchProcessedError):
        HandoverService(db).generate_code(m.id)


def test_handover_service_expired(db):
    m = MatchRecord(lost_id=1, found_id=1, match_score=85.0, status=int(MatchStatus.CLAIMING))
    db.add(m)
    db.flush()
    hc = HandoverCode(
        match_id=m.id,
        seq=1,
        code="EXPTST",
        qr_token="x" * 64,
        status=int(HandoverStatus.VALID),
        expire_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
    )
    db.add(hc)
    db.commit()
    with pytest.raises(HandoverExpiredError) as exc:
        HandoverService(db).verify(code="EXPTST", role="lost")
    assert exc.value.code == 4002
    assert exc.value.http_status == 400


def test_handover_service_conflict(db):
    m = MatchRecord(lost_id=1, found_id=1, match_score=85.0, status=int(MatchStatus.CLAIMING))
    db.add(m)
    db.flush()
    hc = HandoverCode(
        match_id=m.id,
        seq=1,
        code="CNFTST",
        qr_token="y" * 64,
        status=int(HandoverStatus.VALID),
        expire_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=30),
    )
    db.add(hc)
    db.commit()
    res = HandoverService(db).verify(code="CNFTST", role="lost")
    assert res["verified_by_lost"] is True
    assert res["both_verified"] is False
    with pytest.raises(HandoverConflictError) as exc:
        HandoverService(db).verify(code="CNFTST", role="lost")
    assert exc.value.code == 4003
    assert exc.value.http_status == 409


def test_handover_service_invalid_code(db):
    with pytest.raises(HandoverInvalidError):
        HandoverService(db).verify(code="NOPE11", role="lost")
