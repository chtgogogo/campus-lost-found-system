"""发布编排服务（§4 发布→打标→入库→反向主动匹配→疑似提醒）。

- 上传图片 → 本地存储返回 URL。
- 类目解析（v4）：优先按 `category_name` / 提取名词命中种子类目；否则调用视觉降级。
- **v4 挂载**：发布时由 `TaggingService` 抽取结构化标签（名词优先）、由 `PerceptualHash` 计算首图感知哈希。
- 写入 lost_item / found_item（地点语义已并入 description，不再存独立 location 列）。
- 反向主动匹配（v4 名词召回）：召回「同类目 ∪ 共享物品名词 tag」的候选，按新公式打分后
  以 (-score, id) 降序，**无论分数**均生成 status=0 候选（Q1/P0-1 拍板）。
- **v10 变更 B**：候选输出由「硬截断前 MATCH_TOP_N 条」改为
  **「保底前 MATCH_TOP_N 条 + 其后所有 ≥ MATCH_THRESHOLD 的疑似」**（`_cut_with_suspects`）。
  `MATCH_TOP_N` 变量名不改，语义改为「普通候选保底条数」；疑似不受此限，上限由
  `MATCH_SUSPECT_MAX` 兜底防爆。三处（`_reverse_match_lost` / `_reverse_match_found` /
  `refresh_lost_candidates`）口径一致。
- 落审计日志；拾物「暂为保管」隐式信誉 +1（同事务）。
- **v4 keep_status 强制**：`keep_status=0`（暂为保管）必须开启联系（`contact_allowed=1`），收到 0 抛 ParamError。
- **2026-08-05 flow-v2（R2）/ flow-v3 修订**：
  - keep_status=1（留在原地未挪动）拾物**单向进入匹配池**（flow-v3 修订 flow-v2 的双向退出）：
    - 正向（失物 → 拾物，`_recall_lost_candidates`）：**参与召回**，keep1 拾物可成为失主侧候选对象；
    - 反向（拾物 → 失物，`_reverse_match_found`）：**不生成候选**，keep1 发布者不参与下一步。
    责任模型：keep1 拾得者只负责"看见 → 拍照 → 发出来帮忙"，物品不在他手上，
    东西被谁领走与他无关，因此不为他生成任何需要他处理的候选。
  - keep1「申请即完成」`complete_keep1_claim`：候选一步到位终态 status=2 + flow_type=1 + completed_at，
    lost/found 双端置已解决 + 审计 `keep1_claim_complete`。
  - keep1「撤回」`revoke_keep1_claim`：status→6 REVOKED（终态）、lost.status 回退 0/1、found.status 回退 0、
    双方 expires_at 顺延 + 审计 `keep1_claim_revoke`；`_exists_match` 排除终态 {2,3,6} 使撤回后可再次申请。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import CategoryError, MatchProcessedError, NotFoundError, ParamError
from app.models.category import Category
from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord
from app.models.user import TrustScoreLog
from app.schemas.common import (
    FoundItemStatus,
    KeepStatus,
    LostItemStatus,
    MatchStatus,
)
from app.schemas.item import FoundItemPublishDTO, LostItemPublishDTO
from app.services import audit_service
from app.services.match_service import MatchService
from app.services.perceptual_hash import PerceptualHash
from app.services.tagging_service import NOUN_SET, TaggingService
from app.services.vision_service import get_vision_service
from app.utils import storage as storage_util


def _now() -> datetime:
    """朴素 UTC 当前时间（与 SQLite 存储一致，避免 naive/aware 比较报错）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cut_with_suspects(scored: list, base_n: int) -> list:
    """v10 变更 B 统一切片助手：**保底 base_n 条 + 其后所有疑似**。

    `scored` 必须**已按 `(-score, id)` 降序排好**。由于已降序，「前 base_n 条之后仍
    ≥ MATCH_THRESHOLD 的元素」必然紧邻其后连续排列，因此只需从 `base_n` 起向后扫到
    第一个 < 阈值的位置即可，等价于 `scored[: max(base_n, 疑似条数)]`，单切片无需两次遍历。

    Args:
        scored: `[(score, obj), ...]`，已降序。
        base_n: 普通候选保底条数（通常为 `settings.MATCH_TOP_N`，可为 0）。

    Returns:
        切片后的列表。上限 `min(n, max(MATCH_TOP_N, MATCH_SUSPECT_MAX))` 防候选爆炸；
        `cap` 用 `max(...)` 兜底，避免有人把 `MATCH_SUSPECT_MAX` 配成 <10 反而砍掉保底条数。
    """
    n = max(0, int(base_n))
    while n < len(scored) and scored[n][0] >= settings.MATCH_THRESHOLD:
        n += 1
    cap = max(settings.MATCH_TOP_N, settings.MATCH_SUSPECT_MAX)
    return scored[: min(n, cap)]


class PublishService:
    """发布编排。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._matcher = MatchService()

    # ---------------- 视觉结果 → 内部 category_id ----------------
    def _category_from_vision(self, vision_result: dict) -> int:
        """由视觉结果解析内部 category_id（仅用于匹配候选检索）。

        视觉不可用（降级）时优先返回「其他」类（v8：兜底回退目标），保证发布可继续。
        """
        cat = self.db.get(Category, vision_result["category_id"])
        if not cat or not cat.is_active:
            # v8：降级兜底优先指向「其他」类（按名称解析，避免硬编码 id 耦合）
            other = (
                self.db.query(Category)
                .filter(Category.is_active == 1, Category.name == settings.OTHER_CATEGORY_NAME)
                .first()
            )
            if other is not None:
                return int(other.id)
            fallback = self.db.query(Category).filter(Category.is_active == 1).first()
            if not fallback:
                raise CategoryError("无可用分类，请先 seed")
            return int(fallback.id)
        return int(vision_result["category_id"])

    # ---------------- v4 类目解析（名词优先） ----------------
    def _resolve_category_id(
        self, category_name: Optional[str], vision_result: dict, noun_tags: list[str]
    ) -> int:
        """解析内部 category_id（v4：名词优先于视觉降级）。

        优先级：
        1) ``category_name`` 精确命中活跃分类（用户填写的规范名词）。
        2) 提取名词 tag 命中种子类目名（如 "钥匙" → 类目「钥匙」）。
        3) 回退视觉结果（保持 v3 降级），避免无图/无名词时断发布。
        """
        name = (category_name or "").strip()
        if name:
            cat = (
                self.db.query(Category)
                .filter(Category.is_active == 1, Category.name == name)
                .first()
            )
            if cat:
                return int(cat.id)
        for noun in noun_tags:
            if not noun:
                continue
            cat = (
                self.db.query(Category)
                .filter(Category.is_active == 1, Category.name == noun)
                .first()
            )
            if cat:
                return int(cat.id)
        return self._category_from_vision(vision_result)

    @staticmethod
    def _vision_label(vision_result: dict) -> Optional[str]:
        """仅当视觉为**真实识别**（confidence>0）时返回 label；降级占位不返回。

        避免 fallback label（如 "书包" + confidence=0.0）污染 tags，导致纯文字
        失物 containment 分母虚增、匹配漏检（见 AC2 设计说明）。
        """
        if vision_result.get("confidence", 0) and vision_result.get("label"):
            return vision_result["label"]
        return None

    # ---------------- 失物发布 ----------------
    def publish_lost(
        self,
        publisher,
        dto: LostItemPublishDTO,
        ip: Optional[str] = None,
        ua: Optional[str] = None,
    ) -> tuple[LostItem, list[MatchRecord]]:
        if not dto.category_name or not dto.category_name.strip():
            raise ParamError("category_name 必填（纯自由文本分类）")
        image_urls = storage_util.save_images(dto.images)
        first_bytes = dto.images[0][1] if dto.images else b""
        vision_result = get_vision_service().predict(first_bytes)
        # v4：真实识别 label 才注入；名词优先于视觉 label
        tags = TaggingService.extract(
            title=dto.title,
            description=dto.description,
            vision_label=self._vision_label(vision_result),
            category_name=dto.category_name.strip(),
        )
        category_id = self._resolve_category_id(dto.category_name.strip(), vision_result, tags)
        # v8：若解析到「其他」类，category_name 同步归一化为「其他」，
        # 保证 score 的「其他」路径（按 category_name 判定）与召回（按 category_id 相等）一致。
        resolved_cat = self.db.get(Category, category_id) if category_id is not None else None
        category_name = (
            settings.OTHER_CATEGORY_NAME
            if (resolved_cat is not None and resolved_cat.name == settings.OTHER_CATEGORY_NAME)
            else dto.category_name.strip()
        )
        image_hash = PerceptualHash.compute(first_bytes) or None

        lost = LostItem(
            publisher_id=publisher.id,
            category_id=category_id,
            category_name=category_name,
            title=dto.title,
            description=dto.description,
            images=image_urls,
            color=dto.color,
            tags=tags,
            image_hash=image_hash,
            appearance=dto.appearance,
            features=dto.features,
            location=dto.location,
            lost_time=dto.lost_time,
            status=int(LostItemStatus.PENDING_MATCH),
        )
        self.db.add(lost)
        self.db.flush()

        audit_service.write_audit(
            self.db,
            user_id=publisher.id,
            action="publish_lost",
            target_type="lost",
            target_id=lost.id,
            ip=ip,
            ua=ua,
            detail=f"title={dto.title};category_id={category_id};category_name={dto.category_name.strip()};tags={tags}",
        )

        matches = self._reverse_match_lost(lost)
        self.db.commit()
        self.db.refresh(lost)
        return lost, matches

    # ---------------- 拾物发布 ----------------
    def publish_found(
        self,
        finder,
        dto: FoundItemPublishDTO,
        ip: Optional[str] = None,
        ua: Optional[str] = None,
    ) -> tuple[FoundItem, list[MatchRecord]]:
        if not dto.images:
            raise ValueError("拾物需至少上传 1 张照片")
        if not dto.category_name or not dto.category_name.strip():
            raise ParamError("category_name 必填（纯自由文本分类）")

        # v4：暂为保管（keep_status=0）必须开启联系；收到 0 拒绝发布
        if dto.keep_status == 0 and dto.contact_allowed == 0:
            raise ParamError("暂为保管的物品必须开启联系（contact_allowed=1）")

        image_urls = storage_util.save_images(dto.images)
        first_bytes = dto.images[0][1] if dto.images else b""
        vision_result = get_vision_service().predict(first_bytes)
        # v4：真实识别 label 才注入；名词优先于视觉 label
        tags = TaggingService.extract(
            title=None,
            description=dto.description,
            vision_label=self._vision_label(vision_result),
            category_name=dto.category_name.strip(),
        )
        category_id = self._resolve_category_id(dto.category_name.strip(), vision_result, tags)
        # v8：若解析到「其他」类，category_name 同步归一化为「其他」（同 publish_lost 说明）。
        resolved_cat = self.db.get(Category, category_id) if category_id is not None else None
        category_name = (
            settings.OTHER_CATEGORY_NAME
            if (resolved_cat is not None and resolved_cat.name == settings.OTHER_CATEGORY_NAME)
            else dto.category_name.strip()
        )
        image_hash = PerceptualHash.compute(first_bytes) or None

        # 暂为保管（keep_status=0）强制 contact_allowed=1（后端二次兜底，不信任前端）
        contact_allowed = 1 if dto.keep_status == 0 else dto.contact_allowed

        found = FoundItem(
            finder_id=finder.id,
            category_id=category_id,
            category_name=category_name,
            description=dto.description,
            images=image_urls,
            tags=tags,
            image_hash=image_hash,
            appearance=dto.appearance,
            features=dto.features,
            location=dto.location,
            found_time=dto.found_time,
            keep_status=dto.keep_status,
            contact_allowed=contact_allowed,
            status=int(FoundItemStatus.PENDING),
        )
        self.db.add(found)
        self.db.flush()

        # 暂为保管（keep_status=0）隐式信誉 +1（同事务）
        if dto.keep_status == 0:
            finder.credit_score = int(finder.credit_score) + 1
            self.db.add(
                TrustScoreLog(
                    user_id=finder.id,
                    delta=1,
                    reason="keep_found",
                    ref_type="found_item",
                    ref_id=found.id,
                )
            )

        audit_service.write_audit(
            self.db,
            user_id=finder.id,
            action="publish_found",
            target_type="found",
            target_id=found.id,
            ip=ip,
            ua=ua,
            detail=f"keep_status={dto.keep_status};category_id={category_id};category_name={dto.category_name.strip()};tags={tags}",
        )

        matches = self._reverse_match_found(found)
        self.db.commit()
        self.db.refresh(found)
        return found, matches

    # ---------------- 候选召回（v4 名词召回） ----------------
    def _recall_lost_candidates(self, lost: LostItem) -> list[FoundItem]:
        """召回「同类目 ∪ 共享物品名词 tag」的待认领拾物（Python 侧过滤，规避 JSON 查询可移植性）。

        flow-v3（修订 flow-v2 R2-a）：**不再按 keep_status 过滤** —— keep1（留在原地未挪动）
        拾物单向进入匹配池，可作为失主侧候选对象出现（"原地就有一件很像的东西"）。
        单向性由反向侧保证：`_reverse_match_found` 仍对 keep1 早退，不为拾得者生成候选。

        本方法被 `_reverse_match_lost`（发布失物）与 `refresh_lost_candidates`（刷新候选）
        共同复用，故存量 keep1 拾物由失主点一次「刷新候选」即可自助补入，无需回填脚本。
        """
        noun_tags = {t for t in (lost.tags or []) if t in NOUN_SET}
        candidates = (
            self.db.query(FoundItem)
            .filter(FoundItem.status == int(FoundItemStatus.PENDING))
            .filter(FoundItem.deleted_at.is_(None))  # v7：软删物品退出候选池（Q8）
            .all()
        )

        def _recalled(f: FoundItem) -> bool:
            if f.category_id == lost.category_id:
                return True
            if not noun_tags:
                return False
            return bool(noun_tags & set(f.tags or []))

        return [f for f in candidates if _recalled(f)]

    def _recall_found_candidates(self, found: FoundItem) -> list[LostItem]:
        """召回「同类目 ∪ 共享物品名词 tag」的待匹配/匹配中失物（对称）。"""
        noun_tags = {t for t in (found.tags or []) if t in NOUN_SET}
        candidates = (
            self.db.query(LostItem)
            .filter(
                LostItem.status.in_(
                    [int(LostItemStatus.PENDING_MATCH), int(LostItemStatus.MATCHING)]
                )
            )
            .filter(LostItem.deleted_at.is_(None))  # v7：软删物品退出候选池（Q8）
            .all()
        )

        def _recalled(l: LostItem) -> bool:
            if l.category_id == found.category_id:
                return True
            if not noun_tags:
                return False
            return bool(noun_tags & set(l.tags or []))

        return [l for l in candidates if _recalled(l)]

    # ---------------- 反向主动匹配 ----------------
    def _reverse_match_lost(self, lost: LostItem) -> list[MatchRecord]:
        """失物发布：对全部召回候选打分，按 (-score, found_id) 降序落 status=0 待认领。

        v10 变更 B：输出不再是硬截断前 MATCH_TOP_N 条，而是
        **「保底前 MATCH_TOP_N 条 + 其后所有 ≥ MATCH_THRESHOLD 的疑似」**（见
        `_cut_with_suspects`）。`MATCH_TOP_N` 语义由「候选上限」改为「普通候选保底条数」。
        生成任意候选时 lost.status → MATCHING。
        """
        candidates = self._recall_lost_candidates(lost)
        scored: list[tuple[float, FoundItem]] = []
        for f in candidates:
            if self._exists_match(lost.id, f.id):   # 幂等去重（任意状态）
                continue
            scored.append((self._matcher.score(lost, f), f))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))   # 分数降序，同分按 id 升序（确定性）
        created: list[MatchRecord] = []
        for score, f in _cut_with_suspects(scored, settings.MATCH_TOP_N):
            m = MatchRecord(
                lost_id=lost.id,
                found_id=f.id,
                match_score=score,
                status=int(MatchStatus.PENDING_CLAIM),
            )
            self.db.add(m)
            self.db.flush()
            created.append(m)
        if created:                                  # 候选 0 条时不置 MATCHING
            lost.status = int(LostItemStatus.MATCHING)
        return created

    def _reverse_match_found(self, found: FoundItem) -> list[MatchRecord]:
        """拾物发布：对称地对『待匹配/匹配中』失物打分并落库；
        每条生成的候选将其 lost.status → MATCHING（Q5 对称）。

        flow-v3（单向性核心，**保留** flow-v2 的早退）：keep_status=1（留在原地未挪动）拾物
        开头早退 —— 不反向匹配失物。正向召回（`_recall_lost_candidates`）已放开 keep1，
        此处若一并放开即变成双向，会为"不负责任"的 keep1 拾得者制造无效打扰与误操作面。

        v10 变更 B（B-2/B-3）：
        - 单件失物已有候选数 ≥ MATCH_TOP_N 时**不再无条件跳过**：必须**先打分**，
          只有本对 `< MATCH_THRESHOLD`（非疑似）才跳过，维持「不打扰」；
          `≥ MATCH_THRESHOLD` 的疑似允许追加为第 11 条及以后（AC-B4）。
          ⚠️ 语句顺序不可退回「先 count 后 score」——那样疑似永远拿不到分数。
        - 本拾物最多喂给几件失物同样放开疑似，与正向路径口径对称。
        """
        if int(found.keep_status) == int(KeepStatus.NOT_KEEPING):
            return []  # flow-v3：keep1 单向 —— 拾物侧不反向生成候选失物
        candidates = self._recall_found_candidates(found)
        scored: list[tuple[float, LostItem]] = []
        for l in candidates:
            if self._exists_match(l.id, found.id):
                continue
            s = self._matcher.score(l, found)       # B-2：必须先打分
            existing = (
                self.db.query(MatchRecord).filter(MatchRecord.lost_id == l.id).count()
            )
            if existing >= settings.MATCH_TOP_N and s < settings.MATCH_THRESHOLD:
                continue                            # 已满且非疑似 → 不打扰（G-4）
            scored.append((s, l))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        created: list[MatchRecord] = []
        for score, l in _cut_with_suspects(scored, settings.MATCH_TOP_N):
            m = MatchRecord(
                lost_id=l.id,
                found_id=found.id,
                match_score=score,
                status=int(MatchStatus.PENDING_CLAIM),
            )
            self.db.add(m)
            self.db.flush()
            created.append(m)
            l.status = int(LostItemStatus.MATCHING)
        return created

    def refresh_lost_candidates(self, lost: LostItem) -> list[MatchRecord]:
        """P2-1：对单条失物重跑召回+打分，增量补充新发布拾物。

        去重（_exists_match）、不挤占旧候选。

        v10 变更 B（B-4/B-5）：**删除「已满即返回空」的早退**。改为算出普通候选剩余配额
        `quota = max(0, MATCH_TOP_N - existing)` 后照常打分：
        - `existing < MATCH_TOP_N` → 补齐到保底 10 条，并额外追加所有疑似；
        - `existing >= MATCH_TOP_N` → `quota=0`，只补 ≥ MATCH_THRESHOLD 的疑似（AC-B6）。
        `quota` 必须显式夹 0 下限：原写法 `MATCH_TOP_N - existing` 为负时 Python 切片会
        静默返回空，改造后负数会让 `_cut_with_suspects` 的起点越界。
        """
        existing = (
            self.db.query(MatchRecord).filter(MatchRecord.lost_id == lost.id).count()
        )
        quota = max(0, settings.MATCH_TOP_N - existing)
        candidates = self._recall_lost_candidates(lost)
        scored: list[tuple[float, FoundItem]] = []
        for f in candidates:
            if self._exists_match(lost.id, f.id):
                continue
            scored.append((self._matcher.score(lost, f), f))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        created: list[MatchRecord] = []
        for score, f in _cut_with_suspects(scored, quota):
            m = MatchRecord(
                lost_id=lost.id,
                found_id=f.id,
                match_score=score,
                status=int(MatchStatus.PENDING_CLAIM),
            )
            self.db.add(m)
            self.db.flush()
            created.append(m)
        if created:
            lost.status = int(LostItemStatus.MATCHING)
        return created

    def _exists_match(self, lost_id: int, found_id: int) -> bool:
        """幂等去重：该 (lost_id, found_id) 是否存在「阻断性」匹配。

        P1-2：排除终态 {2 已完成, 3 已拒绝, 6 已撤回} —— 撤回后可再次生成/申请；
        {0,1,4,5} 仍阻断（进行中/待自取/已放弃保持幂等现状）。
        """
        return (
            self.db.query(MatchRecord)
            .filter(
                MatchRecord.lost_id == lost_id,
                MatchRecord.found_id == found_id,
                ~MatchRecord.status.in_(
                    [
                        int(MatchStatus.COMPLETED),
                        int(MatchStatus.REJECTED),
                        int(MatchStatus.REVOKED),
                    ]
                ),
            )
            .first()
            is not None
        )

    # ---------------- flow-v2：keep1 单边完成 / 撤回（R2） ----------------
    def _lost_has_active_match(self, lost_id: int, exclude_match_id: Optional[int] = None) -> bool:
        """该失物下是否存在其他「进行中」匹配（status∈{0,1,4}，可排除自身）。

        用于撤回时失物状态回退判定：有其他进行中匹配 → MATCHING(1)，否则 PENDING_MATCH(0)。
        """
        q = self.db.query(MatchRecord).filter(
            MatchRecord.lost_id == lost_id,
            MatchRecord.status.in_(
                [
                    int(MatchStatus.PENDING_CLAIM),
                    int(MatchStatus.CLAIMING),
                    int(MatchStatus.MANUAL_PENDING),
                ]
            ),
        )
        if exclude_match_id is not None:
            q = q.filter(MatchRecord.id != exclude_match_id)
        return q.first() is not None

    def _apply_keep1_completion(self, match: MatchRecord, lost: LostItem, found: FoundItem, ip, ua) -> MatchRecord:
        """共享私有方法：把一条 keep1 匹配记录置为终态已完成。

        status→2 COMPLETED、flow_type=1、completed_at=now；lost.status=RESOLVED(3)、
        found.status=RESOLVED(1)；双方 expires_at 顺延 90 天；审计 `keep1_claim_complete`。
        """
        now = _now()
        match.status = int(MatchStatus.COMPLETED)
        match.flow_type = 1
        match.completed_at = now
        lost.status = int(LostItemStatus.RESOLVED)
        found.status = int(FoundItemStatus.RESOLVED)
        lost.expires_at = now + timedelta(days=90)
        found.expires_at = now + timedelta(days=90)
        audit_service.write_audit(
            self.db,
            user_id=lost.publisher_id,
            action="keep1_claim_complete",
            target_type="match",
            target_id=match.id,
            ip=ip,
            ua=ua,
            detail=(
                f"lost_id={match.lost_id};found_id={match.found_id};"
                f"score={match.match_score};flow=keep1"
            ),
        )
        return match

    def complete_keep1_claim(self, match: MatchRecord, ip: Optional[str] = None, ua: Optional[str] = None) -> MatchRecord:
        """keep1「申请即完成」（P0-3）：对 status=0 候选一步到位生成终态已完成记录。

        校验：found.keep_status==1；match.status==PENDING_CLAIM(0)；found.status==PENDING(0)。
        不填理由、不生成交接码、不要求拾得者确认。
        """
        lost = self.db.get(LostItem, match.lost_id)
        found = self.db.get(FoundItem, match.found_id)
        if lost is None or found is None:
            raise NotFoundError("匹配关联物品不存在")
        if int(found.keep_status) != int(KeepStatus.NOT_KEEPING):
            raise ParamError("该拾物非「留在原地未挪动」，请走标准认领流程")
        if int(match.status) != int(MatchStatus.PENDING_CLAIM):
            raise MatchProcessedError("仅待认领候选可申请即完成")
        if int(found.status) != int(FoundItemStatus.PENDING):
            raise MatchProcessedError("该拾物已处理，不可申请")
        return self._apply_keep1_completion(match, lost, found, ip, ua)

    def revoke_keep1_claim(self, match: MatchRecord, ip: Optional[str] = None, ua: Optional[str] = None) -> MatchRecord:
        """keep1「撤回」（P0-4/Q3/Q7）：仅 flow_type==1 且 status==COMPLETED(2)，不限时限。

        效果：match.status→6 REVOKED（终态，completed_at 保留原值）；lost.status 回退
        （有其他进行中匹配→MATCHING(1)，否则→PENDING_MATCH(0)）；found.status→PENDING(0)；
        双方 expires_at 顺延 90 天恢复可检索；审计 `keep1_claim_revoke`（created_at 即撤回时间）。
        """
        lost = self.db.get(LostItem, match.lost_id)
        found = self.db.get(FoundItem, match.found_id)
        if lost is None or found is None:
            raise NotFoundError("匹配关联物品不存在")
        if int(getattr(match, "flow_type", 0) or 0) != 1:
            raise MatchProcessedError("仅 keep1 申请即完成的记录可撤回")
        if int(match.status) != int(MatchStatus.COMPLETED):
            raise MatchProcessedError("仅已完成记录可撤回")
        now = _now()
        match.status = int(MatchStatus.REVOKED)
        # completed_at 保留原值（撤回时间以审计 created_at 为准）
        lost.status = (
            int(LostItemStatus.MATCHING)
            if self._lost_has_active_match(lost.id, exclude_match_id=match.id)
            else int(LostItemStatus.PENDING_MATCH)
        )
        found.status = int(FoundItemStatus.PENDING)
        lost.expires_at = now + timedelta(days=90)
        found.expires_at = now + timedelta(days=90)
        audit_service.write_audit(
            self.db,
            user_id=lost.publisher_id,
            action="keep1_claim_revoke",
            target_type="match",
            target_id=match.id,
            ip=ip,
            ua=ua,
            detail=(
                f"lost_id={match.lost_id};found_id={match.found_id};"
                f"match_id={match.id};reason=误操作撤回"
            ),
        )
        return match
