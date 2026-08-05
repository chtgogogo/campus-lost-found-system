"""IM 路由（§3.5，v3 需求 D：联系对方）。

端点：
- ``POST /im/sessions``：创建 / 复用对话（携带门控：对端 ``contact_allowed==0`` 时 403）。
- ``GET  /im/sessions/{id}/messages``：轮询历史（前端每 ~4s 拉取，``since_id`` 增量）。
- ``POST /im/sessions/{id}/messages``：发消息（JWT 鉴权 + 门控双保险 + 禁链接 + 镜像 audit_log）。

约束（Q5/Q6/Q7 拍板）：
- 门控唯一来源为 ``found_item.contact_allowed``（v3 不引入 lost_item.contact_allowed）。
- 实时机制为前端轮询（非 WebSocket）。
- 每条消息镜像至 ``audit_log``（``action="im_message"`` / ``target_type="im_session"``），供冒领溯源；
  留存期由 ``IM_RETENTION_DAYS`` 控制（v3：7 → 30）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ParamError, PermissionError
from app.models.im import IMMessage, IMSession
from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord
from app.models.user import User
from app.routers.deps import get_current_user
from app.schemas.common import (
    ContentType,
    FoundItemStatus,
    LostItemStatus,
    MatchStatus,
    SenderRole,
    StandardResponse,
    success,
)
from app.schemas.im import (
    IMMessageCreate,
    IMMessageOut,
    IMSessionCreate,
    IMSessionListItem,
    IMSessionOut,
)
from app.services import audit_service
from app.services import im_service as im_svc

# 禁链接正则：拦截 http(s)://、www.、HTML 锚点，以及常见外链宿主（防骚扰 / 防导流）。
_LINK_PATTERN = re.compile(
    r"(https?://|www\.)"
    r"|(<a\s|href\s*=)"
    r"|(t\.me/|qr\.alipay|w\.paotui|u\.wechat)",
    re.IGNORECASE,
)

router = APIRouter(tags=["im"])


# ---------------- 内部工具 ----------------
def _ensure_participant(session: IMSession, user: User) -> None:
    """当前用户必须是会话双方之一，否则拒绝。"""
    if int(user.id) not in (int(session.lost_user_id), int(session.finder_user_id)):
        raise PermissionError("无权访问该会话")


def _sender_role(session: IMSession, user: User) -> int:
    """按当前用户在会话中的身份推导发送者角色（0 失主 / 1 拾得者）。"""
    if int(user.id) == int(session.lost_user_id):
        return int(SenderRole.LOST)
    if int(user.id) == int(session.finder_user_id):
        return int(SenderRole.FINDER)
    raise PermissionError("无权发送消息")


def _load_found_item(db: Session, session: IMSession) -> Optional[FoundItem]:
    """取得会话关联拾物（用于读取 contact_allowed 门控）。

    v4：优先按 ``found_id``（无 match 的联系会话）；否则回退到 ``match_id``。
    """
    if session.found_id is not None:
        return db.get(FoundItem, session.found_id)
    if session.match_id is None:
        return None
    match = db.get(MatchRecord, session.match_id)
    if match is None:
        return None
    return db.get(FoundItem, match.found_id)


def _contact_gateway_blocked(db: Session, session: IMSession) -> bool:
    """对端 ``contact_allowed==0`` 时禁止会话 / 发送。"""
    found = _load_found_item(db, session)
    if found is None:
        return False
    return int(found.contact_allowed) == 0


# ---------------- 创建 / 复用会话 ----------------
@router.post("/im/sessions", response_model=StandardResponse)
def create_session(
    body: IMSessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建或复用一次「联系对方」会话（门控：对端未开启联系则 403）。

    v4：支持无 match 的「联系」入口——传入 ``found_id``（不传 ``match_id``）即绑定到
    具体拾物，强溯源 + 发送端二次门控；此时 lost_user_id=当前用户、finder_user_id=拾物发布者。
    match_id / found_id 至少传其一。
    """
    if body.found_id is not None:
        found = db.get(FoundItem, body.found_id)
        if found is None:
            raise NotFoundError("拾物不存在")
        lost_user_id = int(user.id)
        finder_user_id = int(found.finder_id)
        # 门控：唯一来源为 found_item.contact_allowed（Q5）
        if int(found.contact_allowed) == 0:
            raise PermissionError("对方暂未开启联系")
        # 复用同一拾物下仍开启的会话
        session = (
            db.query(IMSession)
            .filter(IMSession.found_id == found.id, IMSession.status == 0)
            .order_by(IMSession.id.desc())
            .first()
        )
        if session is None:
            now = datetime.now(timezone.utc)
            session = IMSession(
                match_id=None,
                found_id=found.id,
                lost_user_id=lost_user_id,
                finder_user_id=finder_user_id,
                status=0,
                expires_at=now + timedelta(days=settings.IM_RETENTION_DAYS),
            )
            db.add(session)
            db.flush()
            db.commit()
            db.refresh(session)
        return success(data=_session_out(session))

    # 既有 match_id 路径
    match = db.get(MatchRecord, body.match_id)
    if match is None:
        raise NotFoundError("匹配记录不存在")
    lost = db.get(LostItem, match.lost_id)
    found = db.get(FoundItem, match.found_id)
    if lost is None or found is None:
        raise NotFoundError("匹配关联物品不存在")

    lost_user_id = int(lost.publisher_id)
    finder_user_id = int(found.finder_id)
    if int(user.id) not in (lost_user_id, finder_user_id):
        raise PermissionError("无权对该匹配发起会话")

    # 门控：唯一来源为 found_item.contact_allowed（Q5）
    if int(found.contact_allowed) == 0:
        raise PermissionError("对方暂未开启联系")

    # 复用同一匹配下仍开启的会话
    session = (
        db.query(IMSession)
        .filter(IMSession.match_id == match.id, IMSession.status == 0)
        .order_by(IMSession.id.desc())
        .first()
    )
    if session is None:
        now = datetime.now(timezone.utc)
        session = IMSession(
            match_id=match.id,
            found_id=None,
            lost_user_id=lost_user_id,
            finder_user_id=finder_user_id,
            status=0,
            expires_at=now + timedelta(days=settings.IM_RETENTION_DAYS),
        )
        db.add(session)
        db.flush()
        db.commit()
        db.refresh(session)

    return success(data=_session_out(session))


# ---------------- 轮询历史 ----------------
@router.get("/im/sessions/{session_id}/messages", response_model=StandardResponse)
def get_messages(
    session_id: int,
    since_id: int = Query(0, ge=0, description="增量游标：仅返回 id > since_id 的消息"),
    limit: int = Query(50, ge=1, le=200, description="单次拉取上限"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """拉取会话历史（前端每 ~4s 轮询，配合 since_id 做增量更新）。"""
    session = db.get(IMSession, session_id)
    if session is None:
        raise NotFoundError("会话不存在")
    _ensure_participant(session, user)

    msgs = (
        db.query(IMMessage)
        .filter(IMMessage.session_id == session.id, IMMessage.id > since_id)
        .order_by(IMMessage.id.asc())
        .limit(limit)
        .all()
    )
    return success(data=[_message_out(m) for m in msgs])


# ---------------- 发消息 ----------------
@router.post("/im/sessions/{session_id}/messages", response_model=StandardResponse)
def send_message(
    session_id: int,
    body: IMMessageCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """发送一条消息（JWT 鉴权 + 门控双保险 + 禁链接 + 镜像审计日志）。"""
    session = db.get(IMSession, session_id)
    if session is None:
        raise NotFoundError("会话不存在")
    _ensure_participant(session, user)

    now = datetime.now(timezone.utc)
    # 会话过期后禁止再发送（留存期满后由清理任务物理删除）
    # SQLite DateTime 无时区，读回为 naive，统一规整为 UTC 再比较。
    expires = session.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires is not None and expires <= now:
        raise PermissionError("会话已过期，无法发送消息")

    # 门控双保险：即便复用旧会话，对端关闭联系时仍拒绝
    if _contact_gateway_blocked(db, session):
        raise PermissionError("对方暂未开启联系")

    content = (body.content or "").strip()
    if not content:
        raise ParamError("消息内容不能为空")
    if _LINK_PATTERN.search(content):
        raise ParamError("消息中不可包含外部链接")

    ctype = (body.type or "text").lower()
    content_type = int(ContentType.TEMPLATE) if ctype == "template" else int(ContentType.TEXT)

    msg = IMMessage(
        session_id=session.id,
        sender_id=int(user.id),
        sender_role=_sender_role(session, user),
        content_type=content_type,
        content=content[:500],
    )
    db.add(msg)
    session.last_message_at = now
    db.flush()

    # 镜像审计（冒领溯源）：action="im_message" / target_type="im_session"
    audit_service.write_audit(
        db,
        user_id=int(user.id),
        action="im_message",
        target_type="im_session",
        target_id=session.id,
        ip=request.client.host if request.client else None,
        ua=request.headers.get("user-agent"),
        detail=f"[{content_type}] {content[:200]}",
    )
    db.commit()
    db.refresh(msg)
    return success(data=_message_out(msg))


# ---------------- 输出装配 ----------------
def _session_out(session: IMSession) -> IMSessionOut:
    return IMSessionOut(
        id=session.id,
        match_id=session.match_id,
        found_id=session.found_id,
        lost_user_id=session.lost_user_id,
        finder_user_id=session.finder_user_id,
        status=session.status,
        created_at=session.created_at,
        last_message_at=session.last_message_at,
        expires_at=session.expires_at,
    )


def _message_out(msg: IMMessage) -> IMMessageOut:
    return IMMessageOut(
        id=msg.id,
        session_id=msg.session_id,
        sender_id=msg.sender_id,
        sender_role=msg.sender_role,
        content_type=msg.content_type,
        content=msg.content,
        sent_at=msg.sent_at,
    )


# ---------------- v5：「我的消息」会话列表 ----------------
@router.get("/im/sessions", response_model=StandardResponse)
def list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前用户参与且 ``status=0`` 的会话（富化），按 ``last_message_at`` 倒序。

    每项含：对方用户摘要、拼装标题、最后消息时间/预览、粗粒度未读标记。
    """
    items = im_svc.list_sessions_for_user(db, int(user.id))
    return success(data=items)


# ---------------- v5：删除此对话（软删 status=1） ----------------
@router.delete("/im/sessions/{session_id}", response_model=StandardResponse)
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """软删会话（status=1 隐藏），后台按 ``IM_RETENTION_DAYS`` 保留。"""
    session = db.get(IMSession, session_id)
    if session is None:
        raise NotFoundError("会话不存在")
    _ensure_participant(session, user)
    im_svc.soft_delete_session(session, db)
    db.commit()
    return success(data={"id": session.id, "status": session.status})


# ---------------- v5：招领成功（软删 + 归档关联 match） ----------------
@router.post("/im/sessions/{session_id}/success", response_model=StandardResponse)
def success_session(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """软删会话 + 若关联未完成 MatchRecord 则归档为 COMPLETED（终态保护）。

    - 关联 ``match.status ∈ {0,1,4}`` → 置 COMPLETED(2) + 双端物品已解决 + 审计。
    - 无 match 或 match 已终态（2/3/5）→ 仅软删，不动 match。
    """
    session = db.get(IMSession, session_id)
    if session is None:
        raise NotFoundError("会话不存在")
    _ensure_participant(session, user)
    matched = im_svc.success_session_archive(db, session, user, request)
    db.commit()
    return success(
        data={"id": session.id, "status": session.status, "match_archived": matched}
    )
