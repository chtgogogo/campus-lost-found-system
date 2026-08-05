"""错误路径与统一返回体（{code,message,data}）测试。"""
from __future__ import annotations

from datetime import datetime

from conftest import API, PNG, auth_header, publish_pair, register_and_login


def test_404_not_found(client):
    token, _, _, _, _ = register_and_login(client, "e1")
    r = client.get(f"{API}/lost-items/999999", headers=auth_header(token))
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["code"] == 2001
    assert "message" in body


def test_422_validation_missing_field(client):
    token, _, _, _, _ = register_and_login(client, "e2")
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "description": "缺少标题",
            "lost_location": "x",
            "category_name": "书包",
            "lost_time": datetime(2026, 7, 16).isoformat(),
        },
        files={"images": ("l.png", PNG, "image/png")},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == 9001
    assert isinstance(body["data"], list)  # 校验错误明细


def test_claim_empty_reason_400(client):
    token_a, _, _, match_id = publish_pair(client)
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=auth_header(token_a),
        json={"claim_reason": ""},
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == 3002


def test_claim_not_owner_forbidden(client):
    token_a, _, _, match_id = publish_pair(client)
    token_c, _, _, _, _ = register_and_login(client, "intruder")
    r = client.post(
        f"{API}/matches/{match_id}/claim",
        headers=auth_header(token_c),
        json={"claim_reason": "我是失主"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == 2003


def test_revoke_found_not_owner_forbidden(client):
    _, token_b, _, _ = publish_pair(client)
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token_b),
        data={"keep_status": "0", "description": "x", "category_name": "钥匙"},
        files={"images": ("f.png", PNG, "image/png")},
    )
    fid = r.json()["data"]["item"]["id"]
    token_c, _, _, _, _ = register_and_login(client, "intruder2")
    r = client.delete(f"{API}/found-items/{fid}", headers=auth_header(token_c))
    assert r.status_code == 403
    assert r.json()["code"] == 2003


def test_handover_verify_bad_role_422(client):
    token_a, _, _, match_id = publish_pair(client)
    client.post(
        f"{API}/matches/{match_id}/claim",
        headers=auth_header(token_a),
        json={"claim_reason": "x"},
    )
    r = client.post(
        f"{API}/matches/{match_id}/handover/generate",
        headers=auth_header(token_a),
    )
    code = r.json()["data"]["code"]
    r = client.post(
        f"{API}/matches/{match_id}/handover/verify",
        headers=auth_header(token_a),
        json={"code": code, "role": "unknown"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == 9001


def test_error_body_shape(client):
    token, _, _, _, _ = register_and_login(client, "eb")
    r = client.get(f"{API}/lost-items/999999", headers=auth_header(token))
    body = r.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["data"] is None
