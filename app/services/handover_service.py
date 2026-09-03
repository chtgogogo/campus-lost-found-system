"""交接码服务（§3.4 交接 / §2.6）。

双码交叉验证模型：
- 失主调用 generate → 生成 lost_code（4位数字，10秒过期）
- 拾得者调用 generate → 生成 finder_code（4位数字，10秒过期）
- 失主输入拾得者的码（role="lost"）→ finder_code_verified=True（确认物品已收到）
- 拾得者输入失主的码（role="finder"）→ lost_code_verified=True（证明是授权领取人）
- 双方交叉验证通过 → 交接完成

DB 表 handover_code 为权威存储（Redis 默认关闭，仅做活性加速）。
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
    PermissionError,
)
from app.models.item import FoundItem, LostItem
from app.models.match import HandoverCode, MatchRecord
from app.schemas.common import FoundItemStatus, HandoverStatus, LostItemStatus, MatchStatus
from app.services import audit_service


def _gen_code() -> str:
    """生成4位随机数字码（0000-9999）。"""
    return f"{secrets.randbelow(10000):04d}"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # 朴素 UTC，便于 SQLite 比较


# ---------------- 交接码活跃存储（Redis / 内存兜底） ----------------
# 将交接码活性写入 KV 存储：`REDIS_ENABLED=True` 走 Redis，否则走进程内内存兜底。
# DB 始终是权威存储，缓存缺失/降级时无缝回退 DB，绝不改变既有业务语义。
def _cache_handover_code(code: str, match_id: int, role: str) -> None:
    """生成交接码后写入 KV 活跃存储，TTL = HANDOVER_TTL_SEC。"""
    try:
        ttl = int(settings.HANDOVER_TTL_SEC)
        get_redis().set(f"handover:{match_id}:{role}", code, ttl_sec=ttl)
    except Exception:  # pragma: no cover - 缓存失败绝不影响业务
        pass


class HandoverService:
    """交接码生成 / 双码交叉验证。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def generate_code(
        self, match_id: int, operator_id: Optional[int] = None
    ) -> tuple[HandoverCode, str]:
        """为认领中的匹配生成交接码（双码模型：根据 operator 判断生成 lost_code 或 finder_code）。

        Returns:
            (HandoverCode, role) 元组，role 为 "lost" 或 "finder"。
        """
        match = self.db.get(MatchRecord, match_id)
        if not match:
            raise NotFoundError("匹配不存在")
        if match.status != int(MatchStatus.CLAIMING):
            raise MatchProcessedError("仅认领中（待交接）的匹配可生成交接码")

        # 根据 operator_id 判断角色
        lost = self.db.get(LostItem, match.lost_id)
        found = self.db.get(FoundItem, match.found_id)
        if not lost or not found:
            raise NotFoundError("匹配关联物品不存在")
        if operator_id is not None and int(operator_id) == int(lost.publisher_id):
            role = "lost"
        elif operator_id is not None and int(operator_id) == int(found.finder_id):
            role = "finder"
        else:
            raise PermissionError("仅失主或拾得者可生成交接码")

        now = _now()
        expire = now + timedelta(seconds=settings.HANDOVER_TTL_SEC)

        # 查找当前有效行（同一 match 最新 seq，status=VALID）
        hc = (
            self.db.query(HandoverCode)
            .filter(
                HandoverCode.match_id == match_id,
                HandoverCode.status == int(HandoverStatus.VALID),
            )
            .order_by(HandoverCode.seq.desc())
            .first()
        )

        if hc is None:
            # 新建一轮
            last = (
                self.db.query(HandoverCode)
                .filter(HandoverCode.match_id == match_id)
                .order_by(HandoverCode.seq.desc())
                .first()
            )
            seq = (last.seq + 1) if last else 1
            hc = HandoverCode(
                match_id=match_id, seq=seq, status=int(HandoverStatus.VALID)
            )
            self.db.add(hc)

        # 设置该方的码 + 过期时间，重置该码的验证标记
        if role == "lost":
            hc.lost_code = _gen_code()
            hc.lost_code_expire = expire
            hc.lost_code_verified = False
        else:
            hc.finder_code = _gen_code()
            hc.finder_code_expire = expire
            hc.finder_code_verified = False

        self.db.flush()

        # 镜像到 match_record（最新生成的码）
        code_value = hc.lost_code if role == "lost" else hc.finder_code
        match.code = code_value
        match.code_expire = expire
        self.db.flush()

        audit_service.write_audit(
            self.db,
            user_id=operator_id,
            action="handover_generate",
            target_type="match",
            target_id=match_id,
            detail=f"seq={hc.seq};role={role};code={code_value}",
        )
        self.db.commit()

        # 缓存层（Redis 默认关闭，DB 是权威存储）
        _cache_handover_code(code_value, match_id, role)

        self.db.refresh(hc)
        return hc, role

    def verify(
        self,
        match_id: int,
        code: str,
        role: str,
        gps: Optional[str] = None,
        operator_id: Optional[int] = None,
    ) -> dict:
        """双码交叉验证。

        role="lost"  → 失主在验证，输入的是 finder_code（确认物品已收到）
        role="finder" → 拾得者在验证，输入的是 lost_code（证明是授权领取人）

        Returns:
            {both_verified, lost_code_verified, finder_code_verified}
        """
        if role not in ("lost", "finder"):
            raise ParamError("role 必须为 lost 或 finder")

        # 通过 match_id + status=VALID 查找当前有效行
        hc = (
            self.db.query(HandoverCode)
            .filter(
                HandoverCode.match_id == match_id,
                HandoverCode.status == int(HandoverStatus.VALID),
            )
            .order_by(HandoverCode.seq.desc())
            .first()
        )
        if not hc:
            raise HandoverInvalidError()

        now = _now()

        if role == "lost":
            # 失主验证 → 输入的是 finder_code
            target_code = hc.finder_code
            target_expire = hc.finder_code_expire
            if hc.finder_code_verified:
                raise HandoverConflictError("你已验证，请等待对方确认")
        else:
            # 拾得者验证 → 输入的是 lost_code
            target_code = hc.lost_code
            target_expire = hc.lost_code_expire
            if hc.lost_code_verified:
                raise HandoverConflictError("你已验证，请等待对方确认")

        # 检查对方是否已生成码
        if target_code is None:
            raise HandoverInvalidError("对方尚未生成交接码")

        # 检查码是否正确
        if target_code != code:
            raise HandoverInvalidError()

        # 检查是否过期
        if target_expire and target_expire < now:
            raise HandoverExpiredError()

        # 标记验证通过
        if role == "lost":
            hc.finder_code_verified = True
            hc.gps_lost = gps
        else:
            hc.lost_code_verified = True
            hc.gps_finder = gps
        self.db.flush()

        both = bool(hc.lost_code_verified and hc.finder_code_verified)
        if both:
            hc.status = int(HandoverStatus.VERIFIED)
            match = self.db.get(MatchRecord, hc.match_id)
            if match:
                match.status = int(MatchStatus.COMPLETED)
                lost = self.db.get(LostItem, match.lost_id)
                found = self.db.get(FoundItem, match.found_id)
                if lost:
                    lost.status = int(LostItemStatus.RESOLVED)
                    lost.expires_at = now + timedelta(days=90)
                if found:
                    found.status = int(FoundItemStatus.RESOLVED)
                    found.expires_at = now + timedelta(days=90)
                match.completed_at = now
                audit_service.write_audit(
                    self.db,
                    user_id=operator_id,
                    action="handover_complete",
                    target_type="match",
                    target_id=match.id,
                    gps=f"{hc.gps_lost or ''}|{hc.gps_finder or ''}",
                    detail=f"seq={hc.seq};lost_code={hc.lost_code};finder_code={hc.finder_code}",
                )

        self.db.commit()
        self.db.refresh(hc)
        return {
            "both_verified": both,
            "lost_code_verified": bool(hc.lost_code_verified),
            "finder_code_verified": bool(hc.finder_code_verified),
        }
