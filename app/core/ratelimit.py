"""API 限流（v13）：固定窗口计数器，复用 ``redis_client.kv``（Redis 优先，内存兜底）。

设计要点：
- **固定窗口**（60s）：以 ``int(time // 60)`` 为窗口号拼接 key，``kv.incr`` 原子计数；
  窗口切换后旧 key 靠 TTL 自然过期。对防刷场景足够，不需要精确滑动窗口。
- **开关**：``RATE_LIMIT_ENABLED=False``（测试/本地一键关闭）或 ``DEBUG=True``
  （开发/测试套件同 IP 高频注册登录，全局关闭避免误伤）时直接放行。
- **异常**：超限抛 ``RateLimitError``（HTTP 429，exceptions.py 既有）。
"""
from __future__ import annotations

import time

from app.core import redis_client
from app.core.config import settings
from app.core.exceptions import RateLimitError


def check_rate_limit(key: str, limit_per_min: int) -> None:
    """按 ``key``（如 ``user:3`` / ``ip:1.2.3.4``）做每分钟限流。

    Args:
        key: 限流对象标识（调用方负责拼前缀区分维度）。
        limit_per_min: 每分钟允许的最大次数。

    Raises:
        RateLimitError: 超过窗口内限额（HTTP 429）。
    """
    if not settings.RATE_LIMIT_ENABLED or settings.DEBUG:
        return
    window = int(time.time() // 60)
    count = redis_client.kv.incr(f"ratelimit:{key}:{window}", ttl_sec=120)
    if count > limit_per_min:
        raise RateLimitError(f"请求过于频繁，请 {60 - int(time.time() % 60)} 秒后再试")
