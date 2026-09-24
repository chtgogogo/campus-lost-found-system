"""轻量可观测层（v17⑤）：request_id 全链路 + JSON 结构化日志 + /metrics + 慢 SQL 日志。

零外部依赖（标准库 logging / contextvars / time，不引 Prometheus 等重型组件），
单机校园项目的诚实规模。简历口径：「请求 ID 全链路贯穿结构化日志 + /metrics 暴露
QPS/p95/错误率 + 慢 SQL 日志，零外部依赖」。

四件套：
1. ``RequestIdMiddleware``：每请求生成/透传 ``X-Request-ID``（响应头回写），
   写入 ContextVar——任何层的日志行自动携带，故障可用 request_id 把一条请求的
   全部日志（含慢 SQL 告警）串成一条线；
2. ``JsonFormatter``：标准库 logging Formatter，输出单行 JSON
   （time/level/logger/message/request_id/extra），由 ``LOG_JSON`` 开关启用；
3. ``metrics`` 进程内指标：按 (方法, 路由模板) 聚合请求数/错误数/耗时样本，
   ``/metrics`` 暴露 QPS、p95、错误率；样本环形上限防内存膨胀；
4. 慢 SQL 监听：SQLAlchemy ``before/after_cursor_execute`` 事件，
   超过 ``SLOW_SQL_MS``（默认 100ms）打 WARNING（含耗时与语句摘要）。

演示端点见 ``main.py`` 的 ``/__demo/slow``（``OBS_DEMO_ENDPOINT=true`` 才挂载，
演示「慢接口 + 慢 SQL」如何被 request_id 串成一条线；明确标注为演示用途）。
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from sqlalchemy import event

from app.core.config import settings

# request_id 贯穿：中间件写入，logging filter 与 /metrics 读取
REQUEST_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_METRICS_MAX_SAMPLES = 1000  # 每路由保留的最近耗时样本数（环形，防内存膨胀）

logger = logging.getLogger("observability")


def get_request_id() -> str:
    """当前请求的 request_id（无请求上下文时返回 "-"）。"""
    return REQUEST_ID_VAR.get()


class RequestIdFilter(logging.Filter):
    """给每条日志记录注入 request_id（供 formatter 输出，全链路贯穿）。"""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = REQUEST_ID_VAR.get()
        return True


class JsonFormatter(logging.Formatter):
    """单行 JSON 结构化日志（标准库实现，无第三方依赖）。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", REQUEST_ID_VAR.get()),
        }
        for key in ("duration_ms", "statement", "method", "path", "status_code"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_logging_configured = False


def setup_logging() -> None:
    """按 ``LOG_JSON`` 装配根日志：JSON 结构化 或 人类可读（均携带 request_id）。

    幂等：只装配一次（create_app 可能被多次调用，重复装配会清掉 pytest caplog 等外部 handler）。
    """
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler()
    if settings.LOG_JSON:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


# ---------------- 请求指标（进程内按路由聚合） ----------------

class _RouteStats:
    __slots__ = ("count", "errors", "samples", "_durations")

    def __init__(self) -> None:
        self.count = 0
        self.errors = 0
        self.samples = 0
        self._durations: list[float] = []  # 最近 N 个请求耗时（ms）

    def observe(self, duration_ms: float, is_error: bool) -> None:
        self.count += 1
        if is_error:
            self.errors += 1
        if len(self._durations) >= _METRICS_MAX_SAMPLES:
            self._durations.pop(0)
        self._durations.append(duration_ms)
        self.samples += 1

    def p95(self) -> float | None:
        if not self._durations:
            return None
        ordered = sorted(self._durations)
        idx = min(len(ordered) - 1, max(0, round(0.95 * len(ordered) + 0.5) - 1))
        return ordered[idx]


class MetricsRegistry:
    """进程内指标注册表：{(method, route_template): _RouteStats}，线程安全靠 GIL 原子操作。"""

    def __init__(self) -> None:
        self.started_at = time.time()
        self.routes: "OrderedDict[tuple[str, str], _RouteStats]" = OrderedDict()

    def observe(self, method: str, route: str, duration_ms: float, status_code: int) -> None:
        key = (method, route)
        stats = self.routes.get(key)
        if stats is None:
            stats = _RouteStats()
            self.routes[key] = stats
        stats.observe(duration_ms, status_code >= 500)

    def snapshot(self) -> dict:
        uptime = max(0.0, time.time() - self.started_at)
        rows = []
        for (method, route), stats in self.routes.items():
            count = stats.count
            rows.append(
                {
                    "method": method,
                    "route": route,
                    "count": count,
                    "qps": round(count / uptime, 2) if uptime > 0 else 0.0,
                    "errors": stats.errors,
                    "error_rate": round(stats.errors / count, 4) if count else 0.0,
                    "p95_ms": round(stats.p95(), 1) if stats.p95() is not None else None,
                    "avg_ms": (
                        round(sum(stats._durations) / len(stats._durations), 1)
                        if stats._durations
                        else None
                    ),
                }
            )
        return {"uptime_sec": round(uptime, 1), "window_samples": _METRICS_MAX_SAMPLES, "routes": rows}


metrics = MetricsRegistry()


class ObservabilityMiddleware:
    """request_id + 指标采集中间件（Starlette 纯 ASGI 实现，零依赖）。

    request_id 优先透传上游的 ``X-Request-ID``（网关/前端追踪用），否则生成短随机 id。
    路由模板取 ``scope["route"].path``（FastAPI 匹配后注入），未匹配请求记 ``unmatched``。
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id")
        request_id = (
            incoming.decode("ascii", errors="replace")[:64]
            if incoming
            else uuid.uuid4().hex[:12]
        )
        token = REQUEST_ID_VAR.set(request_id)
        started = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers") or [])
                raw_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = raw_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            route = scope.get("route")
            route_path = getattr(route, "path", None) or "unmatched"
            status_code = scope.get("state", {}).get("_obs_status") or 0
            method = scope.get("method", "?")
            metrics.observe(method, route_path, duration_ms, status_code)
            logger.info(
                "%s %s -> %s %.1fms",
                method,
                scope.get("path", "-"),
                status_code,
                duration_ms,
                extra={"method": method, "path": scope.get("path", "-"), "status_code": status_code},
            )
            REQUEST_ID_VAR.reset(token)


class StatusCaptureMiddleware:
    """捕获响应状态码到 scope.state（供 ObservabilityMiddleware 统计错误率）。

    独立小中间件的原因：ASGI 下 send 包装能拿到状态码，但把「采集」与「状态捕获」
    分开后，ObservabilityMiddleware 可以放在最外层（尽早设置 request_id）。
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        scope.setdefault("state", {})

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                scope["state"]["_obs_status"] = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ---------------- 慢 SQL 监听 ----------------

_query_start: contextvars.ContextVar[float] = contextvars.ContextVar("query_start", default=0.0)


def register_slow_sql_listener(engine) -> None:
    """注册 SQLAlchemy 游标事件：耗时 > SLOW_SQL_MS 的语句打 WARNING（含 request_id）。"""

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        context._obs_query_start = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        start = getattr(context, "_obs_query_start", None)
        if start is None:
            return
        duration_ms = (time.perf_counter() - start) * 1000
        if duration_ms > settings.SLOW_SQL_MS:
            logger.warning(
                "慢 SQL: %.1fms (阈值 %sms)",
                duration_ms,
                settings.SLOW_SQL_MS,
                extra={"duration_ms": round(duration_ms, 1), "statement": str(statement)[:500]},
            )


def metrics_snapshot_safe() -> dict:
    """/metrics 用：采集本身出错时返回空快照（观测不得拖垮业务）。"""
    try:
        return metrics.snapshot()
    except Exception:  # pragma: no cover - 防御性兜底
        return {"uptime_sec": 0, "routes": []}


# ---------------- 演示端点（OBS_DEMO_ENDPOINT=true 才挂载） ----------------

def register_demo_slow_route(app) -> None:  # noqa: ANN001
    """演示端点：sleep 150ms + 跑一段真实慢 SQL（递归 CTE 计数），双慢叠加。

    用 request_id 演示故障定位：一条请求的「慢接口访问日志 + 慢 SQL 告警」串成一条线。
    **明确标注为演示用途**，默认关闭，由 ``OBS_DEMO_ENDPOINT=true`` 启用。
    """

    @app.get("/__demo/slow", tags=["meta"])
    def demo_slow():  # pragma: no cover - 演示端点，测试仅验证挂载
        """⚠️ 演示端点：人为制造慢接口 + 慢 SQL，供 request_id 全链路追踪演示。"""
        time.sleep(0.15)
        from sqlalchemy import text

        from app.core.database import engine

        with engine.connect() as conn:
            conn.execute(
                text(
                    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c "
                    "WHERE x < 900000) SELECT COUNT(*) FROM c"
                )
            )
        return {"code": 0, "message": "ok（演示：此请求故意慢：150ms sleep + 慢 SQL）", "data": None}
