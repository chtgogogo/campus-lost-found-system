"""图片魔数校验（v13）：按文件头（magic bytes）判定真实类型，拒收伪装文件。

背景：此前仅校验扩展名白名单（storage._safe_ext），未知扩展名还会被静默改存
``.jpg``——把 ``.html/.svg/.exe`` 改名 ``.png`` 即可绕过。本模块在**字节层**校验，
与 ``IMG_MAX_SIZE_MB`` 一起构成发布图片的两道闸。

允许类型与 storage 扩展名白名单对齐：JPEG / PNG / GIF / WEBP / BMP。
（HEIC 需解析 ftyp box 且存储层不支持，统一拒收，前端压缩后均为 JPEG/PNG。）
"""
from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import ParamError

# (名称, 判定函数)：按常见度排列，命中即返回
_MAGIC_SIGNATURES: tuple[tuple[str, object], ...] = (
    ("JPEG", lambda b: b[:3] == b"\xff\xd8\xff"),
    ("PNG", lambda b: b[:8] == b"\x89PNG\r\n\x1a\n"),
    ("GIF", lambda b: b[:6] in (b"GIF87a", b"GIF89a")),
    ("WEBP", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
    ("BMP", lambda b: b[:2] == b"BM"),
)


def detect_image_type(content: bytes) -> str | None:
    """按魔数识别图片真实类型；无法识别返回 None。

    Args:
        content: 文件原始字节。

    Returns:
        类型名（JPEG/PNG/GIF/WEBP/BMP）或 None。空字节安全返回 None。
    """
    if not content:
        return None
    for name, matcher in _MAGIC_SIGNATURES:
        if matcher(content):
            return name
    return None


def validate_images(images: list[tuple[str, bytes]]) -> None:
    """校验发布图片列表：大小上限 + 魔数白名单，违规抛 ``ParamError``。

    Args:
        images: ``[(filename, content), ...]``（与发布 DTO 的 images 字段同构）。

    Raises:
        ParamError: 任一图片超过大小上限，或魔数不在白名单内。
    """
    max_bytes = settings.IMG_MAX_SIZE_MB * 1024 * 1024
    for filename, content in images:
        name = filename or "未命名文件"
        if len(content) > max_bytes:
            raise ParamError(f"图片 {name} 超过 {settings.IMG_MAX_SIZE_MB}MB 上限")
        if detect_image_type(content) is None:
            raise ParamError(
                f"图片 {name} 不是有效图片（仅支持 JPG/PNG/GIF/WEBP/BMP），已拒绝"
            )
