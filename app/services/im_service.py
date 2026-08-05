"""IM 留存清理服务（v3 需求 D / Q7）。

- 镜像溯源：每条消息已由 ``app.routers.im.send_message`` 写入 ``audit_log``
  （``action="im_message"`` / ``target_type="im_session"``），留存期满后物理删除
  ``im_session`` / ``im_message`` 不影响审计溯源。
- 清理：删除 ``expires_at`` 早于当前的会话及其消息；仅清理 IM 表，审计长期留存。

v5 增量：新增「我的消息」列表富化 / 软删 / 招领成功归档 helper。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.core.exceptions import PermissionError
from app.models.im import IMMessage, IMSession
from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord
from app.models.user import User
from app.schemas.common import (
    FoundItemStatus,
    LostItemStatus,
    MatchStatus,
)
from app.schemas.im import IMSessionListItem, PeerUser


# ---------------- 工具 ----------------
def _now() -> datetime:
    """v7：朴素 UTC 当前时间（与 SQLite 存储一致，避免 naive/aware 比较报错）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# 标题前缀（主理人拍板 #4：统一前缀，不区分发起方视角）
_TITLE_PREFIX = "联系对方 · "
# 无 category_name 时 description 回退截断长度
_DESC_FALLBACK_LEN = 12
# 最后消息预览截断长度
_PREVIEW_LEN = 20


def purge_expired_im(db: Session, now: datetime | None = None) -> int:
    """物理删除已过期的 IM 会话与消息（审计日志保留）。

    返回被清理的会话数量。调用方负责提交事务。
    """
    now = now or datetime.now(timezone.utc)
    expired = (
        db.query(IMSession.id)
        .filter(IMSession.expires_at <= now)
        .all()
    )
    if not expired:
        return 0
    expired_ids = [row[0] for row in expired]
    # 先删消息（外键 RESTRICT，先清子表）
    db.execute(delete(IMMessage).where(IMMessage.session_id.in_(expired_ids)))
    db.execute(delete(IMSession).where(IMSession.id.in_(expired_ids)))
    db.flush()
    return len(expired_ids)


# ---------------- v5：「我的消息」富化 helper ----------------

def _load_found_item(db: Session, session: IMSession) -> Optional[FoundItem]:
    """取得会话关联拾物（用于拼装标题）。

    优先 ``found_id``（无 match 的联系会话）；否则回退 ``match_id``。
    """
    if session.found_id is not None:
        return db.get(FoundItem, session.found_id)
    if session.match_id is None:
        return None
    match = db.get(MatchRecord, session.match_id)
    if match is None:
        return None
    return db.get(FoundItem, match.found_id)


def build_session_title(db: Session, session: IMSession) -> str:
    """拼装会话标题（主理人拍板 #4）：「联系对方 · {物品标题}」。

    物品标题来源：``found_item.category_name``；为空则回退 ``description`` 截断 12 字。
    """
    name = ""
    found = _load_found_item(db, session)
    if found is not None:
        name = (found.category_name or "").strip()
        if not name:
            desc = (found.description or "").strip()
            name = desc[:_DESC_FALLBACK_LEN]
    return f"{_TITLE_PREFIX}{name}" if name else _TITLE_PREFIX.rstrip(" · ")


def build_peer_user(db: Session, session: IMSession, user: User) -> PeerUser:
    """取得会话对方用户摘要。"""
    peer_id = (
        int(session.finder_user_id)
        if int(user.id) == int(session.lost_user_id)
        else int(session.lost_user_id)
    )
    peer = db.get(User, peer_id)
    nickname = peer.real_name if (peer and peer.real_name) else f"用户{peer_id}"
    student_no = peer.student_no if peer else ""
    return PeerUser(id=peer_id, nickname=nickname, student_no=student_no)


def session_list_item(db: Session, session: IMSession, user: User) -> IMSessionListItem:
    """将单个会话富化为列表项（含对方 / 标题 / 未读 / 最后消息预览）。"""
    last_msg = (
        db.query(IMMessage)
        .filter(IMMessage.session_id == session.id)
        .order_by(IMMessage.id.desc())
        .first()
    )
    last_message_at = session.last_message_at
    preview: Optional[str] = None
    unread = False
    if last_msg is not None:
        preview = (last_msg.content or "")[:_PREVIEW_LEN] or None
        unread = int(last_msg.sender_id) != int(user.id)
        if last_message_at is None:
            last_message_at = last_msg.sent_at

    return IMSessionListItem(
        id=session.id,
        match_id=session.match_id,
        found_id=session.found_id,
        lost_user_id=session.lost_user_id,
        finder_user_id=session.finder_user_id,
        peer_user=build_peer_user(db, session, user),
        title=build_session_title(db, session),
        last_message_at=last_message_at,
        last_message_preview=preview,
        unread=unread,
        status=session.status,
    )


def list_sessions_for_user(db: Session, user_id: int) -> List[IMSessionListItem]:
    """列出当前用户参与且 ``status=0`` 的会话，按 ``last_message_at`` 倒序富化。"""
    sessions = (
        db.query(IMSession)
        .filter(
            IMSession.status == 0,
            or_(
                IMSession.lost_user_id == user_id,
                IMSession.finder_user_id == user_id,
            ),
        )
        .order_by(
            IMSession.last_message_at.is_(None),
            IMSession.last_message_at.desc(),
        )
        .all()
    )
    return [session_list_item(db, s, db.get(User, user_id)) for s in sessions]


def soft_delete_session(session: IMSession, db: Session) -> None:
    """软删会话（status=1），后台按 ``IM_RETENTION_DAYS`` 保留。"""
    session.status = 1
    db.flush()


def success_session_archive(db: Session, session: IMSession, user: User, request) -> bool:
    """招领成功：软删会话 + 若关联未完成 MatchRecord 则归档（终态保护）。

    返回是否对 match 做了归档（True=归档；False=仅软删，无 match 或 match 已终态）。
    """
    soft_delete_session(session, db)
    if session.match_id is None:
        return False
    match = db.get(MatchRecord, session.match_id)
    if match is None:
        return False
    # 终态保护：仅未完成（0/1/4）的 match 才归档；2/3/5 已终态则仅软删
    if int(match.status) not in (
        int(MatchStatus.PENDING_CLAIM),
        int(MatchStatus.CLAIMING),
        int(MatchStatus.MANUAL_PENDING),
    ):
        return False

    lost = db.get(LostItem, match.lost_id)
    found = db.get(FoundItem, match.found_id)
    match.status = int(MatchStatus.COMPLETED)
    # v7：写完成时间 + 重置关联双方失效时间（顺延 90 天）
    match.completed_at = _now()
    if lost is not None:
        lost.status = int(LostItemStatus.RESOLVED)
        lost.expires_at = _now() + timedelta(days=90)
    if found is not None:
        found.status = int(FoundItemStatus.RESOLVED)
        found.expires_at = _now() + timedelta(days=90)
    db.flush()

    from app.services import audit_service

    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    audit_service.write_audit(
        db,
        user_id=int(user.id),
        action="im_success_archive",
        target_type="match",
        target_id=match.id,
        ip=ip,
        ua=ua,
        detail=f"lost_id={match.lost_id};found_id={match.found_id}",
    )
    return True
