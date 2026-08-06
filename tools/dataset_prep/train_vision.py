# -*- coding: utf-8 -*-
"""失物招领视觉模型训练入口（A + B 共用）。

修复旧训练的致命缺陷：旧脚本用 `val=False/--no-val`，导致 120 轮里只有最后一轮做验证，
`best.pt` 实际等于 last.pt、无 mAP 曲线、无法选出最优轮次。本脚本**默认每轮验证 + 早停**，
`best.pt` 按 mAP 自动选取。

用法示例（在项目根目录运行）：
  # B：零成本复训 YOLOv8n（CIoU，仅验证修正）
  python tools/dataset_prep/train_vision.py --model-size n --loss CIoU --name lostfound_v8n_v2

  # A：升级 YOLOv8s 重训（CIoU，推荐）
  python tools/dataset_prep/train_vision.py --model-size s --loss CIoU --name lostfound_v8s_ciou

  # 从已有权重继续（迁移/微调）
  python tools/dataset_prep/train_vision.py --model-size s --loss CIoU \
      --weights models/weights/best.pt --name lostfound_v8s_ciou2

训练结束后自动把 runs/detect/<name>/weights/best.pt 备份旧权重并覆盖到 models/weights/best.pt，
app 直接可用。
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA = PROJECT_ROOT / "dataset" / "final" / "data.yaml"
DEST_WEIGHT = PROJECT_ROOT / "models" / "weights" / "best.pt"


def resolve_data(data_arg: str) -> dict:
    """读取 data.yaml，将相对 path 解析为绝对路径（ultralytics 以 CWD 解析 path）。"""
    p = Path(data_arg)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve() if not p.exists() else p.resolve()
    if not p.exists():
        sys.exit(f"[错误] data.yaml 不存在: {p}")
    with open(p, "r", encoding="utf-8") as f:
        d = yaml.safe_load(f)
    rp = d.get("path")
    if rp and not Path(rp).is_absolute():
        abs_p = (Path.cwd() / rp).resolve()
        if not abs_p.exists():
            abs_p = (p.parent / rp).resolve()
        if not abs_p.exists():
            sys.exit(f"[错误] data.yaml 中 path 解析不到: {abs_p}")
        d["path"] = str(abs_p)
    return d


def parse_args():
    ap = argparse.ArgumentParser(description="失物招领视觉模型训练（A+B）")
    ap.add_argument("--model-size", choices=["n", "s"], default="s", help="YOLOv8 骨干: n(纳米)/s(小)，A 用 s，B 用 n")
    ap.add_argument("--loss", choices=["CIoU", "WIoU"], default="CIoU", help="边界框损失: CIoU(默认/推荐) / WIoU(对本长尾数据集有害，勿用)")
    ap.add_argument("--epochs", type=int, default=120, help="训练轮数")
    ap.add_argument("--batch", type=int, default=None, help="批次大小（默认 n=16 / s=8，6G 显存友好）")
    ap.add_argument("--imgsz", type=int, default=640, help="输入尺寸")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="data.yaml 路径")
    ap.add_argument("--weights", default=None, help="初始权重(.pt)；省略则自动下载 yolov8{size}.pt")
    ap.add_argument("--name", default=None, help="本次运行名（runs/detect/<name>）")
    ap.add_argument("--device", default="0", help="设备: 0 / cpu")
    ap.add_argument("--patience", type=int, default=30, help="早停在多少轮无提升后停止")
    ap.add_argument("--workers", type=int, default=8, help="dataloader 进程数（Windows 内存紧时降到 0-2，避免 fork 出大量 torch 副本撑爆页面文件）")
    ap.add_argument("--no-val", action="store_true", help="训练期间不验证（省内存）；训完用 eval_vision.py 单独评测。默认每轮验证以选最优 best.pt")
    return ap.parse_args()


def main():
    args = parse_args()
    batch = args.batch or (16 if args.model_size == "n" else 8)
    name = args.name or f"lostfound_v8{args.model_size}_{'wiou' if args.loss=='WIoU' else 'ciou'}"

    if args.loss == "WIoU":
        from wiou_loss import _install_wiou
        _install_wiou()
        print(f"[train] 损失函数: WIoU（已注入）")
        print(
            "[WARN] WIoU 对本数据集有害：长尾失衡≈103:1，WIoU v3 聚焦机制会抑制稀有类"
            "低质量预测梯度，实测 val mAP@0.5 仅 0.060（CIoU 为 0.710）。仅用于消融对照，"
            "生产训练请用默认 CIoU。"
        )
    else:
        print(f"[train] 损失函数: CIoU（默认/推荐）")

    # 解析 data.yaml 路径：ultralytics 的 model.train(data=...) 只接受 yaml 文件路径，
    # 不接受 dict（8.4.98 会把它当文件路径去 check_file 而报错）。
    data_yaml = Path(args.data)
    if not data_yaml.is_absolute():
        candidate = PROJECT_ROOT / args.data
        data_yaml = candidate if candidate.exists() else data_yaml.resolve()
    if not data_yaml.exists():
        sys.exit(f"[错误] data.yaml 不存在: {data_yaml}")
    info = resolve_data(args.data)  # 仅用于打印 nc / path 信息

    from ultralytics import YOLO

    init_weights = args.weights or f"yolov8{args.model_size}.pt"
    print(f"[train] 初始权重: {init_weights} | 骨干: YOLOv8{args.model_size} | batch={batch} imgsz={args.imgsz} | workers={args.workers} | val={not args.no_val}")
    model = YOLO(init_weights)

    print(f"[train] 数据: {info.get('path')} | nc={info.get('nc')} | 每轮验证+早停(patience={args.patience})")

    model.train(
        data=str(data_yaml),  # ✅ 必须是 yaml 文件路径，不能传 dict
        epochs=args.epochs,
        batch=batch,
        imgsz=args.imgsz,
        device=args.device,
        name=name,
        patience=args.patience,
        val=not args.no_val,  # 默认每轮验证（修复旧 bug）；内存紧可 --no-val 训完再用 eval_vision.py
        workers=args.workers,
        close_mosaic=10,     # 最后 10 轮关 mosaic，提升 mAP（对小目标有效）
        plots=True,          # 输出混淆矩阵/曲线，论文可用
        exist_ok=True,
    )

    # 回灌 app
    run_best = PROJECT_ROOT / "runs" / "detect" / name / "weights" / "best.pt"
    if not run_best.exists():
        print(f"[warn] 未找到训练产出: {run_best}，未覆盖 app 权重")
        return
    if DEST_WEIGHT.exists():
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = DEST_WEIGHT.with_suffix(f".pt.bak.{ts}")
        shutil.copy(DEST_WEIGHT, backup)
        print(f"[train] 已备份旧权重 -> {backup.name}")
    shutil.copy(run_best, DEST_WEIGHT)
    print(f"[train] 已覆盖 models/weights/best.pt（来自 runs/detect/{name}/weights/best.pt）")
    print(f"[train] 完成 ✅ app 现使用新模型。")


if __name__ == "__main__":
    main()
