"""审计日志服务（黑匣子，不可篡改，纯写入）。

所有关键操作（发布 / 认领 / 交接 / 申诉 / 封禁）均落 audit_log，供管理员追溯。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def write_audit(
    db: Session,
    *,
    user_id: int | None = None,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    ip: str | None = None,
    ua: str | None = None,
    session_id: str | None = None,
    gps: str | None = None,
    detail: str | None = None,
) -> AuditLog:
    """写入一条审计日志（不提交，由调用方事务统一提交）。"""
    log = AuditLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        ua=ua,
        session_id=session_id,
        gps=gps,
        detail=detail,
    )
    db.add(log)
    db.flush()
    return log
