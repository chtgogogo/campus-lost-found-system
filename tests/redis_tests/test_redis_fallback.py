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
from app.models.match import MatchRecord
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


def test_handover_code_generate_verify_without_redis(db, monkeypatch):
    # 即便 KV 处于内存兜底（无 Redis），交接码生成 / 双端校验仍可走 DB 完整跑通
    monkeypatch.setattr(settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:6399/0")
    assert RedisClient().available is False  # 确认内存兜底生效

    m = MatchRecord(
        lost_id=1, found_id=1, match_score=85.0, status=int(MatchStatus.CLAIMING)
    )
    db.add(m)
    db.flush()
    hc = HandoverService(db).generate_code(m.id)
    assert hc.code
    res1 = HandoverService(db).verify(code=hc.code, role="lost")
    assert res1["verified_by_lost"] is True
    assert res1["both_verified"] is False
    res2 = HandoverService(db).verify(code=hc.code, role="finder")
    assert res2["both_verified"] is True
