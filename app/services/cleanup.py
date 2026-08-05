"""v7 周期清理服务（§3.2）。

超 1 年数据按依赖序物理清理：``IMMessage → IMSession → MatchRecord → Item``，
规避 ``MatchRecord.lost_id/found_id`` 的 RESTRICT 外键。仅清理「双方物品都超期」的匹配，
确保物品侧随后可安全删除（不破坏引用完整性）。

保留窗：管理员留存 1 年，即物品 ``expires_at + 270 天`` 之后才进入清理范围；
``expires_at`` 为 NULL 的存量（理论不存在，迁移已回填）按"保留"处理，不参与清理。

时区：与 SQLite 存储一致，统一使用朴素 UTC ``now``（避免 naive/aware 比较报错）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.im import IMMessage, IMSession
from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord


def _now() -> datetime:
    """朴素 UTC 当前时间（与 SQLite 存储一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CleanupService:
    """超期数据物理清理（依赖序，规避 RESTRICT FK）。"""

    # v10（Q4 方案 A · P1）：留存天数配置化，默认仍 270 → `test_v7_cleanup_fk_order.py` 零回归。
    # ⚠️ **必须保持类属性形态**：`run_once` 用 `self.ADMIN_RETENTION_DAYS`，
    # 存量/后续测试可能直接 monkeypatch 该类属性；不要改成实例属性或在 run_once 里读 config。
    ADMIN_RETENTION_DAYS = settings.ADMIN_RETENTION_DAYS

    def __init__(self, db: Session) -> None:
        self.db = db

    def run_once(self, limit: int | None = None) -> dict:
        """执行一轮清理，返回 ``{purged_matches, purged_items}``。

        顺序（核心，F6）：先删依赖 ``MatchRecord`` 的 ``IMMessage``/``IMSession``，
        再删 ``MatchRecord`` 自身，最后删无引用的超期 ``Item``。
        """
        now = _now()
        cutoff = now - timedelta(days=self.ADMIN_RETENTION_DAYS)

        # ---- 1) 超期匹配（仅选双方物品都超期的匹配） ----
        overdue = (
            self.db.query(MatchRecord)
            .join(LostItem, MatchRecord.lost_id == LostItem.id)
            .join(FoundItem, MatchRecord.found_id == FoundItem.id)
            .filter(LostItem.expires_at < cutoff)
            .filter(FoundItem.expires_at < cutoff)
            .order_by(MatchRecord.id.asc())
        )
        if limit is not None:
            overdue = overdue.limit(limit)
        matches = overdue.all()

        purged_matches = 0
        for m in matches:
            # 1a) IMMessage（关联该匹配的会话下的消息，依赖 IMSession）
            session_ids = [
                sid
                for (sid,) in self.db.query(IMSession.id)
                .filter(IMSession.match_id == m.id)
                .all()
            ]
            if session_ids:
                self.db.query(IMMessage).filter(
                    IMMessage.session_id.in_(session_ids)
                ).delete(synchronize_session=False)
                self.db.query(IMSession).filter(
                    IMSession.match_id == m.id
                ).delete(synchronize_session=False)
            # 1b) MatchRecord 自身
            self.db.query(MatchRecord).filter(MatchRecord.id == m.id).delete(
                synchronize_session=False
            )
            purged_matches += 1

        # ---- 2) 超期且无剩余引用的物品 ----
        referenced_lost = self.db.query(MatchRecord.lost_id)
        referenced_found = self.db.query(MatchRecord.found_id)

        overdue_lost = (
            self.db.query(LostItem)
            .filter(LostItem.expires_at < cutoff)
            .filter(~LostItem.id.in_(referenced_lost))
            .all()
        )
        overdue_found = (
            self.db.query(FoundItem)
            .filter(FoundItem.expires_at < cutoff)
            .filter(~FoundItem.id.in_(referenced_found))
            .all()
        )
        for it in overdue_lost:
            self.db.query(LostItem).filter(LostItem.id == it.id).delete(
                synchronize_session=False
            )
        for it in overdue_found:
            self.db.query(FoundItem).filter(FoundItem.id == it.id).delete(
                synchronize_session=False
            )

        self.db.commit()
        return {
            "purged_matches": purged_matches,
            "purged_items": len(overdue_lost) + len(overdue_found),
        }
