"""v20① /uploads 签名校验（2026-09-28）。

覆盖：未签名/篡改/过期签名拒绝、合法签名放行（字节一致 + 缓存头）、
路径穿越拦截、发布接口出口 URL 自动带签名（roundtrip）、
签名按小时取整稳定（缓存友好）、非 uploads 路径原样透传。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import API, PNG, auth_header, register_and_login

from app.core.config import settings
from app.core.signed_url import sign_image_url, verify_image_signature


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch):
    """把上传目录指到临时目录，放一个真实 PNG。"""
    d = tmp_path / "uploads"
    d.mkdir()
    (d / "a.png").write_bytes(PNG)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(d))
    return d


def test_unsigned_access_forbidden(client, upload_dir):
    r = client.get("/uploads/a.png")
    assert r.status_code == 403
    # 乱签名同样拒绝
    r = client.get("/uploads/a.png?e=9999999999&s=deadbeef")
    assert r.status_code == 403


def test_signed_access_ok(client, upload_dir):
    url = sign_image_url("/uploads/a.png")
    assert "?e=" in url and "&s=" in url
    r = client.get(url)
    assert r.status_code == 200
    assert r.content == PNG
    assert "max-age" in r.headers.get("cache-control", "")


def test_expired_signature_forbidden(client, upload_dir):
    path = "/uploads/a.png"
    expired = int(time.time()) - 10
    from app.core.signed_url import _digest
    url = f"{path}?e={expired}&s={_digest(path, expired)}"
    r = client.get(url)
    assert r.status_code == 403


def test_path_traversal_blocked(client, upload_dir):
    # %2e%2e 绕过客户端路径规范化，路由侧 resolve 校验应拦截（一律 404 不泄露存在性）
    r = client.get("/uploads/%2e%2e/dev.db")
    assert r.status_code == 404
    r = client.get("/uploads/../dev.db")
    assert r.status_code in (403, 404)


def test_missing_file_is_404_even_signed(client, upload_dir):
    url = sign_image_url("/uploads/notexist.png")
    assert client.get(url).status_code == 404


def test_publish_returns_signed_url_roundtrip(client, upload_dir):
    token, _, _, _, _ = register_and_login(client, "upsec")
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={"title": "黑色书包", "description": "测试", "category_name": "书包"},
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    images = r.json()["data"]["item"]["images"]
    assert images, "发布响应应含图片"
    url = images[0]
    assert "?e=" in url and "&s=" in url, f"出口 URL 应带签名：{url}"
    # 列表接口同样带签名
    r = client.get(f"{API}/lost-items", headers=auth_header(token))
    listed = r.json()["data"]["items"][0]["images"][0]
    assert "?e=" in listed
    # 全链路 roundtrip：用返回的签名 URL 直接取图
    assert client.get(url).status_code == 200


def test_verify_expired_and_tampered_unit():
    path = "/uploads/a.png"
    now = 1_800_000_000
    expired = now - 1
    from app.core.signed_url import _digest
    assert not verify_image_signature(path, expired, _digest(path, expired), now=now)
    good = now + 3600
    assert verify_image_signature(path, good, _digest(path, good), now=now)
    assert not verify_image_signature(path, good, "0" * 64, now=now)
    assert not verify_image_signature(path, None, "x", now=now)
    assert not verify_image_signature(path, "abc", "x", now=now)  # 非整数 e


def test_sign_stable_within_hour_and_passthrough():
    a = sign_image_url("/uploads/a.png")
    b = sign_image_url("/uploads/a.png")
    assert a == b, "同一小时内签名应稳定（浏览器缓存友好）"
    assert sign_image_url("data:image/png;base64,xxx") == "data:image/png;base64,xxx"
    assert sign_image_url("https://cdn.example.com/a.png") == "https://cdn.example.com/a.png"
    assert sign_image_url(None) == ""
    assert sign_image_url("uploads/relative.png") == "uploads/relative.png"  # 非 / 前缀原样
