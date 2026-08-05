"""图片上传存储（默认本地磁盘 uploads/，路径在项目内；可扩展 MinIO/OSS）。

返回相对 URL（由 main.py 将 /uploads 挂载到本地目录供静态访问）。
"""
from __future__ import annotations

import os
import uuid
from typing import List, Tuple

from app.core.config import settings

_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def ensure_upload_dir() -> str:
    """确保上传目录存在，返回绝对路径。"""
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    return settings.UPLOAD_DIR


def _safe_ext(filename: str) -> str:
    """从文件名提取安全扩展名，未知则默认 .jpg。"""
    _, ext = os.path.splitext(filename or "")
    ext = ext.lower()
    return ext if ext in _ALLOWED_EXT else ".jpg"


def save_image(filename: str, content: bytes) -> str:
    """保存单张图片，返回静态访问 URL（/uploads/xxx.ext）。"""
    ensure_upload_dir()
    ext = _safe_ext(filename)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    abs_path = os.path.join(settings.UPLOAD_DIR, stored_name)
    with open(abs_path, "wb") as f:
        f.write(content)
    return f"/uploads/{stored_name}"


def save_images(files: List[Tuple[str, bytes]]) -> List[str]:
    """批量保存图片，返回 URL 列表。"""
    return [save_image(name, content) for name, content in files]
