# 训练增强配置说明（P0-①⑤）

> **一句话 note：上述训练增强（WIoU_v3、小目标增广、难例挖掘、坐标注意力）均为「配置 + 代码集成点」，
> 实际重训需在独立 GPU 机器上运行 `tools/dataset_prep/train_yolov8.py`，非本次范围。**

本文档对应 `training_artifacts/train_config.yaml` 与 `tools/dataset_prep/train_yolov8.py` 的增强项。

## P0-① WIoU_v3 边界框损失

- **配置**：`train_config.yaml` 中 `box_loss: WIoU`。
- **原生支持情况**：ultralytics 原生 CLI 未直接暴露 `WIoU` 选项（仅 CIoU/DIoU/GIoU/SIoU/EIoU 部分版本）。
- **自定义损失接入点**（已在 `train_yolov8.py:_build_wiou_trainer` 落地为代码）：
  - 自定义 `WIoUDetectionTrainer(DetectionTrainer)`，覆写 `get_model` 将 `model.criterion`
    替换为 `WIoUDetectionLoss`（继承 `v8DetectionLoss`）。
  - `WIoUDetectionLoss.compute_loss` 内临时把 `ultralytics.utils.metrics.bbox_iou` 的
    `iou_type` 切换为 `'WIoU'`（目标 ultralytics>=8.2），在 `finally` 中还原，避免污染全局。
  - WIoU_v3 通过动态聚焦机制对小/低质量锚框降权，提升小目标（钥匙、校园卡）定位精度。
- **验证要求**：需在 GPU 训练机上确认 `bbox_iou(iou_type='WIoU')` 在本机 ultralytics 版本可用；
  若内部结构变化导致不可用，脚本自动回退 CIoU 并告警。

## P0-⑤ 小目标增强（augmentation）

- **配置**：`mosaic: 1.0`、`copy_paste: 0.3`、`mixup: 0.1`、`close_mosaic: 10`，以及标准
  `scale/fliplr/hsv_*` 抖动（保持默认）。
- **作用**：mosaic 提供多图上下文、copy_paste 对稀少/小目标类增广明显、mixup 抑制过拟合；
  `close_mosaic` 在末段 epoch 关闭 mosaic 以稳定收敛（小目标建议保留更久，5~10）。
- **说明**：以上为 ultralytics 原生支持的超参，已直接接入 `model.train(...)`，无需自定义代码。

## 难例挖掘（Hard Example Mining / Focal）

- **现状**：ultralytics 默认无显式 OHEM/focal。
- **集成点（本次仅规划，未实现完整训练循环）**：
  - 在自定义 `DetectionTrainer.compute_loss` 中按预测难度（低置信/高损失样本）加权（focal 权重），
    或对易分样本降权（focal loss 形式）；亦可做在线难例重采样（OHEM）。
  - `train_config.yaml` 的 `hard_mining` 为占位开关（`enabled: false`），供后续接钩子。

## 坐标注意力（SPM/CA，见 `app/models/attention.py`）

- 标准 CA 模块，训练时通过 `USE_COORDINATE_ATTENTION` 开关插入 backbone（见 `insert_into_backbone`）。
- **不改动推理路径**：best.pt 不变；仅当用含 CA 的模型重新训练并覆盖 best.pt 后才生效。
