"""视觉预识别响应 Schema（对齐 app/routers/vision.py）。"""
from __future__ import annotations

from pydantic import BaseModel


class VisionCategory(BaseModel):
    """可选分类（供前端手动改类下拉）。"""

    id: int
    name: str


class VisionPredictResponse(BaseModel):
    """视觉预识别结果。

    字段与 `VisionService.predict` 的契约一致：
    `category_id` / `label` / `confidence`（加 `categories` 供前端手动纠偏）。
    """

    category_id: int
    label: str
    confidence: float
    categories: list[VisionCategory] = []
