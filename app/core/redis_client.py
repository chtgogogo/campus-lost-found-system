"""KV 存储抽象（Redis 优先，进程内内存兜底）。

MVP 阶段 Redis 可选：若 `REDIS_ENABLED=False` 或连接失败，自动降级为内存字典，
保证单进程开发 / 端到端自测可跑通。生产环境开启 Redis 以获得 TTL 自动失效与限流能力。

- jti 存储：刷新令牌吊销（rt:{jti}）。
- 限流计数：短信 / 接口（ratelimit:{key}）。
"""
from __future__ import annotations

import threading
import time

from app.core.config import settings


class _MemoryStore:
    """极简进程内 KV，支持 TTL（秒）。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, bytes]] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: str, ttl_sec: int | None = None) -> None:
        expire_at = (time.time() + ttl_sec) if ttl_sec else None
        with self._lock:
            self._data[key] = (expire_at or 0.0, value.encode("utf-8"))

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expire_at, raw = item
            if expire_at and time.time() > expire_at:
                self._data.pop(key, None)
                return None
            return raw.decode("utf-8")

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def incr(self, key: str, ttl_sec: int | None = None) -> int:
        with self._lock:
            item = self._data.get(key)
            now = time.time()
            if item:
                expire_at, raw = item
                if expire_at and now > expire_at:
                    item = None
            if not item:
                self._data[key] = (now + ttl_sec if ttl_sec else 0.0, b"1")
                return 1
            expire_at, raw = item
            new_val = int(raw.decode("utf-8")) + 1
            self._data[key] = (expire_at, str(new_val).encode("utf-8"))
            return new_val

    def expire(self, key: str, ttl_sec: int) -> None:
        """刷新已有键的 TTL（秒）；键不存在则忽略。"""
        with self._lock:
            item = self._data.get(key)
            if item:
                self._data[key] = (time.time() + ttl_sec, item[1])


class RedisClient:
    """KV 客户端：优先 Redis，失败/禁用时回退内存。"""

    def __init__(self) -> None:
        self._memory = _MemoryStore()
        self._redis = None
        self.available = False
        if settings.REDIS_ENABLED:
            try:
                import redis  # noqa: F401

                self._redis = redis.Redis.from_url(
                    settings.REDIS_URL, socket_connect_timeout=1.0, socket_timeout=1.0
                )
                self._redis.ping()
                self.available = True
            except Exception:  # pragma: no cover - 环境无 Redis
                self._redis = None
                self.available = False

    # -------- jti（刷新令牌） --------
    def set_jti(self, jti: str, user_id: str, ttl_sec: int) -> None:
        if self.available and self._redis is not None:
            self._redis.set(f"rt:{jti}", user_id, ex=ttl_sec)
        else:
            self._memory.set(f"rt:{jti}", user_id, ttl_sec=ttl_sec)

    def get_jti(self, jti: str) -> str | None:
        if self.available and self._redis is not None:
            val = self._redis.get(f"rt:{jti}")
            return val.decode("utf-8") if val else None
        return self._memory.get(f"rt:{jti}")

    def delete_jti(self, jti: str) -> None:
        if self.available and self._redis is not None:
            self._redis.delete(f"rt:{jti}")
        else:
            self._memory.delete(f"rt:{jti}")

    # -------- 通用限流计数 --------
    def incr(self, key: str, ttl_sec: int | None = None) -> int:
        if self.available and self._redis is not None:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            if ttl_sec:
                pipe.expire(key, ttl_sec)
            results = pipe.execute()
            return int(results[0])
        return self._memory.incr(key, ttl_sec=ttl_sec)

    def get(self, key: str) -> str | None:
        if self.available and self._redis is not None:
            val = self._redis.get(key)
            return val.decode("utf-8") if val else None
        return self._memory.get(key)

    def set(self, key: str, value: str, ttl_sec: int | None = None) -> None:
        if self.available and self._redis is not None:
            self._redis.set(key, value, ex=ttl_sec)
        else:
            self._memory.set(key, value, ttl_sec=ttl_sec)

    def delete(self, key: str) -> None:
        if self.available and self._redis is not None:
            self._redis.delete(key)
        else:
            self._memory.delete(key)

    def expires(self, key: str, ttl_sec: int) -> None:
        """刷新已有键的过期时间（秒）。Redis 走 EXPIRE；内存兜底更新内部 TTL。"""
        if self.available and self._redis is not None:
            self._redis.expire(key, ttl_sec)
        else:
            self._memory.expire(key, ttl_sec)


# 模块级单例
kv = RedisClient()
