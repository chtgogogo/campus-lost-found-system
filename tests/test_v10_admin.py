"""v10 变更 C + D：管理员注册 / 管理后台 集成测试（AC-C1~C5、C9；AC-D1~D12）。

安全重点（变更 C）：邀请码机制必须**对外不可探测** —— 错码、空码、不填三者
的响应体必须完全一致（AC-C9）。因此本文件对"响应结构"而非"提示文案"做断言。
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import admin_export_service
from app.services.admin_export_service import ExportDependencyError
from conftest import API, PNG, _fresh_phone, _rand, auth_header, publish_pair


def register_raw(client, tag: str, admin_code=None) -> dict:
    """注册一个用户，可选携带 admin_code，返回完整响应 JSON（不做断言）。"""
    phone = _fresh_phone()
    r = client.post(f"{API}/auth/send-sms", json={"phone": phone, "purpose": "register"})
    assert r.status_code == 200, r.text
    dev_code = r.json()["data"]["dev_code"]

    payload = {
        "student_no": _rand(f"{tag}_"),
        "phone": phone,
        "sms_code": dev_code,
        "password": "Passw0rd!",
        "real_name": tag,
    }
    if admin_code is not None:
        payload["admin_code"] = admin_code
    r = client.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def make_admin(client, tag: str = "adm") -> str:
    """注册一个管理员并返回其 access_token。"""
    body = register_raw(client, tag, admin_code=settings.ADMIN_APPLY_CODE)
    assert body["data"]["user"]["role"] == 1, "邀请码正确时应升为管理员"
    return body["data"]["token"]["access_token"]


# ===========================================================================
# 变更 C：管理员注册
# ===========================================================================
def test_c1_correct_invite_code_grants_admin(client):
    """AC-C1：邀请码正确 → 静默升为 role=1。"""
    body = register_raw(client, "c1", admin_code=settings.ADMIN_APPLY_CODE)
    assert body["code"] == 0
    assert body["data"]["user"]["role"] == 1


def test_c2_wrong_invite_code_degrades_silently(client):
    """AC-C2：邀请码错误 → 静默降级 role=0，**注册照常成功**（不报错、不拒绝）。"""
    body = register_raw(client, "c2", admin_code="wrong-code-xxx")
    assert body["code"] == 0, "错码不得导致注册失败"
    assert body["data"]["user"]["role"] == 0


def test_c3_empty_invite_code_is_not_admin(client):
    """空串邀请码不得命中（否则空配置会导致全员管理员）。"""
    assert register_raw(client, "c3", admin_code="")["data"]["user"]["role"] == 0


def test_c3_whitespace_invite_code_is_not_admin(client):
    """纯空白邀请码等价于未填写。"""
    assert register_raw(client, "c3b", admin_code="   ")["data"]["user"]["role"] == 0


def test_c5_register_without_admin_code_unchanged(client):
    """AC-C5：不传 `admin_code` 的老调用零回归 —— 正常注册为普通用户。"""
    body = register_raw(client, "c5", admin_code=None)
    assert body["code"] == 0
    assert body["data"]["user"]["role"] == 0
    assert body["data"]["token"]["access_token"]


def test_c9_wrong_code_and_no_code_are_indistinguishable(client):
    """AC-C9（安全核心）：错码与不填的响应**结构完全一致**，不可被探测。

    只比较结构与 role，不比较 id/token/学号这类天然随机的字段。
    """
    wrong = register_raw(client, "c9a", admin_code="definitely-not-the-code")
    absent = register_raw(client, "c9b", admin_code=None)

    assert wrong["code"] == absent["code"]
    assert wrong["message"] == absent["message"]
    assert set(wrong["data"].keys()) == set(absent["data"].keys())
    assert set(wrong["data"]["user"].keys()) == set(absent["data"]["user"].keys())
    assert wrong["data"]["user"]["role"] == absent["data"]["user"]["role"] == 0


def test_c_empty_configured_code_disables_mechanism(client, monkeypatch):
    """运维把 `ADMIN_APPLY_CODE` 配成空串时，**任何**邀请码都不得命中。

    缺少 `bool(expected)` 护栏时，"不填邀请码"会与空串相等 → 全员管理员，严重越权。
    """
    monkeypatch.setattr(settings, "ADMIN_APPLY_CODE", "")
    assert register_raw(client, "c0a", admin_code="")["data"]["user"]["role"] == 0
    assert register_raw(client, "c0b", admin_code=None)["data"]["user"]["role"] == 0
    assert register_raw(client, "c0c", admin_code="110")["data"]["user"]["role"] == 0


def test_c_admin_registration_writes_audit(client):
    """AC-C4：管理员注册落 `register_admin` 审计埋点。"""
    from app.core.database import SessionLocal
    from app.models.audit import AuditLog

    make_admin(client, "c4")
    with SessionLocal() as db:
        actions = [
            a.action for a in db.query(AuditLog)
            .filter(AuditLog.action == "register_admin").all()
        ]
    assert "register_admin" in actions


# ===========================================================================
# 变更 D1：GET /admin/users
# ===========================================================================
def test_d1_list_users_requires_admin(client):
    """普通用户访问后台接口必须被拒（非 2xx）。"""
    from conftest import register_and_login

    token, *_ = register_and_login(client, "d1n")
    r = client.get(f"{API}/admin/users", headers=auth_header(token))
    assert r.status_code >= 400, "普通用户不得访问 /admin/users"


def test_d1_list_users_returns_plaintext_phone(client):
    """AC-D1：管理员可见**明文**手机号（区别于 UserOut 的脱敏）。"""
    token = make_admin(client, "d1")
    r = client.get(f"{API}/admin/users", headers=auth_header(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0

    items = body["data"]["items"]
    assert items, "至少应有刚注册的管理员自己"
    for user in items:
        assert "*" not in user["phone"], f"管理后台手机号必须明文，实际 {user['phone']}"
        assert set(user) >= {
            "id", "student_no", "phone", "real_name", "role", "credit_score",
            "status", "created_at",
        }


def test_d1_list_users_pagination_shape(client):
    """分页信封字段齐全，且 page/page_size 回显正确。"""
    token = make_admin(client, "d1p")
    r = client.get(
        f"{API}/admin/users", headers=auth_header(token), params={"page": 1, "page_size": 2}
    )
    data = r.json()["data"]
    assert set(data) >= {"items", "total", "page", "page_size"}
    assert data["page"] == 1 and data["page_size"] == 2
    assert len(data["items"]) <= 2


def test_d1_list_users_filter_by_role(client):
    """`role=1` 过滤只返回管理员。"""
    token = make_admin(client, "d1r")
    r = client.get(f"{API}/admin/users", headers=auth_header(token), params={"role": 1})
    items = r.json()["data"]["items"]
    assert items, "至少应命中自己"
    assert all(u["role"] == 1 for u in items)


def test_d1_list_users_keyword_matches_student_no(client):
    """`keyword` 对学号做 LIKE 匹配。"""
    body = register_raw(client, "d1k", admin_code=settings.ADMIN_APPLY_CODE)
    token = body["data"]["token"]["access_token"]
    student_no = body["data"]["user"]["student_no"]

    r = client.get(
        f"{API}/admin/users", headers=auth_header(token), params={"keyword": student_no}
    )
    items = r.json()["data"]["items"]
    assert [u["student_no"] for u in items] == [student_no]


# ===========================================================================
# 变更 D2：GET /admin/matches/{id}/detail
# ===========================================================================
def test_d2_match_detail_returns_both_sides_and_conversation(client):
    """AC-D2：详情含双方明文用户与结构化对话数组。"""
    _, _, _, match_id = publish_pair(client)
    token = make_admin(client, "d2")

    r = client.get(f"{API}/admin/matches/{match_id}/detail", headers=auth_header(token))
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["match"]["id"] == match_id
    assert set(data) >= {"match", "lost_user", "found_user", "conversation"}
    assert isinstance(data["conversation"], list), "无会话时也必须是空数组而非 null"
    for side in ("lost_user", "found_user"):
        if data[side]:
            assert "*" not in data[side]["phone"]


def test_d2_match_detail_404_for_missing(client):
    """匹配不存在 → 404 + code 9001（不得 500）。"""
    token = make_admin(client, "d2m")
    r = client.get(f"{API}/admin/matches/99999999/detail", headers=auth_header(token))
    assert r.status_code == 404
    assert r.json()["code"] == 9001


def test_d2_match_out_carries_v10_dimensions(client):
    """详情里的 MatchOut 必须带上 v10 十个新字段（前端明细依赖）。"""
    _, _, _, match_id = publish_pair(client)
    token = make_admin(client, "d2v")
    match = client.get(
        f"{API}/admin/matches/{match_id}/detail", headers=auth_header(token)
    ).json()["data"]["match"]

    for key in (
        "photo_category", "qty", "color", "state", "place", "keyword",
        "signals", "raw_total", "norm_factor", "provided_dims",
    ):
        assert key in match, f"MatchOut 缺少 v10 字段 {key}"


# ===========================================================================
# 变更 D3：POST /admin/export（scope × format）
# ===========================================================================
def test_d8_legacy_export_call_still_csv(client):
    """AC-D8：老前端只传 `ids` → 与 v7 行为一致（CSV + 全量取证列）。

    v8 长表（2026-08-20）：整张 CSV 仅为一张表 `[记录ID, 字段, 值, 说明]`，
    不再保留 v7 的宽表头；故改为断言"match_id 字段作为长表行的「字段」列存在"。
    """
    _, _, _, match_id = publish_pair(client)
    token = make_admin(client, "d8")

    r = client.post(f"{API}/admin/export", headers=auth_header(token), json={"ids": [match_id]})
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    # 剥掉 # 取证声明注释行后，第一行应是长表表头
    non_comment = [ln for ln in r.text.splitlines() if not ln.lstrip().startswith("#")]
    assert non_comment and non_comment[0].startswith("记录ID,字段,值,说明"), \
        f"长表表头不符：{non_comment[0] if non_comment else '<空>'}"
    # 取证数据：match_id 字段 + 值=match_id 应同时出现于长表某行
    assert f",match_id,{match_id}," in r.text


@pytest.mark.parametrize("scope", ["profile", "conversation", "all"])
def test_d3_export_csv_all_scopes(client, scope):
    """三种 scope 的 CSV 导出都应成功。

    - `profile` / `all`：长表表头 `[记录ID, 字段, 值, 说明]`；
    - `conversation`：**无长表**，只有独立对话流水（时间 角色：内容）。
    """
    _, _, _, match_id = publish_pair(client)
    token = make_admin(client, f"d3{scope[:3]}")

    r = client.post(
        f"{API}/admin/export",
        headers=auth_header(token),
        json={"ids": [match_id], "format": "csv", "scope": scope},
    )
    assert r.status_code == 200, r.text
    if scope == "conversation":
        # 对话流水独立于长表：应为「时间 角色：内容」的可读形式（无对话时注明）
        assert "对话记录" in r.text, f"scope=conversation 应含对话流水区块：{r.text[:200]}"
        assert (
            "失主：" in r.text or "拾得者：" in r.text or "无对话记录" in r.text
        ), f"对话流水应含角色+内容（或无对话提示）：{r.text[:200]}"
        return
    non_comment = [ln for ln in r.text.splitlines() if not ln.lstrip().startswith("#")]
    assert non_comment and non_comment[0].startswith("记录ID,字段,值,说明"), \
        f"scope={scope} 表头应为 记录ID,字段,值,说明，实际 {non_comment[0] if non_comment else '<空>'}"
    # 不应再有「字段说明」单独块
    assert "字段说明" not in r.text
    # v9：编码字段说明直接解出含义（status=2 → 已完成）
    assert "匹配状态：" in r.text and "已完成" in r.text, "status 说明应解出具体含义"


def test_d3_export_md_is_markdown(client):
    """md 导出零依赖，应产出 Markdown 表格。

    v8 长表：不再按匹配分节（## 匹配 #N），整张 md 就是一张大表 [记录ID | 字段 | 值 | 说明]。
    """
    _, _, _, match_id = publish_pair(client)
    token = make_admin(client, "d3md")

    r = client.post(
        f"{API}/admin/export",
        headers=auth_header(token),
        json={"ids": [match_id], "format": "md", "scope": "profile"},
    )
    assert r.status_code == 200, r.text
    assert "# 失物招领取证导出" in r.text
    # v8 长表头与表头分隔行
    assert "| 记录ID | 字段 | 值 | 说明 |" in r.text
    assert "| --- | --- | --- | --- |" in r.text
    # 该匹配记录应在表中出现
    assert f"| {match_id} | match_id | {match_id} |" in r.text


def test_d3_export_xlsx_is_zip_container(client):
    """xlsx 导出应返回真正的 xlsx（zip 魔数 PK）。"""
    pytest.importorskip("openpyxl")
    _, _, _, match_id = publish_pair(client)
    token = make_admin(client, "d3x")

    r = client.post(
        f"{API}/admin/export",
        headers=auth_header(token),
        json={"ids": [match_id], "format": "xlsx", "scope": "all"},
    )
    assert r.status_code == 200, r.text
    assert r.content[:2] == b"PK", "xlsx 必须是 zip 容器"
    assert "spreadsheetml" in r.headers["content-type"]


@pytest.mark.parametrize(
    "payload",
    [
        {"ids": [], "format": "pdf"},
        {"ids": [], "scope": "everything"},
        {"ids": [], "format": "csv", "scope": "not-a-scope"},
    ],
)
def test_d3_invalid_scope_or_format_returns_400(client, payload):
    """非法 scope/format → 400 + code 9001（**不得 500**）。"""
    token = make_admin(client, "d3bad")
    r = client.post(f"{API}/admin/export", headers=auth_header(token), json=payload)
    assert r.status_code == 400
    assert r.json()["code"] == 9001


def test_d12_missing_openpyxl_returns_400_not_500(client, monkeypatch):
    """AC-D12：openpyxl 缺失 → 400 + code 9001，绝不冒泡成 500 堆栈。"""
    token = make_admin(client, "d12")

    def _boom(*args, **kwargs):
        raise ExportDependencyError("服务器未安装 openpyxl，无法导出 xlsx")

    monkeypatch.setattr(admin_export_service, "render_xlsx", _boom)

    r = client.post(
        f"{API}/admin/export",
        headers=auth_header(token),
        json={"ids": [], "format": "xlsx", "scope": "all"},
    )
    assert r.status_code == 400, f"应降级为 400，实际 {r.status_code}"
    assert r.json()["code"] == 9001


def test_d3_export_requires_admin(client):
    """普通用户不得导出取证数据。"""
    from conftest import register_and_login

    token, *_ = register_and_login(client, "d3n")
    r = client.post(f"{API}/admin/export", headers=auth_header(token), json={"ids": []})
    assert r.status_code >= 400


# ===========================================================================
# 变更 D4：GET /admin/matches?all_time
# ===========================================================================
def test_d4_matches_default_behaviour_unchanged(client):
    """不传 `all_time` 时行为与 v7 完全一致（留存窗生效），响应为标准分页。"""
    publish_pair(client)
    token = make_admin(client, "d4a")

    r = client.get(f"{API}/admin/matches", headers=auth_header(token))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert set(data) >= {"items", "total", "page", "page_size"}


def test_d4_all_time_returns_superset(client):
    """`all_time=true` 跳过时间窗 → 条数必然 ≥ 默认查询。"""
    publish_pair(client)
    token = make_admin(client, "d4b")

    default_total = client.get(
        f"{API}/admin/matches", headers=auth_header(token)
    ).json()["data"]["total"]
    all_time_total = client.get(
        f"{API}/admin/matches", headers=auth_header(token), params={"all_time": "true"}
    ).json()["data"]["total"]

    assert all_time_total >= default_total


def test_d4_matches_audit_and_detail_endpoints_write_audit(client):
    """AC-D9：`admin_list_users` / `admin_view_match_detail` / `admin_export` 三处埋点落库。"""
    from app.core.database import SessionLocal
    from app.models.audit import AuditLog

    _, _, _, match_id = publish_pair(client)
    token = make_admin(client, "d9")

    client.get(f"{API}/admin/users", headers=auth_header(token))
    client.get(f"{API}/admin/matches/{match_id}/detail", headers=auth_header(token))
    client.post(f"{API}/admin/export", headers=auth_header(token), json={"ids": [match_id]})

    with SessionLocal() as db:
        actions = {a.action for a in db.query(AuditLog).all()}
    for expected in ("admin_list_users", "admin_view_match_detail", "admin_export"):
        assert expected in actions, f"缺少审计埋点 {expected}，实际 {sorted(actions)}"
