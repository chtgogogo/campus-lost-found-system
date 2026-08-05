"""坐标注意力（Coordinate Attention, Hou et al., CVPR 2021）—— 可插拔模块。

论文论述项 P0（SPM/CA 坐标注意力）。本模块为标准 CA 实现，可插入 YOLOv8 backbone
（如替换 C2f 后的 1×1 卷积、或作为 SPPF 前的通道重标定），提升对「位置相关」小目标
（钥匙、校园卡）的判别力。

重要不变量（务必遵守）：
- 本文件为**训练侧能力模块**，仅在训练脚本（tools/）中显式 import；
  应用运行时（app 服务）**绝不 import 本文件**，故不会触发 torch 依赖，
  不影响「无 torch 环境下 56 个回归测试全绿」的红线。
- 本模块**不改动推理路径**：best.pt 权重保持不变，仅靠插入 CA 的模型重新训练后才生效。
  即：插入 CA + 重新训练 → 导出新权重覆盖 best.pt → 推理代码零修改即可获得增益。
- 通过训练开关 `USE_COORDINATE_ATTENTION` 控制是否在 backbone 装配 CA；
  关闭时等价于原生 YOLOv8，保证向后兼容。

接入方式（训练时，需在自有 GPU 上重训，非本次范围）：
1. 在自定义 DetectionTrainer / model 构建阶段，按 `insert_into_backbone` 的注释，
   将 CA 替换 backbone 中指定位置的 1×1 卷积或接入 C2f 输出。
2. 训练开关 `USE_COORDINATE_ATTENTION=True`，用 train_yolov8.py 重新训练。
3. 训完把 best.pt 复制覆盖 models/weights/best.pt，推理服务无需改动。

注意：当前 best.pt 为不含 CA 的原生 YOLOv8n 权重；CA 仅在「重训后」生效。
"""
from __future__ import annotations

import torch
import torch.nn as nn


# 训练开关：是否在 backbone 装配坐标注意力。关闭时等价原生 YOLOv8。
# 仅在训练脚本中读取；推理路径（best.pt）不受此影响。
USE_COORDINATE_ATTENTION: bool = False


class CoordinateAttention(nn.Module):
    """坐标注意力模块。

    将通道注意力沿 **水平 / 垂直** 两个空间方向分解编码，使注意力同时感知
    「通道 what」与「位置 where」，优于仅做通道压缩的 SE 模块。

    Args:
        in_channels: 输入通道数（= 插入位置的 backbone 通道数）。
        reduction: 中间通道压缩比，默认 32（至少保留 8 通道）。
        out_channels: 输出通道数，默认与输入一致（残差相乘，不改变张量形状）。
    """

    def __init__(
        self,
        in_channels: int,
        reduction: int = 32,
        out_channels: int | None = None,
    ) -> None:
        super().__init__()
        out_channels = out_channels or in_channels
        self.in_channels = in_channels
        self.out_channels = out_channels

        # 沿 H / W 方向分别做一维全局池化
        self.pool_h = nn.AdaptiveAvgPool2d((None, 1))
        self.pool_w = nn.AdaptiveAvgPool2d((1, None))

        # 中间瓶颈通道（压缩 + BN + 激活）
        mid_channels = max(8, in_channels // reduction)
        self.conv1 = nn.Conv2d(in_channels, mid_channels, kernel_size=1, bias=False)
        self.bn1 = nn.BatchNorm2d(mid_channels)
        self.act = nn.SiLU(inplace=True)

        # 两个方向各自生成注意力权重
        self.conv_h = nn.Conv2d(mid_channels, out_channels, kernel_size=1, bias=False)
        self.conv_w = nn.Conv2d(mid_channels, out_channels, kernel_size=1, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """前向：输出 = 输入 ⊙ 横向注意力 ⊙ 纵向注意力（形状不变）。"""
        identity = x
        n, c, h, w = x.size()

        # 横向（H 方向）与纵向（W 方向）特征
        x_h = self.pool_h(x)            # (n, c, h, 1)
        x_w = self.pool_w(x)            # (n, c, 1, w)
        x_w = x_w.permute(0, 1, 3, 2)   # (n, c, w, 1)

        # 拼接后联合编码（保留方向信息）
        y = torch.cat([x_h, x_w], dim=2)  # (n, c, h + w, 1)
        y = self.conv1(y)
        y = self.bn1(y)
        y = self.act(y)

        # 拆分回两个方向并各自生成空间注意力
        x_h, x_w = torch.split(y, [h, w], dim=2)
        x_w = x_w.permute(0, 1, 3, 2)   # (n, c, 1, w)

        att_h = self.sigmoid(self.conv_h(x_h))  # (n, out, h, 1)
        att_w = self.sigmoid(self.conv_w(x_w))  # (n, out, 1, w)

        out = identity * att_h * att_w
        return out


def insert_into_backbone(model, ca_reduction: int = 32) -> nn.Module:
    """将 CA 插入 YOLOv8 backbone 的示例钩子（训练时调用，非推理路径）。

    说明：ultralytics 的 YOLOv8 backbone 由 C2f / Conv / SPPF 组成。典型插入点：
      - 在 backbone 末端（SPPF 之前或之后）接一个 CoordinateAttention，对 512 通道做
        位置敏感重标定；
      - 或把某个 C2f 模块后的 1×1 Conv 替换为 CA（保持 in/out 通道一致）。

    本函数给出最小可行骨架：遍历模型子模块，将首个匹配的 1×1 Conv 替换为 CA。
    实际接入点需按具体 backbone 结构微调，并在自有 GPU 上重训验证。

    Args:
        model: ultralytics YOLO 模型（model.model 为 nn.Module）。
        ca_reduction: CA 中间压缩比。

    Returns:
        被原地修改后的模型（插入 CA 后）。
    """
    if not USE_COORDINATE_ATTENTION:
        # 开关关闭：保持原生结构，零影响、可向后兼容。
        return model

    backbone = getattr(model, "model", model)
    replaced = False
    for name, module in backbone.named_modules():
        if isinstance(module, nn.Conv2d) and module.kernel_size == (1, 1) and module.in_channels == module.out_channels:
            parent = backbone
            *path, leaf = name.split(".")
            for p in path:
                parent = getattr(parent, p)
            setattr(parent, leaf, CoordinateAttention(module.in_channels, reduction=ca_reduction))
            replaced = True
            break
    if not replaced:  # pragma: no cover - 结构相关，训练时按实际 backbone 调整
        raise RuntimeError(
            "未在 backbone 中找到可替换的 1×1 等通道卷积；请在 USE_COORDINATE_ATTENTION=True 时"
            "按实际 backbone 结构指定插入点。"
        )
    return model
