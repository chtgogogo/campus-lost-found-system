"""统一响应包装与公共枚举（§5.1 / §5.2）。

- `StandardResponse[DataT]`：成功响应泛型 `{code, message, data}`。
- `ErrorResponse`：失败响应用（data=null）。
- `Page[T]`：分页容器。
- 全局枚举：角色 / 状态 / 交接码状态等。
"""
from __future__ import annotations

from enum import IntEnum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class StandardResponse(BaseModel, Generic[DataT]):
    """统一成功响应包装。"""

    code: int = 0
    message: str = "success"
    data: Optional[DataT] = None


class ErrorResponse(BaseModel):
    """统一失败响应（data 一般为 null，参数校验错误时承载错误明细）。"""

    code: int
    message: str
    data: Any = None


class Page(BaseModel, Generic[DataT]):
    """分页数据容器。"""

    items: list[DataT]
    total: int
    page: int
    page_size: int


def success(data: DataT | None = None, message: str = "success") -> StandardResponse[DataT]:
    """构造成功响应。"""
    return StandardResponse[DataT](code=0, message=message, data=data)


# ---------------- 枚举 ----------------
class UserRole(IntEnum):
    NORMAL = 0
    ADMIN = 1


class UserStatus(IntEnum):
    NORMAL = 0
    BANNED = 1


class LostItemStatus(IntEnum):
    PENDING_MATCH = 0   # 待匹配
    MATCHING = 1        # 匹配中
    PENDING_CLAIM = 2   # 待认领
    RESOLVED = 3        # 已解决


class FoundItemStatus(IntEnum):
    PENDING = 0         # 待认领
    RESOLVED = 1        # 已解决


class MatchStatus(IntEnum):
    PENDING_CLAIM = 0   # 待认领
    CLAIMING = 1        # 认领中
    COMPLETED = 2       # 已完成
    REJECTED = 3        # 已拒绝
    MANUAL_PENDING = 4  # 待自取（v4 手动申请匹配，失主单边完成）
    GIVEN_UP = 5        # 已放弃 / 未找回（v5：软删匹配 + 失物重入匹配池；零迁移扩展 SmallInt 值域）
    REVOKED = 6         # 已撤回（v2：keep1 完成记录撤回后的终态，Q7 拍板）


class KeepStatus(IntEnum):
    KEEPING = 0         # 暂为保管
    NOT_KEEPING = 1     # 未保管


class HandoverStatus(IntEnum):
    VALID = 0           # 有效
    VERIFIED = 1        # 已验证
    EXPIRED = 2         # 已过期


class SenderRole(IntEnum):
    LOST = 0            # 失主
    FINDER = 1          # 拾得者


class ContentType(IntEnum):
    TEXT = 0
    TEMPLATE = 1


class RecognitionMode(IntEnum):
    COCO = 0            # YOLOv8-COCO
    WORLD = 1           # YOLO-World 零样本


class AuditAction(IntEnum):
    PUBLISH = 1
    CLAIM = 2
    HANDOVER = 3
    APPEAL = 4
    BAN = 5
    IM_MESSAGE = 6   # v3 需求 D：IM 消息镜像（冒领溯源）
