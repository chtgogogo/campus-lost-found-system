"""管理后台 Schema（v10 变更 D）。

仅承载「管理员视角」的响应结构：匹配详情（含结构化对话）与导出请求扩展枚举。
用户列表复用 `app/schemas/user.py::AdminUserOut`（手机号明文，禁止复用会脱敏的 `UserOut`）。

时间统一朴素 UTC（与 `admin.py::_now` / `cleanup.py::_now` 一致），禁止混入 aware datetime。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.match import MatchOut
from app.schemas.user import AdminUserOut

# 导出范围 / 格式枚举（前后端共享口径；非法值由路由层返回 400 + code 9001）
ExportScope = Literal["profile", "conversation", "all"]
ExportFormat = Literal["csv", "xlsx", "md"]


class AdminConversationItem(BaseModel):
    """匹配详情中的单条 IM 消息（结构化，供后台对话气泡渲染）。"""

    sent_at: Optional[datetime] = Field(None, description="发送时间（朴素 UTC）")
    sender_role: int = Field(0, description="0=失主 1=拾得者")
    role_label: str = Field("", description="角色中文名，避免前端再映射一次")
    content: str = Field("", description="消息正文")


class AdminMatchDetailOut(BaseModel):
    """`GET /admin/matches/{match_id}/detail` 响应体。

    Q11：**不硬限制** `match.status == 2`，任意状态的匹配都可查看详情
    （UI 默认从已完成列表进入，但取证时常需要看未完成/已拒绝的会话）。
    """

    match: MatchOut
    lost_user: Optional[AdminUserOut] = Field(None, description="失主（手机号明文）")
    found_user: Optional[AdminUserOut] = Field(None, description="拾得者（手机号明文）")
    conversation: list[AdminConversationItem] = Field(
        default_factory=list, description="全部 IM 消息，按 sent_at 升序；无会话为空数组"
    )
