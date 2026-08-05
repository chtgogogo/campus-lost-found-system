"""交接码服务（§3.4 交接 / §2.6）。

MVP：交接码以 DB 表 `handover_code` 为活性存储（替代 Redis），通过 `expire_at` 判定 TTL；
生产期可切换 Redis 活性存储 + MySQL 审计镜像（T-DEP）。

流程：generate（认领中可生成）→ 双端 verify（lost / finder）→ 双方确认后
match_record 置已完成、lost/found 置已解决。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings, get_redis
from app.core.exceptions import (
    HandoverConflictError,
    HandoverExpiredError,
    HandoverInvalidError,
    MatchProcessedError,
    NotFoundError,
    ParamError,
)
from app.models.item import FoundItem, LostItem
from app.models.match import HandoverCode, MatchRecord
from app.schemas.common import FoundItemStatus, HandoverStatus, LostItemStatus, MatchStatus
from app.services import audit_service

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去除易混淆字符


def _gen_code(length: int = 6) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # 朴素 UTC，便于 SQLite 比较


# ---------------- 交接码活跃存储（Redis / 内存兜底） ----------------
# 将交接码活性写入 KV 存储：`REDIS_ENABLED=True` 走 Redis，否则走进程内内存兜底
# （见 app.core.redis_client / app.core.config.get_redis）。缓存为「活性叠加层」，
# DB 始终是权威存储，缓存缺失/降级时无缝回退 DB，绝不改变既有业务语义。
def _cache_handover_code(code: str, match_id: int) -> None:
    """生成交接码后写入 KV 活跃存储，TTL = HANDOVER_TTL_MIN。"""
    try:
        ttl = int(settings.HANDOVER_TTL_MIN * 60)
        get_redis().set(f"handover:{code}", str(match_id), ttl_sec=ttl)
    except Exception:  # pragma: no cover - 缓存失败绝不影响业务
        pass


def _touch_handover_code(code: str) -> None:
    """成功验证后刷新交接码 TTL（活性续期），走 Redis/内存兜底。"""
    try:
        ttl = int(settings.HANDOVER_TTL_MIN * 60)
        get_redis().expires(f"handover:{code}", ttl)
    except Exception:  # pragma: no cover
        pass


class HandoverService:
    """交接码生成 / 双端验证。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def generate_code(self, match_id: int, operator_id: Optional[int] = None) -> HandoverCode:
        """为认领中的匹配生成交接码。"""
        match = self.db.get(MatchRecord, match_id)
        if not match:
            raise NotFoundError("匹配不存在")
        if match.status != int(MatchStatus.CLAIMING):
            raise MatchProcessedError("仅认领中（待交接）的匹配可生成交接码")

        last = (
            self.db.query(HandoverCode)
            .filter(HandoverCode.match_id == match_id)
            .order_by(HandoverCode.seq.desc())
            .first()
        )
        seq = (last.seq + 1) if last else 1

        now = _now()
        hc = HandoverCode(
            match_id=match_id,
            seq=seq,
            code=_gen_code(),
            qr_token=secrets.token_hex(32),
            status=int(HandoverStatus.VALID),
            expire_at=now + timedelta(minutes=settings.HANDOVER_TTL_MIN),
        )
        self.db.add(hc)
        self.db.flush()

        # 镜像到 match_record
        match.code = hc.code
        match.code_expire = hc.expire_at
        self.db.flush()

        audit_service.write_audit(
            self.db,
            user_id=operator_id,
            action="handover_generate",
            target_type="match",
            target_id=match_id,
            detail=f"seq={seq};code={hc.code}",
        )
        self.db.commit()
        # 交接码活性写入 KV 存储（Redis 或内存兜底），TTL=HANDOVER_TTL_MIN
        _cache_handover_code(hc.code, match_id)
        self.db.refresh(hc)
        return hc

    def verify(
        self,
        code: str,
        role: str,
        gps: Optional[str] = None,
        operator_id: Optional[int] = None,
    ) -> dict:
        """双端验证交接码，返回 {both_verified, verified_by_lost, verified_by_finder}。"""
        if role not in ("lost", "finder"):
            raise ParamError("role 必须为 lost 或 finder")

        hc = (
            self.db.query(HandoverCode)
            .filter(HandoverCode.code == code, HandoverCode.status == int(HandoverStatus.VALID))
            .order_by(HandoverCode.id.desc())
            .first()
        )
        if not hc:
            raise HandoverInvalidError()

        now = _now()
        if hc.expire_at < now:
            hc.status = int(HandoverStatus.EXPIRED)
            self.db.commit()
            raise HandoverExpiredError()

        if role == "lost":
            if hc.verified_by_lost:
                raise HandoverConflictError("失主端已验证，请等待对方确认")
            hc.verified_by_lost = True
            hc.gps_lost = gps
        else:  # finder
            if hc.verified_by_finder:
                raise HandoverConflictError("拾得者端已验证，请等待对方确认")
            hc.verified_by_finder = True
            hc.gps_finder = gps
        self.db.flush()
        # 成功验证即刷新交接码 TTL（活性续期），走 Redis/内存兜底
        _touch_handover_code(code)

        both = bool(hc.verified_by_lost and hc.verified_by_finder)
        if both:
            hc.status = int(HandoverStatus.VERIFIED)
            match = self.db.get(MatchRecord, hc.match_id)
            if match:
                match.status = int(MatchStatus.COMPLETED)
                lost = self.db.get(LostItem, match.lost_id)
                found = self.db.get(FoundItem, match.found_id)
                if lost:
                    lost.status = int(LostItemStatus.RESOLVED)
                if found:
                    found.status = int(FoundItemStatus.RESOLVED)
                # v7：写完成时间 + 重置关联双方失效时间（顺延 90 天）
                match.completed_at = now
                if lost:
                    lost.expires_at = now + timedelta(days=90)
                if found:
                    found.expires_at = now + timedelta(days=90)
                audit_service.write_audit(
                    self.db,
                    user_id=operator_id,
                    action="handover_complete",
                    target_type="match",
                    target_id=match.id,
                    gps=f"{hc.gps_lost or ''}|{hc.gps_finder or ''}",
                    detail=f"code={hc.code}",
                )

        self.db.commit()
        self.db.refresh(hc)
        return {
            "both_verified": both,
            "verified_by_lost": bool(hc.verified_by_lost),
            "verified_by_finder": bool(hc.verified_by_finder),
        }
