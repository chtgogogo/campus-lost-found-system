"""进程内视觉识别服务（真推理：YOLOv8n-COCO + YOLO-World 零样本）。

契约保持不变：`predict(image_bytes: bytes) -> dict` 返回
固定三键 `{category_id, label, confidence}`，对上层零侵入。

实现要点：
- 双分支推理（COCO 11 类 + YOLO-World 零样本），合并择优。
- **YOLO-World 激活契约（论文论述项）**：仅当某分类 ``recognition_mode==1`` 且
  ``yolo_prompt`` 非空时，``_build_category_map`` 才会收集该 prompt，``_load_world``
  才会加载 YOLO-World 并对该 prompt 做零样本检测并融合进 ``predict()``。
  当前 seed 全 ``mode=0`` → ``_world_prompts==[]`` → 分支休眠（详见 app/core/seed.py 注释）。
- **torch / ultralytics 仅在本文件内部惰性导入**（在 `__init__` 与方法体内），
  绝不出现在模块顶层。这是硬性红线：保证在无 GPU / 未安装权重 / 未装
  torch 依赖时，56 个回归测试仍可全绿（import 阶段不触发重依赖）。
- 降级铁律：`predict` 永不抛异常；无权重 / 无检测 → 返回**有效活跃分类**
  + `confidence=0.0` + label（来自分类表），`category_id` 永远落在活跃集合内。
"""
from __future__ import annotations

import io
import logging
import os
from typing import Optional

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.category import Category

logger = logging.getLogger("vision")


class VisionService:
    """进程内视觉识别（真 YOLOv8 推理）。"""

    def __init__(
        self,
        device: Optional[str] = None,
        model_dir: Optional[str] = None,
    ) -> None:
        self.device = device or settings.YOLO_DEVICE
        self.model_dir = model_dir or settings.YOLO_MODEL_DIR
        self.conf_threshold = float(settings.YOLO_CONF_THRESHOLD)
        self.fallback_category_id = int(settings.YOLO_FALLBACK_CATEGORY_ID)

        self._coco_model = None
        self._world_model = None
        self._coco_map: dict[int, tuple[int, str]] = {}
        self._world_map: dict[str, tuple[int, str]] = {}
        self._world_prompts: list[str] = []
        self._active: list[tuple[int, str]] = []

        # 构建分类映射（读 DB；DB 未就绪时为空，predict 时惰性重建）
        try:
            self._build_category_map()
        except Exception as exc:  # pragma: no cover - DB 不可用时仅影响映射
            logger.warning("[vision] 分类映射构建失败，将走降级: %s", exc)

        # 预热权重（失败自动降级，不抛异常）
        self._load_models()

    # ---------------- 模型加载（惰性 import） ----------------
    def _load_models(self) -> None:
        """加载 COCO 与 YOLO-World 权重；任意失败均降级为 None，不抛异常。"""
        self._load_coco()
        self._load_world()

    def _resolve_path(self, model_name: str) -> str:
        return os.path.join(self.model_dir, model_name)

    def _load_coco(self) -> None:
        try:
            # 惰性导入：仅在真正加载权重时引入 ultralytics / torch
            from ultralytics import YOLO  # type: ignore

            path = self._resolve_path(settings.YOLO_COCO_MODEL)
            self._coco_model = YOLO(path)
            logger.info("[vision] COCO 模型加载成功: %s", path)
        except Exception as exc:
            self._coco_model = None
            logger.warning("[vision] COCO 模型不可用（降级）: %s", exc)

    def _load_world(self) -> None:
        # 激活点：仅当分类表存在 recognition_mode==1 且带 prompt 的类时 _world_prompts 非空，
        # 才会真正加载 YOLO-World 并对该 prompt 做零样本检测、融合进 predict()。
        if not self._world_prompts:
            return
        try:
            from ultralytics import YOLO  # type: ignore

            path = self._resolve_path(settings.YOLO_WORLD_MODEL)
            self._world_model = YOLO(path)
            # 固化校园专属零样本提示词（顺序即 set_classes 顺序）
            self._world_model.set_classes(self._world_prompts)
            logger.info("[vision] YOLO-World 模型加载成功: %s", path)
        except Exception as exc:
            self._world_model = None
            logger.warning("[vision] YOLO-World 模型不可用（降级）: %s", exc)

    # ---------------- 分类映射（只读 category 表） ----------------
    def _build_category_map(self) -> None:
        os.makedirs(self.model_dir, exist_ok=True)
        with SessionLocal() as db:
            rows = (
                db.query(
                    Category.id,
                    Category.name,
                    Category.yolo_class_id,
                    Category.recognition_mode,
                    Category.yolo_prompt,
                    Category.is_active,
                )
                .all()
            )
        coco_map: dict[int, tuple[int, str]] = {}
        world_map: dict[str, tuple[int, str]] = {}
        world_prompts: list[str] = []
        active: list[tuple[int, str]] = []
        for cid, name, yolo_class_id, mode, prompt, is_active in rows:
            if int(is_active) == 1:
                active.append((int(cid), name))
            if int(mode) == 0 and yolo_class_id is not None:
                coco_map[int(yolo_class_id)] = (int(cid), name)
            elif int(mode) == 1 and prompt:
                world_map[prompt] = (int(cid), name)
                world_prompts.append(prompt)
        self._coco_map = coco_map
        self._world_map = world_map
        self._world_prompts = world_prompts
        self._active = active

    def _ensure_map(self) -> None:
        """predict 调用前确保映射存在（预热时 DB 未就绪的兜底）。

        同时处理「初始化时 DB 尚未就绪、后续分类表出现 mode=1+prompt 类」的场景：
        若检测到待激活的 YOLO-World 提示词而模型尚未加载，则动态补加载。
        """
        if self._active and self._coco_map and self._world_map:
            return
        try:
            self._build_category_map()
        except Exception:  # pragma: no cover
            pass
        # 动态补加载 YOLO-World：仅当 _world_prompts 非空且模型未加载时触发
        if self._world_prompts and self._world_model is None:
            self._load_world()

    # ---------------- 推理 ----------------
    def _decode_image(self, image_bytes: bytes):
        from PIL import Image

        return Image.open(io.BytesIO(image_bytes)).convert("RGB")

    def predict(self, image_bytes: bytes) -> dict:
        """对图片打标，返回 `{category_id, label, confidence}`。

        永不抛异常；无模型 / 无检测 → 降级为有效活跃分类 + confidence=0.0。
        """
        self._ensure_map()

        # 双模型皆不可用：直接降级（避免无谓的图片解码）
        if self._coco_model is None and self._world_model is None:
            return self._fallback()

        if not image_bytes:
            return self._fallback()

        try:
            img = self._decode_image(image_bytes)
        except Exception as exc:
            logger.warning("[vision] 图片解码失败，走降级: %s", exc)
            return self._fallback()

        best: Optional[tuple[int, str, float]] = None
        coco = self._predict_coco(img)
        world = self._predict_world(img)
        for cand in (coco, world):
            if cand is None:
                continue
            if best is None or cand[2] > best[2]:
                best = cand

        if best is None:
            return self._fallback()
        return {
            "category_id": best[0],
            "label": best[1],
            "confidence": round(float(best[2]), 4),
        }

    def _predict_coco(self, img) -> Optional[tuple[int, str, float]]:
        if self._coco_model is None or not self._coco_map:
            return None
        try:
            results = self._coco_model.predict(
                img, conf=self.conf_threshold, device=self.device, verbose=False
            )
            # 遍历每一个框：仅当"类别命中白名单且置信度达标"时才参与
            # "白名单类里取最高置信度"的比较（局部 best 累积）。
            # 不再用全局 best_idx = argmax，避免最高置信度框是非白名单类时
            # 直接降级、白白忽略画面中真实存在的白名单目标。
            best: Optional[tuple[int, str, float]] = None
            for r in results:
                if r.boxes is None or len(r.boxes) == 0:
                    continue
                confs = r.boxes.conf.cpu().numpy()
                cls_ids = r.boxes.cls.cpu().numpy().astype(int)
                for i in range(len(cls_ids)):
                    coco_cls = int(cls_ids[i])
                    score = float(confs[i])
                    mapping = self._coco_map.get(coco_cls)
                    if mapping is not None and score >= self.conf_threshold:
                        if best is None or score > best[2]:
                            best = (mapping[0], mapping[1], score)
            return best
        except Exception as exc:  # pragma: no cover - 推理异常不阻断发布
            logger.warning("[vision] COCO 推理异常，跳过: %s", exc)
            return None

    def _predict_world(self, img) -> Optional[tuple[int, str, float]]:
        if self._world_model is None or not self._world_map:
            return None
        try:
            results = self._world_model.predict(
                img, conf=self.conf_threshold, device=self.device, verbose=False
            )
            # 遍历每一个框：按 world_idx 取 prompt、命中 _world_map 且置信度达标才
            # 参与"白名单类里取最高置信度"的比较（局部 best 累积）。
            best: Optional[tuple[int, str, float]] = None
            for r in results:
                if r.boxes is None or len(r.boxes) == 0:
                    continue
                confs = r.boxes.conf.cpu().numpy()
                cls_ids = r.boxes.cls.cpu().numpy().astype(int)
                for i in range(len(cls_ids)):
                    world_idx = int(cls_ids[i])
                    score = float(confs[i])
                    # 提示词顺序即 set_classes 顺序
                    prompt = (
                        self._world_prompts[world_idx]
                        if 0 <= world_idx < len(self._world_prompts)
                        else None
                    )
                    mapping = self._world_map.get(prompt) if prompt else None
                    if mapping is not None and score >= self.conf_threshold:
                        if best is None or score > best[2]:
                            best = (mapping[0], mapping[1], score)
            return best
        except Exception as exc:  # pragma: no cover
            logger.warning("[vision] YOLO-World 推理异常，跳过: %s", exc)
            return None

    # ---------------- 降级 ----------------
    def _first_active(self) -> Optional[tuple[int, str]]:
        return self._active[0] if self._active else None

    def _fallback(self) -> dict:
        """降级：返回「其他」类 + confidence=0.0（category_id 永远落在活跃集合内）。"""
        cat = next((c for c in self._active if c[1] == "其他"), None) or self._first_active()
        if cat is None:
            # 极端情况：分类表尚未 seed，退回配置值（publish_service 会再次兜底）
            return {
                "category_id": self.fallback_category_id,
                "label": "unknown",
                "confidence": 0.0,
            }
        return {"category_id": cat[0], "label": cat[1], "confidence": 0.0}


# 进程内单例：真实模型仅加载一次（唯一加载点）
_vision_instance: Optional[VisionService] = None


def get_vision_service() -> VisionService:
    """获取（惰性创建）进程内视觉服务单例。"""
    global _vision_instance
    if _vision_instance is None:
        _vision_instance = VisionService()
    return _vision_instance
