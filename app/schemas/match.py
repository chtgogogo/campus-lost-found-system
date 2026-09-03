"""匹配 / 认领 / 交接 Schema（§3.4）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.item import FoundItemOut, LostItemOut


class ClaimCreate(BaseModel):
    """认领申请请求体（claim_reason 必填，空串由服务层判定为 3002）。"""

    claim_reason: str = Field(..., description="认领理由 / 独有凭证（必填，空串将返回 3002）")
    unique_proof: Optional[str] = Field(None, description="独有凭证补充（选填）")


class MatchManualCreate(BaseModel):
    """手动申请匹配请求体（v4 新增）：失主针对某拾物发起「待自取」匹配。

    校验在服务层：当前用户须为 lost_id 发布者；found_item.status==0（待认领）；
    lost_item.status ∈ {0,1,2}；该 (lost_id, found_id) 尚无进行中匹配。
    """

    lost_id: int = Field(..., description="失主发布的失物 id（须为当前用户发布）")
    found_id: int = Field(..., description="目标拾物 id（须为待认领状态）")


class HandoverGenerateOut(BaseModel):
    """交接码生成响应（返回调用方刚生成的码）。"""

    role: str          # "lost" | "finder" — 本次生成的是哪方的码
    code: str          # 4位数字码
    expire_at: datetime


class HandoverVerifyRequest(BaseModel):
    """交接码验证请求体（结构不变，语义变更）。"""

    code: str = Field(..., min_length=4, max_length=4, description="对方的4位数字码")
    role: str = Field(..., description="lost | finder — 谁在验证")
    gps: Optional[str] = None


class HandoverVerifyOut(BaseModel):
    """交接码验证响应。"""

    both_verified: bool
    lost_code_verified: bool       # 拾得者已正确输入失主码
    finder_code_verified: bool     # 失主已正确输入拾得者码


class MatchOut(BaseModel):
    """匹配记录输出。"""

    id: int
    lost_id: int
    found_id: int
    match_score: float
    status: int
    claim_reason: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None  # v7：完成时间
    lost_item: Optional[LostItemOut] = None
    found_item: Optional[FoundItemOut] = None
    suspected: bool = False  # 是否达到疑似阈值
    shared_attributes: list[str] = []  # 失物/拾物 tags 交集（可解释：展示"共享：钱包/粉色/..."）
    # v2 新增：完成方式标记（0=双向交接 keep0 / 1=keep1 单边「申请即完成」），撤回动作唯一门控
    flow_type: int = 0
    # flow-v2 维度明细（加权贡献，供前端展示各维度占比 / 论文可解释性）
    photo: Optional[float] = None
    category: Optional[float] = None
    appearance: Optional[float] = None  # [deprecated] 旧六维占位，flow-v2 并入 text，恒 0.0 或缺失
    feature: Optional[float] = None     # [deprecated] 旧六维占位，flow-v2 并入 text，恒 0.0 或缺失
    time: Optional[float] = None
    location: Optional[float] = None
    # flow-v2 新增：文字维度（R4）
    text: Optional[float] = None            # 文字维度加权贡献（v10 起 = 文字五子维度之和，0–70）
    text_match_rate: Optional[float] = None  # v10 语义变更：= text / 70（0–1）
    shared_text: list[str] = []             # 失物侧被命中的词（可解释："共享文字"）
    total: Optional[float] = None
    # ---- v10 评分引擎 v2 新增 10 个字段（全部 Optional，老前端不读不报错，C-2） ----
    # 七子维度返回的都是**归一化前的原始分**；只有 total / match_score 是归一化后的。
    photo_category: Optional[float] = None   # 照片 / 系统分类一致性（0–20）
    qty: Optional[float] = None              # 量词一致性（0–15）
    color: Optional[float] = None            # 颜色合类一致性（0–20）
    state: Optional[float] = None            # 状态 / 形容词（0–10）
    place: Optional[float] = None            # 地点四级（0–15，= 旧键 location）
    keyword: Optional[float] = None          # 其他关键词（0–10）
    signals: list[str] = []                  # color_conflict / state_conflict 子集
    raw_total: Optional[float] = None        # 归一化前原始总分（0–100）
    norm_factor: Optional[float] = None      # 归一化系数 k（≥1.0）
    provided_dims: list[str] = []            # 失主实际填写的维度名（可解释 + 可测）
    # v11（2026-08-27）：CLIP 图片相似度（0-1），NULL=未精排/CLIP 不可用。
    # 仅作列表同分打破平局，不改 match_score 语义；前端据此显示"AI 精排中"过渡态。
    clip_sim: Optional[float] = None

    @classmethod
    def from_model(
        cls,
        match,
        lost_item=None,
        found_item=None,
        lost_name: Optional[str] = None,
        found_name: Optional[str] = None,
        threshold: float = 80.0,
        photo: Optional[float] = None,
        category: Optional[float] = None,
        appearance: Optional[float] = None,
        feature: Optional[float] = None,
        time: Optional[float] = None,
        location: Optional[float] = None,
        total: Optional[float] = None,
        flow_type: Optional[int] = None,
        text: Optional[float] = None,
        text_match_rate: Optional[float] = None,
        shared_text: Optional[list[str]] = None,
        photo_category: Optional[float] = None,
        qty: Optional[float] = None,
        color: Optional[float] = None,
        state: Optional[float] = None,
        place: Optional[float] = None,
        keyword: Optional[float] = None,
        signals: Optional[list[str]] = None,
        raw_total: Optional[float] = None,
        norm_factor: Optional[float] = None,
        provided_dims: Optional[list[str]] = None,
    ) -> "MatchOut":
        # 计算可解释的交集标签（失物 tags ∩ 拾物 tags）
        lost_tags = set(getattr(lost_item, "tags", None) or [])
        found_tags = set(getattr(found_item, "tags", None) or [])
        shared = sorted(lost_tags & found_tags)
        return cls(
            id=match.id,
            lost_id=match.lost_id,
            found_id=match.found_id,
            match_score=float(match.match_score),
            status=int(match.status),
            claim_reason=match.claim_reason,
            created_at=match.created_at,
            completed_at=match.completed_at,
            lost_item=LostItemOut.from_model(lost_item) if lost_item else None,
            found_item=FoundItemOut.from_model(found_item) if found_item else None,
            suspected=float(match.match_score) >= threshold,
            shared_attributes=shared,
            flow_type=flow_type if flow_type is not None else int(getattr(match, "flow_type", 0) or 0),
            photo=photo,
            category=category,
            appearance=appearance,
            feature=feature,
            time=time,
            location=location,
            text=text,
            text_match_rate=text_match_rate,
            shared_text=shared_text or [],
            total=total,
            photo_category=photo_category,
            qty=qty,
            color=color,
            state=state,
            place=place,
            keyword=keyword,
            signals=signals or [],
            raw_total=raw_total,
            norm_factor=norm_factor,
            provided_dims=provided_dims or [],
            clip_sim=(
                float(match.clip_sim) if getattr(match, "clip_sim", None) is not None else None
            ),
        )


class MatchListQuery(BaseModel):
    """匹配列表查询参数。"""

    status: Optional[int] = None
    page: int = 1
    page_size: int = 20
