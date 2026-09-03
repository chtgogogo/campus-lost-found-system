"""CLIP 两阶段精排后台任务（2026-08-27 激活，③）。

激活「已定义未调用」的 CLIP：发布生成候选后，由 items 路由通过 FastAPI
BackgroundTasks 挂载本任务，对本次创建的候选（top-N）逐对计算图片相似度，
写入 ``MatchRecord.clip_sim``。

定位（不改变打分语义）：
- ``match_score`` 仍是七维打分归一化后的总分（阈值 80 语义不变）；
- ``clip_sim`` 仅作为列表「同分打破平局」的**次排序键**（列表 ORDER BY score DESC,
  clip_sim DESC, id ASC）——同分时照片真像的排前面。
- 发布请求不卡：YOLO 识别仍同步、精排走后台，用户提交后立即可离开页面。

兼容性铁律（沿用 clip_service）：
- CLIP 任何失败（包缺失/权重缺失/图片缺失/OOM）→ ``clip_sim`` 保持 NULL，静默，
  排序退化为「score DESC, id ASC」，与激活前行为完全一致，零风险。
- 本模块自身永不抛异常（最外层 try/except 兜底）。
"""
from __future__ import annotations

import logging
import os

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord
from app.services.clip_service import image_similarity as clip_image_similarity

logger = logging.getLogger("clip_reorder")


def _read_first_image_bytes(image_urls) -> bytes | None:
    """按 /uploads/xxx 相对 URL 读首图字节；任何异常 → None（CLIP 侧会回退）。"""
    if not image_urls:
        return None
    name = str(image_urls[0]).rsplit("/", 1)[-1]
    if not name:
        return None
    path = os.path.join(settings.UPLOAD_DIR, name)
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def reorder_match_ids(match_ids) -> None:
    """对给定匹配记录逐对算 CLIP 图相似度并写回 clip_sim（后台任务入口）。

    Args:
        match_ids: 本次发布创建的 MatchRecord id 列表（≤ MATCH_SUSPECT_MAX）。

    幂等：clip_sim 已非 NULL 的记录跳过；CLIP 不可用/图片缺失 → 保持 NULL。
    失败只记日志，绝不影响发布主流程。
    """
    if not match_ids:
        return
    try:
        db = SessionLocal()
        try:
            for mid in match_ids:
                try:
                    m = db.get(MatchRecord, mid)
                    if m is None or m.clip_sim is not None:
                        continue
                    lost = db.get(LostItem, m.lost_id)
                    found = db.get(FoundItem, m.found_id)
                    if lost is None or found is None:
                        continue
                    bytes_a = _read_first_image_bytes(lost.images)
                    bytes_b = _read_first_image_bytes(found.images)
                    if not bytes_a or not bytes_b:
                        continue
                    sim = clip_image_similarity(bytes_a, bytes_b)
                    if sim is not None:
                        m.clip_sim = round(float(sim), 4)
                        db.commit()
                except Exception:  # 单条失败不影响其它候选
                    continue
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover - 防御性兜底
        logger.warning("[clip_reorder] 后台精排整体失败（静默）: %s", exc)
