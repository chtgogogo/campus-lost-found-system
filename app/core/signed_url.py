"""上传图片签名 URL（v20①：/uploads 从公开静态目录改为签名校验路由）。

背景：此前 /uploads 以 StaticFiles 无条件挂载，任何拿到图片路径的人无需登录
即可批量拉取用户照片（失物照片常含人脸/证件，属个保法第 51 条访问控制义务范围）。

思路同对象存储预签名 URL：出口层（schema 序列化）为图片路径附加过期时间 e
与 HMAC 签名 s，路由侧验签通过才回文件。两点设计取舍：

1. 签名有效期按小时取整（同一小时内同一路径生成的 URL 完全一致），
   避免每次刷新列表都产生新 URL 把浏览器缓存击穿；
2. HMAC 密钥复用 JWT_SECRET，但消息加 "uploads-sign:" 域前缀，
   与 JWT 签名跨用途隔离（拿图片签名拼不出 token，反之亦然）。
"""
from __future__ import annotations

import hashlib
import hmac
import time

from app.core.config import settings

SIGN_TTL_SECONDS = 24 * 3600  # 有效期 24h：覆盖一次会话，泄露链接次日自动失效
_SIGN_DOMAIN = "uploads-sign:"


def _secret() -> bytes:
    return settings.JWT_SECRET.encode()


def _digest(path: str, expires: int) -> str:
    msg = f"{_SIGN_DOMAIN}{path}:{expires}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def _hour_floor(ts: float) -> int:
    return int(ts) // 3600 * 3600


def sign_image_url(path: str | None) -> str:
    """出口签名：/uploads/ 开头的相对路径附加 e/s 参数，其余（data:、http、空）原样返回。"""
    if not path or not path.startswith("/uploads/"):
        return path or ""
    expires = _hour_floor(time.time()) + SIGN_TTL_SECONDS
    return f"{path}?e={expires}&s={_digest(path, expires)}"


def verify_image_signature(path: str, expires: int | None, sig: str | None,
                           now: float | None = None) -> bool:
    """路由侧验签：签名匹配且未过期。比较用常数时间函数，防时序侧信道。"""
    if expires is None or sig is None:
        return False
    if not isinstance(expires, int) or expires < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(_digest(path, expires), sig)
