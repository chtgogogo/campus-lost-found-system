"""视觉服务白名单提取回归测试（不加载真实权重）。

覆盖已确诊 bug：当模型检出的框里**最高置信度是不在白名单的类**
（如 person, cls=0）但同时存在一个白名单类（如书包, cls=24，
conf≥阈值）时，`predict()` 必须返回该白名单类的 category_id 且
confidence > 0，而不能因为全局最高 conf 框不在白名单就直接降级。

通过 monkeypatch 向 sys.modules 注入假 ultralytics + torch，并让
`VisionService._coco_model.predict` 返回确定性多框预测，无需真权重。
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
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, ".."))
from conftest import PNG  # noqa: E402


# ---------------- 假推理栈（不依赖 numpy / torch） ----------------
class _FakeTensor:
    """模拟 ultralytics 返回的 torch.Tensor：支持 .cpu().numpy().astype(int)."""

    def __init__(self, arr):
        self._arr = list(arr)

    def cpu(self):
        return self

    def numpy(self):
        return self

    def astype(self, t):
        return [t(x) for x in self._arr]

    def __getitem__(self, i):
        return self._arr[i]


class _FakeBoxes:
    def __init__(self, confs, clses, n=None):
        self.conf = _FakeTensor(confs)
        self.cls = _FakeTensor(clses)
        self._n = n if n is not None else len(clses)

    def __len__(self):
        # 模拟"该帧有 N 个检测框"
        return self._n


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class FakeYOLO:
    """假模型：COCO 与 YOLO-World 共用，靠是否调用 set_classes 区分分支。"""

    last_set_classes = None

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
_COCO_BOXES = _FakeBoxes([0.0], [0])
_WORLD_BOXES = _FakeBoxes([0.0], [0])


@pytest.fixture
def whitelist_branch(monkeypatch):
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


def test_predict_returns_whitelisted_class_when_top_box_is_not_whitelisted(
    db, whitelist_branch
):
    """回归：最高置信度框非白名单（COCO 类 person,80），但有白名单目标（书包,best.pt 索引）。

    新逻辑遍历每个框，返回白名单内最高 conf 的目标，而非因全局最高 conf 框
    不在白名单（0-10）就整体降级。注意：best.pt 索引 0-10 才是白名单，80 落在
    白名单之外。
    """
    bag = (
        db.query(Category)
        .filter(Category.name == "书包", Category.is_active == 1)
        .one()
    )
    bag_yid = bag.yolo_class_id  # 新 seed 下为 best.pt 索引 3
    non_whitelist_cls = 80  # COCO person，落在 0-10 白名单之外
    # 两框：cls=80(person) conf=0.9（非白名单）、cls=书包 conf=0.6（≥阈值 0.25）
    _COCO_BOXES.conf = _FakeTensor([0.9, 0.6])
    _COCO_BOXES.cls = _FakeTensor([non_whitelist_cls, bag_yid])
    # YOLO-World 分支保持噪声（新 seed 全 mode=0，world 分支本就不加载）
    _WORLD_BOXES.conf = _FakeTensor([0.0])
    _WORLD_BOXES.cls = _FakeTensor([0])

    res = whitelist_branch.predict(PNG)

    assert res["category_id"] == bag.id
    assert res["label"] == "书包"
    assert res["confidence"] > 0
    assert res["confidence"] == pytest.approx(0.6)


def test_predict_returns_highest_conf_whitelisted_when_mixed(db, whitelist_branch):
    """回归：混合框中，返回白名单内置信度最高的目标（忽略非白名单的高 conf 框）。

    新设计下全部 category 为 mode=0，不再有 YOLO-World 零样本分支；白名单即
    best.pt 索引 0-10。框：person(80,0.9 非白名单)、书包(0.6)、钥匙(0.7) →
    应返回钥匙(0.7)。
    """
    key = (
        db.query(Category)
        .filter(Category.name == "钥匙", Category.is_active == 1)
        .one()
    )
    # person=80 非白名单；书包=best.pt 索引 3；钥匙=best.pt 索引 2
    _COCO_BOXES.conf = _FakeTensor([0.9, 0.6, 0.7])
    _COCO_BOXES.cls = _FakeTensor([80, 3, key.yolo_class_id])
    _WORLD_BOXES.conf = _FakeTensor([0.0])
    _WORLD_BOXES.cls = _FakeTensor([0])

    res = whitelist_branch.predict(PNG)

    assert res["category_id"] == key.id
    assert res["label"] == "钥匙"
    assert res["confidence"] > 0
    assert res["confidence"] == pytest.approx(0.7)
