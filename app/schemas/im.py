"""即时通讯 Schema（§3.5，IM 为 P1 增量，此处仅建模型供后续路由复用）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PeerUser(BaseModel):
    """会话对方用户摘要（v5「我的消息」列表用）。"""

    id: int
    nickname: str  # real_name 或「用户{id}」
    student_no: str


class IMSessionListItem(BaseModel):
    """「我的消息」列表富化项（v5 新增，不污染既有 IMSessionOut 契约）。

    - ``peer_user``：对方用户摘要
    - ``title``：后端拼好的「联系对方 · {物品标题}」
    - ``last_message_at``：会话最后消息时间（无消息则取会话创建占位）
    - ``last_message_preview``：最后一条消息截断（~20 字），无则 null
    - ``unread``：粗粒度未读（最后消息存在且 sender_id != 当前用户）
    """

    id: int
    match_id: Optional[int] = None
    found_id: Optional[int] = None
    lost_user_id: int
    finder_user_id: int
    peer_user: PeerUser
    title: str
    last_message_at: Optional[datetime] = None
    last_message_preview: Optional[str] = None
    unread: bool = False
    status: int


class IMSessionCreate(BaseModel):
    """创建会话请求体。

    v4：支持无 match 的「联系」入口——传 ``found_id``（不传 ``match_id``）即绑定到具体拾物。
    二者至少传其一。
    """

    match_id: Optional[int] = None
    found_id: Optional[int] = None


class IMSessionOut(BaseModel):
    """会话输出。"""

    id: int
    match_id: Optional[int] = None
    found_id: Optional[int] = None
    lost_user_id: int
    finder_user_id: int
    status: int
    created_at: datetime
    last_message_at: Optional[datetime] = None
    expires_at: datetime


class IMMessageCreate(BaseModel):
    """发送消息请求体（上行帧）。"""

    type: str = Field("text", description="text | template")
    content: str = Field(..., max_length=500, description="文本内容或模板 id")


class IMMessageOut(BaseModel):
    """消息输出（下行帧）。"""

    id: int
    session_id: int
    sender_id: int
    sender_role: int
    content_type: int
    content: str
    sent_at: datetime
