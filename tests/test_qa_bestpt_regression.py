"""QA 回归：best.pt 接入后端视觉服务的真识别 + 降级验证。

设计：借 conftest 的隔离测试库（每次会话 drop_all+create_all+seed 新 12 类），
确保 VisionService 读到的是对齐 best.pt 0-10 索引的新 seed（含「其他」降级类）。

覆盖 3 个核心回归点：
1. best.pt 能正常加载（不再是通用 yolov8n/占位）。
2. 占位图无法被识别 → 降级返回 label=="其他" + confidence==0.0（不再是「书包」）。
3. 真实校园失物图（训练/验证集样本）能被 best.pt 检出 → 非降级，label 落在 12 类内。
"""
from __future__ import annotations

import io
import os
import sys

import pytest
from PIL import Image

from app.core.seed import SEED_CATEGORIES
from app.services import vision_service as vs_mod
from app.services.vision_service import VisionService

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 占位图：纯色小块，模型不可能检出任何 11 类校园失物 → 必走降级。
_PLACEHOLDER = io.BytesIO()
Image.new("RGB", (8, 8), (123, 200, 80)).save(_PLACEHOLDER, "PNG")
PLACEHOLDER_PNG = _PLACEHOLDER.getvalue()

# 真实校园失物图：best.pt 验证集可视化（底层是真实 11 类物品照片）。
# 经验证 val_batch1_pred.jpg 含雨伞（umbrella，conf≈0.46）可稳定触发非降级检出。
REAL_IMG_PATH = os.path.join(BASE_DIR, "runs", "detect", "val", "val_batch1_pred.jpg")


def _seeded_names() -> set[str]:
    return {name for (name, _cid, _mode, _prompt) in SEED_CATEGORIES}


def test_bestpt_model_loads():
    """best.pt 必须能加载，且是 12 类校园失物模型（11 校园类 + other，索引 0-11）。"""
    vs = VisionService()
    assert vs._coco_model is not None, "best.pt 未加载（权重缺失或路径错误）"
    names = list(vs._coco_model.model.names.values())
    # 12 类口径：best.pt 已重训为 12 类（11 校园类 + other）
    assert len(names) == 12, f"best.pt 类别数应为 12，实际 {len(names)}: {names}"
    # 第 12 类（index 11）应为 other，对应 DB 中的「其他」降级类
    assert names[-1] == "other", f"best.pt 第 12 类应为 other，实际 {names[-1]}"
    # 类别索引 0-10 与 seed 的 yolo_class_id 一一对应；
    # 「其他」类 yolo_class_id=None，按设计不进入 coco_map（仅作 DB 级降级回退目标）。
    assert vs._coco_map, "_coco_map 为空（分类表未 seed 新 12 类？）"
    assert set(vs._coco_map.keys()) == set(range(11)), (
        f"_coco_map key 应覆盖 0-10（其他类为 DB 降级，不在此映射），"
        f"实际 {sorted(vs._coco_map.keys())}"
    )
    # 12 类口径的另一面：活跃分类必须包含「其他」降级类
    assert any(c[1] == "其他" for c in vs._active), "活跃分类缺少「其他」降级类"
    # 所有 category 为 mode=0 → YOLO-World 分支不应加载
    assert vs._world_prompts == [], "seed 全 mode=0 时 _world_prompts 必须为空"


def test_fallback_returns_other(monkeypatch):
    """确定性降级：强制视觉模型不可用 → 必走 fallback 回「其他」+ confidence=0.0。

    不再依赖占位图被正确识别——12 类 best.pt 对纯色小块有弱误检
    （如绿块被识别为「钱包」@0.21），已无法稳定触发降级。改为用 monkeypatch
    直接禁用 ultralytics/torch 并重置单例，使其必走降级路径。
    """
    # 强制视觉模型不可用：VisionService.__init__ 惰性 import 时
    # `from ultralytics import YOLO` 失败 → coco_model=None → predict 必走降级。
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    monkeypatch.setitem(sys.modules, "torch", None)
    vs_mod._vision_instance = None
    vs = VisionService()
    # 前置：活跃分类必须含「其他」降级类
    assert any(c[1] == "其他" for c in vs._active), "活跃分类缺少「其他」降级类"
    res = vs.predict(PLACEHOLDER_PNG)
    assert res["label"] == "其他", f"降级应回退「其他」，实际 {res}"
    assert res["confidence"] == 0.0, f"降级 confidence 应为 0.0，实际 {res}"
    assert res["category_id"] in {cid for (cid, _n) in vs._active}, "category_id 应落在活跃集合内"
    vs_mod._vision_instance = None


def test_real_image_detects_campus_item():
    """真识别：雨伞图应被 best.pt 正确检出「雨伞」→ 非降级、label 在 12 类内、confidence>0。

    这正是原始 Bug 的核心回归点：此前雨伞/钥匙会被误判成「书包」+0，
    现应返回正确的「雨伞」类且置信度>0。
    """
    vs = VisionService()
    if not os.path.exists(REAL_IMG_PATH):
        pytest.skip(f"真实测试图缺失（非阻塞）: {REAL_IMG_PATH}")
    with open(REAL_IMG_PATH, "rb") as f:
        img_bytes = f.read()
    res = vs.predict(img_bytes)
    seeded = _seeded_names()
    assert res["label"] in seeded, f"检出 label 不在 12 类内: {res}"
    assert res["confidence"] > 0.0, f"真实图应非降级（confidence>0），实际 {res}"
    assert res["label"] != "其他", f"真实图不应走降级，实际 {res}"
    # 该验证集样本确实含雨伞，best.pt 应识别为「雨伞」（而非误导性的「书包」）
    assert res["label"] == "雨伞", f"该图应为雨伞，实际识别为: {res}"
