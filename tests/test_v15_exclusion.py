"""v15 增量测试：「不是我的」候选排除与重返。

- 单条排除后从匹配列表隐藏、进入排除池（幂等：重复排除不重复建记录）
- 「重返匹配池」后恢复可见
- 批量排除（「重新匹配」第一步）
- 权限：非失主不可排除；排除不影响对端用户视图
"""
from __future__ import annotations

from conftest import API, PNG, auth_header, publish_pair


class TestExclusion:
    def test_exclude_hides_from_list_and_pool_shows(self, client):
        token_a, token_b, lost_id, match_id = publish_pair(client)
        h = auth_header(token_a)

        # 基线：列表可见 1 条
        r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=h)
        assert r.status_code == 200
        assert len(r.json()["data"]) == 1

        # 排除
        r = client.post(f"{API}/lost-items/{lost_id}/matches/{match_id}/exclude", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["excluded"] is True

        # 列表不再可见
        r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=h)
        assert r.json()["data"] == []

        # 排除池可见（幂等：仍只有 1 条排除记录）
        r = client.get(f"{API}/lost-items/{lost_id}/matches/excluded", headers=h)
        assert r.status_code == 200
        pool = r.json()["data"]
        assert len(pool) == 1
        assert pool[0]["found_id"] and pool[0]["exclusion_id"]

    def test_repeat_exclude_is_idempotent(self, client):
        token_a, _, lost_id, match_id = publish_pair(client)
        h = auth_header(token_a)
        for _ in range(2):
            r = client.post(f"{API}/lost-items/{lost_id}/matches/{match_id}/exclude", headers=h)
            assert r.status_code == 200
        r = client.get(f"{API}/lost-items/{lost_id}/matches/excluded", headers=h)
        assert len(r.json()["data"]) == 1

    def test_restore_returns_to_list(self, client):
        token_a, _, lost_id, match_id = publish_pair(client)
        h = auth_header(token_a)
        client.post(f"{API}/lost-items/{lost_id}/matches/{match_id}/exclude", headers=h)
        r = client.get(f"{API}/lost-items/{lost_id}/matches/excluded", headers=h)
        exclusion_id = r.json()["data"][0]["exclusion_id"]

        # 重返
        r = client.delete(f"{API}/lost-items/{lost_id}/matches/exclusions/{exclusion_id}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["restored"] is True

        # 列表恢复
        r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=h)
        assert len(r.json()["data"]) == 1
        # 排除池清空
        r = client.get(f"{API}/lost-items/{lost_id}/matches/excluded", headers=h)
        assert r.json()["data"] == []

    def test_exclude_batch(self, client):
        token_a, token_b, lost_id, match_id = publish_pair(client)
        h = auth_header(token_a)
        # 再发布一件同类拾物，制造第二个候选
        r = client.post(
            f"{API}/found-items",
            headers=auth_header(token_b),
            data={
                "keep_status": "0",
                "description": "又捡到一个黑色书包，像失主丢的那个",
                "found_location": "图书馆三楼门口",
                "category_name": "书包",
            },
            files={"images": ("f2.png", PNG, "image/png")},
        )
        assert r.status_code == 200, r.text
        # 拿到当前全部候选
        r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=h)
        match_ids = [m["id"] for m in r.json()["data"]]
        assert len(match_ids) >= 2

        # 批量排除
        r = client.post(
            f"{API}/lost-items/{lost_id}/matches/exclude-batch",
            headers=h,
            json={"match_ids": match_ids},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["excluded"] == len(match_ids)

        # 列表清空，排除池有量
        r = client.get(f"{API}/lost-items/{lost_id}/matches", headers=h)
        assert r.json()["data"] == []
        r = client.get(f"{API}/lost-items/{lost_id}/matches/excluded", headers=h)
        assert len(r.json()["data"]) >= 2

    def test_excluded_hidden_in_my_matches_aggregate(self, client):
        """防回归：排除项在「我的匹配」聚合接口同样隐藏（v15.2 修复的泄露点）。"""
        token_a, token_b, lost_id, match_id = publish_pair(client)
        h = auth_header(token_a)
        client.post(f"{API}/lost-items/{lost_id}/matches/{match_id}/exclude", headers=h)
        # 聚合接口：排除项不得出现
        r = client.get(f"{API}/matches", headers=h)
        assert r.status_code == 200
        assert all(m["id"] != match_id for m in r.json()["data"]["items"])
        # 排除池仍可见（可重返）
        r = client.get(f"{API}/lost-items/{lost_id}/matches/excluded", headers=h)
        assert len(r.json()["data"]) == 1

    def test_non_owner_cannot_exclude(self, client):
        token_a, token_b, lost_id, match_id = publish_pair(client)
        # 拾主（非失主）尝试排除 → 拒绝
        r = client.post(
            f"{API}/lost-items/{lost_id}/matches/{match_id}/exclude",
            headers=auth_header(token_b),
        )
        assert r.status_code in (401, 403), r.text

    def test_exclusion_does_not_affect_counterpart_view(self, client):
        """排除是 per-user 视图：失主排除后，拾主侧自己的匹配不受影响。"""
        token_a, token_b, lost_id, match_id = publish_pair(client)
        client.post(f"{API}/lost-items/{lost_id}/matches/{match_id}/exclude", headers=auth_header(token_a))
        # 拾主 B 的「我的匹配」仍能看到该记录
        r = client.get(f"{API}/matches", headers=auth_header(token_b))
        assert r.status_code == 200
        assert any(m["id"] == match_id for m in r.json()["data"]["items"])
