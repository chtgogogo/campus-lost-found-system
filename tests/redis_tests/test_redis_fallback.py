"""Redis 兜底测试：REDIS_ENABLED=true 但无 redis 服务时，KV 走进程内内存且可往返；
并验证交接码生成/校验流程在无 Redis 环境下（DB 存储）可完整跑通。
"""
from __future__ import annotations

import os
import sys

import pytest

from app.core import redis_client
from app.core.config import settings
from app.core.redis_client import RedisClient
from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord
from app.models.user import User
from app.schemas.common import MatchStatus
from app.services.handover_service import HandoverService

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))
from conftest import API  # noqa: E402


def test_redis_enabled_but_unavailable_falls_back_to_memory(monkeypatch):
    # 模拟生产配置开启 Redis 但服务不可达（死端口）→ 自动降级为内存
    monkeypatch.setattr(settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:6399/0")
    client = RedisClient()
    assert client.available is False
    # 进程内内存兜底往返
    client.set("code:abc", "valid", ttl_sec=60)
    assert client.get("code:abc") == "valid"
    client.delete("code:abc")
    assert client.get("code:abc") is None


def test_kv_singleton_memory_roundtrip():
    # 默认测试环境 REDIS_ENABLED=false → 内存兜底
    assert redis_client.kv.available is False
    redis_client.kv.set("k1", "v1", ttl_sec=60)
    assert redis_client.kv.get("k1") == "v1"
    redis_client.kv.delete("k1")
    assert redis_client.kv.get("k1") is None


def _make_match_with_items(db):
    """创建 User + LostItem + FoundItem + MatchRecord，供服务级测试使用。"""
    u_lost = User(student_no="rdq_lost", phone="13000000011", password_hash="x")
    u_found = User(student_no="rdq_found", phone="13000000012", password_hash="x")
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
        status=int(MatchStatus.CLAIMING),
    )
    db.add(m)
    db.flush()
    return m, u_lost, u_found


def test_handover_code_generate_verify_without_redis(db, monkeypatch):
    # 即便 KV 处于内存兜底（无 Redis），交接码生成 / 双码交叉验证仍可走 DB 完整跑通
    monkeypatch.setattr(settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:6399/0")
    assert RedisClient().available is False  # 确认内存兜底生效

    m, u_lost, u_found = _make_match_with_items(db)

    # 失主生成 lost_code
    hc_lost, role_lost = HandoverService(db).generate_code(m.id, operator_id=u_lost.id)
    assert role_lost == "lost"
    assert hc_lost.lost_code

    # 拾得者生成 finder_code
    hc_finder, role_finder = HandoverService(db).generate_code(m.id, operator_id=u_found.id)
    assert role_finder == "finder"
    assert hc_finder.finder_code

    # 失主验证拾得者的码（确认物品已收到）
    res1 = HandoverService(db).verify(
        match_id=m.id, code=hc_finder.finder_code, role="lost"
    )
    assert res1["finder_code_verified"] is True
    assert res1["both_verified"] is False

    # 拾得者验证失主的码（证明是授权领取人）
    res2 = HandoverService(db).verify(
        match_id=m.id, code=hc_lost.lost_code, role="finder"
    )
    assert res2["both_verified"] is True
