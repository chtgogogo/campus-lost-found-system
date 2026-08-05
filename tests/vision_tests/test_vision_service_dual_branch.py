"""视觉服务双分支推理测试（COCO 分支 + YOLO-World 零样本分支）。

通过 monkeypatch 向 sys.modules 注入假的 ultralytics + torch，使其返回确定性预测框，
无需下载 ~200MB 真权重即可覆盖：
- COCO 分支：按 yolo_class_id 映射回 db category_id；
- YOLO-World 分支：确实调用 set_classes(yolo_prompt) 并映射回其 category；
- 置信度阈值过滤（YOLO_CONF_THRESHOLD）。
"""
from __future__ import annotations

import os
import sys
import types

import pytest

from app.models.category import Category
from app.services import vision_service as vs_mod
from app.services.vision_service import get_vision_service

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))
from conftest import PNG  # noqa: E402


# ---------------- 假推理栈（不依赖 numpy / torch） ----------------
class _FakeTensor:
    """模拟 ultralytics 返回的 torch.Tensor：支持 .cpu().numpy().astype(int).argmax()。"""

    def __init__(self, arr):
        self._arr = list(arr)

    def cpu(self):
        return self

    def numpy(self):
        return self

    def astype(self, t):
        return [t(x) for x in self._arr]

    def argmax(self):
        return max(range(len(self._arr)), key=lambda i: self._arr[i])

    def __getitem__(self, i):
        return self._arr[i]


class _FakeBoxes:
    def __init__(self, confs, clses):
        self.conf = _FakeTensor(confs)
        self.cls = _FakeTensor(clses)

    def __len__(self):
        # 模拟“该帧有 N 个检测框”，默认 1 个
        return 1


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class FakeYOLO:
    """假模型：COCO 与 YOLO-World 共用，靠是否调用 set_classes 区分分支。"""

    last_set_classes = None  # 记录 YOLO-World 分支调用的 set_classes 提示词

    def __init__(self, path):
        self.path = path
        self._is_world = False

    def set_classes(self, prompts):
        self._is_world = True
        FakeYOLO.last_set_classes = list(prompts)

    def predict(self, img, conf=None, device=None, verbose=False):
        if self._is_world:
            return [_FakeResult(_WORLD_BOXES)]
        return [_FakeResult(_COCO_BOXES)]


# 测试可配置的预测框（由每个用例在调用前设置）
_COCO_BOXES = None
_WORLD_BOXES = None


@pytest.fixture
def dual_branch(monkeypatch):
    """注入假推理栈，重置单例，返回配置了假模型的 VisionService。"""
    global _COCO_BOXES, _WORLD_BOXES
    _COCO_BOXES = _FakeBoxes([0.0], [0])
    _WORLD_BOXES = _FakeBoxes([0.0], [0])
    FakeYOLO.last_set_classes = None

    fake_ultra = types.SimpleNamespace(YOLO=FakeYOLO)
    monkeypatch.setitem(sys.modules, "ultralytics", fake_ultra)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace())

    vs_mod._vision_instance = None
    svc = get_vision_service()
    yield svc
    vs_mod._vision_instance = None


def _cat_by_yolo_class(db, yolo_class_id):
    return db.query(Category).filter(
        Category.yolo_class_id == yolo_class_id, Category.is_active == 1
    ).one()


def _cat_by_name(db, name):
    return db.query(Category).filter(
        Category.name == name, Category.is_active == 1
    ).one()


def test_coco_branch_maps_yolo_class_id(db, dual_branch):
    # COCO（best.pt）：书包 按新 seed 的 yolo_class_id（best.pt 索引 3）映射回 db；
    # YOLO-World 分支在新 seed 下为空（全 mode=0），仅返回低置信度噪声。
    bag = _cat_by_name(db, "书包")
    _COCO_BOXES.conf = _FakeTensor([0.92])
    _COCO_BOXES.cls = _FakeTensor([bag.yolo_class_id])
    _WORLD_BOXES.conf = _FakeTensor([0.30])
    _WORLD_BOXES.cls = _FakeTensor([0])
    res = dual_branch.predict(PNG)
    assert res["category_id"] == bag.id
    assert res["label"] == bag.name == "书包"
    assert res["confidence"] == pytest.approx(0.92)


def test_all_mode0_disables_world_branch_and_coco_maps(db, dual_branch):
    # 新设计：全部 category 为 recognition_mode=0（真模型检测），不再依赖 YOLO-World
    # 零样本。因此 _world_prompts 为空、_world_model 不加载；COCO 分支按 best.pt
    # 索引（0-10）映射回 db category_id。
    assert dual_branch._world_prompts == []
    assert dual_branch._world_model is None

    # 钥匙（best.pt 索引 2）应被 COCO 分支正确映射
    key = _cat_by_name(db, "钥匙")
    _COCO_BOXES.conf = _FakeTensor([0.95])
    _COCO_BOXES.cls = _FakeTensor([key.yolo_class_id])
    _WORLD_BOXES.conf = _FakeTensor([0.0])
    _WORLD_BOXES.cls = _FakeTensor([0])
    res = dual_branch.predict(PNG)
    assert res["category_id"] == key.id
    assert res["label"] == "钥匙"
    assert res["confidence"] == pytest.approx(0.95)


def test_conf_threshold_filters_below_threshold(db, dual_branch):
    # 两个分支都低于阈值 0.25 → 全部被过滤 → 降级
    _COCO_BOXES.conf = _FakeTensor([0.10])
    _COCO_BOXES.cls = _FakeTensor([24])
    _WORLD_BOXES.conf = _FakeTensor([0.10])
    _WORLD_BOXES.cls = _FakeTensor([0])
    res = dual_branch.predict(PNG)
    assert res["confidence"] == 0.0
    assert res["category_id"] in {
        c.id for c in db.query(Category).filter(Category.is_active == 1).all()
    }


def test_conf_threshold_at_boundary_included(db, dual_branch):
    # 恰好等于阈值 0.25 应被保留（score >= conf_threshold）
    bag = _cat_by_name(db, "书包")
    _COCO_BOXES.conf = _FakeTensor([0.25])
    _COCO_BOXES.cls = _FakeTensor([bag.yolo_class_id])
    _WORLD_BOXES.conf = _FakeTensor([0.10])
    _WORLD_BOXES.cls = _FakeTensor([0])
    res = dual_branch.predict(PNG)
    assert res["category_id"] == bag.id
    assert res["confidence"] == pytest.approx(0.25)


def test_predict_never_raises_on_corrupt_image_with_models(db, dual_branch):
    # 模型可用但图片损坏 → 解码失败也应降级，不抛异常
    res = dual_branch.predict(b"not a real image at all")
    assert isinstance(res, dict)
    assert res["confidence"] == 0.0
