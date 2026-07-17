"""视觉服务降级路径测试（Fallback）。

覆盖：torch / ultralytics 不可用时，predict() 永不抛异常，返回合法活跃分类
+ confidence=0.0 + 非空 label；get_vision_service() 为进程内单例。
"""
from __future__ import annotations

import os
import sys

import pytest

from app.models.category import Category
from app.services import vision_service as vs_mod
from app.services.vision_service import get_vision_service

# 复用根 conftest 中的测试字节；将 tests/ 与项目根加入 sys.path 以支持子目录导入
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))
from conftest import PNG  # noqa: E402


@pytest.fixture
def unavailable_vision(monkeypatch):
    """强制 ultralytics / torch 不可用，确保走降级（无依赖 / 无权重）。"""
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    monkeypatch.setitem(sys.modules, "torch", None)
    vs_mod._vision_instance = None
    svc = get_vision_service()
    yield svc
    vs_mod._vision_instance = None


def test_predict_fallback_returns_active_category_zero_confidence(db, unavailable_vision):
    active_ids = {c.id for c in db.query(Category).filter(Category.is_active == 1).all()}
    assert active_ids, "分类应已 seed"
    res = unavailable_vision.predict(PNG)
    assert isinstance(res, dict)
    assert set(res.keys()) == {"category_id", "label", "confidence"}
    assert res["category_id"] in active_ids
    assert isinstance(res["label"], str) and res["label"]
    assert res["confidence"] == 0.0


def test_predict_never_raises_on_empty_and_corrupt_bytes(db, unavailable_vision):
    # 空字节
    r1 = unavailable_vision.predict(b"")
    assert isinstance(r1, dict) and r1["confidence"] == 0.0
    # 非图片字节（两种情况都应降级，不抛异常）
    r2 = unavailable_vision.predict(b"this is definitely not an image")
    assert isinstance(r2, dict) and r2["confidence"] == 0.0
    assert r2["category_id"] in {
        c.id for c in db.query(Category).filter(Category.is_active == 1).all()
    }


def test_get_vision_service_is_singleton(unavailable_vision):
    a = get_vision_service()
    b = get_vision_service()
    assert a is b
