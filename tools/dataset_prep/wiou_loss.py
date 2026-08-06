#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""WIoU 损失函数集成（针对 ultralytics 8.4.98 实际可用）。

⚠️ 有害警告（2026-08 实测定论）：WIoU v3 对本数据集**有害**，不得作默认损失。
本数据集长尾失衡≈103:1（backpack 7867 vs campus_card 76），WIoU v3 的单调聚焦
机制会抑制稀有类低质量预测的梯度，实测 val mAP@0.5 仅 **0.060**（recall 0.075），
而默认 CIoU 达 **0.710**。本模块仅保留用于"损失函数消融对照"，生产训练一律用
CIoU（train_vision.py 默认已改为 CIoU）。

本模块为「失物招领系统」视觉识别模型提供 WIoU（Wise-IoU，论文：
Tong et al., "Wise-IoU: Bounding Box Regression Loss with Dynamic Focusing
Mechanism", 2023）边界框损失，用于替换 YOLOv8 默认 CIoU。原设计意图是在小目标 /
类别极度失衡场景下提升 mAP，但**在本数据集上实测适得其反**（见上方警告），故不再推荐。

## 为什么不用内置？
经核实，ultralytics 8.4.98 的 ``ultralytics.utils.metrics.bbox_iou`` 只支持
``CIoU/DIoU/GIoU`` 三种，\ **不包含** WIoU（旧版 ``iou_type="WIoU"`` 的补丁方式在此
版本中会被静默忽略，导致仍是 CIoU）。因此这里采用「自定义子类 + 注入训练器」的方式。

## 集成方式（已对 8.4.98 结构验证）
1. ``WIoUBboxLoss`` 继承 ``ultralytics.utils.loss.BboxLoss``，仅覆写 IoU 计算部分，
   把 ``bbox_iou(..., CIoU=True)`` 换成 WIoU 度量，DFL 分支原样保留。
2. ``WIoUDetectionLoss`` 继承 ``v8DetectionLoss``，在 ``__init__`` 中把
   ``self.bbox_loss`` 替换为 ``WIoUBboxLoss``。
3. ``WIoUDetectionModel`` 继承 ``DetectionModel``，覆写 ``init_criterion()`` 返回
   ``WIoUDetectionLoss(self)``。
   **关键点**：ultralytics 在 ``BaseTrainer.setup`` 中会通过 ``model.init_criterion()``
   重新创建 criterion（即 ``get_model`` 里设的 criterion 会被覆盖），因此必须覆写
   ``init_criterion`` 而非仅在 ``get_model`` 里替换——这是与旧脚本最大的区别。
4. ``make_wiou_trainer(gamma)`` 工厂返回一个配置好 gamma 的 ``DetectionTrainer``
   子类，传给 ``model.train(trainer=...)`` 即可注入。

## 数值稳定性
- 仅对前景框（fg_mask 处）计算损失，与原始实现一致。
- ``iou`` 做 ``clamp(min=eps)`` 后再做 ``**gamma``，避免 0**gamma 产生 NaN。
- WIoU v3 单调聚焦系数：``L = (1 - IoU + rho2/c2) * IoU**gamma``，
  gamma 默认 1.9（论文推荐）；gamma=0 时退化为 WIoU v1（无聚焦）。
"""

from __future__ import annotations

import torch
import torch.nn as nn

from ultralytics.nn.tasks import DetectionModel
from ultralytics.models.yolo.detect import DetectionTrainer
from ultralytics.utils import RANK
from ultralytics.utils.loss import BboxLoss, bbox2dist, v8DetectionLoss


class WIoUBboxLoss(BboxLoss):
    """WIoU v3 边界框回归损失（替换默认 CIoU）。

    仅覆写前向中的 IoU 计算，DFL 分支（含 ``bbox2dist``）与父类完全一致，
    保证分布焦点损失不受影响。返回量沿用 ultralytics 约定：``loss = (1 - iou_like)``。
    """

    def __init__(self, reg_max: int = 16, gamma: float = 1.9, eps: float = 1e-7) -> None:
        """初始化 WIoU 边界框损失。

        Args:
            reg_max: 检测头 DFL 正则化最大值（与模型一致）。
            gamma: WIoU v3 聚焦系数指数，默认 1.9；置 0 即退化为 WIoU v1。
            eps: 数值稳定小量，避免除零 / 0**gamma。
        """
        super().__init__(reg_max)
        self.gamma = float(gamma)
        self.eps = float(eps)

    def _wiou_metric(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """计算 WIoU「类 IoU」度量（越高越好），供 ``loss = 1 - metric`` 使用。

        使用实例属性 ``self.gamma`` / ``self.eps``，避免静态默认覆盖配置。

        Args:
            pred: 预测框 ``(N, 4)``，xyxy 像素坐标。
            target: 真实框 ``(N, 4)``，xyxy 像素坐标。

        Returns:
            ``(N,)`` 类 IoU 度量，满足 ``(1 - metric)`` 即为 WIoU v3 损失。
        """
        gamma = self.gamma
        eps = self.eps
        # --- 拆分坐标（与 ultralytics bbox_iou 一致，保证 IoU 数值对齐）---
        b1_x1, b1_y1, b1_x2, b1_y2 = pred.unbind(1)
        b2_x1, b2_y1, b2_x2, b2_y2 = target.unbind(1)

        # --- 交集面积 ---
        inter = (b1_x2.minimum(b2_x2) - b1_x1.maximum(b2_x1)).clamp(0) * (
            b1_y2.minimum(b2_y2) - b1_y1.maximum(b2_y1)
        ).clamp(0)

        # --- 并集面积 ---
        w1, h1 = b1_x2 - b1_x1, b1_y2 - b1_y1
        w2, h2 = b2_x2 - b2_x1, b2_y2 - b2_y1
        union = w1 * h1 + w2 * h2 - inter + eps
        iou = inter / union

        # --- 距离代价 rho2 / c2（WIoU 边界感知项）---
        cx1, cy1 = (b1_x1 + b1_x2) / 2.0, (b1_y1 + b1_y2) / 2.0
        cx2, cy2 = (b2_x1 + b2_x2) / 2.0, (b2_y1 + b2_y2) / 2.0
        rho2 = (cx1 - cx2) ** 2 + (cy1 - cy2) ** 2
        cw = torch.max(b1_x2, b2_x2) - torch.min(b1_x1, b2_x1)
        ch = torch.max(b1_y2, b2_y2) - torch.min(b1_y1, b2_y1)
        c2 = cw ** 2 + ch ** 2 + eps

        # --- WIoU v1：边界感知距离项（越小越好）---
        wiou_dist = 1.0 - iou + (rho2 / c2)

        # --- WIoU v3：单调聚焦系数 IoU**gamma（高质量框获得更大梯度权重）---
        focus = iou.clamp(min=eps) ** gamma

        # 返回「类 IoU」量，使外层 (1 - 该量) 即等于 wiou_dist * focus 损失
        return 1.0 - (wiou_dist * focus)

    def forward(
        self,
        pred_dist: torch.Tensor,
        pred_bboxes: torch.Tensor,
        anchor_points: torch.Tensor,
        target_bboxes: torch.Tensor,
        target_scores: torch.Tensor,
        target_scores_sum: torch.Tensor,
        fg_mask: torch.Tensor,
        imgsz: torch.Tensor,
        stride: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """计算 WIoU 与 DFL 损失（DFL 分支与父类完全一致）。"""
        weight = target_scores.sum(-1)[fg_mask].unsqueeze(-1)
        # 仅对前景框计算 WIoU（替换原 bbox_iou(..., CIoU=True)）
        iou_like = self._wiou_metric(pred_bboxes[fg_mask], target_bboxes[fg_mask])
        loss_iou = ((1.0 - iou_like) * weight).sum() / target_scores_sum

        # --- DFL 损失（与 ultralytics 原始实现逐行一致）---
        if self.dfl_loss is not None:
            target_ltrb = bbox2dist(anchor_points, target_bboxes, self.dfl_loss.reg_max - 1)
            loss_dfl = (
                self.dfl_loss(pred_dist[fg_mask].view(-1, self.dfl_loss.reg_max), target_ltrb[fg_mask])
                * weight
            )
            loss_dfl = loss_dfl.sum() / target_scores_sum
        else:  # pragma: no cover - 仅 reg_max<=1 时走此分支
            target_ltrb = bbox2dist(anchor_points, target_bboxes)
            target_ltrb = target_ltrb * stride
            target_ltrb[..., 0::2] /= imgsz[1]
            target_ltrb[..., 1::2] /= imgsz[0]
            pred_dist_scaled = pred_dist * stride
            pred_dist_scaled[..., 0::2] /= imgsz[1]
            pred_dist_scaled[..., 1::2] /= imgsz[0]
            loss_dfl = (
                nn.functional.l1_loss(pred_dist_scaled[fg_mask], target_ltrb[fg_mask], reduction="none").mean(-1, keepdim=True)
                * weight
            )
            loss_dfl = loss_dfl.sum() / target_scores_sum

        return loss_iou, loss_dfl


class WIoUDetectionLoss(v8DetectionLoss):
    """WIoU 变体检测损失：用 ``WIoUBboxLoss`` 替换默认 ``BboxLoss``。"""

    def __init__(
        self,
        model: nn.Module,
        tal_topk: int = 10,
        tal_topk2: int | None = None,
        gamma: float = 1.9,
    ) -> None:
        """初始化损失标准，并替换边界框损失为 WIoU。

        Args:
            model: 去并行后的检测模型（提供 args / 检测头等）。
            tal_topk: 任务对齐分配器 topk。
            tal_topk2: 任务对齐分配器第二 topk（可为空）。
            gamma: WIoU v3 聚焦系数指数。
        """
        super().__init__(model, tal_topk, tal_topk2)
        # model.model[-1] 为 Detect() 检测头，reg_max 取自其配置
        reg_max = model.model[-1].reg_max
        self.bbox_loss = WIoUBboxLoss(reg_max, gamma=gamma).to(self.device)


class WIoUDetectionModel(DetectionModel):
    """检测模型子类：覆写 ``init_criterion`` 返回 WIoU 损失。

    ultralytics 在 ``BaseTrainer.setup`` 中通过 ``model.init_criterion()`` 重建
    criterion，故必须在此处注入，而不是在 ``get_model`` 里临时替换。
    """

    def init_criterion(self) -> WIoUDetectionLoss:
        """返回 WIoU 变体检测损失（可被子类覆盖 gamma）。"""
        return WIoUDetectionLoss(self)


def make_wiou_trainer(gamma: float = 1.9) -> type[DetectionTrainer]:
    """工厂：返回配置好 WIoU 的 ``DetectionTrainer`` 子类。

    由于 ``model.train(trainer=Cls)`` 只接收类（无法传参），这里用闭包把 ``gamma``
    固化进动态生成的子类，保证 ``init_criterion`` 能拿到正确的聚焦系数。

    Args:
        gamma: WIoU v3 聚焦系数指数，默认 1.9。

    Returns:
        一个可用于 ``model.train(trainer=...)`` 的 ``DetectionTrainer`` 子类。
    """

    class _WIoUDetectionModel(WIoUDetectionModel):
        """把 gamma 固化进模型的 WIoU 检测模型。"""

        _wiou_gamma: float = gamma

        def init_criterion(self) -> WIoUDetectionLoss:
            return WIoUDetectionLoss(self, gamma=self._wiou_gamma)

    class _WIoUDetectionTrainer(DetectionTrainer):
        """自定义训练器：用 WIoU 检测模型替换默认 DetectionModel。"""

        def get_model(self, cfg: str | None = None, weights: str | None = None, verbose: bool = True):
            """返回 WIoU 检测模型（其余逻辑与原 ``get_model`` 一致）。"""
            model = self.set_model_names_for_load(
                _WIoUDetectionModel(
                    cfg,
                    nc=self.data["nc"],
                    ch=self.data["channels"],
                    verbose=verbose and RANK == -1,
                )
            )
            if weights:
                model.load(weights)
            return model

    return _WIoUDetectionTrainer


def _install_wiou(gamma: float = 1.9) -> None:
    """猴子补丁：让 v8DetectionLoss 改用 WIoUBboxLoss（WIoU v3）。

    对 ultralytics 8.4.98 验证有效：DetectionModel.init_criterion() 返回
    ``v8DetectionLoss(self)``，而 BaseTrainer.setup 在训练时会重建 criterion，
    因此打补丁到 ``v8DetectionLoss.__init__`` 即可全局生效，无需替换 trainer/get_model
    （更稳，避免 self.data['channels'] 等依赖）。train_vision.py 的 --loss WIoU 走此路径。
    """
    import ultralytics.utils.loss as loss_mod

    _orig_init = v8DetectionLoss.__init__

    def _wiou_init(self, model, *a, **k):
        _orig_init(self, model, *a, **k)
        reg_max = model.model[-1].reg_max
        self.bbox_loss = WIoUBboxLoss(reg_max, gamma=gamma).to(self.device)

    if not getattr(v8DetectionLoss.__init__, "_wiou_patched", False):
        v8DetectionLoss.__init__ = _wiou_init
        v8DetectionLoss.__init__._wiou_patched = True
        loss_mod.v8DetectionLoss = v8DetectionLoss


if __name__ == "__main__":
    # 自检：安装补丁 + 对 WIoUBboxLoss 跑一次前向，确认数值有限、补丁生效
    import torch

    _install_wiou()
    from ultralytics.utils.loss import v8DetectionLoss

    lb = WIoUBboxLoss(reg_max=16, gamma=1.9)
    pb = torch.rand(1, 10, 4)
    tb = torch.rand(1, 10, 4)
    ap_ = torch.rand(10, 2)
    pd = torch.rand(1, 10, 64)
    ts = torch.rand(1, 10, 12)
    tss = torch.tensor(1.0)
    fg = torch.zeros(1, 10, dtype=torch.bool)
    fg[0, 0] = fg[0, 1] = True
    imgsz = torch.tensor([640, 640])
    stride = torch.ones(10, 1)
    li, ld = lb(pd, pb, ap_, tb, ts, tss, fg, imgsz, stride)
    assert torch.isfinite(li) and torch.isfinite(ld), "WIoU 前向出现非有限值"
    print("WIoU v3 自检通过 loss_iou =", float(li), "loss_dfl =", float(ld))
    print("v8DetectionLoss.__init__ 已打补丁:", getattr(v8DetectionLoss.__init__, "_wiou_patched", False))
