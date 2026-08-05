"""视觉预识别 API 测试：POST /api/v1/vision/predict。

- 鉴权：无 token → 401
- 正常：200 + schema 正确（含 categories 下拉）
- 空图：400
- 无模型优雅降级：返回 200 + confidence=0.0（fallback）
"""
from __future__ import annotations

import os
import sys

import pytest

from app.models.category import Category
from app.services import vision_service as vs_mod
from app.services.vision_service import get_vision_service

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))
from conftest import API, PNG, auth_header, register_and_login  # noqa: E402


def test_vision_predict_requires_auth(client):
    r = client.post(
        f"{API}/vision/predict",
        files={"image": ("x.png", PNG, "image/png")},
    )
    assert r.status_code == 401


def test_vision_predict_returns_schema_and_degrades_gracefully(client, db, monkeypatch):
    # 确定性降级：禁用 ultralytics/torch 并重置单例，强制视觉模型不可用 →
    # 必走 fallback（confidence=0.0）。避免依赖测试 PNG 被 12 类 best.pt 弱检出（如@0.21）。
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    monkeypatch.setitem(sys.modules, "torch", None)
    vs_mod._vision_instance = None
    token, _, _, _, _ = register_and_login(client, "va")
    r = client.post(
        f"{API}/vision/predict",
        headers=auth_header(token),
        files={"image": ("x.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["category_id"], int)
    assert isinstance(body["label"], str) and body["label"]
    assert isinstance(body["confidence"], (int, float))
    # 确定性降级 → confidence=0.0
    assert body["confidence"] == 0.0
    assert body["category_id"] in {
        c.id for c in db.query(Category).filter(Category.is_active == 1).all()
    }
    # categories 下拉可用
    assert isinstance(body["categories"], list) and body["categories"]
    assert {"id", "name"} <= set(body["categories"][0].keys())
    vs_mod._vision_instance = None


def test_vision_predict_empty_image_400(client):
    token, _, _, _, _ = register_and_login(client, "ve")
    r = client.post(
        f"{API}/vision/predict",
        headers=auth_header(token),
        files={"image": ("x.png", b"", "image/png")},
    )
    assert r.status_code == 400, r.text


def test_vision_predict_graceful_when_ultralytics_unavailable(client, db, monkeypatch):
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    monkeypatch.setitem(sys.modules, "torch", None)
    vs_mod._vision_instance = None
    token, _, _, _, _ = register_and_login(client, "vg")
    r = client.post(
        f"{API}/vision/predict",
        headers=auth_header(token),
        files={"image": ("x.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["confidence"] == 0.0
    vs_mod._vision_instance = None
