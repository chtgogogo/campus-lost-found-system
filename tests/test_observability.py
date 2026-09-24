"""v17⑤ 可观测层测试：request_id 贯穿 / JSON 日志 / /metrics 聚合 / 慢 SQL 告警。"""
from __future__ import annotations

import json
import logging

from app.core.config import settings
from app.core.observability import JsonFormatter, metrics, metrics_snapshot_safe


# ---------------- request_id：响应头 + 日志贯穿 ----------------

def test_two_requests_get_different_request_ids(client):
    r1 = client.get("/health")
    r2 = client.get("/health")
    assert r1.status_code == 200 and r2.status_code == 200
    id1 = r1.headers.get("x-request-id")
    id2 = r2.headers.get("x-request-id")
    assert id1 and id2, "响应必须回写 X-Request-ID"
    assert id1 != id2, "每个请求必须有独立的 request_id"


def test_request_id_propagates_to_all_log_lines(client, caplog):
    with caplog.at_level(logging.INFO):
        r = client.get("/health")
    request_id = r.headers.get("x-request-id")
    # 只断言**服务端**观测日志（客户端侧 httpx 日志不在应用请求上下文，request_id 合理为 "-"）
    obs_records = [rec for rec in caplog.records if rec.name == "observability"]
    assert obs_records, "请求链路的服务端日志必须存在"
    assert all(rec.request_id == request_id for rec in obs_records), (
        f"服务端日志 request_id 应与响应头一致（{request_id}）"
    )


def test_incoming_request_id_is_honored(client):
    r = client.get("/health", headers={"X-Request-ID": "trace-from-gateway-123"})
    assert r.headers.get("x-request-id") == "trace-from-gateway-123", "上游 X-Request-ID 应透传"


# ---------------- JSON 结构化日志（标准库实现） ----------------

def test_json_formatter_outputs_parseable_line_with_request_id():
    record = logging.LogRecord(
        name="obs", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    record.request_id = "rid-abc"
    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert payload["message"] == "hello world"
    assert payload["request_id"] == "rid-abc"
    assert payload["level"] == "INFO"
    assert {"time", "level", "logger", "message", "request_id"} <= set(payload)


# ---------------- /metrics：QPS / p95 / 错误率 ----------------

def test_metrics_aggregates_per_route(client):
    before = metrics_snapshot_safe()
    before_health = next(
        (r for r in before["routes"] if r["route"] == "/health" and r["method"] == "GET"),
        {"count": 0},
    )
    client.get("/health")
    client.get("/health")
    snapshot = metrics_snapshot_safe()
    row = next(r for r in snapshot["routes"] if r["route"] == "/health" and r["method"] == "GET")
    assert row["count"] == before_health["count"] + 2, "/health 计数应累加"
    assert row["p95_ms"] is not None and row["qps"] > 0
    assert row["error_rate"] == 0.0, "/health 不应有错误"


def test_metrics_counts_server_errors():
    key = ("GET", "/__test_5xx__")
    metrics.observe("GET", "/__test_5xx__", 5.0, 500)
    metrics.observe("GET", "/__test_5xx__", 7.0, 200)
    row = metrics.snapshot()["routes"][[i for i, r in enumerate(metrics.snapshot()["routes"]) if (r["method"], r["route"]) == key][0]]
    assert row["count"] == 2
    assert row["errors"] == 1
    assert abs(row["error_rate"] - 0.5) < 1e-9, "500 计入错误率"


# ---------------- 慢 SQL 告警 ----------------

def test_slow_sql_warning_fires_below_threshold(db, caplog, monkeypatch):
    monkeypatch.setattr(settings, "SLOW_SQL_MS", 0.0)  # 阈值 0：任何查询都是「慢」
    with caplog.at_level(logging.WARNING, logger="observability"):
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
    slow = [rec for rec in caplog.records if "慢 SQL" in rec.getMessage()]
    assert slow, "低于阈值（0ms）的查询必须触发慢 SQL 告警"
    assert getattr(slow[0], "duration_ms", None) is not None
    assert getattr(slow[0], "statement", None) is not None


def test_no_slow_sql_warning_when_fast(db, caplog, monkeypatch):
    monkeypatch.setattr(settings, "SLOW_SQL_MS", 60_000)  # 阈值 60s：SELECT 1 不可能超
    with caplog.at_level(logging.WARNING, logger="observability"):
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
    assert not [rec for rec in caplog.records if "慢 SQL" in rec.getMessage()]


# ---------------- 演示端点（开关控制） ----------------

def test_demo_endpoint_mounts_only_when_enabled(monkeypatch):
    from app.main import create_app

    monkeypatch.setattr(settings, "OBS_DEMO_ENDPOINT", False)
    assert not any(getattr(r, "path", None) == "/__demo/slow" for r in create_app().routes)
    monkeypatch.setattr(settings, "OBS_DEMO_ENDPOINT", True)
    app = create_app()
    assert any(getattr(r, "path", None) == "/__demo/slow" for r in app.routes), (
        "开关打开时应挂载演示端点"
    )
