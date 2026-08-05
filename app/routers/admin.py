"""管理后台路由。

- P2-03：审计导出 `GET /api/v1/admin/audit-logs/export?format=csv|json`
- v7：未失效匹配列表 / 取证导出 / 周期清理
- **v10 变更 D**：用户列表 `GET /admin/users`、匹配详情
  `GET /admin/matches/{id}/detail`、导出扩 `scope`/`format`、
  匹配列表加 `all_time`（Q4 方案 A：留存更久在查询层放开）。

全部接口由 `require_admin` 守卫。取证类接口回传**明文**手机号/学号，
前端后台必须展示合规提示。四个 v10 接口均落审计埋点。
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord
from app.models.user import User
from app.routers.deps import require_admin
from app.schemas.admin import AdminConversationItem, AdminMatchDetailOut
from app.schemas.common import Page, success
from app.schemas.match import MatchOut
from app.schemas.user import AdminUserOut
from app.services import admin_export_service, audit_service
from app.services.admin_export_service import ExportDependencyError
from app.services.cleanup import CleanupService
from app.services.match_service import build_match_outs

router = APIRouter(prefix="/admin", tags=["admin"])

_EXPORT_FIELDS = [
    "id",
    "user_id",
    "action",
    "target_type",
    "target_id",
    "ip",
    "ua",
    "session_id",
    "gps",
    "detail",
    "created_at",
]


def _serialize(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "ip": row.ip,
        "ua": row.ua,
        "session_id": row.session_id,
        "gps": row.gps,
        "detail": row.detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/audit-logs/export")
def export_audit_logs(
    format: str = Query("csv", description="csv 或 json"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """导出审计日志为 CSV 或 JSON（数据源：MySQL audit_log）。"""
    if format not in ("csv", "json"):
        return Response(
            content=json.dumps({"code": 9001, "message": "format 仅支持 csv|json"}),
            status_code=400,
            media_type="application/json",
        )
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).all()
    records = [_serialize(r) for r in rows]

    if format == "json":
        return Response(
            content=json.dumps(records, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=audit_logs.json"
            },
        )

    # CSV
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for rec in records:
        writer.writerow(rec)
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=audit_logs.csv"
        },
    )


# ---------------- v7：未失效匹配列表 / 取证导出 / 周期清理 ----------------
def _now() -> datetime:
    """v7：朴素 UTC 当前时间（与 SQLite 存储一致，避免 naive/aware 比较报错）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


_FORENSIC_FIELDS = admin_export_service.FORENSIC_FIELDS

# 兼容别名（R2 §5.1）：取证构建已下沉到 `admin_export_service`，此处保留薄别名，
# 避免存量/后续测试直接引用这两个私有名时断裂。成本为 0，请勿删除。
_build_conversation = admin_export_service.build_conversation
_build_forensic_row = admin_export_service.build_forensic_row

_VALID_SCOPES = ("profile", "conversation", "all")
_VALID_FORMATS = ("csv", "xlsx", "md")


def _error(message: str, code: int = 9001, status_code: int = 400) -> Response:
    """统一错误响应体（沿用 v7 `admin.py` 既有写法：裸 JSON + code 9001）。"""
    return Response(
        content=json.dumps({"code": code, "message": message}, ensure_ascii=False),
        status_code=status_code,
        media_type="application/json",
    )


def _audit(request: Request, db: Session, admin, action: str, **kw) -> None:
    """管理后台审计埋点（失败不阻断主流程）。

    Args:
        request: 当前请求（取 IP / UA）。
        db: 数据库会话。
        admin: `require_admin` 返回的当前管理员。
        action: 审计动作名。
        **kw: 透传给 `write_audit` 的 `target_type` / `target_id` / `detail`。
    """
    try:
        audit_service.write_audit(
            db,
            user_id=getattr(admin, "id", None),
            action=action,
            ip=request.client.host if request.client else None,
            ua=request.headers.get("user-agent"),
            **kw,
        )
        db.commit()
    except Exception:       # pragma: no cover - 审计失败绝不影响管理操作本身
        db.rollback()


class AdminExportRequest(BaseModel):
    """导出请求体（v10 就地扩展：新增 `scope`，`format` 扩到三种）。

    老前端只传 `ids` 时，`scope="all"` + `format="csv"` 与 v7 行为完全一致（AC-D8）。
    """

    ids: List[int]
    format: str = Field("csv", description="csv | xlsx | md")
    scope: str = Field("all", description="profile | conversation | all")


@router.get("/users")
def list_admin_users(
    request: Request,
    keyword: Optional[str] = Query(None, description="按 student_no / phone / real_name 模糊搜索"),
    role: Optional[int] = Query(None, description="0=普通 1=管理员，默认全部"),
    status: Optional[int] = Query(None, description="按 User.status 过滤，默认全部"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """v10-D1：用户列表（**手机号明文**，仅管理员可见）。

    按 `id` 降序分页；`keyword` 对学号/手机号/真实姓名做 LIKE 匹配（任一命中）。
    """
    q = db.query(User)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            or_(
                User.student_no.like(like),
                User.phone.like(like),
                User.real_name.like(like),
            )
        )
    if role is not None:
        q = q.filter(User.role == role)
    if status is not None:
        q = q.filter(User.status == status)
    total = q.with_entities(func.count()).scalar() or 0
    users = (
        q.order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    _audit(
        request, db, admin, "admin_list_users",
        target_type="user", target_id=None,
        detail=f"keyword={kw};role={role};status={status};page={page};total={total}",
    )
    return success(
        data=Page[AdminUserOut](
            items=[AdminUserOut.from_model(u) for u in users],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/matches")
def list_admin_matches(
    status: Optional[int] = Query(None, description="按 MatchRecord.status 过滤，默认全部"),
    all_time: bool = Query(False, description="true=不加留存时间窗，返回全部历史匹配（Q4 方案 A）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """管理员匹配列表。

    - `all_time=False`（默认，与 v7 完全一致）：仅返回关联双方物品仍处于留存窗
      （`expires_at > now - ADMIN_RETENTION_DAYS`）的匹配（不判 `deleted_at`，
      软删项在窗内仍可见）。
    - `all_time=True`：**跳过**两个时间窗过滤，返回全部历史匹配（管理员侧留存更久）。
    """
    q = (
        db.query(MatchRecord)
        .join(LostItem, MatchRecord.lost_id == LostItem.id)
        .join(FoundItem, MatchRecord.found_id == FoundItem.id)
    )
    if not all_time:
        cutoff = _now() - timedelta(days=settings.ADMIN_RETENTION_DAYS)
        q = q.filter(LostItem.expires_at > cutoff).filter(FoundItem.expires_at > cutoff)
    if status is not None:
        q = q.filter(MatchRecord.status == status)
    total = q.with_entities(func.count()).scalar() or 0
    matches = (
        q.order_by(MatchRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    outs = build_match_outs(db, matches)
    return success(data=Page[MatchOut](items=outs, total=total, page=page, page_size=page_size))


@router.get("/matches/{match_id}/detail")
def get_admin_match_detail(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """v10-D2：匹配详情（双方**明文**信息 + 结构化对话）。

    Q11：**不硬限制** `status == 2` —— 取证时常需查看未完成/已拒绝的会话。
    匹配不存在 → 404 + `code 9001`。
    """
    match = db.get(MatchRecord, match_id)
    if match is None:
        return _error(f"匹配 {match_id} 不存在", status_code=404)

    lost = db.get(LostItem, match.lost_id)
    found = db.get(FoundItem, match.found_id)
    lost_user = db.get(User, lost.publisher_id) if lost else None
    found_user = db.get(User, found.finder_id) if found else None

    outs = build_match_outs(db, [match])
    detail = AdminMatchDetailOut(
        match=outs[0],
        lost_user=AdminUserOut.from_model(lost_user) if lost_user else None,
        found_user=AdminUserOut.from_model(found_user) if found_user else None,
        conversation=[
            AdminConversationItem(**row)
            for row in admin_export_service.build_conversation_rows(db, match_id)
        ],
    )
    _audit(
        request, db, admin, "admin_view_match_detail",
        target_type="match", target_id=match_id,
        detail=f"lost_id={match.lost_id};found_id={match.found_id};status={match.status}",
    )
    return success(data=detail)


@router.post("/export")
def export_matches(
    payload: AdminExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """取证导出：按勾选的匹配 id 聚合为 1 个文件。

    - `scope`：`profile`（双方身份 + 物品摘要）/ `conversation`（逐条对话）/
      `all`（v7 全量取证行；xlsx 下拆成两个 Sheet）。
    - `format`：`csv` / `xlsx`（需 openpyxl）/ `md`。
    - 非法 `scope`/`format` → 400 + `code 9001`；openpyxl 缺失 → 400（**不是 500**）。
    """
    if payload.format not in _VALID_FORMATS:
        return _error(f"format 仅支持 {'|'.join(_VALID_FORMATS)}")
    if payload.scope not in _VALID_SCOPES:
        return _error(f"scope 仅支持 {'|'.join(_VALID_SCOPES)}")

    matches: List[MatchRecord] = []
    for mid in payload.ids:
        match = db.get(MatchRecord, mid)
        if match is None:
            continue
        matches.append(match)

    try:
        content, media_type, filename = admin_export_service.render(
            db, matches, payload.scope, payload.format
        )
    except ExportDependencyError as exc:
        return _error(str(exc))

    _audit(
        request, db, admin, "admin_export",
        target_type="match", target_id=None,
        detail=f"scope={payload.scope};format={payload.format};ids={payload.ids};rows={len(matches)}",
    )
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    if payload.format == "csv":
        # 保持 v7 的 PlainTextResponse 形态，存量测试直接读 `resp.text`
        return PlainTextResponse(
            content.decode("utf-8"), media_type=media_type, headers=headers
        )
    return Response(content=content, media_type=media_type, headers=headers)


@router.post("/cleanup")
def trigger_cleanup(
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """触发一轮周期清理（依赖序物理删超 1 年数据），返回本次清理计数。"""
    result = CleanupService(db).run_once()
    return success(data=result)
