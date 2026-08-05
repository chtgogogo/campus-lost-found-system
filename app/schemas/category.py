"""物品分类 Schema（§3.8 / §2.2）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CategoryCreate(BaseModel):
    """创建/更新分类请求体。"""

    name: str = Field(..., min_length=1, max_length=50)
    yolo_class_id: Optional[int] = None
    recognition_mode: int = 0  # 0=COCO, 1=YOLO-World
    yolo_prompt: Optional[str] = Field(None, max_length=120)
    parent_id: Optional[int] = None
    is_active: int = 1


class CategoryOut(BaseModel):
    """分类输出。"""

    id: int
    name: str
    yolo_class_id: Optional[int] = None
    recognition_mode: int
    yolo_prompt: Optional[str] = None
    parent_id: Optional[int] = None
    is_active: int

    @classmethod
    def from_model(cls, cat) -> "CategoryOut":
        return cls(
            id=cat.id,
            name=cat.name,
            yolo_class_id=cat.yolo_class_id,
            recognition_mode=int(cat.recognition_mode),
            yolo_prompt=cat.yolo_prompt,
            parent_id=cat.parent_id,
            is_active=int(cat.is_active),
        )
