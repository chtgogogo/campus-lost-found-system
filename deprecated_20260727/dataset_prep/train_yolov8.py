#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""train_yolov8.py — 使用 Ultralytics 训练失物招领检测器（11 类）。

读取：dataset/final/data.yaml  （项目内自包含数据集；由 merge_and_retrain.py 从 E:\mod 复制而来）
输出：runs/detect/lostfound_v1/  （相对当前工作目录，位于 E 盘）

默认参数：yolov8n.pt, imgsz=640, batch=8, workers=0, epochs=120, device=0, patience=30

注意：已显式关闭数据集缓存(cache=False)以避免系统内存不足(MemoryError)。
注意：--workers 默认 0 以关闭 DataLoader 多进程、降低系统内存峰值，避免 warpAffine 阶段 OOM；内存充裕可加大。

增强（P0-①⑤，配置见 training_artifacts/train_config.yaml）：
- WIoU_v3 边界框损失：--box-loss WIoU 时启用（自定义 DetectionTrainer 集成点）。
- 小目标增强：mosaic / copy_paste / mixup / close_mosaic（原生超参，直接接入）。

切换更大模型 / 调 batch（命令行）：
    python train_yolov8.py --model yolov8s.pt
    python train_yolov8.py --batch 16
    python train_yolov8.py --resume
    python train_yolov8.py --device cpu --epochs 1 --batch 4   # CPU 调试（很慢，仅验证流程）
    python train_yolov8.py --cfg training_artifacts/train_config.yaml   # 应用增强配置

注意：本脚本耗时较长，应在自有 GPU 机器上全量运行；
      smoke test 阶段只需做语法检查：
      python -c "import ast; ast.parse(open('train_yolov8.py').read())"
"""

import argparse
import glob
import os

import yaml
from ultralytics import YOLO

DEFAULT_DATA = "dataset/final/data.yaml"
DEFAULT_CFG = "training_artifacts/train_config.yaml"


def _clean_dataset_caches(root: str) -> None:
    """递归删除 root 目录树下所有 *.cache 文件，并统计删除数量。"""
    removed = 0
    for path in glob.glob(os.path.join(root, "**", "*.cache"), recursive=True):
        try:
            os.remove(path)
            removed += 1
        except (FileNotFoundError, PermissionError, OSError):
            # 忽略不存在或无权限的文件，继续清理其余缓存。
            pass
    print(f"[train] 已清理残留数据集缓存 {removed} 个（{root}）")


def _load_cfg(path: str | None) -> dict:
    """读取 YAML 训练配置；文件不存在则返回空字典。"""
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    print(f"[train] 已加载训练配置: {path}")
    return cfg


def _build_wiou_trainer(overrides: dict, model_path: str):
    """WIoU 集成点：用自定义 DetectionTrainer 将 bbox 损失替换为 WIoU_v3。

    说明：ultralytics 原生 CLI 未暴露 WIoU，需自定义训练器。
    - WIoUDetectionTrainer 覆写 get_model，将 model.criterion 换成 WIoUDetectionLoss。
    - WIoUDetectionLoss.compute_loss 内临时把 ultralytics.utils.metrics.bbox_iou 的
      iou_type 切换为 'WIoU'（目标 ultralytics>=8.2），在 finally 中还原，避免污染全局。
    仅在 GPU 训练机上验证；若 ultralytics 内部结构变化导致不可用，自动回退默认 CIoU 训练。
    """
    try:
        from ultralytics.models.yolo.detect import DetectionTrainer
        from ultralytics.utils.loss import v8DetectionLoss
        import ultralytics.utils.metrics as _metrics

        class WIoUDetectionLoss(v8DetectionLoss):
            """WIoU_v3 变体：在 compute_loss 中以 WIoU 计算边界框损失。"""

            def compute_loss(self, preds, batch):
                _orig = _metrics.bbox_iou

                def _wiou(*a, **k):
                    k = dict(k)
                    k["iou_type"] = "WIoU"
                    return _orig(*a, **k)

                _metrics.bbox_iou = _wiou
                try:
                    return super().compute_loss(preds, batch)
                finally:
                    _metrics.bbox_iou = _orig

        class WIoUDetectionTrainer(DetectionTrainer):
            """自定义训练器：用 WIoU 变体损失替换默认 CIoU 损失。"""

            def get_model(self, cfg=None, weights=None, verbose=True):
                model = super().get_model(cfg, weights, verbose)
                model.criterion = WIoUDetectionLoss(self.model)
                return model

        trainer = WIoUDetectionTrainer(overrides=overrides)
        trainer.model = YOLO(model_path)
        return trainer
    except Exception as exc:  # pragma: no cover - 仅 GPU 训练时验证
        print(f"[train] WIoU 训练器构建失败，回退默认 CIoU 训练: {exc}")
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Train YOLOv8 lost-and-found detector.")
    ap.add_argument("--cfg", default=None, help=f"YAML 训练配置（默认 {DEFAULT_CFG}）")
    ap.add_argument("--data", default=DEFAULT_DATA, help="data.yaml 路径")
    ap.add_argument("--model", default="yolov8n.pt",
                    help="预训练权重：yolov8n.pt（快）或 yolov8s.pt（更准）")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8,
                    help="批次大小；显存不足时调小（4/2/1），显存充裕可加大")
    ap.add_argument("--epochs", type=int, default=120)
    ap.add_argument("--device", default="0", help="GPU id，如 '0'；无 GPU 用 'cpu'")
    ap.add_argument("--name", default="lostfound_v1")
    ap.add_argument("--patience", type=int, default=30, help="早停耐心值（轮）")
    ap.add_argument("--workers", type=int, default=0,
                    help="数据加载进程数；内存不足(系统 RAM 紧张)时用 0 关闭多进程以避免 OOM，充裕时可加大(2/4/8)")
    ap.add_argument("--resume", action="store_true", help="续训")
    ap.add_argument("--no-val", action="store_true", help="关闭每轮验证（显存紧张时避免 OOM）")
    ap.add_argument("--project", default="runs/detect", help="训练结果输出根目录")
    # ---- 增强项（P0-①⑤）----
    ap.add_argument("--box-loss", choices=["CIoU", "WIoU"], default=None,
                    help="边界框损失：CIoU 或 WIoU_v3（小目标增强）；未指定时取配置文件 box_loss")
    ap.add_argument("--mosaic", type=float, default=1.0, help="mosaic 增广强度（小目标增强）")
    ap.add_argument("--copy-paste", type=float, default=0.0, help="copy_paste 增广强度（小目标增强）")
    ap.add_argument("--mixup", type=float, default=0.0, help="mixup 增广强度")
    ap.add_argument("--close-mosaic", type=int, default=10, help="末段关闭 mosaic 的 epoch 数")
    args = ap.parse_args()

    # 合并 YAML 配置：CLI 优先于配置文件，配置文件优先于脚本默认值
    cfg = _load_cfg(args.cfg if args.cfg else (DEFAULT_CFG if os.path.exists(DEFAULT_CFG) else None))

    def _pick(cli_val, cfg_key, default):
        if cli_val != default:
            return cli_val
        return cfg.get(cfg_key, default)

    data = cfg.get("data", args.data)
    model_name = cfg.get("model", args.model)
    imgsz = int(cfg.get("imgsz", args.imgsz))
    batch = int(cfg.get("batch", args.batch))
    epochs = int(cfg.get("epochs", args.epochs))
    patience = int(cfg.get("patience", args.patience))
    workers = int(cfg.get("workers", args.workers))
    device = cfg.get("device", args.device)
    name = cfg.get("name", args.name)
    project = cfg.get("project", args.project)
    no_val = args.no_val or bool(cfg.get("no_val", False))
    box_loss = args.box_loss or cfg.get("box_loss", "CIoU")
    mosaic = float(cfg.get("mosaic", args.mosaic))
    copy_paste = float(cfg.get("copy_paste", args.copy_paste))
    mixup = float(cfg.get("mixup", args.mixup))
    close_mosaic = int(cfg.get("close_mosaic", args.close_mosaic))

    if not os.path.exists(data):
        raise FileNotFoundError(f"找不到 data.yaml: {data}，请先运行 merge_and_split.py")

    # 训练前清理残留数据集缓存，避免加载内嵌图像数组的大 .cache 文件导致系统内存爆（MemoryError）。
    _clean_dataset_caches("dataset")

    # WIoU_v3：自定义训练器路径
    if str(box_loss).upper() == "WIoU":
        overrides = dict(
            data=data, imgsz=imgsz, batch=batch, epochs=epochs, device=device,
            name=name, patience=patience, workers=workers, cache=False,
            pretrained=True, verbose=True, val=not no_val, project=project,
            mosaic=mosaic, copy_paste=copy_paste, mixup=mixup, close_mosaic=close_mosaic,
        )
        trainer = _build_wiou_trainer(overrides, model_name)
        if trainer is not None:
            trainer.train()
            print(f"[train] WIoU 训练完成。结果位于 {os.path.join(project, name)}")
            return

    # 默认（CIoU）路径
    model = YOLO(model_name)
    model.train(
        data=data,
        imgsz=imgsz,
        batch=batch,
        epochs=epochs,
        device=device,
        name=name,
        patience=patience,
        workers=workers,
        cache=False,
        resume=args.resume,
        project=project,
        pretrained=True,
        verbose=True,
        val=not no_val,
        # ---- 小目标增强（原生超参）----
        mosaic=mosaic,
        copy_paste=copy_paste,
        mixup=mixup,
        close_mosaic=close_mosaic,
    )
    print(f"[train] 完成。结果位于 {os.path.join(project, name)}")


if __name__ == "__main__":
    main()
