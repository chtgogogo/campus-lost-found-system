"""物品路由（§3.3）：失物 / 拾物发布、列表、详情、撤销、我的发布。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import (
    NotFoundError,
    ParamError,
    PermissionError,
)
from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord
from app.models.user import User
from app.routers.deps import get_current_user
from app.schemas.common import (
    FoundItemStatus,
    LostItemStatus,
    MatchStatus,
    Page,
    StandardResponse,
    success,
)
from app.schemas.item import FoundItemOut, LostItemPublishDTO, LostItemOut
from app.schemas.match import MatchOut
from app.services.match_service import build_match_outs
from app.services.publish_service import PublishService

router = APIRouter(tags=["items"])


# ---------------- 工具 ----------------
def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise ParamError("时间格式错误，应为 ISO-8601（如 2026-07-16T10:00:00）")


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _ensure_owner(item_user_id: int, current_user: User) -> None:
    if int(item_user_id) != int(current_user.id):
        raise PermissionError()


def _now() -> datetime:
    """v7：朴素 UTC 当前时间。

    与 SQLite 存储的 DateTime（tzinfo 被剥离为朴素 UTC）保持一致，
    避免 naive/aware 比较报错；同时作为失效/软删过滤的统一基准。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------- 失物发布 ----------------
@router.post("/lost-items", response_model=StandardResponse)
async def create_lost_item(
    request: Request,
    title: str = Form(..., max_length=100),
    description: str = Form(...),
    category_name: str = Form(..., max_length=100, description="纯自由文本分类（必填）"),
    lost_time: Optional[str] = Form(None, description="丢失时间（选填，R3：不知道/记不清可留空）"),
    color: Optional[str] = Form(None, max_length=30),
    appearance: Optional[str] = Form(None, max_length=255, description="外观描述（材质/形状/颜色）"),
    features: Optional[str] = Form(None, max_length=255, description="特征描述（品牌/数量/特殊标记）"),
    location: Optional[str] = Form(None, max_length=128, description="地点描述"),
    images: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """发布失物：图片→YOLO 打标→自动打标签+算感知哈希→入库→反向匹配→疑似提醒。

    ``lost_time`` 选填（R3：不知道/记不清可留空，落库 NULL）；其余同现状。
    响应 ``suspected_matches``：本次发布自动生成的候选匹配（≤10 条，按分数降序，
    可能含低分 score<80 候选；suspected=false 由 score 派生，前端用 match_score<80 弱化呈现）。
    """
    if len(images) > settings.IMG_MAX_COUNT:
        raise ParamError(f"图片数量不得超过 {settings.IMG_MAX_COUNT} 张")
    img_data = [(f.filename or "img.jpg", await f.read()) for f in images]
    dto = LostItemPublishDTO(
        title=title,
        description=description,
        category_name=category_name,
        lost_time=_parse_dt(lost_time) if lost_time else None,  # R3：选填
        color=color,
        appearance=appearance,
        features=features,
        location=location,
        images=img_data,
    )
    lost, matches = PublishService(db).publish_lost(
        user, dto, ip=_client_ip(request), ua=request.headers.get("user-agent")
    )
    out = LostItemOut.from_model(lost)
    return success(
        data={"item": out, "suspected_matches": build_match_outs(db, matches)}
    )


# ---------------- 拾物发布 ----------------
@router.post("/found-items", response_model=StandardResponse)
async def create_found_item(
    request: Request,
    keep_status: int = Form(..., description="0 暂为保管 / 1 未保管"),
    category_name: str = Form(..., max_length=100, description="纯自由文本分类（必填）"),
    images: List[UploadFile] = File(..., description="至少 1 张照片"),
    description: Optional[str] = Form(None),
    found_time: Optional[str] = Form(None),
    contact_allowed: int = Form(1),
    appearance: Optional[str] = Form(None, max_length=255, description="外观描述（材质/形状/颜色）"),
    features: Optional[str] = Form(None, max_length=255, description="特征描述（品牌/数量/特殊标记）"),
    location: Optional[str] = Form(None, max_length=128, description="地点描述"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """发布拾物（零门槛：images≥1 + keep_status 二选一，其余选填）。

    响应 ``suspected_matches``：对称生成的候选失物匹配（≤10 条，按分数降序，
    可能含低分 score<80 候选；Q5 对称落库，拾得者侧低分由前端弱化呈现）。
    """
    if keep_status not in (0, 1):
        raise ParamError("keep_status 必须为 0 或 1")
    # v4 双保险：暂为保管（keep_status=0）必须开启联系；publish_found 已校验，此处再次拦截
    if keep_status == 0 and contact_allowed == 0:
        raise ParamError("暂为保管的物品必须开启联系（contact_allowed=1）")
    if len(images) > settings.IMG_MAX_COUNT:
        raise ParamError(f"图片数量不得超过 {settings.IMG_MAX_COUNT} 张")
    img_data = [(f.filename or "img.jpg", await f.read()) for f in images]
    if not img_data:
        raise ParamError("拾物需至少上传 1 张照片")

    found_time_dt = _parse_dt(found_time) if found_time else None
    from app.schemas.item import FoundItemPublishDTO

    dto = FoundItemPublishDTO(
        keep_status=keep_status,
        category_name=category_name,
        images=img_data,
        description=description,
        found_time=found_time_dt,
        contact_allowed=contact_allowed,
        appearance=appearance,
        features=features,
        location=location,
    )
    found, matches = PublishService(db).publish_found(
        user, dto, ip=_client_ip(request), ua=request.headers.get("user-agent")
    )
    out = FoundItemOut.from_model(found)
    return success(
        data={"item": out, "suspected_matches": build_match_outs(db, matches)}
    )


# ---------------- 我的发布（v3 需求 E） ----------------
@router.get("/users/me/items", response_model=StandardResponse)
def my_items(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前用户本人发布的全部失物与拾物（供「我的发布」页使用）。"""
    lost = (
        db.query(LostItem)
        .filter(LostItem.publisher_id == user.id)
        .filter(LostItem.deleted_at.is_(None), LostItem.expires_at > _now())
        .order_by(LostItem.id.desc())
        .all()
    )
    found = (
        db.query(FoundItem)
        .filter(FoundItem.finder_id == user.id)
        .filter(FoundItem.deleted_at.is_(None), FoundItem.expires_at > _now())
        .order_by(FoundItem.id.desc())
        .all()
    )
    return success(
        data={
            "lost": [LostItemOut.from_model(it) for it in lost],
            "found": [FoundItemOut.from_model(it) for it in found],
        }
    )


# ---------------- 列表 / 详情 / 撤销 ----------------
@router.get("/lost-items", response_model=StandardResponse)
def list_lost_items(
    status: Optional[int] = Query(None),
    exclude_resolved: bool = Query(False, description="排除已解决项（LostItem.status!=3），用于公示栏主三 tab"),
    resolved_only: bool = Query(False, description="仅返回已解决项（LostItem.status==3），用于「已完成交接」tab"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """失物列表（分页）。

    已解决判定一律以**物品自身 status** 为准：``LostItem.status == 3``（RESOLVED）为已解决。
    ⚠️ 数值碰撞红线：``MatchRecord.status == 3`` 表示 REJECTED（已拒绝），与"已解决"同值异义，
    本过滤**绝不**读取 ``MatchRecord.status``，避免误判。

    过滤优先级：``resolved_only`` > ``exclude_resolved`` > 旧 ``status``。
    """
    q = db.query(LostItem)
    # 优先级：resolved_only > exclude_resolved > status（仅针对物品自身 status）
    if resolved_only:
        q = q.filter(LostItem.status == int(LostItemStatus.RESOLVED))  # == 3
    elif exclude_resolved:
        q = q.filter(LostItem.status != int(LostItemStatus.RESOLVED))  # != 3
    elif status is not None:
        q = q.filter(LostItem.status == status)
    # v7 用户侧过滤（无条件叠加）：隐藏软删与已失效项
    q = q.filter(LostItem.deleted_at.is_(None), LostItem.expires_at > _now())
    total = q.with_entities(func.count()).scalar() or 0
    items = (
        q.order_by(LostItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    outs = [LostItemOut.from_model(it) for it in items]
    return success(data=Page[LostItemOut](items=outs, total=total, page=page, page_size=page_size))


@router.get("/lost-items/{item_id}", response_model=StandardResponse)
def get_lost_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lost = db.get(LostItem, item_id)
    if not lost:
        raise NotFoundError("失物不存在")
    return success(data=LostItemOut.from_model(lost))


@router.delete("/lost-items/{item_id}", response_model=StandardResponse)
def revoke_lost_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """撤销失物（仅发布者）。v7：软删（置 deleted_at），保留拒绝其待处理匹配逻辑。"""
    lost = db.get(LostItem, item_id)
    if not lost:
        raise NotFoundError("失物不存在")
    _ensure_owner(lost.publisher_id, user)
    lost.deleted_at = _now()  # v7：软删标记（不触发 RESTRICT FK）
    db.query(MatchRecord).filter(
        MatchRecord.lost_id == item_id,
        MatchRecord.status.in_([int(MatchStatus.PENDING_CLAIM), int(MatchStatus.CLAIMING)]),
    ).update({MatchRecord.status: int(MatchStatus.REJECTED)})
    db.commit()
    return success(data=LostItemOut.from_model(lost))


@router.get("/found-items", response_model=StandardResponse)
def list_found_items(
    status: Optional[int] = Query(None),
    exclude_resolved: bool = Query(False, description="排除已解决项（FoundItem.status!=1），用于公示栏主三 tab"),
    resolved_only: bool = Query(False, description="仅返回已解决项（FoundItem.status==1），用于「已完成交接」tab"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """拾物列表（分页）。

    已解决判定一律以**物品自身 status** 为准：``FoundItem.status == 1``（RESOLVED）为已解决。
    ⚠️ 数值碰撞红线：``MatchRecord.status == 3`` 表示 REJECTED（已拒绝），与失物"已解决(==3)"同值异义，
    本过滤**绝不**读取 ``MatchRecord.status``，避免误判。

    过滤优先级：``resolved_only`` > ``exclude_resolved`` > 旧 ``status``。
    """
    q = db.query(FoundItem)
    # 优先级：resolved_only > exclude_resolved > status（仅针对物品自身 status）
    if resolved_only:
        q = q.filter(FoundItem.status == int(FoundItemStatus.RESOLVED))  # == 1
    elif exclude_resolved:
        q = q.filter(FoundItem.status != int(FoundItemStatus.RESOLVED))  # != 1
    elif status is not None:
        q = q.filter(FoundItem.status == status)
    # v7 用户侧过滤（无条件叠加）：隐藏软删与已失效项
    q = q.filter(FoundItem.deleted_at.is_(None), FoundItem.expires_at > _now())
    total = q.with_entities(func.count()).scalar() or 0
    items = (
        q.order_by(FoundItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    outs = [FoundItemOut.from_model(it) for it in items]
    return success(data=Page[FoundItemOut](items=outs, total=total, page=page, page_size=page_size))


@router.get("/found-items/{item_id}", response_model=StandardResponse)
def get_found_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    found = db.get(FoundItem, item_id)
    if not found:
        raise NotFoundError("拾物不存在")
    return success(data=FoundItemOut.from_model(found))


@router.delete("/found-items/{item_id}", response_model=StandardResponse)
def revoke_found_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """撤销拾物（仅拾得者）。v7：软删（置 deleted_at），保留拒绝其待处理匹配逻辑。"""
    found = db.get(FoundItem, item_id)
    if not found:
        raise NotFoundError("拾物不存在")
    _ensure_owner(found.finder_id, user)
    found.deleted_at = _now()  # v7：软删标记（不触发 RESTRICT FK）
    db.query(MatchRecord).filter(
        MatchRecord.found_id == item_id,
        MatchRecord.status.in_([int(MatchStatus.PENDING_CLAIM), int(MatchStatus.CLAIMING)]),
    ).update({MatchRecord.status: int(MatchStatus.REJECTED)})
    db.commit()
    return success(data=FoundItemOut.from_model(found))
