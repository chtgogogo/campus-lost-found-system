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

# 审计日志字段含义表（字段 → 基础含义）。导出长表时把说明直接写到对应行的「说明」列，
# 不再单独成块（v8 之前会把字段说明追加到文件末尾，2026-08-20 取消）。
_AUDIT_FIELD_MEANING: dict[str, str] = {
    "id": "审计记录自增主键",
    "user_id": "操作人用户ID（空=系统/匿名）",
    "action": "操作类型",
    "target_type": "操作对象类型",
    "target_id": "操作对象ID",
    "ip": "操作者来源IP",
    "ua": "操作者浏览器/设备标识（User-Agent）",
    "session_id": "登录会话标识",
    "gps": "操作地理位置（如有）",
    "detail": "操作附加明细（如失物标题/类目/标签/交接码等 key=value 形式）",
    "created_at": "操作发生时间（ISO8601 UTC）",
}

# 审计编码字段取值字典：让「说明」列直接解出该值的具体含义，而不是只写字段名。
_AUDIT_ACTION_MEANING: dict[str, str] = {
    "publish_lost": "发布失物",
    "publish_found": "发布拾物",
    "claim": "认领",
    "confirm_return": "确认归还",
    "reject": "拒绝认领",
    "handover_generate": "生成交接码",
    "handover_complete": "交接完成",
    "handover_verify": "验证交接码",
    "ban": "封禁用户",
    "appeal": "申诉",
    "im_message": "发送消息",
    "im_success_archive": "对话归档（交接成功后消息留存）",
    "manual_match_create": "管理员手动创建匹配",
    "manual_self_complete": "管理员手动完成（单边直达终态）",
    "match_give_up": "放弃匹配",
    "keep1_claim_complete": "单边认领即完成（keep1）",
    "keep1_claim_revoke": "撤销单边认领（keep1）",
    "register_admin": "注册管理员",
    "admin_list_users": "管理员查看用户列表",
    "admin_view_match_detail": "管理员查看匹配详情",
    "admin_export": "管理员导出取证数据",
}
_AUDIT_TARGET_TYPE_MEANING: dict[str, str] = {
    "user": "用户",
    "item": "物品",
    "lost": "失物条目",
    "found": "拾物条目",
    "lost_item": "失物条目",
    "found_item": "拾物条目",
    "match": "匹配记录",
    "handover": "交接码",
    "im_session": "会话",
}


def _audit_field_explanation(field: str, value) -> str:
    """审计「说明」：基础含义 +（编码字段）该值的具体含义。

    - `action=handover_complete` → "操作类型：handover_complete=交接完成"
    - `target_type=match` → "操作对象类型：match=匹配记录"
    - 普通字段（如 ip） → 仅基础含义
    """
    base = _AUDIT_FIELD_MEANING.get(field, "")
    if field == "action" and value in _AUDIT_ACTION_MEANING:
        return f"操作类型：{value}={_AUDIT_ACTION_MEANING[value]}"
    if field == "target_type" and value in _AUDIT_TARGET_TYPE_MEANING:
        return f"操作对象类型：{value}={_AUDIT_TARGET_TYPE_MEANING[value]}"
    return base

# 长表列定义：与 `admin_export_service.LONG_FORMAT_COLUMNS` 对齐。
_LONG_COLUMNS = ["记录ID", "字段", "值", "说明"]

_AUDIT_LEGEND_HEADER = (
    "本文件由失物招领系统自动生成，与审计黑匣子一致，"
    "可作为责任认定（追责）依据。时间均为 UTC（ISO8601）。"
)


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
    """导出审计日志为 CSV 或 JSON（数据源：MySQL audit_log）。

    **v8 长表格式（2026-08-20）**：整张文件就是一张表 `[记录ID, 字段, 值, 说明]`，
    每条审计记录的每个字段展开成一行，说明直接跟在值后面；不再有单独一块
    「审计日志字段说明」。记录 ID = 该审计记录的 `id`，方便在 Excel 里按 ID 分组
    看同一记录的所有字段。
    """
    if format not in ("csv", "json"):
        return Response(
            content=json.dumps({"code": 9001, "message": "format 仅支持 csv|json"}),
            status_code=400,
            media_type="application/json",
        )
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).all()
    records = [_serialize(r) for r in rows]

    # 长表：每条记录的每个字段一行（说明对该值的具体含义，而非只写字段名）
    long_rows: list[dict] = []
    for rec in records:
        record_id = rec["id"]
        for field in _EXPORT_FIELDS:
            long_rows.append({
                "记录ID": record_id,
                "字段": field,
                "值": rec.get(field, ""),
                "说明": _audit_field_explanation(field, rec.get(field, "")),
            })

    if format == "json":
        # JSON 也是一张「长表」数组，与 CSV 同源同结构
        payload = {
            "_meta": {
                "导出声明": _AUDIT_LEGEND_HEADER,
                "记录条数": len(records),
                "长表行数": len(long_rows),
                "字段列表": _EXPORT_FIELDS,
            },
            "rows": long_rows,
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=audit_logs.json"
            },
        )

    # CSV：顶部一行 # 取证声明注释，第二行起长表（Excel 打开后第一行仍是表头）
    buf = io.StringIO()
    buf.write(f"# {_AUDIT_LEGEND_HEADER}\n")
    writer = csv.DictWriter(buf, fieldnames=_LONG_COLUMNS)
    writer.writeheader()
    for row in long_rows:
        writer.writerow(row)
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=audit_logs.csv"
        },
    )


@router.get("/audit-logs")
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """审计日志列表（管理后台页内时间线用，与导出同源）。按 id 降序分页。"""
    total = db.query(func.count()).select_from(AuditLog).scalar() or 0
    rows = (
        db.query(AuditLog)
        .order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return success(
        data=Page[dict](
            items=[_serialize(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
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
            db, matches, payload.scope, payload.format, exported_by=getattr(admin, "id", None)
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
