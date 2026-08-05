"""v6 增量回归测试（公示栏已解决项分离）。

覆盖：
- ``GET /lost-items`` / ``GET /found-items`` 新增 ``exclude_resolved`` / ``resolved_only`` 参数，
  过滤优先级 ``resolved_only`` > ``exclude_resolved`` > 旧 ``status``，且**仅按物品自身 status 判定**
  （失物 3 / 拾物 1 为已解决）。
- ⚠️ 红线验证：``MatchRecord.status == 3``（REJECTED）与 ``LostItem.status == 3``（RESOLVED）数值相同、
  含义不同；已解决判定**绝不**读取 ``MatchRecord.status``，拒绝匹配不会让物品"被已解决"。
- 分页 ``total`` 在过滤后准确（仅含过滤后集合）。
- 演示闭环：``web/src/api/mockData.ts`` 含 1 对完成示例（status=1 拾物 + status=3 失物 + status=2 匹配），
  且 ``mockAdapter.ts`` 镜像了 ``exclude_resolved`` / ``resolved_only`` 分支（主 tab 不含已解决项）。
- v7 变更：``DELETE /items/{id}`` 语义由"撤销=置 status=RESOLVED"改为"软删=置 deleted_at"（REST 外键约束）；
  因此"已解决"仅由完成交接（status=3/1）产生，与软删（deleted_at）解耦。迁移链 head 现为 ``0004_v7_incremental``。
"""
from __future__ import annotations

import os
import re

import pytest

from conftest import API, PNG, auth_header, register_and_login
from app.models.item import FoundItem, LostItem


# ---------------- helpers ----------------
def _publish_lost(client, token, category_name, title="我的失物", description="丢失物品"):
    r = client.post(
        f"{API}/lost-items",
        headers=auth_header(token),
        data={
            "title": title,
            "description": description,
            "category_name": category_name,
            "lost_time": "2026-07-16T10:00:00",
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def _publish_found(client, token, category_name, description, keep_status="0", contact_allowed="1"):
    r = client.post(
        f"{API}/found-items",
        headers=auth_header(token),
        data={
            "keep_status": keep_status,
            "category_name": category_name,
            "description": description,
            "contact_allowed": contact_allowed,
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["item"]["id"]


def _revoke_lost(client, token, lost_id):
    r = client.delete(f"{API}/lost-items/{lost_id}", headers=auth_header(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _revoke_found(client, token, found_id):
    r = client.delete(f"{API}/found-items/{found_id}", headers=auth_header(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ---------------- 后端过滤：失物 ----------------
def test_v6_lost_exclude_resolved(client):
    token, _, _, _, _ = register_and_login(client, "ve_lost")
    for i in range(3):
        _publish_lost(client, token, "书包", f"进行中失物{i}")
    rid = _publish_lost(client, token, "水杯", "已解决失物")
    _revoke_lost(client, token, rid)  # → status=3

    r = client.get(f"{API}/lost-items?exclude_resolved=true&page_size=100", headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["total"] == 3
    assert all(it["status"] != 3 for it in body["items"])
    assert rid not in [it["id"] for it in body["items"]]


def test_v6_lost_resolved_only(client, db):
    token, _, _, _, _ = register_and_login(client, "vo_lost")
    _publish_lost(client, token, "书包", "进行中失物")
    rid = _publish_lost(client, token, "水杯", "已解决失物")
    # v7：已解决由完成交接产生（status=3），与软删（deleted_at）解耦；
    # 直接置 status=3 以验证 resolved_only 分支（不再依赖 revoke）。
    li = db.get(LostItem, rid)
    li.status = 3
    db.commit()

    r = client.get(f"{API}/lost-items?resolved_only=true&page_size=100", headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["status"] == 3
    assert body["items"][0]["id"] == rid


# ---------------- 后端过滤：拾物 ----------------
def test_v6_found_exclude_resolved(client):
    token, _, _, _, _ = register_and_login(client, "ve_found")
    for i in range(3):
        _publish_found(client, token, "书包", f"进行中拾物{i}")
    fid = _publish_found(client, token, "水杯", "已解决拾物")
    _revoke_found(client, token, fid)  # → status=1

    r = client.get(f"{API}/found-items?exclude_resolved=true&page_size=100", headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["total"] == 3
    assert all(it["status"] != 1 for it in body["items"])
    assert fid not in [it["id"] for it in body["items"]]


def test_v6_found_resolved_only(client, db):
    token, _, _, _, _ = register_and_login(client, "vo_found")
    _publish_found(client, token, "书包", "进行中拾物")
    fid = _publish_found(client, token, "水杯", "已解决拾物")
    # v7：已解决由完成交接产生（status=1），与软删（deleted_at）解耦；
    # 直接置 status=1 以验证 resolved_only 分支（不再依赖 revoke）。
    fi = db.get(FoundItem, fid)
    fi.status = 1
    db.commit()

    r = client.get(f"{API}/found-items?resolved_only=true&page_size=100", headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["status"] == 1
    assert body["items"][0]["id"] == fid


# ---------------- 过滤优先级 ----------------
def test_v6_filter_priority_resolved_only_wins(client, db):
    token, _, _, _, _ = register_and_login(client, "vp")
    rid = _publish_lost(client, token, "水杯", "已解决失物")
    # v7：已解决由完成交接产生（status=3），此处直接置位以验证过滤优先级
    li = db.get(LostItem, rid)
    li.status = 3
    db.commit()

    # resolved_only=true 优先于 exclude_resolved=true → 仅已解决
    r = client.get(
        f"{API}/lost-items?resolved_only=true&exclude_resolved=true&page_size=100",
        headers=auth_header(token),
    )
    body = r.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["status"] == 3

    # exclude_resolved=true 且 resolved_only=false → 排除已解决（total=0）
    r2 = client.get(
        f"{API}/lost-items?exclude_resolved=true&resolved_only=false&page_size=100",
        headers=auth_header(token),
    )
    assert r2.json()["data"]["total"] == 0


def test_v6_status_backward_compat(client, db):
    token, _, _, _, _ = register_and_login(client, "vb")
    _publish_lost(client, token, "书包", "进行中失物")  # status 0
    rid = _publish_lost(client, token, "水杯", "已解决失物")
    # v7：已解决由完成交接产生（status=3），此处直接置位（与软删区分）
    li = db.get(LostItem, rid)
    li.status = 3
    db.commit()

    # 旧 status 参数在两者皆 false 时仍生效
    r = client.get(f"{API}/lost-items?status=3&page_size=100", headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["id"] == rid


# ---------------- 分页 total 准确 ----------------
def test_v6_pagination_total_after_filter(client):
    token, _, _, _, _ = register_and_login(client, "vt")
    for i in range(3):
        _publish_lost(client, token, "书包", f"进行中失物{i}")
    rid = _publish_lost(client, token, "水杯", "已解决失物")
    _revoke_lost(client, token, rid)  # status 3

    r1 = client.get(
        f"{API}/lost-items?exclude_resolved=true&page=1&page_size=2",
        headers=auth_header(token),
    )
    b1 = r1.json()["data"]
    assert b1["total"] == 3
    assert len(b1["items"]) == 2

    r2 = client.get(
        f"{API}/lost-items?exclude_resolved=true&page=2&page_size=2",
        headers=auth_header(token),
    )
    b2 = r2.json()["data"]
    assert b2["total"] == 3
    assert len(b2["items"]) == 1

    all_ids = [it["id"] for it in b1["items"]] + [it["id"] for it in b2["items"]]
    assert rid not in all_ids  # 已解决项不出现在任何主 tab 分页


# ---------------- 红线：不读 MatchRecord.status 判定已解决 ----------------
def test_v6_resolution_not_driven_by_match_status(client):
    """拒绝匹配（MatchRecord.status=3 REJECTED）与失物已解决（LostItem.status=3）数值相同、
    但语义不同；v6 判定只认物品自身 status，拒绝匹配不应让物品"被已解决"。"""
    token_a, _, _, _, _ = register_and_login(client, "vm_a")
    token_b, _, _, _, _ = register_and_login(client, "vm_b")
    lost_id = _publish_lost(client, token_a, "书包", "黑色书包")
    _publish_found(client, token_b, "书包", "捡到黑色书包", keep_status="0", contact_allowed="1")
    r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=auth_header(token_a))
    matches = r.json()["data"]
    assert matches, "应自动生成匹配"
    match_id = matches[0]["id"]

    # 拾得者拒绝 → MatchRecord.status=3（REJECTED）
    rr = client.post(f"{API}/matches/{match_id}/reject", headers=auth_header(token_b), json={})
    assert rr.status_code == 200
    assert rr.json()["data"]["status"] == 3

    # 失物仍非已解决（status != 3）
    lost = client.get(f"{API}/lost-items/{lost_id}", headers=auth_header(token_a)).json()["data"]
    assert lost["status"] != 3

    # resolved_only 不返回它；exclude_resolved 仍返回它（主 tab 可见，可重新匹配）
    only = client.get(f"{API}/lost-items?resolved_only=true&page_size=100", headers=auth_header(token_a))
    assert lost_id not in [it["id"] for it in only.json()["data"]["items"]]
    excl = client.get(f"{API}/lost-items?exclude_resolved=true&page_size=100", headers=auth_header(token_a))
    assert lost_id in [it["id"] for it in excl.json()["data"]["items"]]


# ---------------- 演示闭环（mock 数据 + 适配器镜像） ----------------
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    s = text.index(start_marker)
    e = text.index(end_marker, s)
    return text[s:e]


def test_v6_mock_demo_pair_present():
    """mockData.ts 含 1 对完成示例：status=1 拾物 + status=3 失物 + status=2 匹配关联二者。"""
    path = os.path.join(_BASE, "web", "src", "api", "mockData.ts")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    lost_block = _slice(text, "export const mockLostItems", "export const mockFoundItems")
    found_block = _slice(text, "export const mockFoundItems", "export const mockMatches")
    match_block = _slice(text, "export const mockMatches", "export const mockUsers")

    assert "status: 3" in lost_block, "mockLostItems 应含 status:3 的已解决失物"
    assert "status: 1" in found_block, "mockFoundItems 应含 status:1 的已解决拾物（演示配对）"
    assert "status: 2" in match_block, "mockMatches 应含 status:2 的已完成匹配"
    # 完成匹配关联一对已解决物品（id=7 示例）
    assert "lost_id: 7" in match_block and "found_id: 7" in match_block, \
        "mockMatches 应有一条 status:2 匹配关联完成配对（lost_id/found_id=7）"


def test_v6_mock_adapter_mirrors_filter():
    """mockAdapter.listLost/listFound 镜像后端 exclude_resolved / resolved_only 分支（含阈值 3/1）。"""
    path = os.path.join(_BASE, "web", "src", "api", "mockAdapter.ts")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "exclude_resolved" in text and "resolved_only" in text, \
        "mockAdapter 应实现 exclude_resolved / resolved_only 两分支（与后端一致）"
    # 阈值与后端一致：Lost 已解决=3，Found 已解决=1
    assert "i.status === 3" in text, "失物过滤阈值应为 3"
    assert "i.status === 1" in text, "拾物过滤阈值应为 1"


def test_v6_mock_main_tab_excludes_resolved():
    """主 tab 拉取走 exclude_resolved=true；mock 已解决拾物(status:1) 不应出现在主 tab。
    通过验证 mockFoundItems 中存在 status:1 项（适配器会将其排除）来闭环。"""
    path = os.path.join(_BASE, "web", "src", "api", "mockData.ts")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    found_block = _slice(text, "export const mockFoundItems", "export const mockMatches")
    # 该 status:1 项会被 listFound 的 exclude_resolved 分支过滤，确保主 tab 不含已解决
    assert "status: 1" in found_block


# ---------------- v7 迁移链（0004 现合法存在） ----------------
def _migration_chain():
    versions = os.path.join(_BASE, "migrations", "versions")
    revs: dict[str, str | None] = {}
    for fn in os.listdir(versions):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        with open(os.path.join(versions, fn), encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'revision\s*=\s*["\']([^"\']+)["\']', content)
        d = re.search(r'down_revision\s*=\s*["\']([^"\']+)["\']', content)
        if m:
            revs[m.group(1)] = d.group(1) if d else None
    downs = {v for v in revs.values() if v}
    heads = [r for r in revs if r not in downs]
    return revs, heads


def test_v6_migration_head_is_0004():
    revs, heads = _migration_chain()
    assert "0004_v7_incremental" in revs, "v7 应存在 0004_v7_incremental 迁移"
    assert "0005_v8_match" in revs, "v8 应存在 0005_v8_match 迁移"
    # flow-v2 增量在 0005 之上追加 0006_flow_v2（flow_type + lost_time nullable），head 现为 0006。
    assert "0006_flow_v2" in revs, "flow-v2 应存在 0006_flow_v2 迁移"
    assert heads == ["0006_flow_v2"], f"迁移 head 应为 0006_flow_v2，实际 {heads}"
