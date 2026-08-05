"""安全工具：密码哈希、JWT 签发/校验、刷新令牌存储。

- 密码：passlib[bcrypt]。
- JWT：HS256，payload = {sub, role, jti, exp, iat}。
- 刷新令牌：jti 存入 KV 存储（Redis 优先，否则内存兜底），支持登出/封禁吊销。
"""
from __future__ import annotations

import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

from app.core import redis_client
from app.core.config import settings


# ---------------- 密码 ----------------
def hash_password(plain: str) -> str:
    """bcrypt 哈希明文密码。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------- JWT ----------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: int, role: int) -> str:
    """签发 access token（默认 120 分钟）。"""
    now = _now()
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": f"a-{user_id}-{int(now.timestamp())}",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MIN)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int, role: int) -> str:
    """签发 refresh token（默认 7 天），并将 jti 写入 KV 存储。"""
    now = _now()
    jti = f"r-{user_id}-{int(now.timestamp())}"
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)).timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    # 存储 jti -> user_id，过期时间 = refresh 有效期
    redis_client.kv.set_jti(
        jti, str(user_id), ttl_sec=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    )
    return token


def decode_token(token: str) -> dict:
    """解码并校验 JWT（签名 + 未过期）。失败抛 jwt 异常。"""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def revoke_refresh_token(jti: str) -> None:
    """吊销刷新令牌（登出 / 封禁）。"""
    redis_client.kv.delete_jti(jti)


def is_refresh_token_valid(jti: str) -> bool:
    """检查 refresh token 的 jti 是否仍有效（未被吊销）。"""
    return redis_client.kv.get_jti(jti) is not None
