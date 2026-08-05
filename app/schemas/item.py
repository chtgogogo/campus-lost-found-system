"""物品（失物 / 拾物）Schema 与发布 DTO（§3.3 / §2.3 / §2.4）。

v3 增量变更：
- 发布 DTO 不再收 `lost_location` / `found_location`（地点语义并入 `description`，见迁移 0002）。
- 输出 `LostItemOut` / `FoundItemOut` 删 `lost_location` / `found_location`，新增 `tags: list[str]`。
- `category_id` 降为可空（仅内部匹配键）；`category_name` 直接读模型字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import FoundItemStatus, LostItemStatus


# ---------------- 发布 DTO（服务层内部使用，图片为原始字节） ----------------
@dataclass
class LostItemPublishDTO:
    """失物发布数据传输对象。"""

    title: str
    description: str
    category_name: str
    lost_time: Optional[datetime] = None  # R3：非必填，未知/记不清可留空
    color: Optional[str] = None
    appearance: Optional[str] = None  # v8：外观描述（材质/形状/颜色）
    features: Optional[str] = None  # v8：特征描述（品牌/数量/特殊标记）
    location: Optional[str] = None  # v8：地点描述
    images: list[tuple[str, bytes]] = field(default_factory=list)  # [(filename, content), ...]


@dataclass
class FoundItemPublishDTO:
    """拾物发布数据传输对象。"""

    keep_status: int
    category_name: str
    images: list[tuple[str, bytes]] = field(default_factory=list)
    description: Optional[str] = None
    found_time: Optional[datetime] = None
    contact_allowed: int = 1
    appearance: Optional[str] = None  # v8：外观描述（材质/形状/颜色）
    features: Optional[str] = None  # v8：特征描述（品牌/数量/特殊标记）
    location: Optional[str] = None  # v8：地点描述


# ---------------- 输出 ----------------
class LostItemOut(BaseModel):
    """失物输出（含自由文本类目名）。"""

    id: int
    publisher_id: int
    category_id: Optional[int] = None
    category_name: str
    title: str
    description: str
    images: list[str] = Field(default_factory=list)
    color: Optional[str] = None
    tags: list[str] = Field(default_factory=list)  # v3 结构化标签
    appearance: Optional[str] = None  # v8：外观描述
    features: Optional[str] = None  # v8：特征描述
    location: Optional[str] = None  # v8：地点描述
    lost_time: Optional[datetime] = None  # R3：非必填，空值前端显示"—"
    status: int
    created_at: datetime
    expires_at: Optional[datetime] = None  # v7：失效时间
    deleted_at: Optional[datetime] = None  # v7：软删时间

    @classmethod
    def from_model(cls, item) -> "LostItemOut":
        images = item.images or []
        return cls(
            id=item.id,
            publisher_id=item.publisher_id,
            category_id=item.category_id,
            category_name=item.category_name,
            title=item.title,
            description=item.description,
            images=list(images),
            color=item.color,
            tags=list(item.tags) if item.tags else [],
            appearance=getattr(item, "appearance", None),
            features=getattr(item, "features", None),
            location=getattr(item, "location", None),
            lost_time=item.lost_time,
            status=int(item.status),
            created_at=item.created_at,
            expires_at=item.expires_at,
            deleted_at=item.deleted_at,
        )


class FoundItemOut(BaseModel):
    """拾物输出。"""

    id: int
    finder_id: int
    category_id: Optional[int] = None
    category_name: str
    description: Optional[str] = None
    images: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)  # v3 结构化标签
    appearance: Optional[str] = None  # v8：外观描述
    features: Optional[str] = None  # v8：特征描述
    location: Optional[str] = None  # v8：地点描述
    found_time: Optional[datetime] = None
    keep_status: int
    contact_allowed: int
    status: int
    created_at: datetime
    expires_at: Optional[datetime] = None  # v7：失效时间
    deleted_at: Optional[datetime] = None  # v7：软删时间

    @classmethod
    def from_model(cls, item) -> "FoundItemOut":
        images = item.images or []
        return cls(
            id=item.id,
            finder_id=item.finder_id,
            category_id=item.category_id,
            category_name=item.category_name,
            description=item.description,
            images=list(images),
            tags=list(item.tags) if item.tags else [],
            appearance=getattr(item, "appearance", None),
            features=getattr(item, "features", None),
            location=getattr(item, "location", None),
            found_time=item.found_time,
            keep_status=int(item.keep_status),
            contact_allowed=int(item.contact_allowed),
            status=int(item.status),
            created_at=item.created_at,
            expires_at=item.expires_at,
            deleted_at=item.deleted_at,
        )


class ItemListQuery(BaseModel):
    """物品列表查询参数。

    v3：仅按 status 过滤，关键词检索由前端承担。
    """
    status: Optional[int] = None
    page: int = 1
    page_size: int = 20
