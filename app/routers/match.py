"""匹配路由（§3.4）：匹配列表 / 认领 / 确认归还 / 交接码生成与验证 / 拒绝。"""
from __future__ import annotations

from typing import Optional

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import (
    ClaimReasonRequiredError,
    MatchProcessedError,
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
    KeepStatus,
    LostItemStatus,
    MatchStatus,
    Page,
    StandardResponse,
    success,
)
from app.schemas.match import (
    ClaimCreate,
    HandoverGenerateOut,
    HandoverVerifyOut,
    HandoverVerifyRequest,
    MatchManualCreate,
    MatchOut,
)
from app.services.handover_service import HandoverService
from app.services.match_service import MatchService, build_match_outs
from app.services.publish_service import PublishService


# ---------------- 工具 ----------------
def _now() -> datetime:
    """v7：朴素 UTC 当前时间（与 SQLite 存储一致，避免 naive/aware 比较报错）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
from app.services import audit_service

router = APIRouter(tags=["match"])


class RejectRequest(BaseModel):
    reason: Optional[str] = None


def _get_match_or_404(db: Session, match_id: int) -> MatchRecord:
    m = db.get(MatchRecord, match_id)
    if not m:
        raise NotFoundError("匹配不存在")
    return m


def _counterpart_hidden(db: Session, m: MatchRecord) -> bool:
    """P1-2：候选对端物品已软删 / 进行中状态对端已解决 → 对当前用户隐藏。

    仅对「进行中」状态（0 待认领 / 1 认领中 / 4 待自取）做对端已解决过滤；
    终态（2 已完成 / 3 已拒绝 / 5 已放弃 / 6 已撤回）必须保留在对应 tab，不参与过滤。
    """
    lost = db.get(LostItem, m.lost_id)
    found = db.get(FoundItem, m.found_id)
    if lost is None or found is None:
        return True
    if lost.deleted_at is not None or found.deleted_at is not None:
        return True
    if int(m.status) in (int(MatchStatus.PENDING_CLAIM), int(MatchStatus.CLAIMING), int(MatchStatus.MANUAL_PENDING)):
        if int(lost.status) == int(LostItemStatus.RESOLVED) or int(found.status) == int(FoundItemStatus.RESOLVED):
            return True
    return False


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


# ---------------- 失物的匹配列表（按 score 降序） ----------------
@router.get("/lost-items/{item_id}/matches", response_model=StandardResponse)
def list_matches_for_lost(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """某失物的候选匹配列表（score 降序，≤10 条，含低分）。

    候选上限与分数已由发布侧 top10 控制（含低分），此处放开阈值不做二次过滤；
    仅追加对端（拾物侧）软删/已解决过滤（P1-2）。
    """
    lost = db.get(LostItem, item_id)
    if not lost:
        raise NotFoundError("失物不存在")
    if int(lost.publisher_id) != int(user.id):
        raise PermissionError()
    matches = (
        db.query(MatchRecord)
        .filter(MatchRecord.lost_id == item_id)
        .all()
    )
    matches = [m for m in matches if not _counterpart_hidden(db, m)]
    outs = build_match_outs(db, matches)
    return success(data=outs)


# ---------------- 我的匹配 ----------------
@router.get("/matches", response_model=StandardResponse)
def list_my_matches(
    status: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前用户相关的匹配（失主或拾得者）。

    结果含低分候选（suspected=false，按 score 降序）；进行中候选的对端物品
    已软删 / 已解决时隐藏（P1-2）。page_size 上限 200 以适配多件失物 × 10 候选场景（P1-4）。

    flow-v3 U2=完全隐藏（方案 2）：as_found 分支过滤掉 keep1（留在原地未挪动）拾物的
    全部候选，拾得者侧不再看到任何 keep1 匹配记录（无论状态），单向性由列表层过滤保证。
    """
    as_lost = (
        db.query(MatchRecord)
        .join(LostItem, MatchRecord.lost_id == LostItem.id)
        .filter(LostItem.publisher_id == user.id)
    )
    as_found = (
        db.query(MatchRecord)
        .join(FoundItem, MatchRecord.found_id == FoundItem.id)
        .filter(FoundItem.finder_id == user.id)
        # flow-v3 U2=完全隐藏：过滤 keep1（NOT_KEEPING=1）拾物的全部候选，
        # 拾得者侧不再看到任何 keep1 匹配记录（与 claim/confirm-return/reject 守卫互为纵深）
        .filter(FoundItem.keep_status != int(KeepStatus.NOT_KEEPING))
    )
    if status is not None:
        as_lost = as_lost.filter(MatchRecord.status == status)
        as_found = as_found.filter(MatchRecord.status == status)
    matches = as_lost.all() + as_found.all()
    # 去重
    seen = set()
    unique = []
    for m in matches:
        if m.id not in seen:
            seen.add(m.id)
            unique.append(m)
    unique.sort(key=lambda x: float(x.match_score), reverse=True)
    # P1-2：对端软删 / 进行中状态对端已解决 → 隐藏（终态保留）
    unique = [m for m in unique if not _counterpart_hidden(db, m)]
    total = len(unique)
    start = (page - 1) * page_size
    page_items = unique[start : start + page_size]
    outs = build_match_outs(db, page_items)
    return success(
        data=Page[MatchOut](items=outs, total=total, page=page, page_size=page_size)
    )


# ---------------- 手动刷新候选（P2-1） ----------------
@router.post("/lost-items/{item_id}/refresh-matches", response_model=StandardResponse)
def refresh_matches_for_lost(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P2-1：对单条失物重跑召回+打分，增量补充新发布拾物候选。

    仅失主可调；已解决 / 已软删失物拒绝刷新。刷新为增量补足（去重、每件 ≤ MATCH_TOP_N、
    不挤占旧候选），候选已满时幂等返回 created=0。响应含本次新增数与当前全部候选。
    """
    lost = db.get(LostItem, item_id)
    if lost is None:
        raise NotFoundError("失物不存在")
    if int(lost.publisher_id) != int(user.id):
        raise PermissionError()
    if lost.deleted_at is not None:
        raise ParamError("该失物已删除，不可刷新候选")
    if int(lost.status) == int(LostItemStatus.RESOLVED):
        raise ParamError("已解决的失物不可刷新候选")
    created = PublishService(db).refresh_lost_candidates(lost)
    db.commit()
    matches = (
        db.query(MatchRecord)
        .filter(MatchRecord.lost_id == item_id)
        .all()
    )
    matches = [m for m in matches if not _counterpart_hidden(db, m)]
    outs = build_match_outs(db, matches)
    return success(data={"created": len(created), "matches": outs})


# ---------------- 认领 ----------------
@router.post("/matches/{match_id}/claim", response_model=StandardResponse)
def claim_match(
    match_id: int,
    body: ClaimCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """失主认领（claim_reason 必填）。

    P0-3 分流守卫：keep_status=1（留在原地未挪动）拾物不允许走普通 claim，
    请使用「申请即完成」（POST /matches/{id}/claim-complete）。
    """
    if not body.claim_reason or not body.claim_reason.strip():
        raise ClaimReasonRequiredError()
    m = _get_match_or_404(db, match_id)
    lost = db.get(LostItem, m.lost_id)
    if not lost or int(lost.publisher_id) != int(user.id):
        raise PermissionError("仅失主可认领")
    if int(m.status) != int(MatchStatus.PENDING_CLAIM):
        raise MatchProcessedError("该匹配已处理（非待认领）")
    found = db.get(FoundItem, m.found_id)
    if found is not None and int(found.keep_status) == int(KeepStatus.NOT_KEEPING):
        raise ParamError("该拾物留在原地未挪动，请使用「申请即完成」")

    m.status = int(MatchStatus.CLAIMING)
    m.claim_reason = body.claim_reason
    lost.status = 2  # 待认领
    db.flush()
    audit_service.write_audit(
        db,
        user_id=user.id,
        action="claim",
        target_type="match",
        target_id=m.id,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
        detail=body.claim_reason,
    )
    db.commit()
    db.refresh(m)
    return success(data=build_match_outs(db, [m])[0])


# ---------------- 确认归还 ----------------
@router.post("/matches/{match_id}/confirm-return", response_model=StandardResponse)
def confirm_return(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """拾得者确认归还（双端交接前置）。

    flow-v3 keep1 单向性守卫：keep_status=1（留在原地未挪动）拾物由失主自取完成，
    拾得者无操作权（物品不在他手上，东西被谁领走与他无关），一律 422。
    """
    m = _get_match_or_404(db, match_id)
    found = db.get(FoundItem, m.found_id)
    if not found or int(found.finder_id) != int(user.id):
        raise PermissionError("仅拾得者可确认归还")
    # flow-v3：keep1 拾得者不可操作（与 claim 守卫对称：ParamError → 422 / code 9001）
    if int(found.keep_status) == int(KeepStatus.NOT_KEEPING):
        raise ParamError("该物品留在原地未挪动，无需你确认归还，请等待失主申请后自行取回")
    if int(m.status) not in (int(MatchStatus.PENDING_CLAIM), int(MatchStatus.CLAIMING)):
        raise MatchProcessedError("该匹配状态不可确认归还")

    # 保持认领中（待交接）；记录审计
    audit_service.write_audit(
        db,
        user_id=user.id,
        action="confirm_return",
        target_type="match",
        target_id=m.id,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(m)
    return success(data=build_match_outs(db, [m])[0])


# ---------------- 交接码生成 ----------------
@router.post("/matches/{match_id}/handover/generate", response_model=StandardResponse)
def handover_generate(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """生成动态交接码（仅认领中可生成）。"""
    m = _get_match_or_404(db, match_id)
    lost = db.get(LostItem, m.lost_id)
    found = db.get(FoundItem, m.found_id)
    if not lost or not found:
        raise NotFoundError("匹配关联物品不存在")
    if int(user.id) not in (int(lost.publisher_id), int(found.finder_id)):
        raise PermissionError("仅失主或拾得者可生成交接码")

    hc = HandoverService(db).generate_code(match_id, operator_id=user.id)
    return success(
        data=HandoverGenerateOut(
            code=hc.code, qr_token=hc.qr_token, expire_at=hc.expire_at
        )
    )


# ---------------- 交接码验证 ----------------
@router.post("/matches/{match_id}/handover/verify", response_model=StandardResponse)
def handover_verify(
    match_id: int,
    body: HandoverVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """双端验证交接码；双方确认后自动完成交接。"""
    m = _get_match_or_404(db, match_id)
    lost = db.get(LostItem, m.lost_id)
    found = db.get(FoundItem, m.found_id)
    if not lost or not found:
        raise NotFoundError("匹配关联物品不存在")
    if int(user.id) not in (int(lost.publisher_id), int(found.finder_id)):
        raise PermissionError("仅失主或拾得者可验证交接码")

    result = HandoverService(db).verify(
        code=body.code,
        role=body.role,
        gps=body.gps,
        operator_id=user.id,
    )
    return success(
        data=HandoverVerifyOut(
            both_verified=result["both_verified"],
            verified_by_lost=result["verified_by_lost"],
            verified_by_finder=result["verified_by_finder"],
        )
    )


# ---------------- 拒绝 ----------------
@router.post("/matches/{match_id}/reject", response_model=StandardResponse)
def reject_match(
    match_id: int,
    body: RejectRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """拾得者拒绝认领。

    flow-v3 keep1 单向性守卫：keep_status=1（留在原地未挪动）拾物是否被领走由失主决定，
    拾得者不得单方面把候选打成 REJECTED（否则会与「刷新候选」形成再召回—再拒绝的骚扰循环），
    一律 422。
    """
    m = _get_match_or_404(db, match_id)
    found = db.get(FoundItem, m.found_id)
    if not found or int(found.finder_id) != int(user.id):
        raise PermissionError("仅拾得者可拒绝认领")
    # flow-v3：keep1 拾得者不可操作（与 claim 守卫对称：ParamError → 422 / code 9001）
    if int(found.keep_status) == int(KeepStatus.NOT_KEEPING):
        raise ParamError("该物品留在原地未挪动，是否被领走由失主决定，你无需处理")
    if int(m.status) not in (int(MatchStatus.PENDING_CLAIM), int(MatchStatus.CLAIMING)):
        raise MatchProcessedError("该匹配已处理（非待认领/认领中）")

    m.status = int(MatchStatus.REJECTED)
    lost = db.get(LostItem, m.lost_id)
    if lost and int(lost.status) == 2:
        lost.status = 1  # 回退到匹配中
    db.flush()
    audit_service.write_audit(
        db,
        user_id=user.id,
        action="reject",
        target_type="match",
        target_id=m.id,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
        detail=body.reason,
    )
    db.commit()
    db.refresh(m)
    return success(data=build_match_outs(db, [m])[0])


# ---------------- v4 手动申请匹配（待自取） ----------------
@router.post("/matches/manual", response_model=StandardResponse)
def create_manual_match(
    body: MatchManualCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动申请匹配：失主针对某拾物发起「待自取」匹配（status=4，单边）。

    校验：当前用户 = lost_id 发布者；found_item.status==0（待认领）；
    lost_item.status ∈ {0,1,2}；该 (lost_id, found_id) 尚无进行中匹配（0/1/4）。
    match_score 仅作展示（可 < 阈值）。
    """
    lost = db.get(LostItem, body.lost_id)
    if lost is None:
        raise NotFoundError("失物不存在")
    if int(lost.publisher_id) != int(user.id):
        raise PermissionError("仅失主可发起申请匹配")
    if int(lost.status) not in (
        int(LostItemStatus.PENDING_MATCH),
        int(LostItemStatus.MATCHING),
        int(LostItemStatus.PENDING_CLAIM),
    ):
        raise ParamError("该失物状态不可发起申请匹配")

    found = db.get(FoundItem, body.found_id)
    if found is None:
        raise NotFoundError("拾物不存在")
    # v7：逻辑删除（软删）的物品不可再发起匹配
    if lost.deleted_at is not None:
        raise ParamError("该失物已删除，不可发起申请匹配")
    if found.deleted_at is not None:
        raise ParamError("该拾物已删除，不可申请匹配")
    if int(found.status) != int(FoundItemStatus.PENDING):
        raise MatchProcessedError("该拾物不可申请匹配")

    existing = (
        db.query(MatchRecord)
        .filter(
            MatchRecord.lost_id == body.lost_id,
            MatchRecord.found_id == body.found_id,
            MatchRecord.status.in_(
                [
                    int(MatchStatus.PENDING_CLAIM),
                    int(MatchStatus.CLAIMING),
                    int(MatchStatus.MANUAL_PENDING),
                ]
            ),
        )
        .first()
    )
    if existing is not None:
        raise MatchProcessedError("该失物与拾物已存在进行中的匹配")

    score = MatchService().score(lost, found)
    if int(found.keep_status) == int(KeepStatus.NOT_KEEPING):
        # P1-1 分流：keep1（留在原地未挪动）拾物「申请匹配」= 一步完成（P0-3，不生成待自取）。
        # 直接落终态 status=2 + flow_type=1 + completed_at，复用共享私有方法完成双端置已解决与审计。
        m = MatchRecord(
            lost_id=body.lost_id,
            found_id=body.found_id,
            match_score=score,
            status=int(MatchStatus.COMPLETED),
            flow_type=1,
            completed_at=_now(),
        )
        db.add(m)
        db.flush()
        PublishService(db)._apply_keep1_completion(
            m, lost, found, _client_ip(request), request.headers.get("user-agent")
        )
        db.commit()
        db.refresh(m)
        return success(data=build_match_outs(db, [m])[0])

    m = MatchRecord(
        lost_id=body.lost_id,
        found_id=body.found_id,
        match_score=score,
        status=int(MatchStatus.MANUAL_PENDING),
    )
    db.add(m)
    db.flush()
    audit_service.write_audit(
        db,
        user_id=user.id,
        action="manual_match_create",
        target_type="match",
        target_id=m.id,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
        detail=f"lost_id={body.lost_id};found_id={body.found_id};score={score}",
    )
    db.commit()
    db.refresh(m)
    return success(data=build_match_outs(db, [m])[0])


# ---------------- v4 未挪动自取完成（单边归档，不调 handover） ----------------
@router.post("/matches/{match_id}/self-complete", response_model=StandardResponse)
def self_complete_match(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """未挪动自取完成：失主单边归档（status→2），双端置已解决，不调双码交接。

    校验：当前用户 = lost_id 发布者；match.status==4（待自取）。
    """
    m = _get_match_or_404(db, match_id)
    lost = db.get(LostItem, m.lost_id)
    found = db.get(FoundItem, m.found_id)
    if lost is None or int(lost.publisher_id) != int(user.id):
        raise PermissionError("仅失主可完成自取")
    if int(m.status) != int(MatchStatus.MANUAL_PENDING):
        raise MatchProcessedError("仅待自取匹配可完成")

    m.status = int(MatchStatus.COMPLETED)
    # 2026-08-05 flow-v2：存量 keep1（未挪动）status=4 自取完成时补记 flow_type=1，
    # 使旧「待自取」完成的 keep1 记录也可撤回（设计 §7 待明确事项 6）。
    if found is not None and int(found.keep_status) == int(KeepStatus.NOT_KEEPING):
        m.flow_type = 1
    lost.status = int(LostItemStatus.RESOLVED)
    # v7：写完成时间 + 重置关联双方失效时间（顺延 90 天）
    m.completed_at = _now()
    lost.expires_at = _now() + timedelta(days=90)
    if found is not None:
        found.status = int(FoundItemStatus.RESOLVED)
        found.expires_at = _now() + timedelta(days=90)
    db.flush()
    audit_service.write_audit(
        db,
        user_id=user.id,
        action="manual_self_complete",
        target_type="match",
        target_id=m.id,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
        detail=f"lost_id={m.lost_id};found_id={m.found_id}",
    )
    db.commit()
    db.refresh(m)
    return success(data=build_match_outs(db, [m])[0])


# ---------------- v5 未能找回（撤销匹配 + 失物重入匹配池） ----------------
@router.post("/matches/{match_id}/giveup", response_model=StandardResponse)
def give_up_match(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """未能找回：失主主动放弃匹配（软删 MatchRecord.status=5），关联失物重入匹配池。

    校验：仅失主（当前用户 = lost.publisher_id）可调；匹配非终态（2/3 拒绝，409）；
    终态保护下 status=5 幂等成功。关联 IM 会话保留 match_id 溯源（规避 RESTRICT FK）。
    """
    m = _get_match_or_404(db, match_id)
    lost = db.get(LostItem, m.lost_id)
    if lost is None:
        raise NotFoundError("匹配关联失物不存在")
    if int(lost.publisher_id) != int(user.id):
        raise PermissionError("仅失主可放弃该匹配")

    # 终态保护：已完成(2)/已拒绝(3) 不可放弃
    if int(m.status) in (int(MatchStatus.COMPLETED), int(MatchStatus.REJECTED)):
        raise MatchProcessedError("该匹配已终态，无法放弃")

    m.status = int(MatchStatus.GIVEN_UP)
    lost.status = int(LostItemStatus.PENDING_MATCH)  # 重入待匹配池
    db.flush()
    audit_service.write_audit(
        db,
        user_id=user.id,
        action="match_give_up",
        target_type="match",
        target_id=m.id,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
        detail=f"lost_id={m.lost_id};found_id={m.found_id}",
    )
    db.commit()
    db.refresh(m)
    return success(data=build_match_outs(db, [m])[0])


# ---------------- 2026-08-05 flow-v2：keep1 申请即完成 / 撤回（R2） ----------------
@router.post("/matches/{match_id}/claim-complete", response_model=StandardResponse)
def claim_complete_keep1(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """keep1「申请即完成」（P0-3）：失主对 status=0 候选一步到位完成交接。

    校验：仅失主；匹配存在；found.keep_status==1 且 match.status==0（服务层校验）。
    不填理由、不生成交接码、不要求拾得者确认；返回终态 MatchOut(status=2, flow_type=1)。
    """
    m = _get_match_or_404(db, match_id)
    lost = db.get(LostItem, m.lost_id)
    if lost is None or int(lost.publisher_id) != int(user.id):
        raise PermissionError("仅失主可申请即完成")
    PublishService(db).complete_keep1_claim(
        m, ip=_client_ip(request), ua=request.headers.get("user-agent")
    )
    db.commit()
    db.refresh(m)
    return success(data=build_match_outs(db, [m])[0])


@router.post("/matches/{match_id}/revoke", response_model=StandardResponse)
def revoke_keep1_claim(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """keep1「撤回」（P0-4/Q3/Q7）：失主对已完成记录撤回，不限时限。

    校验：仅失主；flow_type==1 且 status==COMPLETED(2)（否则 409）；
    撤回后 MatchRecord→status=6、lost/found 状态回退、拾物恢复可申请（服务层实现）。
    """
    m = _get_match_or_404(db, match_id)
    lost = db.get(LostItem, m.lost_id)
    if lost is None or int(lost.publisher_id) != int(user.id):
        raise PermissionError("仅失主可撤回")
    if int(getattr(m, "flow_type", 0) or 0) != 1 or int(m.status) != int(MatchStatus.COMPLETED):
        raise MatchProcessedError("仅 keep1 申请即完成的已完成记录可撤回")
    PublishService(db).revoke_keep1_claim(
        m, ip=_client_ip(request), ua=request.headers.get("user-agent")
    )
    db.commit()
    db.refresh(m)
    return success(data=build_match_outs(db, [m])[0])
