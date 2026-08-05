#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""eval_vision.py — 失物招领系统 YOLOv8 视觉模型评测脚本。

用途：
    量化识别准确率，支持 A 换 YOLOv8s+WIoU / B 复训 YOLOv8n / C 补稀有类 三路优化
    前后的可复现指标对比。新权重训练后覆盖到 models/weights/best.pt 同一路径，
    本脚本不改权重、不改训练代码，只读取并评测。

输出：
    1) 终端打印总览指标（mAP50 / mAP50-95 / precision / recall）与逐类 AP 表格；
       重点标注 campus_card / wallet / keys / glasses 四个稀有类的 AP 变化。
    2) 一份 JSON 存档到 runs/detect/eval_<权重名>_<split>_metrics.json，
       便于前后两次评测直接做 diff 对比。

数据：
    默认读取 dataset/final/data.yaml（12 类）。若该文件缺失，脚本内置 12 类名与
    路径兜底（仍优先使用 data.yaml），兜底逻辑见 _fallback_data_yaml()。

约束：
    - 默认 batch=16、imgsz=640，内存友好，适配本机 6G GPU。
    - 不修改 best.pt 等任何产物，只做只读评测。

用法：
    python eval_vision.py --help
    python eval_vision.py                                   # 评测默认权重 + val 集
    python eval_vision.py --split test                      # 评测 test 集
    python eval_vision.py --weights models/weights/best.pt --device 0
    python eval_vision.py --weights runs/detect/exp/weights/best.pt --split test --batch 8
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

# 项目约定：从 dataset/final/data.yaml 读取；这里硬编码 12 类作为代码内兜底。
# 顺序即 class_id（0..11），与 data.yaml 的 names 保持一致。
FALLBACK_NAMES = [
    "phone", "wallet", "keys", "backpack", "suitcase", "laptop",
    "campus_card", "glasses", "notebook", "umbrella", "bottle", "other",
]

# 论文重点关注的四个稀有类（按类名标识，用于终端高亮提示）。
RARE_CLASSES = {"campus_card", "wallet", "keys", "glasses"}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数，提供中文 --help。"""
    here = Path(__file__).resolve().parent
    # 默认路径相对项目根目录（与项目内其他脚本约定一致：从项目根运行）。
    project_root = here.parent.parent  # tools/dataset_prep -> 项目根
    default_weights = project_root / "models" / "weights" / "best.pt"
    default_data = project_root / "dataset" / "final" / "data.yaml"

    ap = argparse.ArgumentParser(
        description="YOLOv8 失物招领模型评测：输出总览指标 + 逐类 AP，并写 JSON 存档。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--weights", default=str(default_weights),
        help="权重 .pt 路径；默认 models/weights/best.pt（训练后新权重覆盖此路径）。",
    )
    ap.add_argument(
        "--data", default=str(default_data),
        help="数据集 data.yaml 路径；缺失时启用内置 12 类兜底。",
    )
    ap.add_argument(
        "--split", default="val", choices=["val", "test"],
        help="评测所用划分：val 或 test。",
    )
    ap.add_argument(
        "--batch", type=int, default=16,
        help="评测 batch size；6G 显存下默认 16，OOM 可下调到 8/4。",
    )
    ap.add_argument("--imgsz", type=int, default=640, help="推理输入尺寸。")
    ap.add_argument(
        "--device", default=None,
        help="运行设备；默认 None 由 ultralytics 自动选择（有 GPU 用 GPU，否则 CPU）。"
             "可显式指定 '0' / 'cpu'。",
    )
    ap.add_argument(
        "--workers", type=int, default=8,
        help="dataloader 进程数；Windows 内存紧（易 1455）时降到 0-2，避免 fork 出大量 torch 副本。",
    )
    return ap.parse_args(argv)


def _load_class_names(data_yaml: str) -> tuple[list[str], str | None]:
    """读取 data.yaml 的类别名；返回 (names, yaml路径)。

    若 data.yaml 缺失，返回内置 FALLBACK_NAMES 并回传 None 表示启用了兜底。
    """
    if not os.path.exists(data_yaml):
        print(f"[eval_vision] 警告：未找到 data.yaml ({data_yaml})，启用内置 12 类兜底。")
        return list(FALLBACK_NAMES), None
    with open(data_yaml, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    names = cfg.get("names", [])
    # data.yaml 的 names 可能是 list 或 dict；统一转为有序 list。
    if isinstance(names, dict):
        names = [names[str(i)] if str(i) in names else names[i] for i in range(len(names))]
    if not names:
        print("[eval_vision] 警告：data.yaml 未提供 names，回退到内置 12 类。")
        return list(FALLBACK_NAMES), None
    return list(names), data_yaml


def _fallback_data_yaml(class_names: list[str], split: str) -> str:
    """data.yaml 缺失时的兜底：生成一份临时 yaml（使用绝对子路径，避免相对解析歧义）。

    返回临时 yaml 的路径；该文件写到 runs/detect/ 下，不污染 dataset 目录。
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    ds_root = project_root / "dataset" / "final"
    cfg = {
        "path": str(ds_root),
        "train": str(ds_root / "images" / "train"),
        "val": str(ds_root / "images" / "val"),
        "test": str(ds_root / "images" / "test"),
        "nc": len(class_names),
        "names": list(class_names),
    }
    os.makedirs(project_root / "runs" / "detect", exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        suffix=".yaml", prefix="eval_fallback_",
        dir=str(project_root / "runs" / "detect"),
    )
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
    print(f"[eval_vision] 已生成兜底 data.yaml：{tmp}（split={split}）")
    return tmp


def _print_per_class_table(names: list[str], ap50: list[float], ap: list[float]) -> None:
    """终端打印逐类 AP 表格，稀有类用 '*' 标注。"""
    print("\n逐类 AP 表格（AP 取值区间 0~1）：")
    print(f"{'idx':>3}  {'class':<12} {'AP@0.5':>8} {'AP@0.5:0.95':>13}  note")
    print("-" * 52)
    for i, name in enumerate(names):
        a50 = float(ap50[i]) if i < len(ap50) else 0.0
        a = float(ap[i]) if i < len(ap) else 0.0
        note = "  *稀有类" if name in RARE_CLASSES else ""
        print(f"{i:>3}  {name:<12} {a50:>8.4f} {a:>13.4f}{note}")
    print("(带 * 的为论文重点关注的稀有类：campus_card / wallet / keys / glasses)")


def main(argv: list[str] | None = None) -> int:
    """评测主流程：加载权重 -> 在指定 split 上 val -> 汇总 -> 打印 + 写 JSON。"""
    args = _parse_args(argv)

    weights = str(Path(args.weights).resolve())
    if not os.path.exists(weights):
        print(f"[eval_vision] 错误：权重文件不存在：{weights}", file=sys.stderr)
        return 2
    data_arg = str(Path(args.data).resolve())
    names, used_yaml = _load_class_names(data_arg)
    if used_yaml is None:
        # 兜底：生成临时 yaml 供 ultralytics 读取。
        data_arg = _fallback_data_yaml(names, args.split)

    from ultralytics import YOLO  # 延迟导入，确保 --help 无需依赖 ultralytics

    print(f"[eval_vision] 权重：{weights}")
    print(f"[eval_vision] 数据：{data_arg} （{args.split} 划分，{len(names)} 类）")
    print(f"[eval_vision] batch={args.batch} imgsz={args.imgsz} device={args.device} workers={args.workers}")

    model = YOLO(weights)
    # model.val 在指定 split 上评测；plots/save_json 关闭以减少磁盘与内存开销。
    results = model.val(
        data=data_arg,
        split=args.split,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device,
        workers=args.workers,
        plots=False,
        save_json=False,
        verbose=True,
        project=str(Path(weights).parent.parent.parent / "runs" / "detect"),
        name=f"eval_{Path(weights).stem}_{args.split}",
        exist_ok=True,
    )

    # results.box 为 Metric 对象：ap50/ap 为逐类数组，mp/mr/map50/map 为标量。
    box = results.box
    overview = {
        "mAP50": round(float(box.map50), 6),
        "mAP50_95": round(float(box.map), 6),
        "precision": round(float(box.mp), 6),
        "recall": round(float(box.mr), 6),
    }
    per_class = [
        {
            "index": i,
            "name": names[i],
            "ap50": round(float(box.ap50[i]), 6) if i < len(box.ap50) else 0.0,
            "ap50_95": round(float(box.ap[i]), 6) if i < len(box.ap) else 0.0,
        }
        for i in range(len(names))
    ]

    # ---- 终端总览 ----
    print("\n==== 总览指标 ====")
    print(f"  mAP@0.5      : {overview['mAP50']:.4f}")
    print(f"  mAP@0.5:0.95 : {overview['mAP50_95']:.4f}")
    print(f"  precision    : {overview['precision']:.4f}")
    print(f"  recall       : {overview['recall']:.4f}")
    _print_per_class_table(names, box.ap50, box.ap)

    # ---- JSON 存档 ----
    out_dir = Path(weights).parent.parent.parent / "runs" / "detect"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"eval_{Path(weights).stem}_{args.split}_metrics.json"
    payload = {
        "meta": {
            "weights": weights,
            "weights_name": Path(weights).stem,
            "data": data_arg,
            "split": args.split,
            "batch": args.batch,
            "imgsz": args.imgsz,
            "device": args.device,
            "ultralytics_version": getattr(__import__("ultralytics"), "__version__", "unknown"),
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
            "class_names": names,
            "fallback_data_yaml": used_yaml is None,
        },
        "overview": overview,
        "per_class": per_class,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n[eval_vision] JSON 存档：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
