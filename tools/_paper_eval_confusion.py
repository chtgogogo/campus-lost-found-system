#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""_paper_eval_confusion.py — 为论文图 4-4 生成 12 类归一化混淆矩阵（测试集）。

与 tools/dataset_prep/eval_vision.py 的差别：本脚本 **强制 plots=True**，
因此会在 runs/detect/<name>/ 下落盘 confusion_matrix_normalized.png。

用法：
    python tools/_paper_eval_confusion.py                 # test 集 + GPU(0)，失败自动降级 CPU
    python tools/_paper_eval_confusion.py --split val
    python tools/_paper_eval_confusion.py --device cpu --batch 4
"""
from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "tools" / "_paper_figures_new"
# val 集兜底：12 类训练产物自带的归一化混淆矩阵
FALLBACK_CM = PROJECT_ROOT / "runs" / "detect" / "lostfound_v8s_ciou" / "confusion_matrix_normalized.png"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="生成论文图 4-4 的 12 类归一化混淆矩阵。")
    ap.add_argument("--weights", default=str(PROJECT_ROOT / "models" / "weights" / "best.pt"))
    ap.add_argument("--data", default=str(PROJECT_ROOT / "dataset" / "final" / "data.yaml"))
    ap.add_argument("--split", default="test", choices=["val", "test"])
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="0", help="'0' 用 GPU，'cpu' 用 CPU。GPU 失败会自动降级。")
    return ap.parse_args(argv)


def _run_val(weights: str, data: str, split: str, batch: int, imgsz: int, device: str) -> Path | None:
    """执行一次 model.val(plots=True)，返回运行目录；失败返回 None。"""
    from ultralytics import YOLO

    model = YOLO(weights)
    name = f"paper_cm_{Path(weights).stem}_{split}_{device.replace(':', '')}"
    results = model.val(
        data=data,
        split=split,
        batch=batch,
        imgsz=imgsz,
        device=device,
        plots=True,            # 关键：必须为 True 才会落盘混淆矩阵
        save_json=False,
        verbose=True,
        project=str(PROJECT_ROOT / "runs" / "detect"),
        name=name,
        exist_ok=True,
    )
    save_dir = Path(getattr(results, "save_dir", PROJECT_ROOT / "runs" / "detect" / name))
    print(f"[INFO] save_dir = {save_dir}")
    print(f"[INFO] mAP50={results.box.map50:.6f} mAP50-95={results.box.map:.6f} "
          f"P={results.box.mp:.6f} R={results.box.mr:.6f}")
    return save_dir


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / "fig_44_confusion.png"

    if not Path(args.weights).exists():
        print(f"[ERR] 权重不存在: {args.weights}")
        return _fallback(dst, reason="权重缺失")
    if not Path(args.data).exists():
        print(f"[ERR] data.yaml 不存在: {args.data}")
        return _fallback(dst, reason="data.yaml 缺失")

    devices = [args.device] if args.device == "cpu" else [args.device, "cpu"]
    for dev in devices:
        try:
            print(f"\n===== 尝试 device={dev} split={args.split} =====")
            save_dir = _run_val(args.weights, args.data, args.split, args.batch, args.imgsz, dev)
            cm = save_dir / "confusion_matrix_normalized.png" if save_dir else None
            if cm and cm.exists():
                shutil.copyfile(cm, dst)
                print(f"[OK] 混淆矩阵已导出 -> {dst}  (split={args.split}, device={dev})")
                (OUT_DIR / "fig_44_confusion.source.txt").write_text(
                    f"split={args.split}\ndevice={dev}\nsrc={cm}\nclasses=12\n", encoding="utf-8")
                return 0
            print(f"[WARN] device={dev} 未生成混淆矩阵文件: {cm}")
        except Exception:  # noqa: BLE001 — 需捕获全部异常以便降级
            traceback.print_exc()
            print(f"[WARN] device={dev} 评测失败，尝试下一个设备。")

    return _fallback(dst, reason="test 集评测全部失败")


def _fallback(dst: Path, reason: str) -> int:
    """降级：复用 12 类训练产物中的 val 集混淆矩阵。"""
    print(f"[FALLBACK] 原因: {reason}")
    if FALLBACK_CM.exists():
        shutil.copyfile(FALLBACK_CM, dst)
        (OUT_DIR / "fig_44_confusion.source.txt").write_text(
            f"split=val (FALLBACK)\nsrc={FALLBACK_CM}\nclasses=12\nreason={reason}\n", encoding="utf-8")
        print(f"[OK] 已使用 val 集兜底混淆矩阵 -> {dst}")
        print("[ACTION] 论文题注需写为“验证集”而非“测试集”。")
        return 0
    print(f"[ERR] 兜底文件也不存在: {FALLBACK_CM}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
