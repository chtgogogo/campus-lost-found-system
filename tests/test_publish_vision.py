"""发布 + 进程内视觉打标测试。"""
from __future__ import annotations

from datetime import datetime

from app.models.category import Category
from app.models.user import User
from app.services.vision_service import get_vision_service

from conftest import API, PNG, auth_header, register_and_login


def test_vision_predict_deterministic_and_confidence():
    vs = get_vision_service()
    r1 = vs.predict(PNG)
    r2 = vs.predict(PNG)
    assert r1["category_id"] == r2["category_id"]          # 同字节确定性
    assert 0.0 <= r1["confidence"] <= 1.0                   # 真实区间（成功识别 >0，降级=0）
    assert isinstance(r1["label"], str) and r1["label"]


def test_vision_predict_category_in_active_set(db):
    active_ids = {c.id for c in db.query(Category).filter(Category.is_active == 1).all()}
    assert active_ids, "分类应已 seed"
    vs = get_vision_service()
    res = vs.predict(PNG)
    assert res["category_id"] in active_ids


def test_publish_lost_uses_vision_tagging(client):
    token, _, _, _, _ = register_and_login(client, "pl")
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": "黑色书包",
            "description": "图书馆丢失黑色书包",
            "lost_location": "图书馆三楼",
            "category_name": "书包",
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    item = r.json()["data"]["item"]
    assert item["category_id"] > 0
    assert r.json()["data"]["suspected_matches"] == []


def test_publish_lost_stores_category_name(client):
    """v2：分类为纯自由文本，后端存储用户传入的 category_name；category_id 由视觉内部解析。"""
    token, _, _, _, _ = register_and_login(client, "pec")
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": "指定分类",
            "description": "描述",
            "lost_location": "地点",
            "category_name": "雨伞",
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    item = r.json()["data"]["item"]
    assert item["category_name"] == "雨伞"
    assert item["category_id"] > 0  # 视觉内部解析


def test_publish_found_requires_image_422(client):
    token, _, _, _, _ = register_and_login(client, "pf")
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={"keep_status": "0"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == 9001


def test_publish_found_invalid_keep_status(client):
    token, _, _, _, _ = register_and_login(client, "pfk")
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={"keep_status": "2"},
        files={"images": ("f.png", PNG, "image/png")},
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == 9001


def test_publish_found_keeping_increases_credit(client, db):
    token, _, _, _, user_id = register_and_login(client, "credit")
    before = db.query(User).filter(User.id == user_id).one().credit_score
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={"keep_status": "0", "description": "捡到钥匙", "category_name": "雨伞"},
        files={"images": ("f.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    after = db.query(User).filter(User.id == user_id).one().credit_score
    assert after == before + 1


def test_publish_found_not_keeping_no_credit_change(client, db):
    token, _, _, _, user_id = register_and_login(client, "nc")
    before = db.query(User).filter(User.id == user_id).one().credit_score
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={"keep_status": "1", "description": "捡到雨伞", "category_name": "雨伞"},
        files={"images": ("f.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    after = db.query(User).filter(User.id == user_id).one().credit_score
    assert after == before
